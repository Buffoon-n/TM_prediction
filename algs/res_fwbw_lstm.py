import os

import numpy as np
import pandas as pd
import tensorflow as tf
from tqdm import tqdm

from Models.lstm.fwbw_lstm_supervisor import fwbw_lstm_model
from common import Config_res_fwbw_lstm as Config
from common.DataPreprocessing import prepare_train_valid_test_2d, data_scalling, create_offline_res_fwbw_lstm
from common.error_utils import error_ratio, calculate_r2_score, calculate_rmse

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
session = tf.Session(config=config)


def plot_test_data(prefix, raw_data, pred_bw, current_data):
    saving_path = Config.RESULTS_PATH + 'plot_check_fwbw_lstm/'

    if not os.path.exists(saving_path):
        os.makedirs(saving_path)

    from matplotlib import pyplot as plt
    for flow_id in range(raw_data.shape[1]):
        plt.plot(raw_data[:, flow_id], label='Actual')
        plt.plot(pred_bw[:, flow_id], label='Pred_bw')
        plt.plot(current_data[:, flow_id], label='Current_pred')

        plt.legend()
        plt.savefig(saving_path + '{}_flow_{:02d}.png'.format(prefix, flow_id))
        plt.close()


def prepare_input_online_prediction(data, labels):
    labels = labels.astype(int)
    data_x_1 = np.zeros(shape=(data.shape[1], Config.RES_FWBW_LSTM_STEP, Config.RES_FWBW_LSTM_FEATURES))
    data_x_2 = np.zeros(shape=(data.shape[1], Config.RES_FWBW_LSTM_STEP, 1))
    for flow_id in range(data.shape[1]):
        x = data[:, flow_id]
        label = labels[:, flow_id]

        data_x_1[flow_id, :, 0] = x
        data_x_1[flow_id, :, 1] = label

        data_x_2[flow_id] = np.reshape(x, newshape=(Config.RES_FWBW_LSTM_STEP, 1))

    return data_x_1, data_x_2


def calculate_forward_backward_loss(labels, pred_forward, pred_backward, rnn_input):
    l_fw, l_bw = [], []
    for flow_id in range(rnn_input.shape[0]):
        idx_fw = labels[flow_id, 1:]

        l_fw.append(error_ratio(y_true=rnn_input[flow_id, 1:][idx_fw == 1.0],
                                y_pred=pred_forward[flow_id, :-1][idx_fw == 1.0],
                                measured_matrix=np.zeros(idx_fw[idx_fw == 1.0].shape)))
        idx_bw = labels[flow_id, 0:-1]

        l_bw.append(error_ratio(y_true=rnn_input[flow_id, :-1][idx_bw == 1.0],
                                y_pred=pred_backward[flow_id, 1:][idx_bw == 1.0],
                                measured_matrix=np.zeros(idx_bw[idx_bw == 1.0].shape)))

    l_fw = np.array(l_fw)
    l_fw[l_fw == 0.] = np.max(l_fw)
    l_bw = np.array(l_bw)
    l_bw[l_bw == 0.] = np.max(l_bw)

    return l_fw, l_bw


def calculate_confident_factors(labels, forward_loss, backward_loss):
    measured_count = np.sum(labels, axis=1).astype(float)  # shape = (#n_flows,)
    _eta = measured_count / Config.RES_FWBW_LSTM_STEP

    alpha = 1.0 - _eta  # shape = (#nflows,)
    alpha = np.tile(np.expand_dims(alpha, axis=1), (1, Config.RES_FWBW_LSTM_STEP))  # shape = (#nflows, #steps)

    rho = np.zeros((labels.shape[0], Config.RES_FWBW_LSTM_STEP))
    mu = np.zeros((labels.shape[0], Config.RES_FWBW_LSTM_STEP))
    for j in range(0, Config.RES_FWBW_LSTM_STEP):
        _rho = (np.sum(labels[:, j:], axis=1)) / float(Config.RES_FWBW_LSTM_STEP - j)
        _mu = (np.sum(labels[:, :(j + 1)], axis=1)) / float(j + 1)
        rho[:, j] = _rho
        mu[:, j] = _mu

    forward_loss = np.tile(np.expand_dims(forward_loss, axis=1), (1, Config.RES_FWBW_LSTM_STEP))
    backward_loss = np.tile(np.expand_dims(backward_loss, axis=1), (1, Config.RES_FWBW_LSTM_STEP))

    beta = (backward_loss + mu) * (1.0 - alpha) / (forward_loss + backward_loss + mu + rho)

    gamma = (forward_loss + rho) * (1.0 - alpha) / (forward_loss + backward_loss + mu + rho)

    return alpha, beta, gamma


