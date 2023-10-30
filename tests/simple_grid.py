# sample grid parameter file
# build grid with "cobaya-grid-create grid_dir simple_grid.py"

import numpy as np
from cobaya import InputDict
from cobaya.grid_tools.batchjob import DataSet

# optional directory (or list) to look for pre-computed covmats with similar parameters
cov_dir = ""

# grid items not to include
skip = ['base_a_1_like1_like2']

default: InputDict = {
    'params': {'a_0': {'prior': {'min': -4, 'max': 2}, 'ref': -1},
               'a_1': 0.1,
               'a_2': 1.1},
    'sampler': {'mcmc': {'max_samples': 500, 'burn_in': 100, 'covmat': 'auto'}},
}

# list of default settings to combine; each item can be dict or yaml file name
defaults = [default]

importance_defaults = []
minimize_defaults = []
getdist_options = {'ignore_rows': 0.3, 'marker[b_0]': 0}

# settings for the variation of each parameter that is varied in the grid
params = {'a_1': {'prior': {'min': -2, 'max': 2}},
          'a_2': {'prior': {'min': -1, 'max': 3}}}

# Additional (non-params) options to use when each parameter is varied
param_extra_opts = {'a_2': {
    'sampler': {'mcmc': {'max_samples': 100}}}}

like1: InputDict = {
    'likelihood':
        {'mix1': {
            # note that must use explicit "class" parameters, so when using
            # two gaussian_mixture likelihoods at the same time the names are distinct
            # This is not otherwise needed
            'class': 'gaussian_mixture',
            'means': [np.array([-1, 0, 1])],
            'covs': [np.array([[1, 0, 0],
                               [0, 1, 0],
                               [0, 0, 1]])],
            'input_params_prefix': 'a'}}}

like2: InputDict = {
    'likelihood':
        {'mix2': {
            'class': 'gaussian_mixture',
            'means': [np.array([0])],
            'covs': [0.1],
            'input_params_prefix': 'b'}},
    'params': {'b_0': {'prior': {'min': -1, 'max': 1}}}
}

# DataSet is a combination of likelihoods, list of name tags to identify data components
joint = DataSet(['like1', 'like2'], [like1, like2])


class ImportanceFilterb0:
    def want_importance(self, jobItem):
        return "like2" in jobItem.data_set.names



# Dictionary of groups of data/parameter combination to run
# datasets is a list of DataSet objects, or tuples of data name tag combinations and
# corresponding list of input dictionaries or yaml files.

groups = {
    'main': {
        'params': [[], ['a_1'], ['a_2'], ['a_1', 'a_2']],
        'datasets': [('like1', like1), joint],
        "extra_opts": {},  # options specific to this group
        'importance_runs': [
            (["cut"], {"params": {"b_0": {"prior": {"min": 0, "max": 1}}}},
             ImportanceFilterb0())]
    }
}
