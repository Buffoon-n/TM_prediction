import numpy as np

from algs.conv_lstm import train_conv_lstm, test_conv_lstm
from common import Config_conv_lstm as Config


def print_conv_lstm_info():
    print('----------------------- INFO -----------------------')
    print('|--- MODE:\t{}'.format(Config.RUN_MODE))
    print('|--- ALG:\t{}'.format(Config.ALG))
    print('|--- TAG:\t{}'.format(Config.TAG))
    print('|--- DATA:\t{}'.format(Config.DATA_NAME))
    print('|--- GPU:\t{}'.format(Config.GPU))

    print('|--- MON_RATIO:\t{}'.format(Config.CONV_LSTM_MON_RATIO))
    print('            -----------            ')

    print('|--- MON_RATIO:\t{}'.format(Config.CONV_LSTM_MON_RATIO))
    print('            -----------            ')

    print('|--- CONV_LAYERS:\t{}'.format(Config.CONV_LSTM_LAYERS))
    print('|--- FILTERS:\t{}'.format(Config.CONV_LSTM_FILTERS))
    print('|--- KERNEL_SIZE:\t{}'.format(Config.CONV_LSTM_KERNEL_SIZE))
    print('|--- STRIDES:\t{}'.format(Config.CONV_LSTM_STRIDES))
    print('|--- DROPOUTS:\t{}'.format(Config.CONV_LSTM_DROPOUTS))
    print('|--- RNN_DROPOUTS:\t{}'.format(Config.CONV_LSTM_RNN_DROPOUTS))

    if Config.RUN_MODE == Config.RUN_MODES[0]:
        print('|--- N_EPOCH:\t{}'.format(Config.CONV_LSTM_N_EPOCH))
        print('|--- BATCH_SIZE:\t{}'.format(Config.CONV_LSTM_BATCH_SIZE))
        print('|--- LSTM_STEP:\t{}'.format(Config.CONV_LSTM_STEP))
        if Config.CONV_LSTM_IMS:
            print('|--- IMS_STEP:\t{}'.format(Config.CONV_LSTM_IMS_STEP))
    elif Config.RUN_MODE == Config.RUN_MODES[1]:
        print('|--- TESTING_TIME:\t{}'.format(Config.CONV_LSTM_TESTING_TIME))
        print('|--- BEST_CHECKPOINT:\t{}'.format(Config.CONV_LSTM_BEST_CHECKPOINT))
    else:
        raise Exception('Unknown RUN_MODE!')
    infor_correct = input('Is the information correct? y(Yes)/n(No):')
    if infor_correct != 'y' and infor_correct != 'yes':
        raise RuntimeError('Information is not correct!')


if __name__ == '__main__':
    data = np.load(Config.DATA_PATH + '{}.npy'.format(Config.DATA_NAME))
    print_conv_lstm_info()

    if Config.RUN_MODE == Config.RUN_MODES[0]:
        train_conv_lstm(data)
    else:
        test_conv_lstm(data)