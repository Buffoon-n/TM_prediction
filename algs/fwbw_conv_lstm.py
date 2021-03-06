import os

import numpy as np
import pandas as pd
import tensorflow as tf
from keras.callbacks import ModelCheckpoint
from sklearn.preprocessing import MinMaxScaler
from tqdm import tqdm

from Models.lstm.FWBW_CONV_LSTM import FWBW_CONV_LSTM
from common import Config_fwbw_conv_lstm as Config
from common.DataPreprocessing import prepare_train_valid_test_2d, create_offline_fwbw_conv_lstm_data_fix_ratio, \
    data_scalling
from common.error_utils import calculate_consecutive_loss_3d, recovery_loss_3d, error_ratio, calculate_r2_score, \
    calculate_rmse

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
session = tf.Session(config=config)


def calculate_flows_weights_3d(rnn_input, rl_forward, rl_backward, measured_matrix):
    eps = 10e-5

    cl = calculate_consecutive_loss_3d(measured_matrix).astype(float)

    flows_stds = np.std(rnn_input, axis=0)

    cl_scaled = MinMaxScaler(feature_range=(eps, 1.0)).fit_transform(cl)
    flows_stds_scaled = MinMaxScaler(feature_range=(eps, 1.0)).fit_transform(flows_stds)
    rl_forward_scaled = MinMaxScaler(feature_range=(eps, 1.0)).fit_transform(rl_forward)
    rl_backward_scaled = MinMaxScaler(feature_range=(eps, 1.0)).fit_transform(rl_backward)

    w = 1 / (rl_forward_scaled * Config.FWBW_CONV_LSTM_HYPERPARAMS[0] +
             rl_backward_scaled * Config.FWBW_CONV_LSTM_HYPERPARAMS[1] +
             cl_scaled * Config.FWBW_CONV_LSTM_HYPERPARAMS[2] +
             flows_stds_scaled * Config.FWBW_CONV_LSTM_HYPERPARAMS[3])

    return w


def set_measured_flow_3d(rnn_input, labels, forward_pred, backward_pred):
    rl_forward, rl_backward = calculate_forward_backward_loss_3d(measured_block=labels,
                                                                 pred_forward=forward_pred,
                                                                 pred_backward=backward_pred,
                                                                 rnn_input=rnn_input)

    w = calculate_flows_weights_3d(rnn_input=rnn_input,
                                   rl_forward=rl_forward,
                                   rl_backward=rl_backward,
                                   measured_matrix=labels)

    sampling = np.zeros(shape=(rnn_input.shape[1] * rnn_input.shape[2]))
    m = int(Config.FWBW_CONV_LSTM_MON_RATIO * rnn_input.shape[1] * rnn_input.shape[2])

    w = w.flatten()
    sorted_idx_w = np.argpartition(w, m)
    sampling[sorted_idx_w[:m]] = 1.0

    sampling = np.expand_dims(sampling, axis=0)

    sampling = np.reshape(sampling, newshape=(rnn_input.shape[1], rnn_input.shape[2]))

    return sampling


def calculate_updated_weights_3d(measured_block, forward_loss, backward_loss):
    measured_count = np.sum(measured_block, axis=0).astype(float)
    _eta = measured_count / Config.FWBW_CONV_LSTM_STEP

    alpha = 1 - _eta  # shape = (od, od)
    alpha = np.tile(np.expand_dims(alpha, axis=0), (Config.FWBW_CONV_LSTM_STEP, 1, 1))

    # Calculate rho
    rho = np.zeros((Config.FWBW_CONV_LSTM_STEP, measured_block.shape[1], measured_block.shape[1]))
    mu = np.zeros((Config.FWBW_CONV_LSTM_STEP, measured_block.shape[1], measured_block.shape[1]))
    for j in range(0, Config.FWBW_CONV_LSTM_STEP):
        _mu = np.sum(measured_block[:(j + 1)], axis=0) / float(j + 1)
        mu[j] = _mu

        _rho = np.sum(measured_block[j:, :, :], axis=0) / float(Config.FWBW_CONV_LSTM_STEP - j)
        rho[j] = _rho

    forward_loss = np.tile(np.expand_dims(forward_loss, axis=0), (Config.FWBW_CONV_LSTM_STEP, 1, 1))
    backward_loss = np.tile(np.expand_dims(backward_loss, axis=0), (Config.FWBW_CONV_LSTM_STEP, 1, 1))

    beta = (backward_loss + mu) * (1.0 - alpha) / (forward_loss + backward_loss + mu + rho)

    gamma = (forward_loss + rho) * (1.0 - alpha) / (forward_loss + backward_loss + mu + rho)

    return alpha[1:-1], beta[1:-1], gamma[1:-1]


