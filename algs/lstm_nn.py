import pandas as pd
import tensorflow as tf

from Models.RNN_LSTM import lstm
from common import Config
from common.DataPreprocessing import *
from common.error_utils import error_ratio, calculate_r2_score, rmse_tm_prediction

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
session = tf.Session(config=config)


def prepare_input_online_prediction(data, labels):
    labels = labels.astype(int)
    dataX = np.zeros(shape=(data.shape[1], Config.LSTM_STEP, 2))
    for flow_id in range(data.shape[1]):
        x = data[-Config.LSTM_STEP:, flow_id]
        label = labels[-Config.LSTM_STEP:, flow_id]

        sample = np.array([x, label]).T
        dataX[flow_id] = sample

    return dataX


def ims_tm_prediction(ret_tm, rnn_model,
                      ims_tm,
                      labels):
    multi_steps_tm = np.copy(ret_tm[-Config.LSTM_STEP:, :])

    measured_matrix = np.copy(labels)

    for ts_ahead in range(Config.IMS_STEP):
        rnn_input = prepare_input_online_prediction(data=multi_steps_tm,
                                                    labels=measured_matrix)
        predictX = rnn_model.predict(rnn_input)
        pred = np.expand_dims(predictX[:, -1, 0], axis=0)

        sampling = np.zeros(shape=(1, pred.shape[1]))
        measured_matrix = np.concatenate([measured_matrix, sampling], axis=0)

        multi_steps_tm = np.concatenate([multi_steps_tm, pred], axis=0)

    multi_steps_tm = multi_steps_tm[Config.LSTM_STEP:, :]
    multi_steps_tm = np.expand_dims(multi_steps_tm, axis=0)

    iterated_multi_steps_tm = np.concatenate([ims_tm, multi_steps_tm], axis=0)

    return iterated_multi_steps_tm


def predict_lstm_nn(test_data, model):
    # Initialize the first input for RNN to predict the TM at time slot look_back
    ret_tm = np.copy(test_data[0:Config.LSTM_STEP, :])
    # Results TM
    # The TF array for random choosing the measured flows
    tf = np.array([True, False])
    measured_matrix = np.ones(shape=(ret_tm.shape[0], ret_tm.shape[1]))

    ims_tm = np.empty(shape=(0, Config.IMS_STEP, ret_tm.shape[1]))

    # Predict the TM from time slot look_back
    for ts in range(0, test_data.shape[0] - Config.LSTM_STEP, 1):
        # This block is used for iterated multi-step traffic matrices prediction

        if ts < test_data.shape[0] - Config.LSTM_STEP - Config.IMS_STEP:
            ims_tm_prediction(ret_tm=ret_tm,
                              rnn_model=model,
                              ims_tm=ims_tm,
                              labels=measured_matrix)

        # Create 3D input for rnn
        rnn_input = prepare_input_online_prediction(data=ret_tm, labels=measured_matrix)

        # Get the TM prediction of next time slot
        predictX = model.predict(rnn_input)

        pred = np.expand_dims(predictX[:, -1, 0], axis=1)

        # Using part of current prediction as input to the next estimation
        # Randomly choose the flows which is measured (using the correct data from test_set)

        # boolean array(1 x n_flows):for choosing value from predicted data
        sampling = np.expand_dims(np.random.choice(tf,
                                                   size=(test_data.shape[1]),
                                                   p=[Config.MON_RAIO, 1 - Config.MON_RAIO]), axis=0)
        measured_matrix = np.concatenate([measured_matrix, sampling], axis=0)
        # invert of sampling: for choosing value from the original data
        inv_sampling = np.invert(sampling)

        pred_input = pred.T * inv_sampling

        ground_true = np.copy(test_data[ts + Config.LSTM_STEP, :])

        measured_input = np.expand_dims(ground_true, axis=0) * sampling

        # Merge value from pred_input and measured_input
        new_input = pred_input + measured_input
        # new_input = np.reshape(new_input, (new_input.shape[0], new_input.shape[1], 1))

        # Concatenating new_input into current rnn_input
        ret_tm = np.concatenate([ret_tm, new_input], axis=0)

    return ret_tm, measured_matrix, ims_tm


def build_model(args, input_shape):
    alg_name = args.alg
    tag = args.tag
    data_name = args.data_name

    net = lstm(input_shape=input_shape,
               hidden=Config.LSTM_HIDDEN_UNIT,
               drop_out=Config.LSTM_DROPOUT,
               alg_name=alg_name, tag=tag, check_point=True,
               saving_path=Config.MODEL_SAVE + '{}-{}-{}/fw/'.format(data_name, alg_name, tag))

    if 'deep-lstm-nn' in alg_name:
        net.seq2seq_deep_model_construction(n_layers=3)
    else:
        net.seq2seq_model_construction()

    return net


