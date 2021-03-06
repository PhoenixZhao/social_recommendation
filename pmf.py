#coding=utf8 
'''
    实现pmf的代码
    version1: rewrite in python the matlab code given by Ruslan, the path is ../code_BPMF/pmf.m
'''

import math
from datetime import datetime
import time
import signal

import numpy as np
from scipy import sparse

import logging
from logging_util import init_logger

#def sigint_handler(signum, frame):
#    print 'Stop pressing the CTRL+C!'
#
#signal.signal(signal.SIGINT, sigint_handler)

ratings_file = '../data/epinions/ver1_ratings_data.txt'
#ratings_file = '../data/Douban/uir.index'
#ratings_file = '../data/Movielens/ml-100k/u.data'
trust_file = '../data/epinions/ver1_trust_data.txt'


sigmod = lambda x: 1.0/(1+pow(math.e, -x))
sigmod_der = lambda x: pow(math.e, x) / (1 + pow(math.e, x)) ** 2
sigmod_f = np.vectorize(lambda x: sigmod(x))
sigmod_d = np.vectorize(lambda x: sigmod_der(x))

class PMF(object):

    def __init__(self, use_normalized_data=True, start_from_zero=False, learning_rate=0.001):
        init_logger(log_file='log/pmf.log', log_level=logging.INFO)
        self.exp_id = datetime.today().strftime('%Y%m%d%H%M%S')
        self.ratings_file = ratings_file
        self.load_data()
        self.obs_num = self.ratings_vector.shape[0]
        self.use_normalized_data = use_normalized_data
        self.start_from_zero = start_from_zero#数据里user_id和item_id是否从0开始，豆瓣是从0开始的

        if self.use_normalized_data:
            self.generate_normalized_ratings()
        self.split_data()

        self.learning_rate = learning_rate
        self.epsilon = learning_rate; #learning rate
        self.lamb = 0.01 #Regularization parameter
        self.momentum = 0.8
        self.max_epoch = 1000 #iteration
        self.feat_num = 10

        #uid, vid以observation里出现的uid为准, 如何划分数据也是一个问题
        self.user_num = self.ratings_vector[:,0].max()
        self.item_num = self.ratings_vector[:,1].max()

        self.U_shape = (self.user_num, self.feat_num)
        self.V_shape = (self.item_num, self.feat_num)

        #U: matrix of user features, V: matrix of item features, generated from gaussian distribution
        self.U = np.random.standard_normal(self.U_shape)
        self.V = np.random.standard_normal(self.V_shape)

    def split_data(self):
        '''
            split the data into two parts: train and validation vector
            choose randomly a proportion of data by train_ratio, the remaining as validation data
        '''
        rand_inds = np.random.permutation(self.obs_num)
        train_ratio = 0.8
        self.train_num = int(self.obs_num * train_ratio)

        self.train_vector = self.ratings_vector[rand_inds[:self.train_num]]
        self.vali_vector = self.ratings_vector[rand_inds[self.train_num:]]
        logging.info('observations=%s, train_ratio=%s, train_num=%s, vali_num=%s',\
                self.obs_num, train_ratio, self.train_vector.shape[0], self.vali_vector.shape[0])
        del rand_inds

    def load_data(self):
        '''
            load triplets(user_id, movie_id, rating)
            make user_id and item_id start from zero
        '''
        self.ratings_vector = np.loadtxt(self.ratings_file,delimiter=' ')
        self.ratings_vector = self.ratings_vector[:,[0,1,2]]

    def generate_normalized_ratings(self, minus_mean=True, mapping_01=False):
        '''
            mapping the rating 1,...,K to [0, 1] by the formula r = (x - 1) / (K - 1)
        '''
        self.mapping_01 = mapping_01
        self.minus_mean = minus_mean
        if self.mapping_01:
            max_ = self.ratings_vector[:,2].max()
            self.ratings_vector[:,2] = (self.ratings_vector[:,2] - 1.0) / (max_ - 1)
        if self.minus_mean:
            mean = np.mean(self.ratings_vector[:,2])
            self.ratings_vector[:,2] -= mean

    def train(self):
        '''
            standard PMF with gradient descent
        '''
        if self.start_from_zero:
            #douban data是从0开始的下标
            user_inds = self.train_vector[:,0].astype(int)
            item_inds = self.train_vector[:,1].astype(int)
        else:
            #starting from 0
            user_inds = self.train_vector[:,0].astype(int) - 1
            item_inds = self.train_vector[:,1].astype(int) - 1
        ratings  = self.train_vector[:,2]

        train_start = time.time()
        real_iter = 0
        for epoch in range(1, self.max_epoch):
            try:
                round_start = time.time()

                U_V_pairwise = np.multiply(self.U[user_inds,:], self.V[item_inds,:])

                #####compute predictions####
                if self.use_normalized_data and self.mapping_01:
                    pred_out = sigmod_f(U_V_pairwise.sum(axis=1))#|R| * K --> |R| * 1
                else:
                    pred_out = U_V_pairwise.sum(axis=1)#|R| * K --> |R| * 1


                err_f = 0.5 * (np.square(pred_out - ratings).sum() + self.lamb * (np.square(self.U).sum() + np.square(self.V).sum()))

                pred_time = time.time()
                #####calculate the gradients#####
                grad_u = np.zeros(self.U_shape)
                grad_v = np.zeros(self.V_shape)

                if self.use_normalized_data and self.mapping_01:
                    ####update gradient
                    sigmod_dot = sigmod_f(U_V_pairwise.sum(axis=1))
                    sigmod_der_V = sigmod_d(U_V_pairwise.sum(axis=1))
                    U_V_delta = np.multiply(sigmod_der_V, (sigmod_dot - ratings)).reshape(self.train_num, 1) #|R| * 1
                    delta_matrix = np.tile(U_V_delta, self.feat_num) # |R| * K, 这样就可以使得u_i和对应的v_j进行dot product, 可以直接使用矩阵运算
                    delta_U = np.multiply(delta_matrix, self.V[item_inds,:])
                    delta_V = np.multiply(delta_matrix, self.U[user_inds,:])

                else:
                    ####update gradient
                    U_V_delta = (pred_out - ratings).reshape(self.train_num, 1) #|R| * 1
                    delta_matrix = np.tile(U_V_delta, self.feat_num) # |R| * K, 这样就可以使得u_i和对应的v_j进行dot product, 可以直接使用矩阵运算
                    delta_U = np.multiply(delta_matrix, self.V[item_inds,:])
                    delta_V = np.multiply(delta_matrix, self.U[user_inds,:])
                dot_time = time.time()

                ind = 0
                for uid, vid, r in self.train_vector:
                    if not self.start_from_zero:
                        uid -= 1
                        vid -= 1
                    grad_u[uid] +=  delta_U[ind]
                    grad_v[vid] +=  delta_V[ind]
                    ind += 1

                accumulate_time = time.time()

                logging.debug('dot/accumulate cost %.1fs/%.1fs', dot_time - pred_time, accumulate_time - dot_time)

                grad_u += self.lamb * self.U
                grad_v += self.lamb * self.V
                cal_grad_time = time.time()

                #####update the U and V vectors
                self.U -= self.epsilon * grad_u
                self.V -= self.epsilon * grad_v
                round_end = time.time()

                logging.info('iter=%s, learning_rate=%s, train error=%s, cost(gradient/round) %.1fs/%.1fs', \
                        epoch, self.epsilon, err_f, cal_grad_time - pred_time, round_end - round_start)

                if epoch % 50 == 0:
                    self.epsilon =self.learning_rate  / epoch * 20
                if epoch % 10 == 0:
                    self.predict()
                    self.evaluate()
                real_iter = epoch
            except KeyboardInterrupt:
                real_iter = epoch
                break

        logging.info('training finished, cost %.2fmin', (time.time() - train_start) / 60.0)
        self.predict()
        self.evaluate()
        logging.info('config: iters=%s, feat=%s, regularization=%s, learning_rate=%s, normalized_data=%s', real_iter, self.feat_num, self.lamb, self.epsilon, 'minus_mean' if self.minus_mean else '')
        logging.info('****************Experiment@%s*******************', self.exp_id)

    def predict(self):
        '''
            predict the rating using the dot product of U,V
        '''
        if self.start_from_zero:
            user_inds = self.vali_vector[:,0].astype(int)
            item_inds = self.vali_vector[:,1].astype(int)
        else:
            user_inds = self.vali_vector[:,0].astype(int) - 1
            item_inds = self.vali_vector[:,1].astype(int) - 1

        if self.use_normalized_data and self.mapping_01:
            self.predictions = sigmod_f(np.multiply(self.U[user_inds,:], self.V[item_inds,:]).sum(axis=1))
        else:
            self.predictions = np.multiply(self.U[user_inds,:], self.V[item_inds,:]).sum(axis=1)

    def evaluate(self):
        '''
            calculate the RMSE&MAE
        '''
        rand_inds = np.random.permutation(len(self.predictions))
        sample_ids = rand_inds[:100]
        vali_ratings = self.vali_vector[:,2]
        samples = [(round(self.predictions[r],1), round(vali_ratings[r], 1)) for r in sample_ids]
        logging.info('prediction samples: %s', samples)
        #大于5小于1改成1，5
        #self.predictions[self.predictions > 5.0] = 5.0
        #self.predictions[self.predictions < 1.0] = 1.0
        delta = self.predictions - vali_ratings
        mae = np.absolute(delta).sum() / delta.shape[0]
        rmse = math.sqrt(np.square(delta).sum() / delta.shape[0])
        logging.info('evaluations: rating_file=%s, mae=%.2f, rmse=%.2f', ratings_file, mae, rmse)

    def run(self):
        logging.info('****************Experiment@%s*******************', self.exp_id)
        logging.info('config: iters=%s, feat=%s, regularization=%s, learning_rate=%s, normalized_data=%s', self.max_epoch, self.feat_num, self.lamb, self.epsilon, 'minus_mean' if self.minus_mean else '')
        self.train()

if __name__ == '__main__':
    pmf = PMF()
    pmf.run()