def data_correction(rnn_input, pred_forward, pred_backward, labels):
    rnn_input = np.copy(rnn_input.T)  # shape = (#n_flows, #time-steps)
    labels = np.copy(labels.T)  # Shape(#n_flows, #time-step)

    forward_loss, backward_loss = calculate_forward_backward_loss(labels=labels,
                                                                  pred_forward=pred_forward,
                                                                  pred_backward=pred_backward,
                                                                  rnn_input=rnn_input)

    alpha, beta, gamma = calculate_confident_factors(labels=labels,
                                                     forward_loss=forward_loss,
                                                     backward_loss=backward_loss)

    considered_forward = pred_forward[:, :-2]
    considered_backward = pred_backward[:, 2:]
    considered_rnn_input = rnn_input[:, 1:-1]

    alpha = alpha[:, 1:-1]
    beta = beta[:, 1:-1]
    gamma = gamma[:, 1:-1]

    updated_rnn_input = considered_backward * gamma + considered_forward * beta + considered_rnn_input * alpha
    # updated_rnn_input = (considered_backward  + considered_forward  + considered_rnn_input)/3.0

    # Return corredted input shape(#time-step, #n_flows)
    return updated_rnn_input.T


def data_correction_v2(rnn_input, pred_backward, labels):
    # Shape = (#n_flows, #time-steps)
    _rnn_input = np.copy(rnn_input.T)
    _labels = np.copy(labels.T)

    beta = np.zeros(_rnn_input.shape)
    for i in range(_rnn_input.shape[1]):
        _b = np.arange(1, _rnn_input.shape[1] - i + 1)
        beta[:, i] = (np.sum(_labels[:, i:], axis=1) / (_rnn_input.shape[1] - i)) * \
                     (np.sum(np.power((_labels[:, i:] / (_rnn_input.shape[1] - i)), _b), axis=1))

    considered_backward = pred_backward[:, 2:]
    considered_rnn_input = _rnn_input[:, 1:-1]

    alpha = 1.0 - beta

    alpha = alpha[:, 1:-1]
    beta = beta[:, 1:-1]
    # gamma = gamma[:, 1:-1]

    # corrected_data = considered_rnn_input * alpha + considered_rnn_input * beta + considered_backward * gamma
    corrected_data = considered_rnn_input * alpha + considered_backward * beta

    return corrected_data.T


def predict_fwbw_lstm_ims(initial_data, initial_labels, model):
    ims_tm_pred = np.zeros(shape=(initial_data.shape[0] + Config.RES_FWBW_LSTM_IMS_STEP, initial_data.shape[1]))
    ims_tm_pred[0:Config.RES_FWBW_LSTM_STEP, :] = initial_data

    labels = np.zeros(shape=(initial_data.shape[0] + Config.RES_FWBW_LSTM_IMS_STEP, initial_data.shape[1]))
    labels[0:Config.LSTM_STEP, :] = initial_labels

    for ts_ahead in range(Config.RES_FWBW_LSTM_IMS_STEP):
        rnn_input = prepare_input_online_prediction(data=ims_tm_pred[ts_ahead:ts_ahead + Config.RES_FWBW_LSTM_STEP],
                                                    labels=labels[ts_ahead:ts_ahead + Config.RES_FWBW_LSTM_STEP])
        fw_outputs, bw_outputs = model.predict(rnn_input)

        fw_outputs = np.squeeze(fw_outputs, axis=2)  # Shape(#n_flows, #time-steps)
        bw_outputs = np.squeeze(bw_outputs, axis=2)

        pred_next_tm = np.copy(fw_outputs[:, -1])

        corrected_data = data_correction(rnn_input=np.copy(ims_tm_pred[ts_ahead: ts_ahead + Config.RES_FWBW_LSTM_STEP]),
                                         pred_forward=fw_outputs,
                                         pred_backward=bw_outputs,
                                         labels=labels[ts_ahead: ts_ahead + Config.RES_FWBW_LSTM_STEP])

        measured_data = ims_tm_pred[ts_ahead + 1:ts_ahead + Config.RES_FWBW_LSTM_STEP - 1] * labels[
                                                                                             ts_ahead + 1:ts_ahead + Config.RES_FWBW_LSTM_STEP - 1]
        pred_data = corrected_data * (1.0 - labels[ts_ahead + 1:ts_ahead + Config.RES_FWBW_LSTM_STEP - 1])
        ims_tm_pred[ts_ahead + 1:ts_ahead + Config.RES_FWBW_LSTM_STEP - 1] = measured_data + pred_data

        ims_tm_pred[ts_ahead + Config.RES_FWBW_LSTM_STEP] = pred_next_tm

    return ims_tm_pred[-1, :]


