from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import tensorflow as tf
from tensorflow.contrib.rnn import RNNCell

from lib import utils


class DCGRUCellWeighted(RNNCell):
    """Graph Convolution Gated Recurrent Unit cell.
    """

    def call(self, inputs, **kwargs):
        pass

    def compute_output_shape(self, input_shape):
        pass

    def __init__(self, num_units, adj_mx, max_diffusion_step, num_nodes, batch_size, num_proj=None,
                 activation=tf.nn.tanh, reuse=None, filter_type="laplacian", use_gc_for_ru=True):
        """

        :param num_units:
        :param adj_mx:
        :param max_diffusion_step:
        :param num_nodes:
        :param input_size:
        :param num_proj:
        :param activation:
        :param reuse:
        :param filter_type: "laplacian", "random_walk", "dual_random_walk".
        :param use_gc_for_ru: whether to use Graph convolution to calculate the reset and update gates.
        """
        super(DCGRUCellWeighted, self).__init__(_reuse=reuse)
        self._activation = activation
        self._num_nodes = num_nodes
        self._num_proj = num_proj
        self._num_units = num_units
        self._max_diffusion_step = max_diffusion_step
        self._supports = []
        self._use_gc_for_ru = use_gc_for_ru
        self._supports_dense = []

        supports = []
        if filter_type == "laplacian":
            supports.append(utils.calculate_scaled_laplacian(adj_mx, lambda_max=None))
        elif filter_type == "random_walk":
            supports.append(utils.calculate_random_walk_matrix(adj_mx).T)
        elif filter_type == "dual_random_walk":
            supports.append(utils.calculate_random_walk_matrix(adj_mx).T)
            supports.append(utils.calculate_random_walk_matrix(adj_mx.T).T)
        else:
            supports.append(utils.calculate_scaled_laplacian(adj_mx))
        for support in supports:
            self._supports.append(self._build_sparse_matrix(support))

        _adj_mx = tf.convert_to_tensor(adj_mx)
        self._adj_mx_repeat = tf.tile(tf.expand_dims(_adj_mx, axis=0), [batch_size, 1, 1])
        for support in self._supports:
            self._supports_dense.append(tf.sparse.to_dense(support))

    @staticmethod
    def _build_sparse_matrix(L):
        L = L.tocoo()
        indices = np.column_stack((L.row, L.col))
        L = tf.SparseTensor(indices, L.data, L.shape)
        return tf.sparse_reorder(L)

    @property
    def state_size(self):
        return self._num_nodes * self._num_units

    @property
    def output_size(self):
        if self._num_proj is not None:
            output_size = self._num_nodes * self._num_proj
        else:
            output_size = self._num_nodes * (self._num_units + 1)
        return output_size

    def __call__(self, inputs, state, scope=None):
        """Gated recurrent unit (GRU) with Graph Convolution.
        :param inputs: (B, num_nodes * input_dim)

        :return
        - Output: A `2-D` tensor with shape `[batch_size x self.output_size]`.
        - New state: Either a single `2-D` tensor, or a tuple of tensors matching
            the arity and shapes of `state`
        """

        with tf.variable_scope(scope or "dcgru_cell_en"):
            with tf.variable_scope("gates"):  # Reset gate and update gate.
                batch_size = inputs.get_shape()[0].value
                inputs = tf.reshape(inputs, (batch_size, self._num_nodes, -1))

                size = inputs.get_shape()[2].value
                weight_nodes = inputs[:, :, -1]
                weight_nodes = tf.reshape(weight_nodes, shape=[batch_size, self._num_nodes, 1])
                weight_nodes_tiled = tf.tile(weight_nodes, [1, 1, self._num_nodes])
                inputs = inputs[:, :, :(size - 1)]
                weight_nodes_tiled = self._adj_mx_repeat * weight_nodes_tiled  # (batch, num_nodes, num_nodes)

                outputsize = 2 * self._num_units
                # We start with bias of 1.0 to not reset and not update.
                value = tf.nn.sigmoid(self._gconv(inputs, state, weight_nodes_tiled, outputsize, bias_start=1.0))
                value = tf.reshape(value, (-1, self._num_nodes, outputsize))
                r, u = tf.split(value=value, num_or_size_splits=2, axis=-1)
                r = tf.reshape(r, (-1, self._num_nodes * self._num_units))
                u = tf.reshape(u, (-1, self._num_nodes * self._num_units))
            with tf.variable_scope("candidate"):
                c = self._gconv(inputs, r * state, weight_nodes_tiled, self._num_units)
                if self._activation is not None:
                    c = self._activation(c)
            output = new_state = u * state + (1 - u) * c
            if self._num_proj is not None:
                with tf.variable_scope("projection"):
                    w = tf.get_variable('w', shape=(self._num_units, self._num_proj))
                    batch_size = inputs.get_shape()[0].value
                    output = tf.reshape(new_state, shape=(-1, self._num_units))
                    output = tf.reshape(tf.matmul(output, w), shape=(batch_size, self.output_size))
            else:
                output = tf.reshape(output, shape=[batch_size, self._num_nodes, self._num_units])
                output = tf.concat([output, weight_nodes], axis=2)
                output = tf.reshape(output, shape=(batch_size, self._num_nodes * (self._num_units + 1)))

        return output, new_state

    @staticmethod
    def _concat(x, x_):
        x_ = tf.expand_dims(x_, 0)
        return tf.concat([x, x_], axis=0)

    def _fc(self, inputs, state, weight_nodes, outputsize, bias_start=0.0):
        dtype = inputs.dtype
        batch_size = inputs.get_shape()[0].value
        inputs = tf.reshape(inputs, (batch_size * self._num_nodes, -1))
        state = tf.reshape(state, (batch_size * self._num_nodes, -1))
        inputs_and_state = tf.concat([inputs, state], axis=-1)
        input_size = inputs_and_state.get_shape()[-1].value
        weights = tf.get_variable(
            'weights', [input_size, outputsize], dtype=dtype,
            initializer=tf.contrib.layers.xavier_initializer())
        value = tf.nn.sigmoid(tf.matmul(inputs_and_state, weights))
        biases = tf.get_variable("biases", [outputsize], dtype=dtype,
                                 initializer=tf.constant_initializer(bias_start, dtype=dtype))
        value = tf.nn.bias_add(value, biases)
        return value

    def _gconv(self, inputs, state, directed_weight_links, outputsize, bias_start=0.0):
        """Graph convolution between input and the graph matrix.

        :param args: a 2D Tensor or a list of 2D, batch x n, Tensors.
        :param output_size:
        :param bias:
        :param bias_start:
        :param scope:
        :return:
        """
        # Reshape input and state to (batch_size, num_nodes, input_dim/state_dim)
        batch_size = inputs.get_shape()[0].value
        inputs = tf.reshape(inputs, (batch_size, self._num_nodes, -1))

        # prepare the inputs_state
        state = tf.reshape(state, (batch_size, self._num_nodes, -1))
        inputs_and_state = tf.concat([inputs, state], axis=2)
        input_size = inputs_and_state.get_shape()[2].value
        dtype = inputs.dtype

        xb = inputs_and_state  # (batch, num_node, arg_size)

        num_matrices = len(self._supports) * self._max_diffusion_step + 1  # Adds for x itself.

        x = tf.zeros(shape=(0, num_matrices, self._num_nodes, input_size))

        scope = tf.get_variable_scope()
        with tf.variable_scope(scope):
            for batch_idx in range(batch_size):
                x0 = xb[batch_idx]  # (num_node, arg_size)
                xk = tf.expand_dims(x0, axis=0)  # results of diffusion process on each input x (1, num_node, arg_size)
                if self._max_diffusion_step == 0:
                    pass
                else:
                    for support_dense in self._supports_dense:
                        # pw (num_nodes, num_nodes)
                        pw = directed_weight_links[batch_idx] * support_dense
                        x1 = tf.matmul(pw, x0)  # (num_node, arg_size)
                        xk = self._concat(xk, x1)

                        for k in range(2, self._max_diffusion_step + 1):
                            x2 = 2 * tf.matmul(pw, x1) - x0
                            xk = self._concat(xk, x2)
                            x1, x0 = x2, x1

                x = self._concat(x, xk)

            x = tf.transpose(x, perm=[0, 2, 3, 1])  # shape (batch, nodes, size, nsupport)
            x = tf.reshape(x, shape=[batch_size * self._num_nodes, input_size * num_matrices])

            weights = tf.get_variable(
                'weights', [input_size * num_matrices, outputsize], dtype=dtype,
                initializer=tf.contrib.layers.xavier_initializer())
            x = tf.matmul(x, weights)  # (batch_size * self._num_nodes, output_size)

            biases = tf.get_variable("biases", [outputsize], dtype=dtype,
                                     initializer=tf.constant_initializer(bias_start, dtype=dtype))
            x = tf.nn.bias_add(x, biases)
        # Reshape res back to 2D: (batch_size, num_node, state_dim) -> (batch_size, num_node * state_dim)
        return tf.reshape(x, [batch_size, self._num_nodes * outputsize])
