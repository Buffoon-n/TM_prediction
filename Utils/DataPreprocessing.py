import numpy as np
from multiprocessing import Process, Manager, Pool, Array, Pipe
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from FlowClassification.SpatialClustering import *


def prepare_train_test_valid_set(data, sampling_itvl=5, splitting_ratio=[0.5, 0.25, 0.25]):
    """
    Divide raw dataset into train, test and valid set based on the splitting_ratio
    :param data: (numpy.ndarray) the raw data (the m x n Traffic Matrix)
    :param sampling_itvl: (int) the interval between each sample
    :param splitting_ratio: (array) splitting ratio. Default: train 50%, test 25%,valid 25%
    :return: (numpy.ndarray) the train set, test set and valid set
    """
    n_timeslots = data.shape[0]
    day_size = 24 * (60 / sampling_itvl)
    n_days = n_timeslots / day_size

    train_size = int(n_days * splitting_ratio[0]) * day_size
    test_size = int(n_days * splitting_ratio[1]) * day_size

    train_set = data[0:train_size, :]
    test_set = data[train_size:(train_size + test_size), :]
    valid_set = data[(train_size + test_size):n_timeslots, :]

    return train_set, test_set, valid_set


def prepare_train_test_set(data, sampling_itvl=5, splitting_ratio=[0.7, 0.3]):
    """
    Divide raw dataset into train and test set based on the splitting ratio.
    :param data: (numpy.ndarray) the raw data (the m x n Traffic Matrix)
    :param sampling_itvl: (int) the interval between each sample
    :param splitting_ratio: (array) splitting ratio. Default: train 70%, test 35%
    :return: (numpy.ndarray) the train set and test set
    """
    n_timeslots = data.shape[0]
    day_size = 24 * (60 / sampling_itvl)
    n_days = n_timeslots / day_size

    train_size = int(n_days * splitting_ratio[0]) * day_size

    train_set = data[0:train_size, :]
    test_set = data[train_size:n_timeslots, :]

    return train_set, test_set


def create_xy_set(data, look_back):
    """
    Create X, Y sets from the dataset based on lookback
    :param data: (numpy.ndarray) the traffic matrix data
    :param look_back: (int) the no of time step of the input data for RNN
    :return: (numpy.ndarray) the X, Y set
    """
    dataX, dataY = [], []
    for j in xrange(data.shape[1]):
        for i in range(data.shape[0] - look_back - 1):
            a = data[i:(i + look_back), j]
            dataX.append(a)
            dataY.append(data[i + look_back, j])

    return np.array(dataX), np.array(dataY)


def create_xy_set_seq2seq(data, look_back):
    """
    Create X, Y sets from the dataset based on lookback
    :param data: (numpy.ndarray) the traffic matrix data
    :param look_back: (int) the no of time step of the input data for RNN
    :return: (numpy.ndarray) the X, Y set
    """
    dataX, dataY = [], []
    for j in xrange(data.shape[1]):
        for i in range(data.shape[0] - look_back - 1):
            a = data[i:(i + look_back), j]
            dataX.append(a)
            y = data[(i+1):(i+look_back+1),j]
            dataY.append(y)

    return np.array(dataX), np.array(dataY)


def create_xy_set_backward(data, look_back):
    """
    Create X, Y sets from the dataset based on lookback
    :param data: (numpy.ndarray) the traffic matrix data
    :param look_back: (int) the no of time step of the input data for RNN
    :return: (numpy.ndarray) the X, Y set
    """
    dataX, dataY = [], []
    for j in xrange(data.shape[1]):
        for i in range(data.shape[0] - look_back - 1):
            y = np.flip(data[i:(i + look_back), j], axis=0)
            dataY.append(y)
            x = np.flip(data[(i+1):(i+look_back+1), j], axis=0)
            dataX.append(x)

    return np.array(dataX), np.array(dataY)



def parallel_create_xy_set_spatial_temporal(data, look_back, sampling_ivtl, nproc, rnn_type='normal_rnn'):
    quota = int(data.shape[1] / nproc)

    p = [0] * nproc

    connections = []

    for proc_id in range(nproc):
        connections.append(Pipe())

    dataX = np.empty((0, look_back, 4))
    dataY = []

    if rnn_type == 'normal_rnn':
        dataY = np.empty((0, 1))
    else:
        dataY = np.empty((0, look_back))
    ret_xy = []

    for proc_id in range(nproc):
        data_quota = data[:, proc_id * quota:(proc_id + 1) * quota] if proc_id < (nproc - 1) else data[:,
                                                                                                  proc_id * quota:]
        p[proc_id] = Process(target=create_xy_set_spatial_temporal,
                             args=(data_quota, look_back, sampling_ivtl, connections[proc_id][1], rnn_type))
        p[proc_id].start()

    for proc_id in range(nproc):
        ret_xy.append(connections[proc_id][0].recv())
        p[proc_id].join()

    for proc_id in range(nproc):
        dataX = np.concatenate([dataX, ret_xy[proc_id][0]], axis=0)
        dataY = np.concatenate([dataY, ret_xy[proc_id][1]], axis=0)

    return dataX, dataY