def predict_fwbw_lstm(initial_data, test_data, model):
    tf_a = np.array([1.0, 0.0])

    # Initialize traffic matrix data
    tm_pred = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1]))
    tm_pred[0:initial_data.shape[0]] = initial_data

    # Initialize traffic matrix data w/o data correction
    tm_pred_no_updated = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1]))
    tm_pred_no_updated[0:initial_data.shape[0]] = initial_data

    # Initialize measurement matrix
    labels = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1]))
    labels[0:initial_data.shape[0]] = np.ones(shape=initial_data.shape)

    ims_tm = np.zeros(shape=(test_data.shape[0] - Config.RES_FWBW_LSTM_IMS_STEP + 1, test_data.shape[1]))

    raw_data = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1]))

    raw_data[0:initial_data.shape[0]] = initial_data
    raw_data[initial_data.shape[0]:] = test_data

    # Predict the TM from time slot look_back
    for ts in tqdm(range(test_data.shape[0])):

        if Config.RES_FWBW_LSTM_IMS and (ts <= test_data.shape[0] - Config.RES_FWBW_LSTM_IMS_STEP):
            ims_tm[ts] = predict_fwbw_lstm_ims(initial_data=tm_pred[ts: ts + Config.RES_FWBW_LSTM_STEP],
                                               initial_labels=labels[ts: ts + Config.RES_FWBW_LSTM_STEP],
                                               model=model)

        # Create 3D input for rnn
        # Shape(#n_flows, #time-steps, #features)
        rnn_input = prepare_input_online_prediction(data=tm_pred[ts: ts + Config.RES_FWBW_LSTM_STEP],
                                                    labels=labels[ts: ts + Config.RES_FWBW_LSTM_STEP])

        rnn_input_wo_corr = prepare_input_online_prediction(data=tm_pred_no_updated[ts: ts + Config.RES_FWBW_LSTM_STEP],
                                                            labels=labels[ts: ts + Config.RES_FWBW_LSTM_STEP])

        fw_outputs, bw_outputs = model.predict(rnn_input)  # Shape(#n_flows, #time-step, 1)

        fw_outputs = np.squeeze(fw_outputs, axis=2)  # Shape(#n_flows, #time-steps)
        bw_outputs = np.squeeze(bw_outputs, axis=2)

        pred_next_tm = np.copy(fw_outputs[:, -1])

        # For comparing tm prediction w/o data correction
        _fw_outputs, _ = model.predict(rnn_input_wo_corr)
        _fw_outputs = np.squeeze(_fw_outputs, axis=2)
        pred_next_tm_wo_corr = np.copy(_fw_outputs[:, -1])

        # Data Correction: Shape(#time-steps, flows) for [ts+1 : ts + Config.RES_FWBW_LSTM_STEP - 1]
        corrected_data = data_correction(rnn_input=np.copy(tm_pred[ts: ts + Config.RES_FWBW_LSTM_STEP]),
                                         pred_forward=fw_outputs,
                                         pred_backward=bw_outputs,
                                         labels=labels[ts: ts + Config.RES_FWBW_LSTM_STEP])

        measured_data = tm_pred[ts + 1:ts + Config.RES_FWBW_LSTM_STEP - 1] * labels[
                                                                             ts + 1:ts + Config.RES_FWBW_LSTM_STEP - 1]
        pred_data = corrected_data * (1.0 - labels[ts + 1:ts + Config.RES_FWBW_LSTM_STEP - 1])
        tm_pred[ts + 1:ts + Config.RES_FWBW_LSTM_STEP - 1] = measured_data + pred_data

        # Partial monitoring
        sampling = np.random.choice(tf_a, size=(test_data.shape[1]),
                                    p=[Config.RES_FWBW_LSTM_MON_RAIO, 1 - Config.RES_FWBW_LSTM_MON_RAIO])

        new_input = pred_next_tm * (1.0 - sampling) + test_data[ts] * sampling
        _new_input = pred_next_tm_wo_corr * (1.0 - sampling) + test_data[ts] * sampling

        tm_pred[ts + Config.RES_FWBW_LSTM_STEP] = new_input
        tm_pred_no_updated[ts + Config.RES_FWBW_LSTM_STEP] = _new_input
        labels[ts + Config.RES_FWBW_LSTM_STEP] = sampling

    return tm_pred[Config.RES_FWBW_LSTM_STEP:], labels[Config.RES_FWBW_LSTM_STEP:], ims_tm, \
           tm_pred_no_updated[Config.RES_FWBW_LSTM_STEP:]


