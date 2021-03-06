import os

import numpy as np
import yaml
from keras.callbacks import ModelCheckpoint, EarlyStopping
from keras.layers import LSTM, Dense, Input
from keras.models import Model
from keras.utils import plot_model
from tqdm import tqdm

from Models.AbstractModel import AbstractModel, TimeHistory
from lib import metrics
from lib import utils


class EncoderDecoder(AbstractModel):

    def __init__(self, is_training=True, **kwargs):
        super(EncoderDecoder, self).__init__(**kwargs)

        self._batch_size = self._data_kwargs.get('batch_size')

        self._data = utils.load_dataset_lstm_ed(seq_len=self._seq_len, horizon=self._horizon,
                                                input_dim=self._input_dim,
                                                mon_ratio=self._mon_ratio,
                                                scaler_type=self._kwargs.get('scaler'),
                                                **self._data_kwargs)
        for k, v in self._data.items():
            if hasattr(v, 'shape'):
                self._logger.info((k, v.shape))

        # Model
        self.callbacks_list = []

        self._checkpoints = ModelCheckpoint(
            self._log_dir + "best_model.hdf5",
            monitor='val_loss', verbose=1,
            save_best_only=True,
            mode='auto', period=1)
        self.callbacks_list = [self._checkpoints]

        self._earlystop = EarlyStopping(monitor='val_loss', patience=self._train_kwargs.get('patience'),
                                        verbose=1, mode='auto')
        self.callbacks_list.append(self._earlystop)

        self._time_callback = TimeHistory()
        self.callbacks_list.append(self._time_callback)

        self.model = self._model_construction(is_training=is_training)

    def _model_construction(self, is_training=True):
        # Model
        encoder_inputs = Input(shape=(None, self._input_dim))
        encoder = LSTM(self._rnn_units, return_state=True)
        encoder_outputs, state_h, state_c = encoder(encoder_inputs)
        # We discard `encoder_outputs` and only keep the states.
        encoder_states = [state_h, state_c]

        # Set up the decoder, using `encoder_states` as initial state.
        decoder_inputs = Input(shape=(None, 1))
        # We set up our decoder to return full output sequences,
        # and to return internal states as well. We don't use the
        # return states in the training model, but we will use them in inference.
        decoder_lstm = LSTM(self._rnn_units, return_sequences=True, return_state=True)
        decoder_outputs, _, _ = decoder_lstm(decoder_inputs,
                                             initial_state=encoder_states)

        decoder_dense = Dense(1, activation='relu')
        decoder_outputs = decoder_dense(decoder_outputs)

        # Define the model that will turn
        # `encoder_input_data` & `decoder_input_data` into `decoder_target_data`
        model = Model([encoder_inputs, decoder_inputs], decoder_outputs)

        if is_training:
            return model
        else:
            self._logger.info("|--- Load model from: {}".format(self._log_dir))
            model.load_weights(self._log_dir + 'best_model.hdf5')
            model.compile(optimizer='adam', loss='mse', metrics=['mse', 'mae'])

            # Construct E_D model for predicting
            self.encoder_model = Model(encoder_inputs, encoder_states)

            decoder_state_input_h = Input(shape=(self._rnn_units,))
            decoder_state_input_c = Input(shape=(self._rnn_units,))
            decoder_states_inputs = [decoder_state_input_h, decoder_state_input_c]
            decoder_outputs, state_h, state_c = decoder_lstm(
                decoder_inputs, initial_state=decoder_states_inputs)
            decoder_states = [state_h, state_c]
            decoder_outputs = decoder_dense(decoder_outputs)
            self.decoder_model = Model(
                [decoder_inputs] + decoder_states_inputs,
                [decoder_outputs] + decoder_states)

            plot_model(model=self.encoder_model, to_file=self._log_dir + '/encoder.png', show_shapes=True)
            plot_model(model=self.decoder_model, to_file=self._log_dir + '/decoder.png', show_shapes=True)

            return model

    def _prepare_input(self, data, m_indicator):

        dataX = np.zeros(shape=(data.shape[1], self._seq_len, 2), dtype='float32')
        for flow_id in range(data.shape[1]):
            x = data[-self._seq_len:, flow_id]
            label = m_indicator[-self._seq_len:, flow_id]

            sample = np.array([x, label]).T
            dataX[flow_id] = sample

        return dataX

    def _ims_tm_prediction_ed(self, input):
        states_value = self.encoder_model.predict(input)

        target_seq = np.zeros((self._nodes, 1, 1))
        target_seq[:, 0, 0] = [0] * self._nodes

        multi_steps_tm = np.zeros(shape=(self._horizon + 1, self._nodes),
                                  dtype='float32')

        for ts_ahead in range(self._horizon + 1):
            output_tokens, h, c = self.decoder_model.predict(
                [target_seq] + states_value)

            output_tokens = output_tokens[:, -1, 0]

            multi_steps_tm[ts_ahead] = output_tokens

            target_seq = np.zeros((self._nodes, 1, 1))
            target_seq[:, 0, 0] = output_tokens

            # Update states
            states_value = [h, c]

        return multi_steps_tm[-self._horizon:]

    def _run_tm_prediction(self):

        test_data_norm = self._data['test_data_norm']

        tf_a = np.array([1.0, 0.0])
        m_indicator = np.zeros(shape=(test_data_norm.shape[0] - self._horizon, self._nodes),
                               dtype='float32')

        tm_pred = np.zeros(shape=(test_data_norm.shape[0] - self._horizon, self._nodes),
                           dtype='float32')

        tm_pred[0:self._seq_len] = test_data_norm[0:self._seq_len]
        m_indicator[0:self._seq_len] = np.ones(shape=(self._seq_len, self._nodes))

        y_preds = []
        y_truths = []

        # Predict the TM from time slot look_back
        for ts in tqdm(range(test_data_norm.shape[0] - self._horizon - self._seq_len)):
            # This block is used for iterated multi-step traffic matrices prediction

            input = self._prepare_input(data=tm_pred[ts:ts + self._seq_len],
                                        m_indicator=m_indicator[ts:ts + self._seq_len])

            # Generate empty target sequence of length 1.
            # Populate the first character of target sequence with the start character.
            predicted_tm = self._ims_tm_prediction_ed(input)

            # Get the TM prediction of next time slot

            y_preds.append(np.expand_dims(predicted_tm, axis=0))
            pred = predicted_tm[0]

            # Using part of current prediction as input to the next estimation
            # Randomly choose the flows which is measured (using the correct data from test_set)

            # boolean array(1 x n_flows):for choosing value from predicted data
            if self._flow_selection == 'Random':
                sampling = np.random.choice(tf_a, size=self._nodes,
                                            p=[self._mon_ratio, 1 - self._mon_ratio])
            else:
                sampling = self._set_measured_flow_fairness(m_indicator=m_indicator[ts: ts + self._seq_len])

            m_indicator[ts + self._seq_len] = sampling
            # invert of sampling: for choosing value from the original data
            inv_sampling = 1.0 - sampling
            pred_input = pred * inv_sampling

            ground_true = test_data_norm[ts + self._seq_len].copy()
            y_truths.append(
                np.expand_dims(test_data_norm[ts + self._seq_len:ts + self._seq_len + self._horizon], axis=0))

            measured_input = ground_true * sampling

            # Merge value from pred_input and measured_input
            new_input = pred_input + measured_input
            # new_input = np.reshape(new_input, (new_input.shape[0], new_input.shape[1], 1))

            # Concatenating new_input into current rnn_input
            tm_pred[ts + self._seq_len] = new_input

        outputs = {
            'tm_pred': tm_pred[self._seq_len:],
            'm_indicator': m_indicator[self._seq_len:],
            'y_preds': y_preds,
            'y_truths': y_truths
        }

        return outputs

    def test(self):
        n_metrics = 4
        # Metrics: MSE, MAE, RMSE, MAPE, ER
        metrics_summary = np.zeros(shape=(self._run_times + 3, self._horizon * n_metrics + 1))

        for i in range(self._run_times):
            self._logger.info('|--- Running time: {}/{}'.format(i, self._run_times))

            test_results = self._run_tm_prediction()

            metrics_summary = self._calculate_metrics(prediction_results=test_results, metrics_summary=metrics_summary,
                                                      scaler=self._data['scaler'],
                                                      runId=i, data_norm=self._data['test_data_norm'])

        self._summarize_results(metrics_summary=metrics_summary, n_metrics=n_metrics)

    def train(self):
        self.model.compile(optimizer='adam', loss='mse', metrics=['mse', 'mae'])

        training_history = self.model.fit([self._data['encoder_input_train'], self._data['decoder_input_train']],
                                          self._data['decoder_target_train'],
                                          batch_size=self._batch_size,
                                          epochs=self._epochs,
                                          callbacks=self.callbacks_list,
                                          validation_data=([self._data['encoder_input_val'],
                                                            self._data['decoder_input_val']],
                                                           self._data['decoder_target_val']),
                                          shuffle=True,
                                          verbose=2)
        if training_history is not None:
            self.plot_training_history(training_history)
            self.save_model_history(times=self._time_callback.times, model_history=training_history)
            config = dict(self._kwargs)
            config_filename = 'config_lstm.yaml'
            config['train']['log_dir'] = self._log_dir
            with open(os.path.join(self._log_dir, config_filename), 'w') as f:
                yaml.dump(config, f, default_flow_style=False)

    def evaluate(self):
        scaler = self._data['scaler']

        y_pred = self.model.predict([self._data['encoder_input_eval'], self._data['decoder_input_eval']])
        y_pred = scaler.inverse_transform(y_pred)
        y_truth = scaler.inverse_transform(self._data['decoder_target_eval'])

        mse = metrics.masked_mse_np(preds=y_pred, labels=y_truth, null_val=0)
        mae = metrics.masked_mae_np(preds=y_pred, labels=y_truth, null_val=0)
        mape = metrics.masked_mape_np(preds=y_pred, labels=y_truth, null_val=0)
        rmse = metrics.masked_rmse_np(preds=y_pred, labels=y_truth, null_val=0)
        self._logger.info(
            "Horizon {:02d}, MSE: {:.2f}, MAE: {:.2f}, RMSE: {:.2f}, MAPE: {:.4f}".format(
                1, mse, mae, rmse, mape
            )
        )