def time_scaler(time_series, feature_range):
    scaler = MinMaxScaler(feature_range=feature_range)
    time_series = np.reshape(np.array(time_series), (len(time_series), -1))
    ret = scaler.fit_transform(time_series)
    return ret.squeeze().tolist()


def create_xy_set_spatial_temporal(data, look_back, sampling_ivtl, conneciton, rnn_type='normal_rnn'):
    """
    Create X, Y sets from the dataset based on lookback
    :param conneciton:
    :param data: (numpy.ndarray) the traffic matrix data
    :param look_back: (int) the no of time step of the input data for RNN
    :return: (numpy.ndarray) the X, Y set
    """

    # Format of an element of a sample: (numpy.ndarray)-(1 x k) k is the no. of features
    # Format of a sample: (numpy.ndarray)-(look_back x k) look_back: the no. of history data points used for predicting
    # Feature tuple (x_c, x_p, x_w, t_c, t_d)
    # xc: current traffic volume at time slot t
    # xp: traffic volume at time slot t+1 of previous day
    # tc: current time slot (1-288 when sampling interval is 5mins)
    # dw: day within a week (1-7)
    k = 4

    day_size = 24 * (60 / sampling_ivtl)
    n_days = int(data.shape[0] / day_size) if (data.shape[0] % day_size) == 0 else int(data.shape[0] / day_size) + 1
    day_in_week = time_scaler(range(1, 8, 1) * day_size * n_days, feature_range=(0, 1))
    time_in_day = time_scaler(range(day_size) * n_days, feature_range=(0, 1))

    dataX = np.empty((0, look_back, k))
    dataY = []
    if rnn_type == 'bidirectional_rnn':
        dataY = np.empty((0, look_back))

    for j in xrange(data.shape[1]):
        for i in range(data.shape[0] - look_back - 1):
            sample = []

            # Get x_c for all look_back
            xc = data[i:(i + look_back), j]
            sample.append(xc)

            # Get x_p: x_p = x_c in the first day in dataset
            if i - day_size + 1 < 0:
                xp = data[i:(i + look_back), j]
                sample.append(xp)
            else:
                xp = data[(i + 1 - day_size):(i + look_back - day_size + 1), j]
                sample.append(xp)

            # Get the current timeslot
            tc = time_in_day[i:(i + look_back)]
            sample.append(tc)

            # Get the current day in week
            dw = day_in_week[i:(i + look_back)]
            sample.append(dw)

            # Stack the feature into a sample and reshape it into the input shape of RNN: (1, timestep, features)
            a_sample = np.reshape(np.array(sample).T, (1, look_back, k))

            # Concatenate the samples into a dataX
            dataX = np.concatenate([dataX, a_sample], axis=0)
            if rnn_type == 'bidirectional_rnn':
                dataY = np.concatenate([dataY, np.expand_dims(data[(i + 1):(i + look_back + 1), j], axis=0)], axis=0)
            else:
                dataY.append(data[i + look_back, j])

    if rnn_type == 'normal_rnn':
        dataY = np.expand_dims(np.array(dataY), axis=1)

    conneciton.send([dataX, dataY])
    conneciton.close()


def parallel_create_xy_set_bidirectional_rnn(data, look_back, sampling_ivtl, nproc):
    return


def create_xy_set_over_day(data, look_back_days, sampling_itvl):
    day_size = 24 * (60 / sampling_itvl)
    ndays = data.shape[0] / day_size

    dataX = np.empty((0, look_back_days))
    dataY = np.empty((0, 1))
    for ts in range(day_size):

        for day in range(ndays - look_back_days - 1):
            based_index = day * day_size
            x_over_day = data[(based_index + ts):(based_index + ts + day_size * look_back_days):day_size, :]
            assert x_over_day.shape[0] == look_back_days
            y_over_day = np.expand_dims(data[(based_index + ts + day_size * look_back_days), :], axis=1)

            dataX = np.concatenate([dataX, x_over_day.T], axis=0)
            dataY = np.concatenate([dataY, y_over_day], axis=0)

    return dataX, dataY