def calculate_forward_backward_loss_3d(measured_block, pred_forward, pred_backward, rnn_input):
    eps = 10e-8

    rl_forward = recovery_loss_3d(rnn_input=rnn_input[1:], rnn_updated=pred_forward[:-1],
                                  measured_matrix=measured_block[1:])
    rl_forward[rl_forward == 0] = eps

    rl_backward = recovery_loss_3d(rnn_input=rnn_input[:-1], rnn_updated=pred_backward[1:],
                                   measured_matrix=measured_block[:-1])
    rl_backward[rl_backward == 0] = eps

    return rl_forward, rl_backward


def updating_historical_data_3d(rnn_input, pred_forward, pred_backward, labels):
    rnn_input = np.copy(rnn_input)
    measured_block = np.copy(labels)

    forward_loss, backward_loss = calculate_forward_backward_loss_3d(measured_block=measured_block,
                                                                     pred_forward=pred_forward,
                                                                     pred_backward=pred_backward,
                                                                     rnn_input=rnn_input)

    alpha, beta, gamma = calculate_updated_weights_3d(measured_block=measured_block,
                                                      forward_loss=forward_loss,
                                                      backward_loss=backward_loss)

    considered_rnn_input = rnn_input[1:-1, :, :]
    considered_forward = pred_forward[0:-2, :, :]
    considered_backward = pred_backward[2:, :, :]

    updated_rnn_input = considered_rnn_input * alpha + considered_forward * beta + considered_backward * gamma
    # updated_rnn_input = (considered_rnn_input + considered_forward + considered_backward) / 3.0

    return updated_rnn_input


def ims_tm_prediction(init_data, init_labels, model):
    multi_steps_tm = np.zeros(shape=(init_data.shape[0] + Config.FWBW_CONV_LSTM_IMS_STEP,
                                     init_data.shape[1], init_data.shape[2]))

    multi_steps_tm[0:init_data.shape[0]] = init_data

    labels = np.zeros(shape=(init_labels.shape[0] + Config.FWBW_CONV_LSTM_IMS_STEP,
                             init_labels.shape[1], init_labels.shape[2]))
    labels[0:init_labels.shape[0]] = init_labels

    for ts_ahead in range(Config.FWBW_CONV_LSTM_IMS_STEP):
        rnn_input = np.zeros(
            shape=(Config.FWBW_CONV_LSTM_STEP, Config.FWBW_CONV_LSTM_WIDE, Config.FWBW_CONV_LSTM_HIGH, 2))

        rnn_input[:, :, :, 0] = multi_steps_tm[ts_ahead:(ts_ahead + Config.FWBW_CONV_LSTM_STEP)]
        rnn_input[:, :, :, 1] = labels[ts_ahead:(ts_ahead + Config.FWBW_CONV_LSTM_STEP)]

        rnn_input = np.expand_dims(rnn_input, axis=0)  # shape(1, timesteps, od, od , 2)

        # Prediction results from forward network
        predictX, predictX_backward = model.predict(rnn_input)  # shape(1, timesteps, od, od , 1)

        predictX = np.squeeze(predictX, axis=0)  # shape(timesteps, od, od , 1)
        predictX = np.reshape(predictX, newshape=(predictX.shape[0],
                                                  Config.FWBW_CONV_LSTM_WIDE,
                                                  Config.FWBW_CONV_LSTM_HIGH))

        predict_tm = np.copy(predictX[-1])

        predictX_backward = np.squeeze(predictX_backward, axis=0)  # shape(timesteps, #nflows)

        # Flipping the backward prediction
        predictX_backward = np.flip(predictX_backward, axis=0)
        predictX_backward = np.reshape(predictX_backward, newshape=(predictX_backward.shape[0],
                                                                    Config.FWBW_CONV_LSTM_WIDE,
                                                                    Config.FWBW_CONV_LSTM_HIGH))

        # Correcting the imprecise input data
        rnn_pred_value = updating_historical_data_3d(
            rnn_input=multi_steps_tm[ts_ahead:ts_ahead + Config.FWBW_CONV_LSTM_STEP],
            pred_forward=predictX,
            pred_backward=predictX_backward,
            labels=labels[ts_ahead:ts_ahead + Config.FWBW_CONV_LSTM_STEP])

        multi_steps_tm[(ts_ahead + 1):(ts_ahead + Config.FWBW_CONV_LSTM_STEP - 1)] = \
            multi_steps_tm[(ts_ahead + 1):(ts_ahead + Config.FWBW_CONV_LSTM_STEP - 1)] * \
            labels[(ts_ahead + 1):(ts_ahead + Config.FWBW_CONV_LSTM_STEP - 1)] + \
            rnn_pred_value

        multi_steps_tm[ts_ahead + Config.FWBW_CONV_LSTM_STEP] = predict_tm

    return multi_steps_tm[-1]


