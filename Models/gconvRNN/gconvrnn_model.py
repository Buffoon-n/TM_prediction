import collections

import numpy as np
import tensorflow as tf

import Models.gconvRNN.graph as graph
from Models.gconvRNN.gconvrnn_utils import show_all_variables
from lib.metrics import masked_mae_tf, masked_mse_tf

# Test for tf1.0
# from tf.contrib.rnn.core_rnn_cell import RNNCell
tfversion_ = tf.VERSION.split(".")
global tfversion
if int(tfversion_[0]) < 1:
    raise EnvironmentError("TF version should be above 1.0!!")

if int(tfversion_[1]) < 1:
    print("Working in TF version 1.0....")
    from tensorflow.python.ops.rnn_cell_impl import _RNNCell as RNNCell

    tfversion = "old"
else:
    print("Working in TF version 1.%d...." % int(tfversion_[1]))
    from tensorflow.python.ops.rnn_cell_impl import RNNCell

    tfversion = "new"


def cheby_conv(x, L, lmax, feat_out, K, W):
    '''
    x : [batch_size, N_node, feat_in] - input of each time step
    nSample : number of samples = batch_size
    nNode : number of node in graph
    feat_in : number of input feature
    feat_out : number of output feature
    L : laplacian
    lmax : ?
    K : size of kernel(number of cheby coefficients)
    W : cheby_conv weight [K * feat_in, feat_out]
    '''
    nSample, nNode, feat_in = x.get_shape()
    nSample, nNode, feat_in = int(nSample), int(nNode), int(feat_in)
    L = graph.rescale_L(L, lmax)  # What is this operation?? --> rescale Laplacian
    L = L.tocoo()

    indices = np.column_stack((L.row, L.col))
    L = tf.SparseTensor(indices, L.data, L.shape)
    L = tf.sparse_reorder(L)

    x0 = tf.transpose(x, perm=[1, 2, 0])  # change it to [nNode, feat_in, nSample]
    x0 = tf.reshape(x0, [nNode, feat_in * nSample])
    x = tf.expand_dims(x0, 0)  # make it [1, nNode, feat_in*nSample]

    def concat(x, x_):
        x_ = tf.expand_dims(x_, 0)
        return tf.concat([x, x_], axis=0)

    if K > 1:
        x1 = tf.sparse_tensor_dense_matmul(L, x0)
        x = concat(x, x1)

    for k in range(2, K):
        x2 = 2 * tf.sparse_tensor_dense_matmul(L, x1) - x0
        x = concat(x, x2)
        x0, x1 = x1, x2

    x = tf.reshape(x, [K, nNode, feat_in, nSample])
    x = tf.transpose(x, perm=[3, 1, 2, 0])
    x = tf.reshape(x, [nSample * nNode, feat_in * K])

    x = tf.matmul(x, W)  # No Bias term?? -> Yes
    out = tf.reshape(x, [nSample, nNode, feat_out])
    return out


# gconvLSTM
_LSTMStateTuple = collections.namedtuple("LSTMStateTuple", ('c', 'h'))


class LSTMStateTuple(_LSTMStateTuple):
    __slots__ = ()  # What is this??

    @property
    def dtype(self):
        (c, h) = self
        if not c.dtype == h.dtype:
            raise TypeError("Inconsistent internal state")
        return c.dtype


