import os

import numpy as np
import pandas as pd
import tensorflow as tf
from tqdm import tqdm

from Models.CnnLSTM_model import CnnLSTM
from common import Config
from common.DataPreprocessing import prepare_train_valid_test_2d, create_offline_cnnlstm_data_fix_ratio, data_scalling
from common.error_utils import error_ratio, calculate_r2_score, \
    calculate_rmse

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
session = tf.Session(config=config)


def plot_test_data(prefix, raw_data, pred, current_data):
    saving_path = Config.RESULTS_PATH + 'plot_check_conv-lstm/'

    if not os.path.exists(saving_path):
        os.makedirs(saving_path)

    from matplotlib import pyplot as plt
    for flow_x in range(raw_data.shape[1]):
        for flow_y in range(raw_data.shape[2]):
            plt.plot(raw_data[:, flow_x, flow_y], label='Actual')
            plt.plot(pred[:, flow_x, flow_y], label='Pred')
            plt.plot(current_data[:, flow_x, flow_y, 0], label='Current_pred')

            plt.legend()
            plt.savefig(saving_path + '{}_flow_{:02d}-{:02d}.png'.format(prefix, flow_x, flow_y))
            plt.close()


def ims_tm_prediction(init_data_labels, cnnlstm_model):
    multi_steps_tm = np.zeros(shape=(init_data_labels.shape[0] + Config.CNNLSTM_IMS_STEP,
                                     init_data_labels.shape[1], init_data_labels.shape[2], init_data_labels.shape[3]))

    multi_steps_tm[0:init_data_labels.shape[0], :, :, :] = init_data_labels

    for ts_ahead in range(Config.CNNLSTM_IMS_STEP):
        rnn_input = multi_steps_tm[-Config.CNNLSTM_STEP:, :, :, :]  # shape(timesteps, od, od , 2)

        rnn_input = np.expand_dims(rnn_input, axis=0)  # shape(1, timesteps, od, od , 2)

        predictX = cnnlstm_model.predict(rnn_input)  # shape(1, timesteps, od, od , 1)

        predictX = np.squeeze(predictX, axis=0)  # shape(timesteps, od, od , 1)
        predictX = np.squeeze(predictX, axis=3)  # shape(timesteps, od, od)

        predict_tm = predictX[-1, :, :]

        sampling = np.zeros(shape=(Config.CNNLSTM_WIDE, Config.CNNLSTM_HIGH, 1))

        # Calculating the true value for the TM
        new_input = predict_tm

        # Concaternating the new tm to the final results
        # Shape = (12, 12, 2)
        new_input = np.concatenate([np.expand_dims(new_input, axis=2), sampling], axis=2)
        multi_steps_tm[ts_ahead + Config.CNNLSTM_STEP] = new_input  # Shape = (timestep, 12, 12, 2)

    return multi_steps_tm[-1, :, :, 0]