def train_lstm_nn(data, args):
    gpu = args.gpu

    if gpu is None:
        gpu = 0

    with tf.device('/device:GPU:{}'.format(gpu)):

        print('|--- Splitting train-test set.')
        train_data, valid_data, test_data = prepare_train_test_set(data=data)
        print('|--- Normalizing the train set.')
        mean_train = np.mean(train_data)
        std_train = np.std(train_data)
        train_data = (train_data - mean_train) / std_train
        valid_data = (valid_data - mean_train) / std_train
        test_data = (test_data - mean_train) / std_train

        input_shape = (Config.LSTM_STEP, Config.LSTM_FEATURES)

        lstm_net = build_model(args, input_shape)

        if os.path.isfile(path=lstm_net.saving_path + 'model.json'):
            lstm_net.load_model_from_check_point(_from_epoch=Config.BEST_CHECKPOINT, weights_file_type='hdf5')

        else:
            print('|---Compile model. Saving path {} --- '.format(lstm_net.saving_path))
            from_epoch = lstm_net.load_model_from_check_point(weights_file_type='hdf5')

            if from_epoch > 0:

                training_history = lstm_net.model.fit_generator(
                    generator_lstm_nn_train_data(data=train_data,
                                                 input_shape=input_shape,
                                                 mon_ratio=Config.MON_RAIO,
                                                 eps=0.5,
                                                 batch_size=Config.BATCH_SIZE),
                    epochs=Config.N_EPOCH,
                    steps_per_epoch=Config.NUM_ITER,
                    initial_epoch=from_epoch,
                    validation_data=generator_lstm_nn_train_data(valid_data, input_shape, Config.MON_RAIO, 0.5,
                                                                 Config.BATCH_SIZE),
                    validation_steps=int(Config.NUM_ITER * 0.2),
                    callbacks=lstm_net.callbacks_list,
                    use_multiprocessing=True, workers=2, max_queue_size=1024
                )
            else:

                training_history = lstm_net.model.fit_generator(
                    generator_lstm_nn_train_data(data=train_data,
                                                 input_shape=input_shape,
                                                 mon_ratio=Config.MON_RAIO,
                                                 eps=0.5,
                                                 batch_size=Config.BATCH_SIZE),
                    epochs=Config.N_EPOCH,
                    steps_per_epoch=Config.NUM_ITER,
                    validation_data=generator_lstm_nn_train_data(valid_data, input_shape, Config.MON_RAIO, 0.5,
                                                                 Config.BATCH_SIZE),
                    validation_steps=int(Config.NUM_ITER * 0.2),
                    callbacks=lstm_net.callbacks_list,
                    use_multiprocessing=True, workers=2, max_queue_size=1024
                )

            if training_history is not None:
                lstm_net.plot_training_history(training_history)
        print('---------------------------------LSTM_NET SUMMARY---------------------------------')
        print(lstm_net.model.summary())

    return


def calculate_iterated_multi_step_tm_prediction_errors(test_set):
    ims_test_set = np.empty(shape=(0, Config.IMS_STEP, test_set.shape[1]))

    for ts in range(test_set.shape[0] - Config.LSTM_STEP - Config.IMS_STEP):
        multi_step_test_set = np.copy(test_set[(ts + Config.LSTM_STEP): (ts + Config.LSTM_STEP + Config.IMS_STEP), :])
        multi_step_test_set = np.expand_dims(multi_step_test_set, axis=0)
        ims_test_set = np.concatenate([ims_test_set, multi_step_test_set], axis=0)

    return ims_test_set


def test_lstm_nn(data, args):
    alg_name = args.alg
    tag = args.tag
    data_name = args.data_name

    print('|--- Splitting train-test set.')
    train_data, valid_data, test_data = prepare_train_test_set_3d(data=data)
    print('|--- Normalizing the train set.')
    mean_train = np.mean(train_data)
    std_train = np.std(train_data)
    test_data_normalized = (test_data - mean_train) / std_train

    print("|--- Create FWBW_CONVLSTM model.")
    input_shape = (Config.LSTM_STEP,
                   Config.CNN_WIDE, Config.CNN_HIGH, Config.CNN_CHANNEL)

    lstm_net = build_model(args, input_shape)

    results_summary = pd.read_csv(Config.RESULTS_PATH + 'sample_results.csv')

    err, r2_score, rmse = [], [], []
    err_ims, r2_score_ims, rmse_ims = [], [], []

    for i in range(Config.TESTING_TIME):
        pred_tm, measured_matrix, ims_tm = predict_lstm_nn(test_data=test_data_normalized,
                                                           model=lstm_net.model)

        pred_tm = pred_tm * std_train + mean_train

        err.append(error_ratio(y_true=test_data_normalized, y_pred=np.copy(pred_tm), measured_matrix=measured_matrix))
        r2_score.append(calculate_r2_score(y_true=test_data_normalized, y_pred=np.copy(pred_tm)))
        rmse.append(rmse_tm_prediction(y_true=test_data_normalized, y_pred=np.copy(pred_tm)))

        ims_tm = ims_tm * std_train + mean_train

        ims_test_set = calculate_iterated_multi_step_tm_prediction_errors(test_set=test_data)

        measured_matrix = np.zeros(shape=ims_test_set.shape)
        err_ims.append(error_ratio(y_pred=ims_tm,
                                   y_true=ims_test_set,
                                   measured_matrix=measured_matrix))

        r2_score_ims.append(calculate_r2_score(y_true=ims_test_set, y_pred=ims_tm))
        rmse_ims.append(rmse_tm_prediction(y_true=ims_test_set, y_pred=ims_tm))

    results_summary['running_time'] = range(Config.TESTING_TIME)
    results_summary['err'] = err
    results_summary['r2_score'] = r2_score
    results_summary['rmse'] = rmse
    results_summary['err_ims'] = err_ims
    results_summary['r2_score_ims'] = r2_score_ims
    results_summary['rmse_ims'] = rmse_ims

    results_summary.to_csv(Config.RESULTS_PATH + '{}-{}-{}.csv'.format(data_name, alg_name, tag),
                           index=False)

    return