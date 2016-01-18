__author__ = 'tomas'

import sys
sys.path.append('../../imtools/')
from imtools import tools

import numpy as np
import matplotlib.pyplot as plt

import cv2
import skimage.data as skidat
import skimage.segmentation as skiseg
import skimage.exposure as skiexp

import pygco
import scipy.stats as scista
import ConfigParser

from color_model import ColorModel


class MarkovRandomField:

    def __init__(self, img, seeds=None, n_objects=2, mask=None, alpha=1, beta=1, scale=0, models_estim=None):
        if img.ndim == 2:
            img = np.expand_dims(img, 0)
        if mask is not None and mask.ndim == 2:
            mask = np.expand_dims(mask, 0)
        if seeds is not None and seeds.ndim == 2:
            seeds = np.expand_dims(seeds, 0)

        self.img_orig = img  # original variable
        # self.img = None  # working variable - i.e. resized data etc.
        self.img = img.copy()  # working variable - i.e. resized data etc.
        self.seeds_orig = seeds  # original variable
        if seeds is not None:
            self.seeds = seeds.copy()  # working variable - i.e. resized data etc.
        else:
            self.seeds = None
        if mask is None:
            self.mask_orig = np.ones_like(self.img)
        else:
            self.mask_orig = mask
        self.mask = self.mask_orig.copy()

        self.n_slices, self.n_rows, self.n_cols = self.img_orig.shape
        if seeds is not None:
            self.n_seeds = (seeds > 0).sum()
        else:
            self.n_seeds = 0

        self.alpha = alpha
        self.beta = beta
        self.scale = scale
        if seeds is not None:
            self.n_objects = self.seeds.max()
        else:
            self.n_objects = n_objects

        self.unaries = None  # unary term = data term
        self.pairwise = None  # pairwise term = smoothness term
        self.labels = None  # labels of the final segmentation

        self.models = None  # list of intensity models used for segmentation

        if models_estim is None:
            if seeds is not None:
                self.models_estim = 'seeds'
            else:
                self.models_estim = 'n_objects'
        elif models_estim == 'hydohy':
            self.n_objects = 3
            self.models_estim = models_estim

        self.params = self.load_parameters()
        params = {'alpha': alpha, 'beta': beta, 'scale': scale}
        self.params.update(params)


    def load_parameters(self, config_path='config.ini'):
        # load parameters
        params_default = {
            'win_l': 50,
            'win_w': 350,
            'alpha': 4,
            'beta': 1,
            'zoom': 0,
            'scale': 0.25,
            'perc': 30,
            'k_std_h': 3,
            'domin_simple_estim': 0,
            'prob_w': 0.0001,
            'unaries_as_cdf': 0,
            'bgd_label': 0,
            'hypo_label': 1,
            'domin_label': 2,
            'hyper_label': 3
            # 'voxel_size': (1, 1, 1)
        }

        config = ConfigParser.ConfigParser()
        config.read(config_path)

        params = dict()

        # an automatic way
        for section in config.sections():
            for option in config.options(section):
                try:
                    params[option] = config.getint(section, option)
                except ValueError:
                    try:
                        params[option] = config.getfloat(section, option)
                    except ValueError:
                        if option == 'voxel_size':
                            str = config.get(section, option)
                            params[option] = np.array(map(int, str.split(', ')))
                        else:
                            params[option] = config.get(section, option)

        # self.params.update(self.load_parameters())
        params_default.update(params)

        return params_default

    def estimate_dominant_pdf(self):
        perc = self.params['perc']
        k_std_l = self.params['k_std_h']
        simple_estim = self.params['domin_simple_estim']

        ints = self.img[np.nonzero(self.mask)]
        hist, bins = skiexp.histogram(ints, nbins=256)
        if simple_estim:
            mu, sigma = scista.norm.fit(ints)
        else:
            # ints = self.img[np.nonzero(self.mask)]

            n_pts = self.mask.sum()
            perc_in = n_pts * perc / 100

            peak_idx = np.argmax(hist)
            n_in = hist[peak_idx]
            win_width = 0

            while n_in < perc_in:
                win_width += 1
                n_in = hist[peak_idx - win_width:peak_idx + win_width].sum()

            idx_start = bins[peak_idx - win_width]
            idx_end = bins[peak_idx + win_width]
            inners_m = np.logical_and(ints > idx_start, ints < idx_end)

            # dom_m = np.zeros_like(self.mask)
            # dom_m[np.nonzero(self.mask)] = inners_m

            # plt.figure()
            # plt.subplot(121), plt.imshow(self.img[0, :, :], 'gray')
            # plt.subplot(122), plt.imshow(dom_m[0, :, :], 'gray', interpolation='nearest')
            # plt.show()

            inners = ints[np.nonzero(inners_m)]

            # liver pdf -------------
            mu = bins[peak_idx]
            sigma = k_std_l * np.std(inners)

        mu = int(mu)
        sigma = int(round(sigma))
        rv = scista.norm(mu, sigma)

        return rv

    def estimate_outlier_pdf(self, rv_domin, outlier_type):
        print 'estimate_outlier_pdf:', outlier_type
        prob_w = self.params['prob_w']

        probs = rv_domin.pdf(self.img) * self.mask

        max_prob = rv_domin.pdf(rv_domin.mean())

        prob_t = prob_w * max_prob

        ints_out_m = (probs < prob_t) * self.mask

        ints_out = self.img[np.nonzero(ints_out_m)]

        # if outlier_type == 'hypo':
        #     ints = ints_out[np.nonzero(ints_out < rv_domin.mean())]
        #
        #     ints_idxs = np.nonzero(ints_out < rv_domin.mean())
        #     ints_out_idxs = np.nonzero(ints_out_m)
        #     ints_im = np.zeros_like(self.img)
        #     indcs = np.ravel_multi_index(ints_out_idxs, self.mask.shape)[ints_idxs[0]]
        #     ints_im[np.unravel_index(indcs, self.mask.shape)] = ints
        # elif outlier_type == 'hyper':
        #     ints = ints_out[np.nonzero(ints_out > rv_domin.mean())]
        #
        #     ints_idxs = np.nonzero(ints_out > rv_domin.mean())
        #     ints_out_idxs = np.nonzero(ints_out_m)
        #     ints_im = np.zeros_like(self.img)
        #     indcs = np.ravel_multi_index(ints_out_idxs, self.mask.shape)[ints_idxs[0]]
        #     ints_im[np.unravel_index(indcs, self.mask.shape)] = ints
        # else:
        #     print 'Wrong outlier specification.'
        #     return
        #
        # # plt.figure()
        # # plt.subplot(221), plt.imshow(self.img[0, :, :], 'gray', interpolation='nearest')
        # # plt.subplot(222), plt.imshow(probs[0, :, :], 'gray', interpolation='nearest'), plt.title('domin probs')
        # # plt.subplot(223), plt.imshow(ints_out_m[0, :, :], 'gray', interpolation='nearest'), plt.title('outlier mask')
        # # plt.subplot(224), plt.imshow(ints_im[0, :, :], 'gray', interpolation='nearest'), plt.title(outlier_type)
        # # plt.show()
        #
        # mu, sigma = scista.norm.fit(ints)

        # norm shift
        domin_max = rv_domin.pdf(rv_domin.mean())
        if outlier_type == 'hypo':
            ints = ints_out[np.nonzero(ints_out < rv_domin.mean())]
            mu, sigma = scista.norm.fit(ints)
            rv = scista.norm(mu, sigma).sf
            # rv_hypo = scista.norm(mu_fit, sigma_fit)
            # y1 = scista.beta(1, 4).pdf(x)
        elif outlier_type == 'hyper':
            ints = ints_out[np.nonzero(ints_out > rv_domin.mean())]
            mu, sigma = scista.norm.fit(ints)
            rv = scista.norm(mu, sigma).cdf
            # rv_hyper = scista.norm(mu_fit, sigma_fit)
        else:
            print 'Wrong outlier specification.'
            return

        # mu = int(mu)
        # sigma = int(sigma)
        # rv = scista.norm(mu, sigma)

        return rv

    def calc_models(self):
        if self.models_estim == 'seeds':
            models = self.calc_models_seeds()
        elif self.models_estim == 'hydohy':
            models = self.calc_models_hydohy()
        else:
            raise ValueError('Wrong type of model estimation mode.')

        return models

    def calc_models_seeds(self):
        models = list()
        for i in range(1, self.n_objects + 1):
            pts = self.img[np.nonzero(self.seeds == i)]
            mu = np.mean(pts)
            sigma = np.std(pts)

            mu = int(mu)
            sigma = int(sigma)
            rv = scista.norm(mu, sigma)
            models.append(rv)

        return models

    def calc_models_hydohy(self):
        # print 'calculating intensity models...'
        # dominant class pdf ------------
        rv_domin = self.estimate_dominant_pdf()
        # print '\tdominant pdf: mu = ', rv_domin.mean(), ', sigma = ', rv_domin.std()

        # hypodense class pdf ------------
        rv_hypo = self.estimate_outlier_pdf(rv_domin, 'hypo')
        # print '\thypo pdf: mu = ', rv_hypo.mean(), ', sigma = ', rv_hypo.std()

        # hyperdense class pdf ------------
        rv_hyper = self.estimate_outlier_pdf(rv_domin, 'hyper')
        # print '\thyper pdf: mu = ', rv_hyper.mean(), ', sigma = ', rv_hyper.std()

        x = np.linspace(0, 256, 100)
        y_domin = rv_domin.pdf(x)
        domin_max = rv_domin.pdf(rv_domin.mean())
        y_hypo = rv_hypo(x) * domin_max
        y_hyper = rv_hyper(x) * domin_max
        plt.figure()
        plt.plot(x, y_hypo, 'b-')
        plt.plot(x, y_domin, 'g-')
        plt.plot(x, y_hyper, 'r-')
        plt.show()

        models = [rv_hypo, rv_domin, rv_hyper]

        return models

    def plot_models(self, nbins=256, show_now=True):
        plt.figure()
        x = np.arange(self.img.min(), self.img.max())  # artificial x-axis

        hist, bins = skiexp.histogram(self.img, nbins=nbins)
        plt.plot(bins, hist, 'k')
        plt.hold(True)
        # if self.rv_heal is not None and self.rv_hypo is not None and self.rv_hyper is not None:
        if self.models is not None:
            if self.params['unaries_as_cdf'] and self.models_estim == 'hydohy':
                domin_p = self.models[1].pdf(x)
                hypo_p = (1 - self.models[0].cdf(x))
                hypo_p *= domin_p.max() / hypo_p.max()
                hyper_p = self.models[2].cdf(x)
                hyper_p *= domin_p.max() / hyper_p.max()
                probs = [hypo_p, domin_p, hyper_p]
            else:
                probs = []
                for m in self.models:
                    probs.append(m.pdf(x))
            y_max = max([p.max() for p in probs])
            fac = hist.max() / y_max

            colors = 'rgbcmy' * 10
            for i, p in enumerate(probs):
                plt.plot(x, fac * p, colors[i], linewidth=2)

            # plt.figure()
            # for i, p in enumerate(probs):
            #     plt.subplot(3, 1, i+1), plt.plot(x, p, colors[i], linewidth=2)
            if show_now:
                plt.show()

    def get_unaries(self, ret_prob=False):
        if self.models is None:
            self.models = self.calc_models()

        hypo = scista.norm(self.models[0].mean() + 0, self.models[0].std())
        self.models[0] = hypo
        domin = scista.norm(self.models[1].mean() + 0, self.models[1].std())
        self.models[1] = domin
        hyper = scista.norm(self.models[2].mean() + 0, self.models[2].std())
        self.models[2] = hyper

        if self.models_estim == 'hydohy' and self.params['unaries_as_cdf']:
            # unaries_dom = - self.models[1].logpdf(self.img * rv_heal.pdf(mu_heal)) * self.mask
            unaries_dom = - self.models[1].logpdf(self.img) * self.mask

            # unaries_hyper = - np.log(self.models[2].cdf(self.img) * self.models[1].pdf(self.models[1].mean())) * self.mask
            # unaries_hyper = - self.models[2].logcdf(self.img)# * self.models[1].pdf(self.models[1].mean()) * self.mask
            unaries_hyper = - self.models[2].logcdf(self.img) * self.mask# * self.models[1].pdf(self.models[1].mean()) * self.mask

            # removing zeros with second lowest value so the log(0) wouldn't throw a warning -
            tmp = 1 - self.models[0].cdf(self.img)
            values = np.unique(tmp)
            tmp = np.where(tmp == 0, values[1], tmp)
            # unaries_hypo = - np.log(tmp * rv_heal.pdf(mu_heal)) * mask
            unaries_hypo = - np.log(tmp * self.models[1].pdf(self.models[1].mean())) * self.mask
            unaries_hypo = np.where(np.isnan(unaries_hypo), 0, unaries_hypo)
            unaries_l = [unaries_hypo, unaries_dom, unaries_hyper]

            x = np.arange(0, 255, 1)
            y_dom_p = self.models[1].pdf(x)
            y_hypo_p = (1 - self.models[0].cdf(x))
            y_hypo_p *= y_dom_p.max() / y_hypo_p.max()
            y_hyper_p = self.models[2].cdf(x)
            y_hyper_p *= y_dom_p.max() / y_hyper_p.max()

            y_dom_u = - self.models[1].logpdf(x)
            y_hyper_u = - self.models[2].logcdf(x)
            tmp = 1 - self.models[0].cdf(x)
            hypo_vals = np.sort(tmp.flatten())
            tmp = np.where(tmp == 0, hypo_vals[1], tmp)
            y_hypo_u = - np.log(tmp * self.models[1].pdf(self.models[1].mean()))
            # y_hypo = np.where(np.isnan(y_hypo), 0, y_hypo)

            plt.figure()
            plt.plot(x, y_hypo_p, 'b-')
            plt.plot(x, y_dom_p, 'g-')
            plt.plot(x, y_hyper_p, 'r-')
            plt.title('probabilities (cdf models)')

            plt.figure()
            plt.plot(x, y_hypo_u, 'b-')
            plt.plot(x, y_dom_u, 'g-')
            plt.plot(x, y_hyper_u, 'r-')
            plt.title('unary term (cdf models)')

            prob_dom = self.models[1].pdf(self.img) * self.mask
            prob_hyper = self.models[2].cdf(self.img)
            prob_hyper *= prob_dom.max() / prob_hyper.max() * self.mask
            prob_hypo = (1 - self.models[0].cdf(self.img))
            prob_hypo *= prob_dom.max() / prob_hypo.max() * self.mask
            un_probs = [prob_hypo, prob_dom, prob_hyper]
        else:
            unaries_l = [- model.logpdf(self.img) for model in self.models]
            un_probs = [model.pdf(self.img) for model in self.models]

            x = np.arange(0, 255, 1)
            y_hypo_p = self.models[0].odf(x)
            y_dom_p = self.models[1].pdf(x)
            y_hyper_p = self.models[2].pdf(x)

            y_hypo_u = - self.models[0].logpdf(x)
            y_dom_u = - self.models[1].logpdf(x)
            y_hyper_u = - self.models[2].logpdf(x)

            plt.figure()
            plt.plot(x, y_hypo_p, 'b-')
            plt.plot(x, y_dom_p, 'g-')
            plt.plot(x, y_hyper_p, 'r-')
            plt.title('probabilities (pdf models)')

            plt.figure()
            plt.plot(x, y_hypo_u, 'b-')
            plt.plot(x, y_dom_u, 'g-')
            plt.plot(x, y_hyper_u, 'r-')
            plt.title('unary term (pdf models)')

        unaries = np.dstack((x.reshape(-1, 1) for x in unaries_l))
        un_probs = np.dstack((x.reshape(-1, 1) for x in un_probs))

        # probs_l = [un_probs[:, :, x].reshape(self.img.shape[1:]) * self.mask[0,:,:] for x in range(un_probs.shape[-1])]
        # tools.arange_figs(probs_l, max_r=1, colorbar=True, same_range=False, show_now=True)

        if ret_prob:
            return unaries.astype(np.int32), un_probs
        else:
            return unaries.astype(np.int32)

    def set_unaries(self, unaries, resize=False):
        '''
        Set unary term.
        :param unaries: list of unary terms - item per object, item has to be an ndarray
        :param resize: if to resize to match the image (scaled down by factor self.scale) shape ot raise an error
        :return:
        '''
        if (unaries.shape[0] != np.prod(self.img.shape)):
        #     if resize:
        #         unaries = [cv2.resize(x, self.img.shape) for x in unaries]
        #     else:
            raise ValueError('Wrong unaries shape. Either input the right shape (1, n_pts, n_objs) or allow resizing.')

        unaries = np.dstack((x.reshape(-1, 1) for x in unaries))

        self.n_objects = unaries.shape[0]
        self.unaries = unaries

    def show_slice(self, slice_id, show_now=True):
        plt.figure()
        plt.subplot(221), plt.imshow(self.img_orig[slice_id, :, :], 'gray', interpolation='nearest'), plt.title('input image')
        plt.subplot(222), plt.imshow(self.seeds_orig[slice_id, :, :], interpolation='nearest'), plt.title('seeds')
        plt.subplot(223), plt.imshow(self.labels[slice_id, :, :], interpolation='nearest'), plt.title('segmentation')
        plt.subplot(224), plt.imshow(skiseg.mark_boundaries(self.img[slice_id, :, :].astype(np.uint8), self.labels[slice_id, :, :]),
                                     interpolation='nearest'), plt.title('segmentation')
        if show_now:
            plt.show()

    def run(self, resize=True):
        #----  rescaling  ----
        if resize and self.scale != 0:
            self.img = tools.resize3D(self.img_orig, self.scale, sliceId=0)
            self.seeds = tools.resize3D(self.seeds_orig, self.scale, sliceId=0)
            self.mask = tools.resize3D(self.mask_orig, self.scale, sliceId=0)
            # for i, (im, seeds, mask) in enumerate(zip(self.img_orig, self.seeds_orig, self.mask_orig)):
            #     self.img[i, :, :] = cv2.resize(im, (0,0), fx=self.scale, fy=self.scale, interpolation=cv2.INTER_NEAREST)
            #     self.seeds[i, :, :] = cv2.resize(seeds, (0,0),  fx=self.scale, fy=self.scale, interpolation=cv2.INTER_NEAREST)
            #     self.mask[i, :, :] = cv2.resize(mask, (0,0),  fx=self.scale, fy=self.scale, interpolation=cv2.INTER_NEAREST)
        # else:
        #     self.img = self.img_orig
        #     self.seeds = self.seeds_orig
        self.n_slices, self.n_rows, self.n_cols = self.img.shape

        #----  calculating intensity models  ----
        if self.unaries is None:
            print 'calculating intensity models ...',
            # self.models = self.calc_intensity_models()
            self.models = self.calc_models()
            print 'done'

        #----  creating unaries  ----
        if self.unaries is None:
            print 'calculating unary potentials ...',
            self.unaries = self.beta * self.get_unaries()
            print 'done'

        #----  create potts pairwise  ----
        if self.pairwise is None:
            print 'calculating pairwise potentials ...',
            self.pairwise = - self.alpha * np.eye(self.n_objects, dtype=np.int32)
            print 'done'

        #----  deriving graph edges  ----
        print 'deriving graph edges ...',
        # use the gerneral graph algorithm
        # first, we construct the grid graph
        # inds = np.arange(self.n_rows * self.n_cols).reshape(self.img.shape)
        # horz = np.c_[inds[:, :-1].ravel(), inds[:, 1:].ravel()]
        # vert = np.c_[inds[:-1, :].ravel(), inds[1:, :].ravel()]
        # self.edges = np.vstack([horz, vert]).astype(np.int32)
        inds = np.arange(self.img.size).reshape(self.img.shape)
        if self.img.ndim == 2:
            horz = np.c_[inds[:, :-1].ravel(), inds[:, 1:].ravel()]
            vert = np.c_[inds[:-1, :].ravel(), inds[1:, :].ravel()]
            self.edges = np.vstack([horz, vert]).astype(np.int32)
        elif self.img.ndim == 3:
            horz = np.c_[inds[:, :, :-1].ravel(), inds[:, :, 1:].ravel()]
            vert = np.c_[inds[:, :-1, :].ravel(), inds[:, 1:, :].ravel()]
            dept = np.c_[inds[:-1, :, :].ravel(), inds[1:, :, :].ravel()]
            self.edges = np.vstack([horz, vert, dept]).astype(np.int32)
        # deleting edges with nodes outside the mask
        nodes_in = np.ravel_multi_index(np.nonzero(self.mask), self.img.shape)
        rows_inds = np.in1d(self.edges, nodes_in).reshape(self.edges.shape).sum(axis=1) == 2
        self.edges = self.edges[rows_inds, :]
        print 'done'

        #----  calculating graph cut  ----
        print 'calculating graph cut ...',
        # we flatten the unaries
        result_graph = pygco.cut_from_graph(self.edges, self.unaries.reshape(-1, self.n_objects), self.pairwise)
        self.labels = result_graph.reshape(self.img.shape)
        print 'done'

        #----  zooming to the original size  ----
        if resize and self.scale != 0:
            # self.labels_orig = cv2.resize(self.labels, (0,0),  fx=1. / self.scale, fy= 1. / self.scale, interpolation=cv2.INTER_NEAREST)
            self.labels_orig = tools.resize3D(self.labels, 1. / self.scale, sliceId=0)
        else:
            self.labels_orig = self.labels

        print '----------'
        print 'segmentation done'

        # self.show_slice(0)

        # plt.figure()
        # plt.subplot(221), plt.imshow(self.img_orig[0, :, :], 'gray', interpolation='nearest'), plt.title('input image')
        # plt.subplot(222), plt.imshow(self.seeds_orig[0, :, :], interpolation='nearest')
        # # plt.hold(True)
        # # seeds_v = np.nonzero(self.seeds)
        # # for i in range(len(seeds_v[0])):
        # #     seed = (seeds_v[0][i], seeds_v[1][i])
        # #     if self.seeds[seed]
        # #
        # # plt.plot
        # plt.title('seeds')
        # plt.subplot(223), plt.imshow(self.labels, interpolation='nearest'), plt.title('segmentation')
        # plt.subplot(224), plt.imshow(skiseg.mark_boundaries(self.img_orig, self.labels), interpolation='nearest'), plt.title('segmentation')
        # plt.show()

        return self.labels_orig


