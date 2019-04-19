# Data Config
DATA_PATH = './Dataset/'
MODEL_SAVE = './trained_models/'
RESULTS_PATH = './results/'

TESTING_TIME = 10

# Training config
N_EPOCH = 100
BATCH_SIZE = 64
NUM_ITER = 10000

# Testing config
BEST_CHECKPOINT = 100

# Config conv_lstm
CNN_LAYERS = 2
FILTERS = [8, 8]
KERNEL_SIZE = [[3, 3], [3, 3]]
STRIDES = [[1, 1], [1, 1]]
DROPOUTS = [0.0, 0.0]
RNN_DROPOUTS = [0.2, 0.2]

# Input Config
CNN_WIDE = 12
CNN_HIGH = 12
CNN_CHANNEL = 2

# LSTM Config
LSTM_STEP = 26
LSTM_FEATURES = 2
LSTM_HIDDEN_UNIT = 64
LSTM_DROPOUT = 0.5
IMS_STEP = 26

# Arima Config
HISTORY_LENGTH = 10

# Problem hyperparams
MON_RAIO = 0.3
HYPERPARAMS = [2.0, 0.1, 5.0, 0.4]
