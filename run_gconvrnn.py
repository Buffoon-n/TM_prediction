import argparse
import os
import sys

import numpy as np
import tensorflow as tf
import yaml

from Models.gconvRNN.gconvRNN_supervisor import GCONVRNN


def print_gconvrnn_info(mode, config):
    print('----------------------- INFO -----------------------')

    print('|--- MODE:\t{}'.format(mode))
    print('|--- ALG:\t{}'.format(config['alg']))
    print('|--- DATA:\t{}'.format(config['data']['data_name']))
    print('|--- GPU:\t{}'.format(config['gpu']))

    print('|--- MON_RATIO:\t{}'.format(config['mon_ratio']))
    print('|--- BASED_DIR:\t{}'.format(config['base_dir']))
    print('|--- SCALER:\t{}'.format(config['scaler']))

    print('|--- ADJ_METHOD:\t{}'.format(config['data']['adj_method']))
    print('|--- ADJ_POS_THRES:\t{}'.format(config['data']['pos_thres']))
    print('|--- ADJ_NEG_THRES:\t{}'.format(config['data']['neg_thres']))

    print('----------------------- MODEL -----------------------')
    print('|--- SEQ_LEN:\t{}'.format(config['model']['seq_len']))
    print('|--- HORIZON:\t{}'.format(config['model']['horizon']))
    print('|--- INPUT_DIM:\t{}'.format(config['model']['input_dim']))
    print('|--- NUM_NODES:\t{}'.format(config['model']['num_nodes']))
    print('|--- NUM_RNN_LAYERS:\t{}'.format(config['model']['num_rnn_layers']))
    print('|--- OUTPUT_DIMS:\t{}'.format(config['model']['output_dim']))
    print('|--- RNN_UNITS:\t{}'.format(config['model']['rnn_units']))
    print('|--- LEARNING_RATE:\t{}'.format(config['model']['learning_rate']))

    if mode == 'train':
        print('----------------------- TRAIN -----------------------')
        print('|--- EPOCHS:\t{}'.format(config['train']['epochs']))
        print('|--- DROPOUT:\t{}'.format(config['train']['dropout']))
        print('|--- EPSILON:\t{}'.format(config['train']['epsilon']))
        print('|--- PATIENCE:\t{}'.format(config['train']['patience']))
        print('|--- BATCH:\t{}'.format(config['model']['batch_size']))
    else:
        print('----------------------- TEST -----------------------')
        print('|--- MODEL_FILENAME:\t{}'.format(config['train']['model_filename']))
        print('|--- RUN_TIMES:\t{}'.format(config['test']['run_times']))

    print('----------------------------------------------------')
    infor_correct = input('Is the information correct? y(Yes)/n(No):')
    if infor_correct != 'y' and infor_correct != 'yes':
        raise RuntimeError('Information is not correct!')


def train_gconvrnn(config):
    print('|-- Run model training gconvrnn.')
    rng = np.random.RandomState(config['seed'])

    tf_config = tf.ConfigProto()
    tf_config.gpu_options.allow_growth = True

    with tf.Session(config=tf_config) as sess:
        model = GCONVRNN(is_training=True, **config)
        model.train()


def test_gconvrnn(config):
    print('|-- Run model testing gconvrnn.')

    tf_config = tf.ConfigProto()
    tf_config.gpu_options.allow_growth = True
    with tf.Session(config=tf_config) as sess:
        model = GCONVRNN(is_training=False, **config)
        model.load(sess, config['train']['model_filename'])
        model.test(sess)
        # np.savez_compressed(os.path.join(HOME_PATH, config['test']['results_path']), **outputs)
        #
        # print('Predictions saved as {}.'.format(os.path.join(HOME_PATH, config['test']['results_path']) + '.npz'))


def evaluate_gconvrnn(config):
    print('|-- Run model testing gconvrnn.')

    tf_config = tf.ConfigProto()
    tf_config.gpu_options.allow_growth = True
    with tf.Session(config=tf_config) as sess:
        model = GCONVRNN(is_training=False, **config)
        model.load(sess, config['train']['model_filename'])
        outputs = model.evaluate(sess)


if __name__ == '__main__':

    sys.path.append(os.getcwd())
    parser = argparse.ArgumentParser()
    parser.add_argument('--use_cpu_only', default=False, type=str, help='Whether to run tensorflow on cpu.')
    parser.add_argument('--config', default='Config/config_gconvrnn.yaml', type=str,
                        help='Config file for pretrained model.')
    parser.add_argument('--mode', default='train', type=str,
                        help='Run mode.')
    parser.add_argument('--output_filename', default='data/gconvrnn_predictions.npz')
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.load(f)

    print_gconvrnn_info(args.mode, config)
    if args.mode == 'train':
        train_gconvrnn(config)
    elif args.mode == 'evaluate' or args.mode == 'evaluation':
        evaluate_gconvrnn(config)
    else:
        test_gconvrnn(config)
    # get_results(data)