def predict_cnnlstm(initial_data, test_data, cnnlstm_model):
    tf_a = np.array([1.0, 0.0])

    init_labels = np.ones((initial_data.shape[0], initial_data.shape[1], initial_data.shape[2]))

    tm_labels = np.zeros(
        shape=(initial_data.shape[0] + test_data.shape[0], initial_data.shape[1], initial_data.shape[2], 2))
    tm_labels[0:initial_data.shape[0], :, :, 0] = initial_data
    tm_labels[0:init_labels.shape[0], :, :, 1] = init_labels

    ims_tm = np.zeros(
        shape=(test_data.shape[0] - Config.CNNLSTM_IMS_STEP + 1, test_data.shape[1], test_data.shape[2]))
    raw_data = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1], test_data.shape[2]))

    raw_data[0:initial_data.shape[0]] = initial_data
    raw_data[initial_data.shape[0]:] = test_data

    for ts in tqdm(range(test_data.shape[0])):

        if Config.CNNLSTM_IMS and (ts <= test_data.shape[0] - Config.CNNLSTM_IMS_STEP):
            ims_tm[ts] = ims_tm_prediction(init_data_labels=tm_labels[ts:ts + Config.CNNLSTM_STEP, :, :, :],
                                           cnnlstm_model=cnnlstm_model)

        rnn_input = tm_labels[ts:(ts + Config.CNNLSTM_STEP)]

        rnn_input = np.expand_dims(rnn_input, axis=0)

        predictX = cnnlstm_model.predict(rnn_input)  # shape(1, timesteps, #nflows)

        predictX = np.squeeze(predictX, axis=0)  # shape(timesteps, #nflows)
        predict_tm = predictX[-1]

        predict_tm = np.reshape(predict_tm, newshape=(test_data.shape[1], test_data.shape[2]))

        # if ts == 20:
        #     plot_test_data('Plot', raw_data[ts + 1:ts + Config.CNNLSTM_STEP - 1],
        #                    predictX[:-2],
        #                    tm_labels[ts + 1:ts + Config.CNNLSTM_STEP - 1])

        # Selecting next monitored flows randomly
        sampling = np.random.choice(tf_a, size=(test_data.shape[1], test_data.shape[2]),
                                    p=(Config.CNNLSTM_MON_RAIO, 1 - Config.CNNLSTM_MON_RAIO))
        inv_sampling = 1 - sampling

        pred_tm = predict_tm * inv_sampling
        corrected_data = test_data[ts]
        ground_truth = corrected_data * sampling

        # Calculating the true value for the TM
        new_tm = pred_tm + ground_truth

        # Concaternating the new tm to the final results
        tm_labels[ts + Config.CNNLSTM_STEP, :, :, 0] = new_tm  # Shape = (timestep, 12, 12, 2)
        tm_labels[ts + Config.CNNLSTM_STEP, :, :, 1] = sampling  # Shape = (timestep, 12, 12, 2)

    return tm_labels[Config.CNNLSTM_STEP:, :, :, :], ims_tm


def build_model(input_shape):
    print('|--- Build models.')
    alg_name = Config.ALG
    tag = Config.TAG
    data_name = Config.DATA_NAME

    cnnlstm_net = CnnLSTM(input_shape=input_shape,
                          cnn_layers=Config.CNNLSTM_LAYERS,
                          a_filters=Config.CNNLSTM_FILTERS,
                          a_strides=Config.CNNLSTM_STRIDES,
                          dropouts=Config.CNNLSTM_DROPOUTS,
                          kernel_sizes=Config.CNNLSTM_KERNEL_SIZE,
                          rnn_dropouts=Config.CNNLSTM_RNN_DROPOUTS,
                          alg_name=alg_name,
                          tag=tag,
                          check_point=True,
                          saving_path=Config.MODEL_SAVE + '{}-{}-{}-{}/'.format(data_name, alg_name, tag,
                                                                                Config.SCALER))
    print(cnnlstm_net.model.summary())
    cnnlstm_net.plot_models()

    return cnnlstm_net


def load_trained_models(input_shape, best_ckp):
    print('|--- Load trained model')
    cnnlstm_net = build_model(input_shape)
    cnnlstm_net.model.load_weights(cnnlstm_net.checkpoints_path + "weights-{:02d}.hdf5".format(best_ckp))

    return cnnlstm_net


