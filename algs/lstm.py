import numpy as np
import tensorflow as tf
from tqdm import tqdm

from Models.lstm_supervised import lstm
from common import Config_lstm as Config
from common.error_utils import error_ratio, calculate_r2_score, calculate_rmse

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
session = tf.Session(config=config)


def prepare_input_online_prediction(data, labels):
    labels = labels.astype(int)
    dataX = np.zeros(shape=(data.shape[1], Config.LSTM_STEP, 2))
    for flow_id in range(data.shape[1]):
        x = data[:, flow_id]
        label = labels[:, flow_id]

        sample = np.array([x, label]).T
        dataX[flow_id] = sample

    return dataX


def ims_tm_prediction(init_data, model, init_labels):
    multi_steps_tm = np.zeros(shape=(init_data.shape[0] + Config.LSTM_IMS_STEP, init_data.shape[1]))
    multi_steps_tm[0:Config.LSTM_STEP] = init_data

    labels = np.zeros(shape=(init_labels.shape[0] + Config.LSTM_IMS_STEP, init_labels.shape[1]))
    labels[0:Config.LSTM_STEP] = init_labels

    for ts_ahead in range(Config.LSTM_IMS_STEP):
        rnn_input = prepare_input_online_prediction(data=multi_steps_tm[ts_ahead:ts_ahead + Config.LSTM_STEP],
                                                    labels=labels[ts_ahead:ts_ahead + Config.LSTM_STEP])
        predictX = model.predict(rnn_input)
        multi_steps_tm[ts_ahead + Config.LSTM_STEP] = predictX[:, -1, 0]

    return multi_steps_tm[-1, :]


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


def set_measured_flow_fairness(rnn_input, labels):
    """

    :param rnn_input: shape(#n_flows, #time-steps)
    :param labels: shape(n_flows, #time-steps)
    :return:
    """

    n_flows = rnn_input.shape[0]

    cl = calculate_consecutive_loss(labels).astype(float)

    w = 1 / cl

    sampling = np.zeros(shape=n_flows)
    m = int(Config.LSTM_MON_RATIO * n_flows)

    w = w.flatten()
    sorted_idx_w = np.argsort(w)
    sampling[sorted_idx_w[:m]] = 1

    return sampling


def predict_lstm_nn(init_data, test_data, model):
    tf_a = np.array([1.0, 0.0])
    labels = np.zeros(shape=(init_data.shape[0] + test_data.shape[0], test_data.shape[1]))

    tm_pred = np.zeros(shape=(init_data.shape[0] + test_data.shape[0], test_data.shape[1]))

    ims_tm = np.zeros(shape=(test_data.shape[0] - Config.LSTM_IMS_STEP + 1, test_data.shape[1]))

    tm_pred[0:init_data.shape[0]] = init_data
    labels[0:init_data.shape[0]] = np.ones(shape=init_data.shape)

    raw_data = np.zeros(shape=(init_data.shape[0] + test_data.shape[0], test_data.shape[1]))

    raw_data[0:init_data.shape[0]] = init_data
    raw_data[init_data.shape[0]:] = test_data

    prediction_times = []
    import pandas as pd
    import time
    dump_prediction_time = pd.DataFrame(index=range(test_data.shape[0]), columns=['time_step', 'pred_time'])

    # Predict the TM from time slot look_back
    for ts in tqdm(range(test_data.shape[0])):
        # This block is used for iterated multi-step traffic matrices prediction
        _start = time.time()

        if Config.LSTM_IMS and (ts < test_data.shape[0] - Config.LSTM_IMS_STEP + 1):
            ims_tm[ts] = ims_tm_prediction(init_data=np.copy(tm_pred[ts:ts + Config.LSTM_STEP]),
                                           model=model,
                                           init_labels=np.copy(labels[ts:ts + Config.LSTM_STEP]))

        # Create 3D input for rnn
        rnn_input = prepare_input_online_prediction(data=tm_pred[ts: ts + Config.LSTM_STEP],
                                                    labels=labels[ts: ts + Config.LSTM_STEP])

        # Get the TM prediction of next time slot
        predictX = model.predict(rnn_input)

        pred = predictX[:, -1, 0]

        # Using part of current prediction as input to the next estimation
        # Randomly choose the flows which is measured (using the correct data from test_set)

        # boolean array(1 x n_flows):for choosing value from predicted data
        if Config.LSTM_FLOW_SELECTION == Config.FLOW_SELECTIONS[0]:
            sampling = np.random.choice(tf_a, size=(test_data.shape[1]),
                                        p=[Config.LSTM_MON_RATIO, 1 - Config.LSTM_MON_RATIO])
        else:
            sampling = set_measured_flow_fairness(rnn_input=np.copy(tm_pred[ts: ts + Config.LSTM_STEP].T),
                                                  labels=labels[ts: ts + Config.LSTM_STEP].T)

        labels[ts + Config.LSTM_STEP] = sampling
        # invert of sampling: for choosing value from the original data
        inv_sampling = 1.0 - sampling
        pred_input = pred * inv_sampling

        ground_true = test_data[ts]

        measured_input = ground_true * sampling

        # Merge value from pred_input and measured_input
        new_input = pred_input + measured_input
        # new_input = np.reshape(new_input, (new_input.shape[0], new_input.shape[1], 1))

        # Concatenating new_input into current rnn_input
        tm_pred[ts + Config.LSTM_STEP] = new_input

        prediction_times.append(time.time() - _start)

    dump_prediction_time['time_step'] = range(test_data.shape[0])
    dump_prediction_time['pred_time'] = prediction_times
    dump_prediction_time.to_csv(Config.RESULTS_PATH + '{}-{}-{}-{}/Prediction_times.csv'.format(Config.DATA_NAME,
                                                                                                Config.ALG,
                                                                                                Config.TAG,
                                                                                                Config.SCALER),
                                index=False)

    return tm_pred[Config.LSTM_STEP:, :], labels[Config.LSTM_STEP:, :], ims_tm