def data_correction(rnn_input, pred_backward, labels):
    # Shape = (#time-steps, #wide, #high)

    beta = np.zeros(rnn_input.shape)
    for i in range(rnn_input.shape[0] - Config.FWBW_CONV_LSTM_R):
        mu = np.sum(labels[i + 1:i + Config.FWBW_CONV_LSTM_R + 1], axis=0) / Config.FWBW_CONV_LSTM_R

        h = np.arange(1, Config.FWBW_CONV_LSTM_R + 1)
        h = np.expand_dims(h, axis=1)
        h = np.expand_dims(h, axis=2)
        h = np.tile(h, (1, Config.FWBW_CONV_LSTM_HIGH, Config.FWBW_CONV_LSTM_WIDE))

        rho = (1 / (np.log(Config.FWBW_CONV_LSTM_R) + 1)) * np.sum(labels[i + 1:i + Config.FWBW_CONV_LSTM_R + 1] / h,
                                                                   axis=0)

        beta[i] = mu * rho

    considered_backward = pred_backward[1:]
    considered_rnn_input = rnn_input[0:-1]

    beta[beta > 0.5] = 0.5

    alpha = 1.0 - beta

    alpha = alpha[0:-1]
    beta = beta[0:-1]

    corrected_data = considered_rnn_input * alpha + considered_backward * beta

    return corrected_data


def predict_fwbw_conv_lstm(initial_data, test_data, model):
    tf_a = np.array([1.0, 0.0])

    tm = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1], test_data.shape[2]))
    tm[0:initial_data.shape[0], :, :] = initial_data

    labels = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1], test_data.shape[2]))
    labels[0:initial_data.shape[0], :, :] = np.ones(shape=initial_data.shape)

    ims_tm = np.zeros(
        shape=(test_data.shape[0] - Config.FWBW_CONV_LSTM_IMS_STEP + 1, test_data.shape[1], test_data.shape[2]))

    for ts in tqdm(range(test_data.shape[0])):
        rnn_input = np.zeros(shape=(Config.FWBW_CONV_LSTM_STEP,
                                    Config.FWBW_CONV_LSTM_WIDE,
                                    Config.FWBW_CONV_LSTM_HIGH,
                                    Config.FWBW_CONV_LSTM_CHANNEL))

        rnn_input[:, :, :, 0] = tm[ts:(ts + Config.FWBW_CONV_LSTM_STEP)]
        rnn_input[:, :, :, 1] = labels[ts:(ts + Config.FWBW_CONV_LSTM_STEP)]

        rnn_input = np.expand_dims(rnn_input, axis=0)

        # Prediction results from forward network
        predictX, predictX_backward = model.predict(rnn_input)  # shape(1, timesteps, od, od , 1)
        predictX = np.squeeze(predictX, axis=0)  # shape(timesteps, #nflows)
        predictX = np.reshape(predictX, newshape=(predictX.shape[0],
                                                  Config.FWBW_CONV_LSTM_WIDE,
                                                  Config.FWBW_CONV_LSTM_HIGH))

        predict_tm = np.copy(predictX[-1])

        # --------------------------------------------------------------------------------------------------------------

        predictX_backward = np.squeeze(predictX_backward, axis=0)  # shape(timesteps, #nflows)
        predictX_backward = np.reshape(predictX_backward, newshape=(predictX_backward.shape[0],
                                                                    Config.FWBW_CONV_LSTM_WIDE,
                                                                    Config.FWBW_CONV_LSTM_HIGH))

        # Correcting the imprecise input data
        corrected_data = data_correction(rnn_input=np.copy(tm[ts:ts + Config.FWBW_CONV_LSTM_STEP]),
                                         pred_backward=predictX_backward,
                                         labels=labels[ts:ts + Config.FWBW_CONV_LSTM_STEP])

        measured_data = tm[ts:ts + Config.FWBW_CONV_LSTM_STEP - 1] * labels[ts:ts + Config.FWBW_CONV_LSTM_STEP - 1]
        pred_data = corrected_data * (1.0 - labels[ts:ts + Config.FWBW_CONV_LSTM_STEP - 1])
        tm[ts:ts + Config.FWBW_CONV_LSTM_STEP - 1] = measured_data + pred_data

        sampling = np.random.choice(tf_a, size=(Config.FWBW_CONV_LSTM_WIDE, Config.FWBW_CONV_LSTM_HIGH),
                                    p=(Config.FWBW_CONV_LSTM_MON_RATIO, 1 - Config.FWBW_CONV_LSTM_MON_RATIO))

        # Calculating the true value for the TM
        new_tm = predict_tm * (1.0 - sampling) + test_data[ts] * sampling

        tm[ts + Config.FWBW_CONV_LSTM_STEP] = new_tm
        labels[ts + Config.FWBW_CONV_LSTM_STEP] = sampling

    return tm[Config.FWBW_CONV_LSTM_STEP:], labels[Config.FWBW_CONV_LSTM_STEP:], ims_tm


