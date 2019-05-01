from matplotlib import pyplot as plt
from common import Config
import numpy as np
import os
from common.error_utils import calculate_r2_score, error_ratio, calculate_rmse


def plot_pred_results(data_name, alg_name, tag, nflows, ndays):
    if 'Abilene' in data_name:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    plotted_path = Config.RESULTS_PATH + 'Plotted_results/{}-{}-{}-{}/'.format(data_name,
                                                                               alg_name,
                                                                               tag,
                                                                               Config.ADDED_RESULT_NAME)
    if not os.path.exists(plotted_path):
        os.makedirs(plotted_path)

    test_data = np.load(Config.RESULTS_PATH + '[test-data]{}.npy'.format(data_name))

    if 'fwbw-conv-lstm' in alg_name or 'fwbw-convlstm' in alg_name:
        run_time = Config.FWBW_CONV_LSTM_TESTING_TIME
    elif 'conv-lstm' in alg_name or 'convlstm' in alg_name:
        run_time = Config.CONV_LSTM_TESTING_TIME
    elif 'lstm-nn' in alg_name:
        run_time = Config.LSTM_TESTING_TIME
    elif 'arima' in alg_name:
        run_time = Config.ARIMA_TESTING_TIME
    elif 'holt-winter' in alg_name:
        run_time = Config.HOLT_WINTER_TESTING_TIME
    else:
        raise ValueError('Unkown alg!')

    for i in range(run_time):
        pred = np.load(Config.RESULTS_PATH + '[pred-{}]{}-{}-{}-{}.npy'.format(i, data_name, alg_name, tag,
                                                                               Config.ADDED_RESULT_NAME))
        measure_matrix = np.load(Config.RESULTS_PATH + '[measure-{}]{}-{}-{}-{}.npy'.format(i, data_name, alg_name, tag,
                                                                                            Config.ADDED_RESULT_NAME))

        # flows_x = np.random.random_integers(0, test_data.shape[1] - 1, size=nflows)
        # flows_y = np.random.random_integers(0, test_data.shape[1] - 1, size=nflows)
        #
        # for j in range(nflows):
        #     x = flows_x[j]
        #     y = flows_y[j]
        #     plt.plot(range(test_data.shape[0] - day_size * (ndays), test_data.shape[0]),
        #              test_data[-day_size * (ndays):, x, y], label='Actual')
        #     plt.plot(range(test_data.shape[0] - day_size * (ndays), test_data.shape[0]),
        #              pred[-day_size * (ndays):, x, y], label='Predicted')
        #     plt.xlabel('Timestep')
        #     plt.ylabel('Traffic Load')
        #
        #     plt.legend()
        #
        #     plt.savefig(plotted_path + 'Flow-{}-{}.png'.format(x, y))
        #     plt.close()

        test_data = test_data[0:(test_data.shape[0] - day_size * ndays)]
        pred = pred[0:(pred.shape[0] - day_size * ndays)]
        measure_matrix = measure_matrix[0:(measure_matrix.shape[0] - day_size * ndays)]

        print('|--- Error Ratio: {}'.format(error_ratio(y_true=test_data,
                                                        y_pred=pred,
                                                        measured_matrix=measure_matrix)))
        print('|--- RMSE: {}'.format(calculate_rmse(y_true=test_data,
                                                    y_pred=pred)))
        print('|--- R2: {}'.format(calculate_r2_score(y_true=test_data,
                                                      y_pred=pred)))