def build_model(config):
    print('|--- Build models.')

    net = lstm(**config)

    if Config.LSTM_DEEP:
        net.seq2seq_deep_model_construction(n_layers=Config.LSTM_DEEP_NLAYERS)
    else:
        net.seq2seq_model_construction()

    # net.res_lstm_construction()
    print(net.model.summary())
    net.plot_models()

    return net


def train_lstm(config):
    print('|-- Run model training.')

    with tf.device('/device:GPU:{}'.format(config['gpu'])):
        lstm_net = build_model(config)

    lstm_net.train()

    return


def ims_tm_test_data(test_data):
    ims_test_set = np.zeros(
        shape=(test_data.shape[0] - Config.LSTM_IMS_STEP + 1, test_data.shape[1]))

    for i in range(Config.LSTM_IMS_STEP - 1, test_data.shape[0], 1):
        ims_test_set[i - Config.LSTM_IMS_STEP + 1] = test_data[i]

    return ims_test_set


def load_trained_model(input_shape, best_ckp):
    print('|--- Load trained model')
    lstm_net = build_model(input_shape)
    lstm_net.model.load_weights(lstm_net.checkpoints_path + "weights-{:02d}.hdf5".format(best_ckp))
    return lstm_net


def test_lstm(config):
    return


def prepare_test_set(test_data2d, test_data_normalized2d):
    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    idx = np.random.random_integers(Config.LSTM_STEP, test_data2d.shape[0] - day_size * Config.LSTM_TEST_DAYS - 10)

    test_data_normalize = test_data_normalized2d[idx:idx + day_size * Config.LSTM_TEST_DAYS]
    init_data_normalize = test_data_normalized2d[idx - Config.LSTM_STEP: idx]
    test_data = test_data2d[idx:idx + day_size * Config.LSTM_TEST_DAYS]

    return test_data_normalize, init_data_normalize, test_data


def prepare_test_set_last_5days(test_data2d, test_data_normalized2d):
    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    idx = test_data2d.shape[0] - day_size * 5 - 10

    test_data_normalize = np.copy(test_data_normalized2d[idx:idx + day_size * 5])
    init_data_normalize = np.copy(test_data_normalized2d[idx - Config.LSTM_STEP: idx])
    test_data = test_data2d[idx:idx + day_size * 5]

    return test_data_normalize, init_data_normalize, test_data


def run_test(test_data2d, test_data_normalized2d, lstm_net, scalers, results_summary):
    err, r2_score, rmse = [], [], []
    err_ims, r2_score_ims, rmse_ims = [], [], []

    for i in range(Config.LSTM_TESTING_TIME):
        print('|--- Running time: {}'.format(i))

        # test_data_normalize, init_data_normalize, test_data = prepare_test_set(test_data2d, test_data_normalized2d)
        test_data_normalize, init_data_normalize, test_data = prepare_test_set_last_5days(test_data2d,
                                                                                          test_data_normalized2d)

        ims_test_data = ims_tm_test_data(test_data=test_data)
        measured_matrix_ims = np.zeros(shape=ims_test_data.shape)

        pred_tm2d, measured_matrix2d, ims_tm2d = predict_lstm_nn(init_data=init_data_normalize,
                                                                 test_data=test_data_normalize,
                                                                 model=lstm_net.model)

        pred_tm_invert2d = scalers.inverse_transform(pred_tm2d)

        err.append(error_ratio(y_true=test_data, y_pred=pred_tm_invert2d, measured_matrix=measured_matrix2d))
        r2_score.append(calculate_r2_score(y_true=test_data, y_pred=pred_tm_invert2d))
        rmse.append(calculate_rmse(y_true=test_data / 1000000, y_pred=pred_tm_invert2d / 1000000))

        if Config.LSTM_IMS:
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

    results_summary['No.'] = range(Config.LSTM_TESTING_TIME)
    results_summary['err'] = err
    results_summary['r2'] = r2_score
    results_summary['rmse'] = rmse
    results_summary['err_ims'] = err_ims
    results_summary['r2_ims'] = r2_score_ims
    results_summary['rmse_ims'] = rmse_ims

    print('Test: {}-{}-{}-{}-{}'.format(Config.DATA_NAME, Config.ALG, Config.TAG, Config.SCALER,
                                        Config.LSTM_FLOW_SELECTION))

    print('avg_err: {} - avg_rmse: {} - avg_r2: {}'.format(np.mean(np.array(err)),
                                                           np.mean(np.array(rmse)),
                                                           np.mean(np.array(r2_score))))
    return results_summary


def evaluate_lstm(config):
    with tf.device('/device:GPU:{}'.format(config['gpu'])):
        lstm_net = build_model(config)
        lstm_net.load()
        lstm_net.evaluate()