def train_cnnlstm(data, experiment):
    print('|-- Run model training.')
    gpu = Config.GPU

    params = Config.set_comet_params_cnnlstm()

    data_name = Config.DATA_NAME
    if 'Abilene' in data_name:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    print('|--- Splitting train-test set.')
    train_data2d, valid_data2d, test_data2d = prepare_train_valid_test_2d(data=data, day_size=day_size)
    print('|--- Normalizing the train set.')

    train_data_normalized2d, valid_data_normalized2d, _, scalers = data_scalling(train_data2d,
                                                                                 valid_data2d,
                                                                                 test_data2d)

    train_data_normalized = np.reshape(np.copy(train_data_normalized2d), newshape=(train_data_normalized2d.shape[0],
                                                                                   Config.CNNLSTM_WIDE,
                                                                                   Config.CNNLSTM_HIGH))
    valid_data_normalized = np.reshape(np.copy(valid_data_normalized2d), newshape=(valid_data_normalized2d.shape[0],
                                                                                   Config.CNNLSTM_WIDE,
                                                                                   Config.CNNLSTM_HIGH))

    input_shape = (Config.CNNLSTM_STEP,
                   Config.CNNLSTM_WIDE, Config.CNNLSTM_HIGH, Config.CNNLSTM_CHANNEL)

    with tf.device('/device:GPU:{}'.format(gpu)):
        cnnlstm_net = build_model(input_shape)

    if not Config.CNNLSTM_VALID_TEST or not os.path.isfile(
            cnnlstm_net.checkpoints_path + 'weights-{:02d}.hdf5'.format(Config.CNNLSTM_BEST_CHECKPOINT)):

        if os.path.isfile(path=cnnlstm_net.checkpoints_path + 'weights-{:02d}.hdf5'.format(Config.CNNLSTM_N_EPOCH)):
            print('|--- Model exist!')
            cnnlstm_net.load_model_from_check_point(_from_epoch=Config.CNNLSTM_BEST_CHECKPOINT)
        else:
            print('|--- Compile model. Saving path %s --- ' % cnnlstm_net.saving_path)

            # -------------------------------- Create offline training and validating dataset --------------------------
            print('|--- Create offline train set for cnnlstm net!')

            trainX, trainY = create_offline_cnnlstm_data_fix_ratio(train_data_normalized,
                                                                   input_shape, Config.CNNLSTM_MON_RAIO,
                                                                   train_data_normalized.std(),
                                                                   Config.CNNLSTM_DATA_GENERATE_TIME)
            print('|--- Create offline valid set for cnnlstm net!')

            validX, validY = create_offline_cnnlstm_data_fix_ratio(valid_data_normalized,
                                                                   input_shape, Config.CNNLSTM_MON_RAIO,
                                                                   train_data_normalized.std(), 1)
            # ----------------------------------------------------------------------------------------------------------

            # Load model check point
            from_epoch = cnnlstm_net.load_model_from_check_point()
            if from_epoch > 0:
                print('|--- Continue training model from epoch %i --- ' % from_epoch)
                training_history = cnnlstm_net.model.fit(x=trainX,
                                                         y=trainY,
                                                         batch_size=Config.CNNLSTM_BATCH_SIZE,
                                                         epochs=Config.CNNLSTM_N_EPOCH,
                                                         callbacks=cnnlstm_net.callbacks_list,
                                                         validation_data=(validX, validY),
                                                         shuffle=True,
                                                         initial_epoch=from_epoch,
                                                         verbose=2)
            else:
                print('|--- Training new model.')
                training_history = cnnlstm_net.model.fit(x=trainX,
                                                         y=trainY,
                                                         batch_size=Config.CNNLSTM_BATCH_SIZE,
                                                         epochs=Config.CNNLSTM_N_EPOCH,
                                                         callbacks=cnnlstm_net.callbacks_list,
                                                         validation_data=(validX, validY),
                                                         shuffle=True,
                                                         verbose=2)

            # Plot the training history
            if training_history is not None:
                cnnlstm_net.plot_training_history(training_history)
    else:
        print('|--- Test valid set')
        cnnlstm_net.load_model_from_check_point(_from_epoch=Config.CNNLSTM_BEST_CHECKPOINT)
    print('---------------------------------CNNLSTM_NET SUMMARY---------------------------------')
    print(cnnlstm_net.model.summary())

    run_test(experiment, valid_data2d, valid_data_normalized2d, train_data_normalized2d[-Config.CNNLSTM_STEP:],
             cnnlstm_net, params, scalers)
    return


