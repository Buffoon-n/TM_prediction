import numpy as np

from algs.fwbw_lstm_2 import train_fwbw_lstm_2, test_fwbw_lstm_2
from common import Config_fwbw_lstm_2 as Config


def print_fwbw_lstm_2_info():
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

    print('|--- MON_RATIO:\t{}'.format(Config.FWBW_LSTM_2_MON_RAIO))
    print('            -----------            ')

    print('|--- LSTM_DEEP:\t{}'.format(Config.FWBW_LSTM_2_DEEP))
    if Config.FWBW_LSTM_2_DEEP:
        print('|--- LSTM_DEEP_NLAYERS:\t{}'.format(Config.FWBW_LSTM_2_DEEP_NLAYERS))
    print('|--- LSTM_DROPOUT:\t{}'.format(Config.FWBW_LSTM_2_DROPOUT))
    print('|--- LSTM_HIDDEN_UNIT:\t{}'.format(Config.FWBW_LSTM_2_HIDDEN_UNIT))
    print('|--- RANDOM_ACTION:\t{}'.format(Config.FWBW_LSTM_2_RANDOM_ACTION))
    if not Config.FWBW_LSTM_2_RANDOM_ACTION:
        print('|--- FWBW_LSTM_HYPERPARAMS:\t{}'.format(Config.FWBW_LSTM_2_HYPERPARAMS))

    if Config.RUN_MODE == Config.RUN_MODES[0]:
        print('|--- N_EPOCH:\t{}'.format(Config.FWBW_LSTM_2_N_EPOCH))
        print('|--- BATCH_SIZE:\t{}'.format(Config.FWBW_LSTM_2_BATCH_SIZE))
        print('|--- LSTM_STEP:\t{}'.format(Config.FWBW_LSTM_2_STEP))
        if Config.FWBW_LSTM_2_IMS:
            print('|--- IMS_STEP:\t{}'.format(Config.FWBW_LSTM_2_IMS_STEP))
    elif Config.RUN_MODE == Config.RUN_MODES[1]:
        print('|--- TESTING_TIME:\t{}'.format(Config.FWBW_LSTM_2_TESTING_TIME))
        print('|--- BEST_CHECKPOINT:\t{}'.format(Config.FWBW_LSTM_2_BEST_CHECKPOINT))
    else:
        raise Exception('Unknown RUN_MODE!')
    print('----------------------------------------------------')
    infor_correct = input('Is the information correct? y(Yes)/n(No):')
    if infor_correct != 'y' and infor_correct != 'yes':
        raise RuntimeError('Information is not correct!')


if __name__ == '__main__':
    data = np.load(Config.DATA_PATH + '{}.npy'.format(Config.DATA_NAME))
    print_fwbw_lstm_2_info()

    if Config.RUN_MODE == Config.RUN_MODES[0]:
        train_fwbw_lstm_2(data)
    else:
        test_fwbw_lstm_2(data)