def calculate_consecutive_loss(measured_matrix):
    """

    :param measured_matrix: shape(#n_flows, #time-steps)
    :return: consecutive_losses: shape(#n_flows)
    """

    consecutive_losses = []
    for flow_id in range(measured_matrix.shape[0]):
        flows_labels = measured_matrix[flow_id, :]
        if flows_labels[-1] == 1:
            consecutive_losses.append(1)
        else:
            measured_idx = np.argwhere(flows_labels == 1)
            if measured_idx.size == 0:
                consecutive_losses.append(measured_matrix.shape[1])
            else:
                consecutive_losses.append(measured_matrix.shape[1] - measured_idx[-1][0])

    consecutive_losses = np.asarray(consecutive_losses)
    return consecutive_losses


def set_measured_flow(rnn_input, pred_forward, labels, ):
    """

    :param rnn_input: shape(#n_flows, #time-steps)
    :param pred_forward: shape(#n_flows, #time-steps)
    :param labels: shape(n_flows, #time-steps)
    :return:
    """

    n_flows = rnn_input.shape[0]

    fw_losses = []
    for flow_id in range(rnn_input.shape[0]):
        idx_fw = labels[flow_id, 1:]

        fw_losses.append(error_ratio(y_true=rnn_input[flow_id, 1:][idx_fw == 1.0],
                                     y_pred=pred_forward[flow_id, :-1][idx_fw == 1.0],
                                     measured_matrix=np.zeros(idx_fw[idx_fw == 1.0].shape)))

    fw_losses = np.array(fw_losses)
    fw_losses[fw_losses == 0.] = np.max(fw_losses)

    w = calculate_flows_weights(rnn_input=rnn_input,
                                fw_losses=fw_losses,
                                measured_matrix=labels)

    sampling = np.zeros(shape=n_flows)
    m = int(Config.RES_FWBW_LSTM_MON_RAIO * n_flows)

    w = w.flatten()
    sorted_idx_w = np.argsort(w)
    sampling[sorted_idx_w[:m]] = 1

    return sampling


def calculate_flows_weights(rnn_input, fw_losses, measured_matrix):
    """

    :param rnn_input: shape(#n_flows, #time-steps)
    :param fw_losses: shape(#n_flows)
    :param measured_matrix: shape(#n_flows, #time-steps)
    :return: w: flow weight shape(#n_flows)
    """

    cl = calculate_consecutive_loss(measured_matrix).astype(float)

    flows_stds = np.std(rnn_input, axis=1)

    w = 1 / (fw_losses * Config.RES_FWBW_LSTM_HYPERPARAMS[0] +
             cl * Config.RES_FWBW_LSTM_HYPERPARAMS[1] +
             flows_stds * Config.RES_FWBW_LSTM_HYPERPARAMS[2])

    return w