def parallel_create_xy_set_temporal(data, n_timesteps, look_back, sampling_ivtl, nproc):
    quota = int(data.shape[1] / nproc)

    p = [0] * nproc

    connections = []

    for proc_id in range(nproc):
        connections.append(Pipe())

    dataX = np.empty((0, n_timesteps, look_back))
    dataY = np.empty((0, n_timesteps, look_back))

    ret_xy = []

    for proc_id in range(nproc):
        data_quota = data[:, proc_id * quota:(proc_id + 1) * quota] if proc_id < (nproc - 1) else data[:,
                                                                                                  proc_id * quota:]
        p[proc_id] = Process(target=create_xy_set_temporal,
                             args=(data_quota, n_timesteps, look_back, sampling_ivtl, connections[proc_id][1]))
        p[proc_id].start()

    for proc_id in range(nproc):
        ret_xy.append(connections[proc_id][0].recv())
        p[proc_id].join()

    for proc_id in range(nproc):
        dataX = np.concatenate([dataX, ret_xy[proc_id][0]], axis=0)
        dataY = np.concatenate([dataY, ret_xy[proc_id][1]], axis=0)

    return dataX, dataY


def create_xy_set_temporal(data, n_timesteps, look_back, sampling_ivtl, conneciton):
    """
    Create X, Y sets from the dataset based on lookback
    :param n_timesteps:
    :param conneciton:
    :param data: (numpy.ndarray) the traffic matrix data
    :param look_back: (int) the no of time step of the input data for RNN
    :return: (numpy.ndarray) the X, Y set
    """

    # Format of an element of a sample: (numpy.ndarray)-(1 x k) k is the no. of features
    # Format of a sample: (numpy.ndarray)-(look_back x k) look_back: the no. of history data points used for predicting
    # Feature tuple (x_c, x_p, x_w, t_c, t_d)
    # xc: current traffic volume at time slot t
    # xp: traffic volume at time slot t+1 of previous day
    # tc: current time slot (1-288 when sampling interval is 5mins)
    # dw: day within a week (1-7)

    day_size = 24 * (60 / sampling_ivtl)
    dataX = np.empty((0, n_timesteps, look_back))
    dataY = np.empty((0, n_timesteps, look_back))

    for j in xrange(data.shape[1]):

        _start_ts = look_back*day_size
        for i in range(_start_ts, data.shape[0] - n_timesteps - 1):
            sampleX = []
            sampleY = []

            for _lb in range(look_back):
                # Get x_c for all look_back
                xc = data[(i - look_back*day_size):(i - look_back*day_size + n_timesteps), j]
                sampleX.append(xc)
                yc = data[(i - look_back*day_size + 1):(i - look_back*day_size + n_timesteps + 1), j]
                sampleY.append(yc)

            # Stack the feature into a sample and reshape it into the input shape of RNN: (1, timestep, features)
            a_sampleX = np.reshape(np.array(sampleX).T, (1, n_timesteps, look_back))
            a_sampleY = np.reshape(np.array(sampleY).T, (1, n_timesteps, look_back))

            # Concatenate the samples into a dataX
            dataX = np.concatenate([dataX, a_sampleX], axis=0)
            dataY = np.concatenate([dataY, a_sampleY], axis=0)

    conneciton.send([dataX, dataY])
    conneciton.close()


def create_xy_labeled(raw_data, data, look_back, labels):

    dataX = np.empty((0, look_back, 2))
    dataY = []
    for flowid in range(data.shape[1]):
        _range = 1 if data.shape[0] == look_back else data.shape[0] - look_back - 1
        for ts in range(_range):
            x = data[ts:(ts+look_back), flowid]
            label = labels[ts:(ts+look_back), flowid]
            sample = np.array([x,label]).T
            sample = np.reshape(sample, (1, sample.shape[0], sample.shape[1]))
            dataX = np.concatenate([dataX, sample], axis=0)

            y = raw_data[ts:(ts+look_back), flowid]
            dataY.append(y)

    dataY = np.array(dataY)
    dataY = np.reshape(dataY, (dataY.shape[0], dataY.shape[1], 1))
    return dataX, dataY


