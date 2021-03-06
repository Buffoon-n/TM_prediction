import tensorflow as tf

from Models.lstm.lstm_supervisor import lstm

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
session = tf.Session(config=config)


def build_model(config):
    print('|--- Build models.')

    net = lstm(**config)

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


def evaluate_lstm(config):
    with tf.device('/device:GPU:{}'.format(config['gpu'])):
        lstm_net = build_model(config)
    lstm_net.load()
    lstm_net.evaluate()


def test_lstm(config):
    with tf.device('/device:GPU:{}'.format(config['gpu'])):
        lstm_net = build_model(config)
    lstm_net.load()
    lstm_net.test()