def predict_fwbw_lstm_v2(initial_data, test_data, model):
    tf_a = np.array([1.0, 0.0])

    # Initialize traffic matrix data
    tm_pred = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1]))
    tm_pred[0:initial_data.shape[0]] = initial_data

    # Initialize traffic matrix data w/o data correction
    # tm_pred_no_updated = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1]))
    # tm_pred_no_updated[0:initial_data.shape[0]] = initial_data

    # Initialize measurement matrix
    labels = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1]))
    labels[0:initial_data.shape[0]] = np.ones(shape=initial_data.shape)

    # Forward losses
    ims_tm = np.zeros(shape=(test_data.shape[0] - Config.RES_FWBW_LSTM_IMS_STEP + 1, test_data.shape[1]))

    raw_data = np.zeros(shape=(initial_data.shape[0] + test_data.shape[0], test_data.shape[1]))

    raw_data[0:initial_data.shape[0]] = initial_data
    raw_data[initial_data.shape[0]:] = test_data

    # Predict the TM from time slot look_back
    for ts in tqdm(range(test_data.shape[0])):

        if Config.RES_FWBW_LSTM_IMS and (ts <= test_data.shape[0] - Config.RES_FWBW_LSTM_IMS_STEP):
            ims_tm[ts] = predict_fwbw_lstm_ims(initial_data=tm_pred[ts: ts + Config.RES_FWBW_LSTM_STEP],
                                               initial_labels=labels[ts: ts + Config.RES_FWBW_LSTM_STEP],
                                               model=model)

        # Create 3D input for rnn
        # Shape(#n_flows, #time-steps, #features)
        rnn_input_1, rnn_input_2 = prepare_input_online_prediction(data=tm_pred[ts: ts + Config.RES_FWBW_LSTM_STEP],
                                                                   labels=labels[ts: ts + Config.RES_FWBW_LSTM_STEP])

        fw_outputs, bw_outputs = model.predict([rnn_input_1, rnn_input_2])  # Shape(#n_flows, #time-step)

        # fw_outputs = np.squeeze(fw_outputs, axis=2)  # Shape(#n_flows, #time-steps)
        # bw_outputs = np.squeeze(bw_outputs, axis=2)

        pred_next_tm = np.copy(fw_outputs[:, -1])

        # For comparing tm prediction w/o data correction
        # _fw_outputs, _ = model.predict(rnn_input_wo_corr)
        # _fw_outputs = np.squeeze(_fw_outputs, axis=2)
        # pred_next_tm_wo_corr = np.copy(_fw_outputs[:, -1])

        # if ts == 100:
        #     plot_test_data('fwbw-lstm', raw_data[ts: ts + Config.RES_FWBW_LSTM_STEP],
        #                    bw_outputs.T, tm_pred[ts: ts + Config.RES_FWBW_LSTM_STEP])

        # Data Correction: Shape(#time-steps, flows) for [ts+1 : ts + Config.RES_FWBW_LSTM_STEP - 1]
        corrected_data = data_correction_v2(rnn_input=np.copy(tm_pred[ts: ts + Config.RES_FWBW_LSTM_STEP]),
                                            pred_backward=bw_outputs,
                                            labels=labels[ts: ts + Config.RES_FWBW_LSTM_STEP])

        measured_data = tm_pred[ts + 1:ts + Config.RES_FWBW_LSTM_STEP - 1] * labels[
                                                                             ts + 1:ts + Config.RES_FWBW_LSTM_STEP - 1]
        pred_data = corrected_data * (1.0 - labels[ts + 1:ts + Config.RES_FWBW_LSTM_STEP - 1])
        tm_pred[ts + 1:ts + Config.RES_FWBW_LSTM_STEP - 1] = measured_data + pred_data

        # Partial monitoring
        if Config.RES_FWBW_LSTM_RANDOM_ACTION:
            sampling = np.random.choice(tf_a, size=(test_data.shape[1]),
                                        p=[Config.RES_FWBW_LSTM_MON_RAIO, 1 - Config.RES_FWBW_LSTM_MON_RAIO])
        else:
            sampling = set_measured_flow(rnn_input=np.copy(tm_pred[ts: ts + Config.RES_FWBW_LSTM_STEP].T),
                                         pred_forward=fw_outputs,
                                         labels=labels[ts: ts + Config.RES_FWBW_LSTM_STEP].T)

        new_input = pred_next_tm * (1.0 - sampling) + test_data[ts] * sampling
        # _new_input = pred_next_tm_wo_corr * (1.0 - sampling) + test_data[ts] * sampling

        tm_pred[ts + Config.RES_FWBW_LSTM_STEP] = new_input
        # tm_pred_no_updated[ts + Config.RES_FWBW_LSTM_STEP] = _new_input
        labels[ts + Config.RES_FWBW_LSTM_STEP] = sampling

    return tm_pred[Config.RES_FWBW_LSTM_STEP:], labels[Config.RES_FWBW_LSTM_STEP:], ims_tm