def build_model(input_shape):
    print('|--- Build models.')
    fwbw_conv_lstm_net = FWBW_CONV_LSTM(input_shape=input_shape,
                                        cnn_layers=Config.FWBW_CONV_LSTM_LAYERS,
                                        a_filters=Config.FWBW_CONV_LSTM_FILTERS,
                                        a_strides=Config.FWBW_CONV_LSTM_STRIDES,
                                        dropouts=Config.FWBW_CONV_LSTM_DROPOUTS,
                                        kernel_sizes=Config.FWBW_CONV_LSTM_KERNEL_SIZE,
                                        rnn_dropouts=Config.FWBW_CONV_LSTM_RNN_DROPOUTS,
                                        alg_name=Config.ALG,
                                        tag=Config.TAG,
                                        check_point=True,
                                        saving_path=Config.MODEL_SAVE + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                                                              Config.ALG,
                                                                                              Config.TAG,
                                                                                              Config.SCALER))
    fwbw_conv_lstm_net.plot_models()
    return fwbw_conv_lstm_net


def load_trained_models(input_shape, best_ckp):
    fwbw_conv_lstm_net = build_model(input_shape)
    print('|--- Load trained model from: {}'.format(fwbw_conv_lstm_net.checkpoints_path))
    fwbw_conv_lstm_net.model.load_weights(fwbw_conv_lstm_net.checkpoints_path + "weights-{:02d}.hdf5".format(best_ckp))

    return fwbw_conv_lstm_net


