import numpy as np

from algs.res_lstm import train_res_lstm, test_res_lstm
from common import Config_res_lstm as Config


def print_res_lstm_info():
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

    print('|--- MON_RATIO:\t{}'.format(Config.RES_LSTM_MON_RAIO))
    print('            -----------            ')

    print('|--- LSTM_DEEP:\t{}'.format(Config.RES_LSTM_DEEP))
    if Config.RES_LSTM_DEEP:
        print('|--- LSTM_DEEP_NLAYERS:\t{}'.format(Config.RES_LSTM_DEEP_NLAYERS))
    print('|--- LSTM_DROPOUT:\t{}'.format(Config.RES_LSTM_DROPOUT))
    print('|--- LSTM_HIDDEN_UNIT:\t{}'.format(Config.RES_LSTM_HIDDEN_UNIT))

    if Config.RUN_MODE == Config.RUN_MODES[0]:
        print('|--- N_EPOCH:\t{}'.format(Config.RES_LSTM_N_EPOCH))
        print('|--- BATCH_SIZE:\t{}'.format(Config.RES_LSTM_BATCH_SIZE))
        print('|--- LSTM_STEP:\t{}'.format(Config.RES_LSTM_STEP))
        if Config.RES_LSTM_IMS:
            print('|--- IMS_STEP:\t{}'.format(Config.RES_LSTM_IMS_STEP))
    elif Config.RUN_MODE == Config.RUN_MODES[1]:
        print('|--- TESTING_TIME:\t{}'.format(Config.RES_LSTM_TESTING_TIME))
        print('|--- BEST_CHECKPOINT:\t{}'.format(Config.RES_LSTM_BEST_CHECKPOINT))
    else:
        raise Exception('Unknown RUN_MODE!')
    print('----------------------------------------------------')
    infor_correct = input('Is the information correct? y(Yes)/n(No):')
    if infor_correct != 'y' and infor_correct != 'yes':
        raise RuntimeError('Information is not correct!')


if __name__ == '__main__':
    data = np.load(Config.DATA_PATH + '{}.npy'.format(Config.DATA_NAME))
    print_res_lstm_info()

    if Config.RUN_MODE == Config.RUN_MODES[0]:
        train_res_lstm(data)
    else:
        test_res_lstm(data)