def build_model(input_shape):
    print('|--- Build models res-fwbw-lstm.')

    # fwbw-lstm model
    fwbw_net = fwbw_lstm_model(input_shape=input_shape,
                               hidden=Config.RES_FWBW_LSTM_HIDDEN_UNIT,
                               drop_out=Config.RES_FWBW_LSTM_DROPOUT,
                               alg_name=Config.ALG, tag=Config.TAG, check_point=True,
                               saving_path=Config.MODEL_SAVE + '{}-{}-{}-{}/'.format(Config.DATA_NAME, Config.ALG,
                                                                                     Config.TAG, Config.SCALER))
    fwbw_net.construct_res_fwbw_lstm()
    print(fwbw_net.model.summary())
    fwbw_net.plot_models()
    return fwbw_net


def load_trained_models(input_shape, ckp):
    fwbw_net = build_model(input_shape)
    print('|--- Load trained model from: {}'.format(fwbw_net.checkpoints_path))
    fwbw_net.model.load_weights(fwbw_net.checkpoints_path + "weights-{:02d}.hdf5".format(ckp))

    return fwbw_net


def train_res_fwbw_lstm(data):
    print('|-- Run model training fwbw_lstm.')

    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    print('|--- Splitting train-test set.')
    train_data2d, valid_data2d, test_data2d = prepare_train_valid_test_2d(data=data, day_size=day_size)
    print('|--- Normalizing the train set.')
    train_data_normalized2d, valid_data_normalized2d, _, scalers = data_scalling(train_data2d,
                                                                                 valid_data2d,
                                                                                 test_data2d)

    input_shape = (Config.RES_FWBW_LSTM_STEP, Config.RES_FWBW_LSTM_FEATURES)

    with tf.device('/device:GPU:{}'.format(Config.GPU)):
        fwbw_net = build_model(input_shape)

    # --------------------------------------------------------------------------------------------------------------

    # --------------------------------------------Training fw model-------------------------------------------------

    if not Config.RES_FWBW_LSTM_VALID_TEST or \
            not os.path.isfile(
                fwbw_net.checkpoints_path + 'weights-{:02d}.hdf5'.format(Config.RES_FWBW_LSTM_BEST_CHECKPOINT)):
        print('|--- Compile model. Saving path %s --- ' % fwbw_net.saving_path)
        # -------------------------------- Create offline training and validating dataset --------------------------

        print('|--- Create offline train set for forward net!')

        trainX_1, trainX_2, trainY_1, trainY_2 = create_offline_res_fwbw_lstm(train_data_normalized2d,
                                                                              input_shape,
                                                                              Config.RES_FWBW_LSTM_MON_RAIO,
                                                                              train_data_normalized2d.std())
        print('|--- Create offline valid set for forward net!')

        validX_1, validX_2, validY_1, validY_2 = create_offline_res_fwbw_lstm(valid_data_normalized2d,
                                                                              input_shape,
                                                                              Config.RES_FWBW_LSTM_MON_RAIO,
                                                                              train_data_normalized2d.std())

        # Load model check point
        from_epoch = fwbw_net.load_model_from_check_point()
        if from_epoch > 0:
            print('|--- Continue training forward model from epoch %i --- ' % from_epoch)
            training_fw_history = fwbw_net.model.fit(x=[trainX_1, trainX_2],
                                                     y=[trainY_1, trainY_2],
                                                     batch_size=1024,
                                                     epochs=Config.RES_FWBW_LSTM_N_EPOCH,
                                                     callbacks=fwbw_net.callbacks_list,
                                                     validation_data=([validX_1, validX_2], [validY_1, validY_2]),
                                                     shuffle=True,
                                                     initial_epoch=from_epoch,
                                                     verbose=2)
        else:
            print('|--- Training new forward model.')

            training_fw_history = fwbw_net.model.fit(x=[trainX_1, trainX_2],
                                                     y=[trainY_1, trainY_2],
                                                     batch_size=1024,
                                                     epochs=Config.RES_FWBW_LSTM_N_EPOCH,
                                                     callbacks=fwbw_net.callbacks_list,
                                                     validation_data=([validX_1, validX_2], [validY_1, validY_2]),
                                                     shuffle=True,
                                                     verbose=2)

        # Plot the training history
        if training_fw_history is not None:
            fwbw_net.plot_training_history(training_fw_history)
            fwbw_net.save_model_history(training_fw_history)

    else:
        fwbw_net.load_model_from_check_point(_from_epoch=Config.RES_FWBW_LSTM_BEST_CHECKPOINT)
    # --------------------------------------------------------------------------------------------------------------

    if not os.path.exists(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                                      Config.ALG, Config.TAG, Config.SCALER)):
        os.makedirs(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                                Config.ALG, Config.TAG, Config.SCALER))
    results_summary = pd.DataFrame(index=range(Config.RES_FWBW_LSTM_TESTING_TIME),
                                   columns=['No.', 'err', 'r2', 'rmse', 'err_ims', 'r2_ims',
                                            'rmse_ims'])

    results_summary = run_test(valid_data2d, valid_data_normalized2d, fwbw_net, scalers, results_summary)

    results_summary.to_csv(Config.RESULTS_PATH +
                           '{}-{}-{}-{}/Valid_results.csv'.format(Config.DATA_NAME, Config.ALG, Config.TAG,
                                                                  Config.SCALER),
                           index=False)

    return