class gconvLSTMCell(RNNCell):
    def __init__(self, num_units, forget_bias=1.0,
                 state_is_tuple=True, activation=None, reuse=None,
                 laplacian=None, lmax=None, K=None, feat_in=None, nNode=None):
        super(gconvLSTMCell, self).__init__(_reuse=reuse)  # super what is it?

        self._num_units = num_units
        self._forget_bias = forget_bias
        self._state_is_tuple = state_is_tuple
        self._activation = activation or tf.tanh
        self._laplacian = laplacian
        self._lmax = lmax
        self._K = K
        self._feat_in = feat_in
        self._nNode = nNode

    @property
    def state_size(self):
        return (LSTMStateTuple((self._nNode, self._num_units), (self._nNode, self._num_units))
                if self._state_is_tuple else 2 * self._num_units)

    @property
    def output_size(self):
        return self._num_units

    def zero_state(self, batch_size, dtype):
        with tf.name_scope(type(self).__name__ + "myZeroState"):
            zero_state_c = tf.zeros([batch_size, self._nNode, self._num_units], name='c')
            zero_state_h = tf.zeros([batch_size, self._nNode, self._num_units], name='h')
            # print("When it called, I print batch_size", batch_size)
            return (zero_state_c, zero_state_h)

    def __call__(self, inputs, state, scope=None):
        with tf.variable_scope(scope or type(self).__name__):
            if self._state_is_tuple:
                c, h = state
            else:
                c, h = tf.split(value=state, num_or_size_splits=2, axis=1)
            laplacian = self._laplacian
            lmax = self._lmax
            K = self._K
            feat_in = self._feat_in

            # The inputs : [batch_size, nNode, feat_in, nTime?] size tensor
            if feat_in is None:
                # Take out the shape of input
                batch_size, nNode, feat_in = inputs.get_shape()
                # print("hey!")

            feat_out = self._num_units

            if K is None:
                K = 2

            scope = tf.get_variable_scope()
            with tf.variable_scope(scope) as scope:
                try:
                    # Need four diff Wconv weight + for Hidden weight
                    Wzxt = tf.get_variable("Wzxt", [K * feat_in, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Wixt = tf.get_variable("Wixt", [K * feat_in, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Wfxt = tf.get_variable("Wfxt", [K * feat_in, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Woxt = tf.get_variable("Woxt", [K * feat_in, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))

                    Wzht = tf.get_variable("Wzht", [K * feat_out, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Wiht = tf.get_variable("Wiht", [K * feat_out, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Wfht = tf.get_variable("Wfht", [K * feat_out, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Woht = tf.get_variable("Woht", [K * feat_out, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                except ValueError:
                    scope.reuse_variables()
                    Wzxt = tf.get_variable("Wzxt", [K * feat_in, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Wixt = tf.get_variable("Wixt", [K * feat_in, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Wfxt = tf.get_variable("Wfxt", [K * feat_in, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Woxt = tf.get_variable("Woxt", [K * feat_in, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))

                    Wzht = tf.get_variable("Wzht", [K * feat_out, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Wiht = tf.get_variable("Wiht", [K * feat_out, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Wfht = tf.get_variable("Wfht", [K * feat_out, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))
                    Woht = tf.get_variable("Woht", [K * feat_out, feat_out], dtype=tf.float32,
                                           initializer=tf.random_uniform_initializer(minval=-0.1, maxval=0.1))

                bzt = tf.get_variable("bzt", [feat_out])
                bit = tf.get_variable("bit", [feat_out])
                bft = tf.get_variable("bft", [feat_out])
                bot = tf.get_variable("bot", [feat_out])

                # gconv Calculation
                zxt = cheby_conv(inputs, laplacian, lmax, feat_out, K, Wzxt)  # Wxc * x_t
                zht = cheby_conv(h, laplacian, lmax, feat_out, K, Wzht)  # Whc * h_(t-1)
                zt = zxt + zht + bzt
                zt = tf.tanh(zt)

                ixt = cheby_conv(inputs, laplacian, lmax, feat_out, K, Wixt)
                iht = cheby_conv(h, laplacian, lmax, feat_out, K, Wiht)
                it = ixt + iht + bit
                it = tf.sigmoid(it)

                fxt = cheby_conv(inputs, laplacian, lmax, feat_out, K, Wfxt)
                fht = cheby_conv(h, laplacian, lmax, feat_out, K, Wfht)
                ft = fxt + fht + bft
                ft = tf.sigmoid(ft)

                oxt = cheby_conv(inputs, laplacian, lmax, feat_out, K, Woxt)
                oht = cheby_conv(h, laplacian, lmax, feat_out, K, Woht)
                ot = oxt + oht + bot
                ot = tf.sigmoid(ot)

                # c
                new_c = ft * c + it * zt

                # h
                new_h = ot * tf.tanh(new_c)

                if self._state_is_tuple:
                    new_state = LSTMStateTuple(new_c, new_h)
                else:
                    new_state = tf.concat([new_c, new_h], 1)
                return new_h, new_state

class Model(object):
    """
    Defined:
        Placeholder
        Model architecture
        Train / Test function
    """

    def __init__(self, is_training, laplacian, lmax, batch_size, reuse, **config):
        self.is_training = is_training
        self.model_type = config['model_type']
        self.batch_size = batch_size
        self.num_nodes = int(config['num_nodes'])
        self.input_dim = int(config['input_dim'])
        self.seq_len = int(config['seq_len'])
        self.output_dim = int(config['output_dim'])
        # Need to import laplacian, lmax
        self.laplacian = laplacian
        self.lmax = lmax

        self.return_seq = config['return_seq']
        self.rnn_units = int(config['rnn_units'])
        self.num_kernel = int(config['num_kernel'])
        self.num_rnn_layers = int(config['num_rnn_layers'])

        self.classif_loss = config['classif_loss']
        self.learning_rate = float(config['learning_rate'])
        self.max_grad_norm = None
        if float(config['max_grad_norm']) > 0:
            self.max_grad_norm = float(config['max_grad_norm'])
        self.optimizer = config['optimizer']

        self._build_placeholders()
        self._build_model()
        self._build_steps()
        self._build_optim()

        show_all_variables()

    def _build_placeholders(self):
        if self.model_type == 'lstm':
            # here, self.num_node is the input feature
            self.rnn_input = tf.placeholder(tf.float32,
                                            [self.batch_size, self.seq_len, self.num_nodes],
                                            name="rnn_input")
            self.rnn_input_seq = tf.unstack(self.rnn_input, self.seq_len, 1)
        elif self.model_type == 'glstm':
            self.rnn_input = tf.placeholder(tf.float32,
                                            [self.batch_size, self.seq_len, self.num_nodes, self.input_dim],
                                            name="rnn_input")
            self.rnn_input_seq = tf.unstack(self.rnn_input, self.seq_len, 1)
        else:
            raise Exception("[!] Unkown model type: {}".format(self.model_type))

        if self.return_seq:
            self.rnn_output = tf.placeholder(tf.float32,
                                             [self.batch_size, self.seq_len, self.num_nodes, self.output_dim],
                                             name="rnn_output")
            self.rnn_output_seq = tf.unstack(self.rnn_output, self.seq_len, 1)
        else:
            self.rnn_output = tf.placeholder(tf.float32,
                                             [self.batch_size, 1, self.num_nodes, self.output_dim],
                                             name="rnn_output")
            self.rnn_output_seq = self.rnn_output

        self.model_step = tf.Variable(
            0, name='model_step', trainable=False)

    @staticmethod
    def _dense(x, units, name=None):
        input_shape = x.get_shape()
        output_variable = {
            'weight': tf.Variable(tf.random_normal([input_shape[1], units])),
            'bias': tf.Variable(tf.random_normal([units]))}
        o = tf.matmul(x, output_variable['weight']) + output_variable['bias']
        return o

    def _build_model(self, reuse=None):
        with tf.variable_scope("gconv_model", reuse=reuse) as sc:
            if self.model_type == 'lstm':
                cell = tf.nn.rnn_cell.BasicLSTMCell(self.rnn_units, forget_bias=1.0)
                cell = tf.nn.rnn_cell.DropoutWrapper(cell, output_keep_prob=0.8)
                cells = [cell] * self.num_rnn_layers
                n_classes = self.num_nodes
                output_variable = {
                    'weight': tf.Variable(tf.random_normal([self.rnn_units, n_classes])),
                    'bias': tf.Variable(tf.random_normal([n_classes]))}
            elif self.model_type == 'glstm':
                cell = gconvLSTMCell(num_units=self.rnn_units, forget_bias=1.0,
                                     laplacian=self.laplacian, lmax=self.lmax,
                                     K=self.num_kernel,
                                     nNode=self.num_nodes)
                cell = tf.nn.rnn_cell.DropoutWrapper(cell, output_keep_prob=0.8)
                cells = [cell] * self.num_rnn_layers

            else:
                raise Exception("[!] Unkown model type: {}".format(self.model_type))

            cells = tf.contrib.rnn.MultiRNNCell(cells, state_is_tuple=True)
            outputs, states = tf.contrib.rnn.static_rnn(cells, self.rnn_input_seq, dtype=tf.float32)
            # cell = tf.contrib.rnn.core_rnn_cell.DropoutWrapper(cell, output_keep_prob=0.8)
            # Check the tf version here
            predictions = []
            if self.return_seq:
                for output in outputs:
                    prediction = tf.reshape(output, [-1, self.rnn_units])
                    # prediction = tf.matmul(prediction, fc_variable['weight']) + fc_variable['bias']
                    prediction = self._dense(prediction, 1)
                    if self.model_type == 'glstm':
                        prediction = tf.reshape(prediction, [-1, self.num_nodes, self.output_dim])
                    predictions.append(prediction)
            else:
                prediction = tf.reshape(outputs[-1], [-1, self.rnn_units])
                prediction = self._dense(prediction, 1)
                if self.model_type == 'glstm':
                    prediction = tf.reshape(prediction, [-1, self.num_nodes, self.output_dim])
                predictions.append(prediction)

            if self.model_type == 'lstm':
                self.pred_out = tf.concat(predictions, 1)

            # pred_out_softmax = tf.nn.softmax(pred_out,dim=1)
            self.predictions = tf.concat(predictions, 0)
            if self.return_seq:
                self.predictions = tf.reshape(self.predictions, [-1, self.seq_len, self.num_nodes, self.output_dim])
            else:
                self.predictions = tf.reshape(self.predictions, [-1, 1, self.num_nodes, self.output_dim])

            self.pred_out = self.predictions
            self.model_vars = tf.contrib.framework.get_variables(
                sc, collection=tf.GraphKeys.TRAINABLE_VARIABLES)

        self._build_loss()

    def _build_loss(self):
        if self.classif_loss == "cross_entropy":
            losses = [tf.nn.sparse_softmax_cross_entropy_with_logits(
                logits=tf.reshape(logits, [-1, self.num_nodes]), labels=labels)
                for logits, labels in zip(self.predictions, self.rnn_output_seq)]
            loss_sum = tf.reduce_sum(losses, axis=1)
            loss_batchmean = tf.reduce_mean(loss_sum, name="model_loss")

        elif self.classif_loss == 'mae':
            loss_batchmean = masked_mae_tf(self.predictions, self.rnn_output_seq)
        elif self.classif_loss == 'mse':
            loss_batchmean = masked_mse_tf(self.predictions, self.rnn_output_seq)
        else:
            raise ValueError(
                "Unsupported loss type {}".format(
                    self.classif_loss))

        with tf.name_scope("losses"):
            self.loss = loss_batchmean

        self.model_summary = tf.summary.merge([tf.summary.scalar("model_loss/cross_entropy",
                                                                 self.loss)])
        # if hasattr(self, "model_summary"):
        #    self.model_summary = loss_summary

    def _build_steps(self):
        def run(sess, feed_dict, fetch,
                summary_op, summary_writer, output_op=None, output_img=None):
            if summary_writer is not None:
                fetch['summary'] = summary_op
            if output_op is not None:
                fetch['output'] = output_op

            result = sess.run(fetch, feed_dict=feed_dict)
            if "summary" in result.keys() and "step" in result.keys():
                summary_writer.add_summary(result['summary'], result['step'])
                summary_writer.flush()
            return result

        def train(sess, feed_dict, summary_writer=None,
                  with_output=False):
            fetch = {'loss': self.loss,
                     'optim': self.model_optim,  # ?
                     }
            return run(sess, feed_dict, fetch,
                       self.model_summary, summary_writer,
                       output_op=self.pred_out if with_output else None, )

        def test(sess, feed_dict, summary_writer=None, with_output=False):
            fetch = {}
            return run(sess, feed_dict, fetch,
                       self.model_summary, summary_writer,
                       output_op=self.pred_out if with_output else None, )

        self.train = train
        self.test = test

    def _build_optim(self):
        def minimize(loss, step, var_list, learning_rate, optimizer):
            if optimizer == "sgd":
                optim = tf.train.GradientDescentOptimizer(learning_rate)
            elif optimizer == "adam":
                optim = tf.train.AdamOptimizer(learning_rate)
            elif optimizer == "rmsprop":
                optim = tf.train.RMSPropOptimizer(learning_rate)
            else:
                raise Exception("[!] Unkown optimizer: {}".format(
                    optimizer))
            ## Gradient clipping ##
            if self.max_grad_norm is not None:
                grads_and_vars = optim.compute_gradients(
                    loss, var_list=var_list)
                new_grads_and_vars = []
                for idx, (grad, var) in enumerate(grads_and_vars):
                    if grad is not None and var in var_list:
                        grad = tf.clip_by_norm(grad, self.max_grad_norm)
                        grad = tf.check_numerics(
                            grad, "Numerical error in gradient for {}".format(
                                var.name))
                        new_grads_and_vars.append((grad, var))
                return optim.apply_gradients(new_grads_and_vars, global_step=step)
            else:
                grads_and_vars = optim.compute_gradients(
                    loss, var_list=var_list)
                return optim.apply_gradients(grads_and_vars,
                                             global_step=step)

        # optim #
        self.model_optim = minimize(
            self.loss,
            self.model_step,
            self.model_vars,
            self.learning_rate,
            self.optimizer)