def ims_tm_test_data(test_data):
    ims_test_set = np.zeros(
        shape=(test_data.shape[0] - Config.LSTM_IMS_STEP + 1, test_data.shape[1]))

    for i in range(Config.LSTM_IMS_STEP - 1, test_data.shape[0], 1):
        ims_test_set[i - Config.LSTM_IMS_STEP + 1] = test_data[i]

    return ims_test_set


def test_cnnlstm(data, experiment):
    print('|-- Run model testing.')
    params = Config.set_comet_params_cnnlstm()
    data_name = Config.DATA_NAME
    if 'Abilene' in data_name:
        day_size = Config.ABILENE_DAY_SIZE
        assert Config.CNNLSTM_WIDE == 12
        assert Config.CNNLSTM_HIGH == 12
    else:
        day_size = Config.GEANT_DAY_SIZE
        assert Config.CNNLSTM_WIDE == 23
        assert Config.CNNLSTM_HIGH == 23

    if not Config.ALL_DATA:
        data = data[0:Config.NUM_DAYS * day_size]

    print('|--- Splitting train-test set.')
    train_data2d, valid_data2d, test_data2d = prepare_train_valid_test_2d(data=data, day_size=day_size)
    print('|--- Normalizing the train set.')

    if 'Abilene' in data_name:
        print('|--- Remove last 3 days in test data.')
        test_data2d = test_data2d[0:-day_size * 3]

    _, valid_data_normalized2d, test_data_normalized2d, scalers = data_scalling(train_data2d,
                                                                                valid_data2d,
                                                                                test_data2d)

    input_shape = (Config.CNNLSTM_STEP,
                   Config.CNNLSTM_WIDE, Config.CNNLSTM_HIGH, Config.CNNLSTM_CHANNEL)

    cnnlstm_net = load_trained_models(input_shape, Config.CNNLSTM_BEST_CHECKPOINT)
    run_test(experiment, test_data2d, test_data_normalized2d, valid_data_normalized2d[-Config.CNNLSTM_STEP:],
             cnnlstm_net, params, scalers)

    return


