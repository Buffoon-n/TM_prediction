import numpy as np

from algs.arima import test_arima
from common import Config_arima as Config
from common.DataPreprocessing import results_processing, prepare_train_test_2d, data_scalling


def print_arima_info():
    print('----------------------- INFO -----------------------')
    if not Config.ALL_DATA:
        print('|--- Train/Test with {}d of data'.format(Config.NUM_DAYS))
    else:
        print('|--- Train/Test with ALL of data'.format(Config.NUM_DAYS))
    print('|--- MODE:\t{}'.format(Config.RUN_MODE))
    print('|--- ALG:\t{}'.format(Config.ALG))
    print('|--- TAG:\t{}'.format(Config.TAG))
    print('|--- DATA:\t{}'.format(Config.DATA_NAME))
    print('|--- GPU:\t{}'.format(Config.GPU))

    print('|--- MON_RATIO:\t{}'.format(Config.ARIMA_MON_RATIO))
    print('            -----------            ')

    if Config.ARIMA_IMS:
        print('|--- IMS_STEP:\t{}'.format(Config.ARIMA_IMS_STEP))
    if Config.RUN_MODE == Config.RUN_MODES[1]:
        print('|--- TESTING_TIME:\t{}'.format(Config.ARIMA_TESTING_TIME))
    else:
        raise Exception('Unknown RUN_MODE!')
    print('----------------------------------------------------')
    infor_correct = input('Is the information correct? y(Yes)/n(No):')
    if infor_correct != 'y' and infor_correct != 'yes':
        raise RuntimeError('Information is not correct!')


def prepare_test_set_last_5days(test_data2d, test_data_normalized2d):
    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    idx = test_data2d.shape[0] - day_size * 5 - 10

    test_data_normalize = np.copy(test_data_normalized2d[idx:idx + day_size * 5])
    init_data_normalize = np.copy(test_data_normalized2d[idx - Config.ARIMA_STEP: idx])
    test_data = test_data2d[idx:idx + day_size * 5]

    return test_data_normalize, init_data_normalize, test_data


def get_results(data):
    print('|--- Test ARIMA')
    if Config.DATA_NAME == Config.DATA_SETS[0]:
        day_size = Config.ABILENE_DAY_SIZE
    else:
        day_size = Config.GEANT_DAY_SIZE

    data[data <= 0] = 0.1

    train_data2d, test_data2d = prepare_train_test_2d(data=data, day_size=day_size)

    if Config.DATA_NAME == Config.DATA_SETS[0]:
        print('|--- Remove last 3 days in test_set.')
        test_data2d = test_data2d[0:-day_size * 3]

    # Data normalization
    scaler = data_scalling(train_data2d)

    test_data_normalized2d = scaler.transform(test_data2d)

    _, _, y_true = prepare_test_set_last_5days(test_data2d, test_data_normalized2d)

    results_path = Config.RESULTS_PATH + '{}-{}-{}-{}/'.format(Config.DATA_NAME,
                                                               Config.ALG, Config.TAG, Config.SCALER)
    results_processing(y_true, Config.ARIMA_TESTING_TIME, results_path)


if __name__ == '__main__':
    data = np.load(Config.DATA_PATH + '{}.npy'.format(Config.DATA_NAME))
    print_arima_info()
    test_arima(data)
    get_results(data)