def train_fwbw_conv_lstm(data):
    print('|-- Run model training.')

    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
        assert Config.FWBW_CONV_LSTM_HIGH == 12
        assert Config.FWBW_CONV_LSTM_WIDE == 12
    else:
        day_size = Config.GEANT_DAY_SIZE
        assert Config.FWBW_CONV_LSTM_HIGH == 23
        assert Config.FWBW_CONV_LSTM_WIDE == 23

    print('|--- Splitting train-test set.')
    train_data2d, valid_data2d, test_data2d = prepare_train_valid_test_2d(data=data, day_size=day_size)
    print('|--- Normalizing the train set.')
    train_data_normalized2d, valid_data_normalized2d, _, scalers = data_scalling(train_data2d,
                                                                                 valid_data2d,
                                                                                 test_data2d)

    train_data_normalized = np.reshape(np.copy(train_data_normalized2d), newshape=(train_data_normalized2d.shape[0],
                                                                                   Config.FWBW_CONV_LSTM_WIDE,
                                                                                   Config.FWBW_CONV_LSTM_HIGH))
    valid_data_normalized = np.reshape(np.copy(valid_data_normalized2d), newshape=(valid_data_normalized2d.shape[0],
                                                                                   Config.FWBW_CONV_LSTM_WIDE,
                                                                                   Config.FWBW_CONV_LSTM_HIGH))

    input_shape = (Config.FWBW_CONV_LSTM_STEP,
                   Config.FWBW_CONV_LSTM_WIDE, Config.FWBW_CONV_LSTM_HIGH, Config.FWBW_CONV_LSTM_CHANNEL)

    with tf.device('/device:GPU:{}'.format(Config.GPU)):
        fwbw_conv_lstm_net = build_model(input_shape)

    # --------------------------------------------------------------------------------------------------------------

    # --------------------------------------------Training fw model-------------------------------------------------

    if not Config.FWBW_CONV_LSTM_VALID_TEST or \
            not os.path.isfile(
                fwbw_conv_lstm_net.checkpoints_path + 'weights-{:02d}.hdf5'.format(
                    Config.FWBW_CONV_LSTM_BEST_CHECKPOINT)):
        print('|--- Create offline train set for forward net!')

        trainX, trainY_fw, trainY_bw = create_offline_fwbw_conv_lstm_data_fix_ratio(train_data_normalized,
                                                                                    input_shape,
                                                                                    Config.FWBW_CONV_LSTM_MON_RATIO,
                                                                                    train_data_normalized.std(), 1)
        print('|--- Create offline valid set for forward net!')

        validX, validY_fw, validY_bw = create_offline_fwbw_conv_lstm_data_fix_ratio(valid_data_normalized,
                                                                                    input_shape,
                                                                                    Config.FWBW_CONV_LSTM_MON_RATIO,
                                                                                    train_data_normalized.std(),
                                                                                    1)

        checkpoint_callback = ModelCheckpoint(fwbw_conv_lstm_net.checkpoints_path + "weights-{epoch:02d}.hdf5",
                                              monitor='val_loss', verbose=1,
                                              save_best_only=True,
                                              mode='auto', period=1)

        training_history = fwbw_conv_lstm_net.model.fit(x=trainX,
                                                        y=[trainY_fw, trainY_bw],
                                                        batch_size=Config.FWBW_CONV_LSTM_BATCH_SIZE,
                                                        epochs=Config.FWBW_CONV_LSTM_N_EPOCH,
                                                        callbacks=[checkpoint_callback],
                                                        validation_data=(validX, [validY_fw, validY_bw]),
                                                        shuffle=True,
                                                        verbose=2)

        # Plot the training history
        if training_history is not None:
            fwbw_conv_lstm_net.plot_training_history(training_history)
            # fwbw_conv_lstm_net.save_model_history(training_history)
    else:
        fwbw_conv_lstm_net.load_model_from_check_point(_from_epoch=Config.FWBW_CONV_LSTM_BEST_CHECKPOINT)

    # --------------------------------------------------------------------------------------------------------------

    if not os.path.exists(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                                      Config.ALG, Config.TAG, Config.SCALER)):
        os.makedirs(
            Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME, Config.ALG, Config.TAG, Config.SCALER))

    results_summary = pd.DataFrame(index=range(Config.FWBW_CONV_LSTM_TESTING_TIME),
                                   columns=['No.', 'err', 'r2', 'rmse', 'err_ims', 'r2_ims',
                                            'rmse_ims'])

    results_summary = run_test(valid_data2d, valid_data_normalized2d, fwbw_conv_lstm_net, scalers, results_summary)

    results_summary.to_csv(Config.RESULTS_PATH +
                           '{}-{}-{}-{}/Valid_results.csv'.format(Config.DATA_NAME, Config.ALG, Config.TAG,
                                                                  Config.SCALER),
                           index=False)

    return


def ims_tm_test_data(test_data):
    ims_test_set = np.zeros(
        shape=(test_data.shape[0] - Config.FWBW_CONV_LSTM_IMS_STEP + 1, test_data.shape[1]))

    for i in range(Config.FWBW_CONV_LSTM_IMS_STEP - 1, test_data.shape[0], 1):
        ims_test_set[i - Config.FWBW_CONV_LSTM_IMS_STEP + 1] = test_data[i]

    return ims_test_set