def run_test(experiment, test_data2d, test_data_normalized2d, init_data2d, cnnlstm_net, params, scalers):
    alg_name = Config.ALG
    tag = Config.TAG
    data_name = Config.DATA_NAME

    results_summary = pd.DataFrame(index=range(Config.CNNLSTM_TESTING_TIME),
                                   columns=['No.', 'err', 'r2', 'rmse', 'err_ims', 'r2_ims', 'rmse_ims'])

    err, r2_score, rmse = [], [], []
    err_ims, r2_score_ims, rmse_ims = [], [], []

    measured_matrix_ims2d = np.zeros((test_data2d.shape[0] - Config.CNNLSTM_IMS_STEP + 1,
                                      Config.CNNLSTM_WIDE * Config.CNNLSTM_HIGH))

    if not os.path.isfile(Config.RESULTS_PATH + 'ground_true_{}.npy'.format(data_name)):
        np.save(Config.RESULTS_PATH + 'ground_true_{}.npy'.format(data_name),
                test_data2d)

    if not os.path.isfile(Config.RESULTS_PATH + 'ground_true_scaled_{}_{}.npy'.format(data_name, Config.SCALER)):
        np.save(Config.RESULTS_PATH + 'ground_true_scaled_{}_{}.npy'.format(data_name, Config.SCALER),
                test_data_normalized2d)

    if not os.path.exists(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(data_name,
                                                                      alg_name, tag, Config.SCALER)):
        os.makedirs(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(data_name, alg_name, tag, Config.SCALER))

    for i in range(Config.CNNLSTM_TESTING_TIME):
        print('|--- Run time {}'.format(i))
        init_data = np.reshape(init_data2d, newshape=(init_data2d.shape[0],
                                                      Config.CNNLSTM_WIDE,
                                                      Config.CNNLSTM_HIGH))
        test_data_normalized = np.reshape(test_data_normalized2d, newshape=(test_data_normalized2d.shape[0],
                                                                            Config.CNNLSTM_WIDE,
                                                                            Config.CNNLSTM_HIGH))

        tm_labels, ims_tm = predict_cnnlstm(initial_data=init_data,
                                            test_data=test_data_normalized,
                                            cnnlstm_model=cnnlstm_net.model)

        pred_tm = tm_labels[:, :, :, 0]
        measured_matrix = tm_labels[:, :, :, 1]

        pred_tm2d = np.reshape(np.copy(pred_tm), newshape=(pred_tm.shape[0], pred_tm.shape[1] * pred_tm.shape[2]))
        measured_matrix2d = np.reshape(np.copy(measured_matrix),
                                       newshape=(measured_matrix.shape[0],
                                                 measured_matrix.shape[1] * measured_matrix.shape[2]))
        np.save(Config.RESULTS_PATH + '{}-{}-{}-{}/pred_scaled-{}.npy'.format(data_name, alg_name, tag,
                                                                              Config.SCALER, i),
                pred_tm2d)

        pred_tm_invert2d = scalers.inverse_transform(pred_tm2d)

        err.append(error_ratio(y_true=test_data2d, y_pred=pred_tm_invert2d, measured_matrix=measured_matrix2d))
        r2_score.append(calculate_r2_score(y_true=test_data2d, y_pred=pred_tm_invert2d))
        rmse.append(calculate_rmse(y_true=test_data2d / 1000000, y_pred=pred_tm_invert2d / 1000000))

        if Config.CNNLSTM_IMS:
            ims_tm2d = np.reshape(np.copy(ims_tm), newshape=(ims_tm.shape[0], ims_tm.shape[1] * ims_tm.shape[2]))

            ims_tm_invert2d = scalers.inverse_transform(ims_tm2d)

            ims_ytrue2d = ims_tm_test_data(test_data=test_data2d)

            err_ims.append(error_ratio(y_pred=ims_tm_invert2d,
                                       y_true=ims_ytrue2d,
                                       measured_matrix=measured_matrix_ims2d))

            r2_score_ims.append(calculate_r2_score(y_true=ims_ytrue2d, y_pred=ims_tm_invert2d))
            rmse_ims.append(calculate_rmse(y_true=ims_ytrue2d / 1000000, y_pred=ims_tm_invert2d / 1000000))
        else:
            err_ims.append(0)
            r2_score_ims.append(0)
            rmse_ims.append(0)

        np.save(Config.RESULTS_PATH + '{}-{}-{}-{}/pred-{}.npy'.format(data_name, alg_name, tag,
                                                                       Config.SCALER, i),
                pred_tm_invert2d)
        np.save(Config.RESULTS_PATH + '{}-{}-{}-{}/measure-{}.npy'.format(data_name, alg_name, tag,
                                                                          Config.SCALER, i),
                measured_matrix2d)

        print('Result: err\trmse\tr2 \t\t err_ims\trmse_ims\tr2_ims')
        print('        {}\t{}\t{} \t\t {}\t{}\t{}'.format(err[i], rmse[i], r2_score[i],
                                                          err_ims[i], rmse_ims[i],
                                                          r2_score_ims[i]))

    results_summary['No.'] = range(Config.CNNLSTM_TESTING_TIME)
    results_summary['err'] = err
    results_summary['r2'] = r2_score
    results_summary['rmse'] = rmse
    results_summary['err_ims'] = err_ims
    results_summary['r2_ims'] = r2_score_ims
    results_summary['rmse_ims'] = rmse_ims

    results_summary.to_csv(Config.RESULTS_PATH + '{}-{}-{}-{}/results.csv'.format(data_name,
                                                                                  alg_name, tag, Config.SCALER),
                           index=False)
    print('Test: {}-{}-{}-{}'.format(data_name, alg_name, tag, Config.SCALER))
    print('avg_err: {} - avg_rmse: {} - avg_r2: {}'.format(np.mean(np.array(err)),
                                                           np.mean(np.array(rmse)),
                                                           np.mean(np.array(r2_score))))

    return