def create_xy_labeled_backward(raw_data, data, look_back, labels):
    dataX = np.empty((0, look_back, 2))
    dataY = []
    for flowid in range(data.shape[1]):
        _range = 1 if data.shape[0] == look_back else data.shape[0] - look_back - 1
        for ts in range(_range):
            x = data[(ts+1):(ts+look_back+1), flowid]
            x = np.flip(x, axis=0)
            label = labels[ts:(ts+look_back), flowid]
            label = np.flip(label, axis=0)
            sample = np.array([x,label]).T
            sample = np.reshape(sample, (1, sample.shape[0], sample.shape[1]))
            dataX = np.concatenate([dataX, sample], axis=0)

            y = raw_data[(ts):(ts+look_back), flowid]
            y = np.flip(y, axis=0)
            dataY.append(y)

    dataY = np.array(dataY)
    dataY = np.reshape(dataY, (dataY.shape[0], dataY.shape[1], 1))
    return dataX, dataY




########################################################################################################################
#                                        Flows Clustering and Normalization                                            #
########################################################################################################################


def flows_seperating(data, labels, n_clusters, flows_clusters, cores):
    """
    Seperate flows into diffterent groups based on the flow's labels and the no. of cluster
    :param data: (numpy.ndarray) The set of flow
    :param labels: (list) The labels list
    :param n_clusters: (int) The no. of cluster
    :param flows_clusters:
    :param cores:
    :return:
    """
    for cluster_id in range(n_clusters):
        flows_indice = np.array(np.where(labels == cluster_id)).squeeze()
        flows = data[:, flows_indice]
        flows_clusters.append(data[:, flows_indice])
        cores.append(np.mean(flows_clusters[cluster_id], axis=0))

    return flows_clusters, cores


def mean_std_flows_clustering(data):
    """
    Cluster flows based on the means and std using dbscan and k-means
    :param data: (numpy.ndarray) The set of flows
    :return:
    """
    # List of seperated flows and the central of the cluster
    seperated_flows = []
    centers = []
    labels = []

    # Initialize no. of cluster equal to 1
    # Using DBSCAN to determine the main group of flows
    # while loop until there are at least 2 clusters have been determined.

    n_clusters = 1
    eps = 0.4
    min_samples = int(0.1 * data.shape[1])

    while n_clusters <= 1:
        eps = eps + 0.001
        db, n_clusters = flows_DBSCAN(data=data, eps=eps, min_samples=min_samples)
        labels = db.labels_
        labels = labels + 1

    # Seperate the noises
    flows_seperating(data, labels=labels, n_clusters=n_clusters, flows_clusters=seperated_flows, cores=centers)

    # Using k-means in order to cluster the noises
    kmeans, k_clusters = flows_k_means(data=seperated_flows[0], max_k=4)
    flows_seperating(data=seperated_flows[0], labels=kmeans.labels_, n_clusters=k_clusters,
                     flows_clusters=seperated_flows, cores=centers)

    return seperated_flows, centers


def different_flows_scaling(data, centers):
    scalers = []
    ret_set = np.empty((data[0].shape[0], 0))
    cluster_lens = []
    for cluster_id in range(len(data)):
        scaler = StandardScaler()
        scaler = scaler.fit(data[cluster_id])
        scalers.append(scaler)
        data[cluster_id] = scaler.transform(data[cluster_id])
        ret_set = np.concatenate([ret_set, data[cluster_id]], axis=1)
        cluster_lens.append(data[cluster_id].shape[1])
    return ret_set, scalers, cluster_lens


def different_flows_invert_scaling(data, scalers, cluster_lens):
    end_index = 0

    invert_data = np.empty((data.shape[0], 0))

    for cluster_id in range(len(scalers)):
        start_index = end_index
        end_index = start_index + cluster_lens[cluster_id]
        scaler = scalers[cluster_id]
        invert_flows = scaler.inverse_transform(data[:, start_index:end_index])
        invert_data = np.concatenate([invert_data, invert_flows], axis=1)

    return invert_data


def different_flows_scaling_without_join(data, centers):
    scalers = []
    cluster_lens = []
    for cluster_id in range(len(data)):
        scaler = MinMaxScaler(feature_range=(0, 1)).fit(data[cluster_id])
        scalers.append(scaler)
        data[cluster_id] = scaler.transform(data[cluster_id])
        cluster_lens.append(data[cluster_id].shape[1])
    return data, scalers, cluster_lens


########################################################################################################################
#                                            Convert TM into one hot vector                                            #
########################################################################################################################

