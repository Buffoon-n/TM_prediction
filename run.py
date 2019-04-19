import sys

import numpy as np

from algs.fwbw_conv_lstm import train_fwbw_conv_lstm, test_fwbw_conv_lstm
from algs.lstm_nn import train_lstm_nn, test_lstm_nn
from algs.arima import train_arima, test_arima
from common.Config import DATA_PATH
from common.cmd_utils import parse_unknown_args, common_arg_parser

from common.DataHelper import create_abilene_data_2d, create_abilene_data_3d


def train(args):
    alg_name = args.alg

    data = np.load(DATA_PATH + '{}.npy'.format(args.data_name))

    if 'fwbw-conv-lstm' in alg_name:
        train_func = train_fwbw_conv_lstm
    elif 'lstm-nn' in alg_name:
        train_func = train_lstm_nn
    elif 'arima' in alg_name:
        train_func = train_arima
    else:
        raise ValueError('Unkown alg!')

    train_func(args=args, data=data)


def test(args):
    alg_name = args.alg

    data = np.load(DATA_PATH + '{}.npy'.format(args.data_name))

    if 'fwbw-conv-lstm' in alg_name:
        test_func = test_fwbw_conv_lstm
    elif 'lstm-nn' in alg_name:
        test_func = test_lstm_nn
    elif 'arima' in alg_name:
        test_func = test_arima
    else:
        raise ValueError('Unkown alg!')

    test_func(args=args, data=data)


def parse_cmdline_kwargs(args):
    def parse(v):

        assert isinstance(v, str)
        try:
            return eval(v)
        except (NameError, SyntaxError):
            return v

    return {k: parse(v) for k, v in parse_unknown_args(args).items()}


def main(args):
    arg_parser = common_arg_parser()
    args, unknown_args = arg_parser.parse_known_args(args)
    extra_args = parse_cmdline_kwargs(unknown_args)

    if args.run_mode == 'training':
        train(args)
    else:
        test(args)

    return


if __name__ == '__main__':
    # create_abilene_data_2d('/home/anle/AbileneTM-all/')
    main(sys.argv)