def ims_tm_test_data(test_data):
    ims_test_set = np.zeros(
        shape=(test_data.shape[0] - Config.RES_FWBW_LSTM_IMS_STEP + 1, test_data.shape[1]))

    for i in range(Config.RES_FWBW_LSTM_IMS_STEP - 1, test_data.shape[0], 1):
        ims_test_set[i - Config.RES_FWBW_LSTM_IMS_STEP + 1] = test_data[i]

    return ims_test_set


def test_res_fwbw_lstm(data):
    print('|-- Run model testing.')
    gpu = Config.GPU

    data_name = Config.DATA_NAME
    if 'Abilene' in data_name:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

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
    input_shape = (Config.RES_FWBW_LSTM_STEP, Config.RES_FWBW_LSTM_FEATURES)

    with tf.device('/device:GPU:{}'.format(gpu)):
        fwbw_net = load_trained_models(input_shape, Config.RES_FWBW_LSTM_BEST_CHECKPOINT)

    if not os.path.exists(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                                      Config.ALG, Config.TAG, Config.SCALER)):
        os.makedirs(Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                                Config.ALG, Config.TAG, Config.SCALER))
    results_summary = pd.DataFrame(index=range(Config.RES_FWBW_LSTM_TESTING_TIME),
                                   columns=['No.', 'err', 'r2', 'rmse', 'err_ims', 'r2_ims',
                                            'rmse_ims'])

    results_summary = run_test(test_data2d, test_data_normalized2d, fwbw_net, scalers, results_summary)

    results_summary.to_csv(Config.RESULTS_PATH +
                           '{}-{}-{}-{}/Test_results.csv'.format(Config.DATA_NAME, Config.ALG, Config.TAG,
                                                                 Config.SCALER),
                           index=False)

    return


def prepare_test_set(test_data2d, test_data_normalized2d):
    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    idx = np.random.random_integers(Config.RES_FWBW_LSTM_STEP,
                                    test_data2d.shape[0] - day_size * Config.RES_FWBW_LSTM_TEST_DAYS - 10)

    test_data_normalize = np.copy(test_data_normalized2d[idx:idx + day_size * Config.RES_FWBW_LSTM_TEST_DAYS])
    init_data_normalize = np.copy(test_data_normalized2d[idx - Config.RES_FWBW_LSTM_STEP: idx])
    test_data = test_data2d[idx:idx + day_size * Config.RES_FWBW_LSTM_TEST_DAYS]

    return test_data_normalize, init_data_normalize, test_data


def prepare_test_set_last_5days(test_data2d, test_data_normalized2d):
    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    idx = test_data2d.shape[0] - day_size * 5 - 10

    test_data_normalize = np.copy(test_data_normalized2d[idx:idx + day_size * 5])
    init_data_normalize = np.copy(test_data_normalized2d[idx - Config.RES_FWBW_LSTM_STEP: idx])
    test_data = test_data2d[idx:idx + day_size * 5]

    return test_data_normalize, init_data_normalize, test_data