def one_hot_encoder(data, max_v, min_v, unique_step, n_unique, connection=None):

    encoded_tm = np.empty((data.shape[0], 0, n_unique))
    for flow in range(data.shape[1]):
        _flow_encoding = list()
        for ts in range(data.shape[0]):
            _value = data[ts, flow]
            _one_index = int((_value - min_v) / unique_step)
            _vector = [0 for _ in range(n_unique)]
            _vector[_one_index] = 1
            _flow_encoding.append(_vector)

        _flow_encoding = np.array(_flow_encoding)
        # print('--- _flow_encoding_shape ' + str(_flow_encoding.shape))
        _flow_encoding = np.reshape(_flow_encoding, (_flow_encoding.shape[0], 1, _flow_encoding.shape[1]))
        encoded_tm = np.concatenate([encoded_tm, _flow_encoding], axis=1)

    # print(encoded_tm.shape)
    if connection is not None:
        connection.send(encoded_tm)
        connection.close()
    else:
        return encoded_tm


def one_hot_decoder(encoded_tm, unique_step):

    decoded_tm = np.empty((encoded_tm.shape[1], 0))

    for flow in range(encoded_tm.shape[0]):
        _encoded_flow = encoded_tm[flow]
        _decoded_flow = np.array([np.argmax(_vector)*unique_step for _vector in _encoded_flow])
        _decoded_flow = np.reshape(_decoded_flow, (encoded_tm.shape[1], 1))
        decoded_tm = np.concatenate([decoded_tm, _decoded_flow], axis=1)

    return decoded_tm


def tms_to_one_hot_encode_without_joint(tms, n_unique):

    encoded_tms = list()
    unique_steps = list()
    for _cluster in range(len(tms)):
        _encoded_tm, _unique_step = parallel_one_hot_encoder(tms[_cluster], n_unique, nproc=8)
        encoded_tms.append(_encoded_tm)
        unique_steps.append(_unique_step)
        print(_encoded_tm.shape)

    return encoded_tms, unique_steps


def parallel_one_hot_encoder(data, min_v, max_v, unique_step, n_unique, nproc):

    if data.shape[1] < nproc:
        nproc = data.shape[1]

    quota = int(data.shape[1] / nproc)

    p = [0] * nproc

    connections = []
    rev_encoded_tm = np.empty((data.shape[0], 0, n_unique))
    for proc_id in range(nproc):
        connections.append(Pipe())

    for proc_id in range(nproc):
        data_quota = data[:, proc_id * quota:(proc_id + 1) * quota] if proc_id < (nproc - 1) else data[:,
                                                                                                  proc_id * quota:]

        p[proc_id] = Process(target=one_hot_encoder,
                             args=(data_quota, max_v, min_v, unique_step, n_unique, connections[proc_id][1]))
        p[proc_id].start()

    for proc_id in range(nproc):
        rev_encoded_tm = np.concatenate([rev_encoded_tm, connections[proc_id][0].recv()], axis=1)
        p[proc_id].join()

    return rev_encoded_tm


def create_xy_set_encoded(data, look_back, connection):

    dataX = np.empty((0, look_back, data.shape[2]))
    dataY = np.empty((0, look_back, data.shape[2]))
    for flowID in range(data.shape[1]):
        for ts in range(data.shape[0] - look_back):
            _sampleX = data[ts:(ts+look_back), flowID, :]
            _sampleX = np.reshape(_sampleX, (1, look_back, data.shape[2]))
            dataX = np.concatenate([dataX, _sampleX], axis=0)
            _sampleY = data[(ts+1):(ts+look_back+1), flowID, :]
            _sampleY = np.reshape(_sampleY, (1, look_back, data.shape[2]))
            dataY = np.concatenate([dataY, _sampleY], axis=0)

    connection.send([dataX, dataY])
    connection.close()


def parallel_create_xy_set_encoded(data, look_back, nproc):


    if data.shape[1] < nproc:
        nproc = data.shape[1]

    quota = int(data.shape[1] / nproc)

    p = [0] * nproc
    connections = []
    ret_xy = list()

    dataX = np.empty((0, look_back, data.shape[2]))
    dataY = np.empty((0, look_back, data.shape[2]))

    for proc_id in range(nproc):
        connections.append(Pipe())

    for proc_id in range(nproc):
        data_quota = data[:, proc_id * quota:(proc_id + 1) * quota, :] if proc_id < (nproc - 1) else data[:,
                                                                                                  proc_id * quota:, :]

        p[proc_id] = Process(target=create_xy_set_encoded,
                             args=(data_quota, look_back, connections[proc_id][1]))
        p[proc_id].start()

    for proc_id in range(nproc):
        ret_xy.append(connections[proc_id][0].recv())
        p[proc_id].join()

    for proc_id in range(nproc):
        dataX = np.concatenate([dataX, ret_xy[proc_id][0]], axis=0)
        dataY = np.concatenate([dataY, ret_xy[proc_id][1]], axis=0)

    return dataX, dataY