def test_fwbw_conv_lstm(data):
    print('|-- Run model testing.')

    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
        assert Config.FWBW_CONV_LSTM_HIGH == 12
        assert Config.FWBW_CONV_LSTM_WIDE == 12

    else:
        day_size = Config.GEANT_DAY_SIZE
        assert Config.FWBW_CONV_LSTM_HIGH == 23
        assert Config.FWBW_CONV_LSTM_WIDE == 23

    print('|--- Splitting train-test set.')
    train_data2d, valid_data2d, test_data2d = prepare_train_valid_test_2d(data=data, day_size=day_size)
    print('|--- Normalizing the train set.')

    if Config.DATA_NAME == Config.DATA_SETS[0]:
        print('|--- Remove last 3 days in test data.')
        test_data2d = test_data2d[0:-day_size * 3]

    _, _, test_data_normalized2d, scalers = data_scalling(train_data2d,
                                                          valid_data2d,
                                                          test_data2d)
    input_shape = (Config.FWBW_CONV_LSTM_STEP,
                   Config.FWBW_CONV_LSTM_WIDE, Config.FWBW_CONV_LSTM_HIGH, Config.FWBW_CONV_LSTM_CHANNEL)

    with tf.device('/device:GPU:{}'.format(Config.GPU)):
        fwbw_conv_lstm_net = load_trained_models(input_shape, Config.FWBW_CONV_LSTM_BEST_CHECKPOINT)

    if not os.path.exists(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                                      Config.ALG, Config.TAG, Config.SCALER)):
        os.makedirs(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                                Config.ALG,
                                                                Config.TAG,
                                                                Config.SCALER))

    results_summary = pd.DataFrame(index=range(Config.FWBW_CONV_LSTM_TESTING_TIME),
                                   columns=['No.', 'err', 'r2', 'rmse', 'err_ims', 'r2_ims',
                                            'rmse_ims'])

    results_summary = run_test(test_data2d, test_data_normalized2d, fwbw_conv_lstm_net, scalers, results_summary)

    if Config.FWBW_CONV_LSTM_IMS:
        result_file_name = 'Test_results_ims_{}_{}.csv'.format(Config.FWBW_CONV_LSTM_IMS_STEP,
                                                               Config.FWBW_CONV_LSTM_FLOW_SELECTION)
    else:
        result_file_name = 'Test_results_{}.csv'.format(Config.FWBW_CONV_LSTM_FLOW_SELECTION)

    results_summary.to_csv(Config.RESULTS_PATH +
                           '{}-{}-{}-{}/{}'.format(Config.DATA_NAME, Config.ALG, Config.TAG,
                                                   Config.SCALER, result_file_name),
                           index=False)

    return


def prepare_test_set(test_data2d, test_data_normalized2d):
    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    idx = np.random.random_integers(Config.FWBW_CONV_LSTM_STEP, test_data2d.shape[0] - day_size * 2 - 10)

    test_data_normalize = np.copy(test_data_normalized2d[idx:idx + day_size * 2])
    init_data_normalize = np.copy(test_data_normalized2d[idx - Config.FWBW_CONV_LSTM_STEP: idx])
    test_data = test_data2d[idx:idx + day_size * 2]

    return test_data_normalize, init_data_normalize, test_data


def prepare_test_set_last_5days(test_data2d, test_data_normalized2d):
    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    idx = test_data2d.shape[0] - day_size * 5 - 10

    test_data_normalize = np.copy(test_data_normalized2d[idx:idx + day_size * 5])
    init_data_normalize = np.copy(test_data_normalized2d[idx - Config.FWBW_CONV_LSTM_STEP: idx])
    test_data = test_data2d[idx:idx + day_size * 5]

    return test_data_normalize, init_data_normalize, test_data