def run_test(test_data2d, test_data_normalized2d, fwbw_net, scalers, results_summary):
    err, r2_score, rmse = [], [], []
    err_ims, r2_score_ims, rmse_ims = [], [], []

    # per_gain = []

    for i in range(Config.RES_FWBW_LSTM_TESTING_TIME):
        print('|--- Run time {}'.format(i))
        # test_data_normalize, init_data_normalize, test_data = prepare_test_set(test_data2d, test_data_normalized2d)
        test_data_normalize, init_data_normalize, test_data = prepare_test_set_last_5days(test_data2d,
                                                                                          test_data_normalized2d)
        ims_test_data = ims_tm_test_data(test_data=test_data)
        measured_matrix_ims = np.zeros(shape=ims_test_data.shape)

        pred_tm2d, measured_matrix2d, ims_tm2d = predict_fwbw_lstm_v2(initial_data=init_data_normalize,
                                                                      test_data=test_data_normalize,
                                                                      model=fwbw_net.model)

        pred_tm_invert2d = scalers.inverse_transform(pred_tm2d)
        # pred_tm_wo_invert2d = scalers.inverse_transform(pred_tm2d_wo)
        if np.any(np.isinf(pred_tm_invert2d)):
            raise ValueError('Value is infinity!')
        elif np.any(np.isnan(pred_tm_invert2d)):
            raise ValueError('Value is NaN!')

        err.append(error_ratio(y_true=test_data, y_pred=pred_tm_invert2d, measured_matrix=measured_matrix2d))
        r2_score.append(calculate_r2_score(y_true=test_data, y_pred=pred_tm_invert2d))
        rmse.append(calculate_rmse(y_true=test_data / 1000000, y_pred=pred_tm_invert2d / 1000000))

        # err_wo = error_ratio(y_true=test_data, y_pred=pred_tm_wo_invert2d, measured_matrix=measured_matrix2d)
        # r2_score_wo = calculate_r2_score(y_true=test_data, y_pred=pred_tm_wo_invert2d)
        # rmse_wo = calculate_rmse(y_true=test_data / 1000000, y_pred=pred_tm_wo_invert2d / 1000000)

        if Config.RES_FWBW_LSTM_IMS:
            # Calculate error for multistep-ahead-prediction
            ims_tm_invert2d = scalers.inverse_transform(ims_tm2d)

            err_ims.append(error_ratio(y_pred=ims_tm_invert2d,
                                       y_true=ims_test_data,
                                       measured_matrix=measured_matrix_ims))

            r2_score_ims.append(calculate_r2_score(y_true=ims_test_data, y_pred=ims_tm_invert2d))
            rmse_ims.append(calculate_rmse(y_true=ims_test_data / 1000000, y_pred=ims_tm_invert2d / 1000000))
        else:
            err_ims.append(0)
            r2_score_ims.append(0)
            rmse_ims.append(0)

        print('Result: err\trmse\tr2 \t\t err_ims\trmse_ims\tr2_ims')
        print('        {}\t{}\t{} \t\t {}\t{}\t{}'.format(err[i], rmse[i], r2_score[i],
                                                          err_ims[i], rmse_ims[i],
                                                          r2_score_ims[i]))
        # print('Result without data correction: mape \t err\trmse\tr2')
        # print('        {}\t{}\t{}\t{}'.format(mape_wo, err_wo, rmse_wo, r2_score_wo))
        #
        # if err[i] < err_wo:
        #     per_gain.append(np.abs(err[i] - err_wo) * 100.0 / err_wo)
        #     print('|-----> Performance gain: {}'.format(np.abs(err[i] - err_wo) * 100.0 / err_wo))
        # else:
        #     per_gain.append(-np.abs(err[i] - err_wo) * 100.0 / err[i])
        #     print('|-----> Performance gain: {}'.format(-np.abs(err[i] - err_wo) * 100.0 / err[i]))

    results_summary['No.'] = range(Config.RES_FWBW_LSTM_TESTING_TIME)
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

    # print('Avg_per_gain: {} - Confidence: {}'.format(np.mean(np.array(per_gain)),
    #                                                  calculate_confident_interval(per_gain)))

    return results_summary

