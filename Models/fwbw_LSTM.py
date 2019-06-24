from keras.layers import LSTM, Dense, Dropout, TimeDistributed, Flatten, Input, Concatenate, Reshape, Add
from keras.models import Model
from keras.utils import plot_model

from Models.AbstractModel import AbstractModel


class fwbw_lstm_model(AbstractModel):

    def __init__(self, saving_path, input_shape, hidden, drop_out,
                 alg_name=None, tag=None, early_stopping=False, check_point=False):
        super().__init__(alg_name=alg_name, tag=tag, early_stopping=early_stopping, check_point=check_point,
                         saving_path=saving_path)

        self.n_timestep = input_shape[0]

        self.hidden = hidden
        self.input_shape = input_shape
        self.drop_out = drop_out
        self.model = None

    def construct_fwbw_lstm_2(self):
        input_tensor = Input(shape=self.input_shape, name='input')

        fw_lstm_layer = LSTM(self.hidden, input_shape=self.input_shape, return_sequences=True)(input_tensor)
        fw_drop_out = Dropout(self.drop_out)(fw_lstm_layer)

        fw_flat_layer = TimeDistributed(Flatten())(fw_drop_out)
        fw_dense_1 = TimeDistributed(Dense(64, ))(fw_flat_layer)
        fw_dense_2 = TimeDistributed(Dense(32, ))(fw_dense_1)
        fw_output = TimeDistributed(Dense(1, ))(fw_dense_2)

        fw_input_tensor_flatten = Reshape((self.input_shape[0] * self.input_shape[1], 1))(input_tensor)
        _input_fw = Concatenate(axis=1)([fw_input_tensor_flatten, fw_output])

        _input_fw = Flatten()(_input_fw)
        _input_fw = Dense(256, )(_input_fw)
        _input_fw = Dense(128, )(_input_fw)
        fw_outputs = Dense(self.n_timestep, name='fw_outputs')(_input_fw)

        bw_lstm_layer = LSTM(self.hidden, input_shape=self.input_shape,
                             return_sequences=True, go_backwards=True)(input_tensor)

        bw_drop_out = Dropout(self.drop_out)(bw_lstm_layer)

        bw_flat_layer = TimeDistributed(Flatten())(bw_drop_out)
        bw_dense_1 = TimeDistributed(Dense(64, ))(bw_flat_layer)
        bw_dense_2 = TimeDistributed(Dense(32, ))(bw_dense_1)
        bw_outputs = TimeDistributed(Dense(1, ))(bw_dense_2)

        input_tensor_flatten = Reshape((self.input_shape[0] * self.input_shape[1], 1))(input_tensor)
        _input = Concatenate(axis=1)([input_tensor_flatten, bw_outputs])

        _input = Flatten()(_input)
        x = Dense(256, )(_input)
        x = Dense(128, )(x)
        corr_data = Dense(self.n_timestep - 2, name='corr_data')(x)

        self.model = Model(inputs=input_tensor, outputs=[fw_outputs, corr_data], name='fwbw-lstm')

        self.model.compile(loss='mse', optimizer='adam', metrics=['mse', 'mae'])

    def construct_fwbw_lstm(self):
        # Input
        input_tensor = Input(shape=self.input_shape, name='input')

        # Forward Network
        fw_lstm_layer = LSTM(self.hidden, input_shape=self.input_shape, return_sequences=True)(input_tensor)
        fw_drop_out = Dropout(self.drop_out)(fw_lstm_layer)
        fw_flat_layer = TimeDistributed(Flatten())(fw_drop_out)
        fw_dense_1 = TimeDistributed(Dense(64, ))(fw_flat_layer)
        fw_dense_2 = TimeDistributed(Dense(32, ))(fw_dense_1)
        fw_outputs = TimeDistributed(Dense(1, ), name='fw_outputs')(fw_dense_2)

        # Backward Network
        bw_lstm_layer = LSTM(self.hidden, input_shape=self.input_shape,
                             return_sequences=True, go_backwards=True)(input_tensor)
        bw_drop_out = Dropout(self.drop_out)(bw_lstm_layer)
        bw_flat_layer = TimeDistributed(Flatten())(bw_drop_out)
        bw_dense_1 = TimeDistributed(Dense(64, ))(bw_flat_layer)
        bw_dense_2 = TimeDistributed(Dense(32, ))(bw_dense_1)
        bw_output = TimeDistributed(Dense(1, ))(bw_dense_2)

        bw_input_tensor_flatten = Reshape((self.input_shape[0] * self.input_shape[1], 1))(input_tensor)
        _input_bw = Concatenate(axis=1)([bw_input_tensor_flatten, bw_output])

        _input_bw = Flatten()(_input_bw)
        _input_bw = Dense(256, )(_input_bw)
        _input_bw = Dense(128, )(_input_bw)
        bw_outputs = Dense(self.n_timestep, name='bw_outputs')(_input_bw)

        self.model = Model(inputs=input_tensor, outputs=[fw_outputs, bw_outputs], name='fwbw-lstm')

        self.model.compile(loss='mse', optimizer='adam', metrics=['mse', 'mae'])

    def construct_fwbw_lstm_no_sc(self):
        # Input
        input_tensor = Input(shape=self.input_shape, name='input')

        # Forward Network
        fw_lstm_layer = LSTM(self.hidden, input_shape=self.input_shape, return_sequences=True)(input_tensor)
        fw_drop_out = Dropout(self.drop_out)(fw_lstm_layer)
        fw_flat_layer = TimeDistributed(Flatten())(fw_drop_out)
        fw_dense_1 = TimeDistributed(Dense(64, ))(fw_flat_layer)
        fw_dense_2 = TimeDistributed(Dense(32, ))(fw_dense_1)
        fw_outputs = TimeDistributed(Dense(1, ), name='fw_outputs')(fw_dense_2)

        # Backward Network
        bw_lstm_layer = LSTM(self.hidden, input_shape=self.input_shape,
                             return_sequences=True, go_backwards=True)(input_tensor)
        bw_drop_out = Dropout(self.drop_out)(bw_lstm_layer)
        bw_flat_layer = TimeDistributed(Flatten())(bw_drop_out)
        bw_dense_1 = TimeDistributed(Dense(64, ))(bw_flat_layer)
        bw_dense_2 = TimeDistributed(Dense(32, ))(bw_dense_1)
        bw_outputs = TimeDistributed(Dense(1, ))(bw_dense_2)

        self.model = Model(inputs=input_tensor, outputs=[fw_outputs, bw_outputs], name='fwbw-lstm')

        self.model.compile(loss='mse', optimizer='adam', metrics=['mse', 'mae'])

    def construct_res_fwbw_lstm(self):
        # Input
        input_tensor = Input(shape=self.input_shape, name='input')
        input_2 = Input(shape=(self.n_timestep, 1), name='input2')

        # Forward Network
        fw_lstm_layer = LSTM(self.hidden, input_shape=self.input_shape, return_sequences=True)(input_tensor)
        fw_drop_out = Dropout(self.drop_out)(fw_lstm_layer)
        fw_flat_layer = TimeDistributed(Flatten())(fw_drop_out)
        fw_dense_1 = TimeDistributed(Dense(64, ))(fw_flat_layer)
        fw_dense_2 = TimeDistributed(Dense(32, ))(fw_dense_1)
        fw_output = TimeDistributed(Dense(1, ))(fw_dense_2)

        # fw_input_tensor_flatten = Reshape((self.input_shape[0] * self.input_shape[1], 1))(input_tensor)
        _input_fw = Add()([input_2, fw_output])

        _input_fw = Flatten()(_input_fw)
        _input_fw = Dense(64, )(_input_fw)
        fw_outputs = Dense(self.n_timestep, name='fw_outputs')(_input_fw)

        # Backward Network
        bw_lstm_layer = LSTM(self.hidden, input_shape=self.input_shape,
                             return_sequences=True, go_backwards=True)(input_tensor)
        bw_drop_out = Dropout(self.drop_out)(bw_lstm_layer)
        bw_flat_layer = TimeDistributed(Flatten())(bw_drop_out)
        bw_dense_1 = TimeDistributed(Dense(64, ))(bw_flat_layer)
        bw_dense_2 = TimeDistributed(Dense(32, ))(bw_dense_1)
        bw_output = TimeDistributed(Dense(1, ))(bw_dense_2)

        _input_bw = Add()([input_2, bw_output])

        _input_bw = Flatten()(_input_bw)
        _input_bw = Dense(64, )(_input_bw)
        bw_outputs = Dense(self.n_timestep, name='bw_outputs')(_input_bw)

        self.model = Model(inputs=[input_tensor, input_2], outputs=[fw_outputs, bw_outputs], name='fwbw-lstm')

        self.model.compile(loss='mse', optimizer='adam', metrics=['mse', 'mae'])

    def plot_models(self):
        plot_model(model=self.model, to_file=self.saving_path + '/model.png', show_shapes=True)

    def plot_training_history(self, model_history):
        import matplotlib.pyplot as plt

        plt.plot(model_history.history['loss'], label='loss')
        plt.plot(model_history.history['val_loss'], label='val_loss')
        plt.savefig(self.saving_path + '[loss]{}-{}.png'.format(self.alg_name, self.tag))
        plt.legend()
        plt.close()

        plt.plot(model_history.history['val_loss'], label='val_loss')
        plt.savefig(self.saving_path + '[val_loss]{}-{}.png'.format(self.alg_name, self.tag))
        plt.legend()
        plt.close()