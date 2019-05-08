import pickle

import matplotlib
import numpy as np
import pandas as pd

from common import Config
from common.DataPreprocessing import prepare_train_test_2d
from common.error_utils import error_ratio, calculate_r2_score, calculate_rmse
from tqdm import tqdm

from statsmodels.tsa.api import ExponentialSmoothing

matplotlib.use('Agg')


def build_holt_winter(data):
    model = ExponentialSmoothing(data,
                                 seasonal_periods=4,
                                 trend=Config.HOLT_WINTER_TREND,
                                 seasonal=Config.HOLT_WINTER_SEASONAL).fit(use_boxcox=True)

    return model


def ims_tm_test_data(test_data):
    ims_test_set = np.zeros(shape=(test_data.shape[0] - Config.HOLT_WINTER_IMS_STEP + 1, test_data.shape[1]))

    for i in range(Config.HOLT_WINTER_IMS_STEP - 1, test_data.shape[0], 1):
        ims_test_set[i - Config.HOLT_WINTER_IMS_STEP + 1] = test_data[i]

    return ims_test_set


def train_holt_winter(args, data):
    alg_name = args.alg
    tag = args.tag
    data_name = args.data_name
    if 'Abilene' in data_name:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    train_data, test_data = prepare_train_test_2d(data=data, day_size=day_size)

    # mean_train = np.mean(train_data)
    # std_train = np.std(train_data)
    # train_data_normalized = (train_data - mean_train) / std_train
    # test_data_normalized = (test_data - mean_train) / std_train

    training_set_series = []
    for flow_id in range(train_data.shape[1]):
        flow_frame = pd.Series(train_data[:, flow_id])
        training_set_series.append(flow_frame)

    import os
    if not os.path.exists(Config.MODEL_SAVE + 'holt_winter/'):
        os.makedirs(Config.MODEL_SAVE + 'holt_winter/')

    for flow_id in tqdm(range(test_data.shape[1])):
        training_set_series[flow_id].dropna(inplace=True)
        flow_train = training_set_series[flow_id].values

        history = [x for x in flow_train.astype(float)]
        history = np.array(history)
        history[history == 0] = 0.0000001

        # Fit all historical data to holt_winter
        model = build_holt_winter(history)

        saved_model = open(Config.MODEL_SAVE + 'holt_winter/{}-{}-{}'.format(flow_id, data_name, alg_name), 'wb')
        pickle.dump(model, saved_model, 2)