#-----------------------------------------------------------------------------------------------------
#-----------------------------------------------------------------------------------------------------
if __name__ == '__main__':
    # loading the image
    img = skidat.camera()
    n_rows, n_cols = img.shape

    # seed points
    seeds_1 = (np.array([90, 252, 394]), np.array([220, 212, 108]))  # first class
    seeds_2 = (np.array([68, 265, 490]), np.array([92, 493, 242]))  # second class
    seeds = np.zeros((n_rows, n_cols), dtype=np.uint8)
    seeds[seeds_1] = 1
    seeds[seeds_2] = 2

    # plt.figure()
    # plt.imshow(seeds, interpolation='nearest')
    # plt.show()

    # plt.figure()
    # plt.imshow(img, 'gray')
    # plt.show()

    # run(img, seeds)

    scale = 0.5  # scaling parameter for resizing the image
    alpha = 1  # parameter for weighting the smoothness term (pairwise potentials)
    beta = 1  # parameter for weighting the data term (unary potentials)
    mrf = MarkovRandomField(img, seeds, alpha=alpha, beta=beta, scale=scale)
    unaries = mrf.get_unaries()
    mrf.set_unaries(unaries)

    plt.figure()
    plt.subplot(131), plt.imshow(img, 'gray')
    plt.subplot(132), plt.imshow(unaries[:, :, 0].reshape(img.shape), 'gray', interpolation='nearest')
    plt.subplot(133), plt.imshow(unaries[:, :, 1].reshape(img.shape), 'gray', interpolation='nearest')
    plt.show()

    labels = mrf.run()

    plt.figure()
    plt.subplot(221), plt.imshow(img, 'gray', interpolation='nearest'), plt.title('input image')
    plt.subplot(222), plt.imshow(seeds, interpolation='nearest')
    # plt.hold(True)
    # seeds_v = np.nonzero(self.seeds)
    # for i in range(len(seeds_v[0])):
    #     seed = (seeds_v[0][i], seeds_v[1][i])
    #     if self.seeds[seed]
    #
    # plt.plot
    plt.title('seeds')
    plt.subplot(223), plt.imshow(labels[0, :, :], interpolation='nearest'), plt.title('segmentation')
    plt.subplot(224), plt.imshow(skiseg.mark_boundaries(img, labels[0, :, :]), interpolation='nearest'), plt.title('segmentation')
    plt.show()