def run_test(test_data2d, test_data_normalized2d, fwbw_conv_lstm_net, scalers, results_summary):
    err, r2_score, rmse = [], [], []
    err_ims, r2_score_ims, rmse_ims = [], [], []

    for i in range(Config.FWBW_CONV_LSTM_TESTING_TIME):
        print('|--- Run time {}'.format(i))

        test_data_normalize, init_data_normalize, test_data = prepare_test_set_last_5days(test_data2d,
                                                                                          test_data_normalized2d)
        # test_data_normalize, init_data_normalize, test_data = prepare_test_set(test_data2d, test_data_normalized2d)

        init_data_normalize = np.reshape(init_data_normalize, newshape=(init_data_normalize.shape[0],
                                                                        Config.FWBW_CONV_LSTM_WIDE,
                                                                        Config.FWBW_CONV_LSTM_HIGH))
        test_data_normalize = np.reshape(test_data_normalize, newshape=(test_data_normalize.shape[0],
                                                                        Config.FWBW_CONV_LSTM_WIDE,
                                                                        Config.FWBW_CONV_LSTM_HIGH))

        measured_matrix_ims2d = np.zeros((test_data.shape[0] - Config.FWBW_CONV_LSTM_IMS_STEP + 1,
                                          Config.FWBW_CONV_LSTM_WIDE * Config.FWBW_CONV_LSTM_HIGH))

        pred_tm, measured_matrix, ims_tm = predict_fwbw_conv_lstm(initial_data=init_data_normalize,
                                                                  test_data=test_data_normalize,
                                                                  model=fwbw_conv_lstm_net.model)

        pred_tm2d = np.reshape(pred_tm, newshape=(pred_tm.shape[0], pred_tm.shape[1] * pred_tm.shape[2]))

        measured_matrix2d = np.reshape(measured_matrix,
                                       newshape=(measured_matrix.shape[0],
                                                 measured_matrix.shape[1] * measured_matrix.shape[2]))

        pred_tm_invert2d = scalers.inverse_transform(pred_tm2d)

        if np.any(np.isinf(pred_tm_invert2d)):
            raise ValueError('Value is infinity!')
        elif np.any(np.isnan(pred_tm_invert2d)):
            raise ValueError('Value is NaN!')

        err.append(error_ratio(y_true=test_data, y_pred=pred_tm_invert2d, measured_matrix=measured_matrix2d))
        r2_score.append(calculate_r2_score(y_true=test_data, y_pred=pred_tm_invert2d))
        rmse.append(calculate_rmse(y_true=test_data / 1000000, y_pred=pred_tm_invert2d / 1000000))

        if Config.FWBW_CONV_LSTM_IMS:
            # Calculate error for multistep-ahead-prediction

            ims_tm2d = np.reshape(np.copy(ims_tm), newshape=(ims_tm.shape[0], ims_tm.shape[1] * ims_tm.shape[2]))

            ims_tm_invert2d = scalers.inverse_transform(ims_tm2d)

            ims_ytrue2d = ims_tm_test_data(test_data=test_data)

            err_ims.append(error_ratio(y_pred=ims_tm_invert2d,
                                       y_true=ims_ytrue2d,
                                       measured_matrix=measured_matrix_ims2d))

            r2_score_ims.append(calculate_r2_score(y_true=ims_ytrue2d, y_pred=ims_tm_invert2d))
            rmse_ims.append(calculate_rmse(y_true=ims_ytrue2d / 1000000, y_pred=ims_tm_invert2d / 1000000))
        else:
            err_ims.append(0)
            r2_score_ims.append(0)
            rmse_ims.append(0)

        print('Result: err\trmse\tr2 \t\t err_ims\trmse_ims\tr2_ims')
        print('        {}\t{}\t{} \t\t {}\t{}\t{}'.format(err[i], rmse[i], r2_score[i],
                                                          err_ims[i], rmse_ims[i],
                                                                  r2_score_ims[i]))
    results_summary['No.'] = range(Config.FWBW_CONV_LSTM_TESTING_TIME)
    results_summary['err'] = err
    results_summary['r2'] = r2_score
    results_summary['rmse'] = rmse
    results_summary['err_ims'] = err_ims
    results_summary['r2_ims'] = r2_score_ims
    results_summary['rmse_ims'] = rmse_ims

    print('Test: {}-{}-{}-{}'.format(Config.DATA_NAME, Config.ALG, Config.TAG, Config.SCALER))

    print('avg_err: {} - avg_rmse: {} - avg_r2: {}'.format(np.mean(np.array(err)),
                                                           np.mean(np.array(rmse)),
                                                           np.mean(np.array(r2_score))))

    return results_summary