def test_holt_winter(data, args):
    alg_name = args.alg
    tag = args.tag
    data_name = args.data_name

    if 'Abilene' in data_name:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    if not Config.ALL_DATA:
        data = data[0:day_size * Config.NUM_DAYS, :]

    train_data, test_data = prepare_train_test_2d(data=data, day_size=day_size)
    if 'Abilene' in data_name:
        print('|--- Remove last 3 days in test data.')
        test_data = test_data[0:-day_size * 3]

    # mean_train = np.mean(train_data)
    # std_train = np.std(train_data)
    # train_data_normalized = (train_data - mean_train) / std_train
    # test_data_normalized = (test_data - mean_train) / std_train

    training_set_series = []
    for flow_id in range(train_data.shape[1]):
        flow_frame = pd.Series(train_data[:, flow_id])
        training_set_series.append(flow_frame)

    tf = np.array([True, False])

    results_summary = pd.DataFrame(index=range(Config.HOLT_WINTER_TESTING_TIME),
                                   columns=['No.', 'err', 'r2', 'rmse', 'err_ims', 'r2_ims', 'rmse_ims'])

    err, r2_score, rmse = [], [], []
    err_ims, r2_score_ims, rmse_ims = [], [], []

    import os
    if not os.path.exists(Config.MODEL_SAVE + 'holt_winter/'):
        os.makedirs(Config.MODEL_SAVE + 'holt_winter/')

    ims_test_set = ims_tm_test_data(test_data=test_data)
    measured_matrix_ims = np.zeros(shape=ims_test_set.shape)

    pred_tm = np.zeros((test_data.shape[0], test_data.shape[1]))
    ims_pred_tm = np.zeros((test_data.shape[0] - Config.HOLT_WINTER_IMS_STEP + 1, test_data.shape[1]))

    if not os.path.isfile(Config.MODEL_SAVE + 'holt_winter/{}-{}-{}'.format(0, data_name, alg_name)):
        train_holt_winter(args, data)

    for running_time in range(Config.HOLT_WINTER_TESTING_TIME):
        print('|--- Run time: {}'.format(running_time))

        measured_matrix = np.random.choice(tf, size=(test_data.shape[0], test_data.shape[1]),
                                           p=[Config.HOLT_WINTER_MON_RATIO, 1 - Config.HOLT_WINTER_MON_RATIO])

        for flow_id in tqdm(range(test_data.shape[1])):
            training_set_series[flow_id].dropna(inplace=True)
            flow_train = training_set_series[flow_id].values

            history = [x for x in flow_train.astype(float)]
            history = np.array(history)
            history[history == 0] = 0.0000001

            predictions = np.zeros(shape=(test_data.shape[0]))

            measured_flow = measured_matrix[:, flow_id]

            flow_ims_pred = np.zeros(shape=(test_data.shape[0] - Config.HOLT_WINTER_IMS_STEP + 1))

            # Load trained holt_winter model
            saved_model = open(Config.MODEL_SAVE + 'holt_winter/{}-{}-{}'.format(flow_id, data_name, alg_name), 'rb')
            model = pickle.load(saved_model)

            for ts in range(test_data.shape[0]):

                if (ts % (day_size * Config.HOLT_WINTER_UPDATE) == 0) and ts != 0:
                    print('|--- Update holt_winter model at ts: {}'.format(ts))
                    try:
                        model = build_holt_winter(history)
                    except:
                        pass

                output = model.forecast(Config.HOLT_WINTER_IMS_STEP)

                if ts <= (test_data.shape[0] - Config.HOLT_WINTER_IMS_STEP):
                    flow_ims_pred[ts] = output[-1]

                yhat = output[0]
                obs = test_data[ts, flow_id]

                # Semi-recursive predicting
                if measured_flow[ts]:
                    np.append(history, obs)
                    predictions[ts] = obs
                else:
                    np.append(history, yhat)
                    predictions[ts] = yhat

            pred_tm[:, flow_id] = predictions
            ims_pred_tm[:, flow_id] = flow_ims_pred

        # pred_tm = pred_tm * std_train + mean_train
        # ims_pred_tm = ims_pred_tm * std_train + mean_train

        measured_matrix = measured_matrix.astype(bool)

        # Calculate error
        try:
            err.append(error_ratio(y_true=test_data,
                                   y_pred=pred_tm,
                                   measured_matrix=measured_matrix))
        except ValueError as VE:
            print(VE)
            err.append(100)
        try:
            r2_score.append(calculate_r2_score(y_true=test_data, y_pred=pred_tm))
        except ValueError as VE:
            print(VE)
            r2_score.append(-100)
        try:
            rmse.append(calculate_rmse(y_true=test_data, y_pred=pred_tm))
        except ValueError as VE:
            print(VE)
            rmse.append(100)

            # Calculate error of ims
        try:
            err_ims.append(error_ratio(y_pred=ims_pred_tm,
                                       y_true=ims_test_set,
                                       measured_matrix=measured_matrix_ims))
        except ValueError as VE:
            print(VE)
            err_ims.append(100)
        try:
            r2_score_ims.append(calculate_r2_score(y_true=ims_test_set, y_pred=ims_pred_tm))
        except ValueError as VE:
            print(VE)
            r2_score_ims.append(-100)
        try:
            rmse_ims.append(calculate_rmse(y_true=ims_test_set, y_pred=ims_pred_tm))
        except ValueError as VE:
            print(VE)
            rmse_ims.append(100)

        print('Result: err\trmse\tr2 \t\t err_ims\trmse_ims\tr2_ims')
        print('        {}\t{}\t{} \t\t {}\t{}\t{}'.format(err[running_time], rmse[running_time], r2_score[running_time],
                                                          err_ims[running_time], rmse_ims[running_time],
                                                          r2_score_ims[running_time]))

        np.save(Config.RESULTS_PATH + '[pred-{}]{}-{}-{}-{}.npy'.format(running_time, data_name, alg_name, tag,
                                                                        Config.ADDED_RESULT_NAME),
                pred_tm)


    results_summary['No.'] = range(Config.HOLT_WINTER_TESTING_TIME)
    results_summary['err'] = err
    results_summary['r2'] = r2_score
    results_summary['rmse'] = rmse
    results_summary['err_ims'] = err_ims
    results_summary['r2_ims'] = r2_score_ims
    results_summary['rmse_ims'] = rmse_ims

    results_summary.to_csv(Config.RESULTS_PATH + '{}-{}-{}-{}.csv'.format(data_name,
                                                                          alg_name, tag, Config.ADDED_RESULT_NAME),
                           index=False)