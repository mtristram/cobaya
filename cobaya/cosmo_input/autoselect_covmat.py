# Global
import hashlib
import os
import pickle
from itertools import chain
import numpy as np
import re
from typing import Optional, List, Dict

# Local
from cobaya.conventions import Extension, packages_path_input
from cobaya.tools import str_to_list, get_translated_params, get_cache_path
from cobaya.parameterization import is_sampled_param
from cobaya.input import update_info
from cobaya.log import LoggedError, get_logger, is_debug

_covmats_file = "covmats_database_%s.pkl"

log = get_logger(__name__)

covmat_folders = [
    "{%s}/data/planck_supp_data_and_covmats/covmats/" % packages_path_input,
    "{%s}/data/bicep_keck_2018/BK18_cosmomc/planck_covmats/" % packages_path_input]

# Global instance of loaded database, for fast calls to get_best_covmat in GUI
_loaded_covmats_database: Dict[str, List[dict]] = {}


def get_covmat_package_folders(packages_path) -> List[str]:
    install_folders = []
    for folder in covmat_folders:
        folder_full = folder.format(
            **{packages_path_input: packages_path}).replace("/", os.sep)
        if os.path.exists(folder_full):
            install_folders.append(folder_full)
    return install_folders


def get_covmat_database(packages_path, cached=True) -> List[dict]:
    install_folders = get_covmat_package_folders(packages_path)
    return get_covmat_database_at_paths(install_folders, cached=cached)


def get_covmat_database_at_paths(installed_folders, cached=True) -> List[dict]:
    # Get folders with corresponding components installed
    _hash = hashlib.md5(str(installed_folders).encode('utf8')).hexdigest()
    covmats_database_fullpath = os.path.join(get_cache_path(), _covmats_file % _hash)
    # Check if there is a usable cached one
    if cached:
        if covmats_database := _loaded_covmats_database.get(_hash):
            return covmats_database
        try:
            with open(covmats_database_fullpath, "rb") as f:
                covmat_database = pickle.load(f)
            # quick and dirty hash for regeneration: check number of .covmat files
            num_files = len(list(chain(
                *[[filename for filename in os.listdir(folder)
                   if filename.endswith(Extension.covmat)]
                  for folder in installed_folders])))
            assert num_files == len(covmat_database)
            log.debug("Loaded cached covmats database")
            _loaded_covmats_database[_hash] = covmat_database
            return covmat_database
        except:
            log.info("No cached covmat database present, not usable or not up-to-date. "
                     "Will be re-created and cached.")
            pass
    # Create it (again)
    covmat_database = []
    for folder_full in installed_folders:
        for filename in os.listdir(folder_full):
            try:
                with open(os.path.join(folder_full, filename),
                          encoding="utf-8-sig") as covmat:
                    header = covmat.readline()
                assert header.strip().startswith("#")
                params = header.strip().lstrip("#").split()
            except:
                continue
            covmat_database.append({"folder": folder_full,
                                    "name": filename, "params": params})
    if cached:
        with open(covmats_database_fullpath, "wb") as f:
            pickle.dump(covmat_database, f)
        _loaded_covmats_database[_hash] = covmat_database
    return covmat_database


def get_best_covmat(info, packages_path=None, cached=True, random_state=None):
    """
    Chooses optimal covmat from a database, based on common parameters and likelihoods.
    Only used by GUI.

    Returns a dict `{folder: [folder_of_covmat], name: [file_name_of_covmat],
    params: [parameters_in_covmat], covmat: [covariance_matrix]}`.
    """

    if not (packages_path := packages_path or info.get(packages_path_input)):
        raise LoggedError(log, "Needs a path to the external packages' installation.")
    updated_info = update_info(info, strict=False)
    for p, pinfo in list(updated_info["params"].items()):
        if not is_sampled_param(pinfo):
            updated_info["params"].pop(p)
    info_sampled_params = updated_info["params"]
    if not (covmat_data := get_best_covmat_ext(get_covmat_package_folders(packages_path),
                                               updated_info["params"],
                                               updated_info["likelihood"], random_state,
                                               cached)):
        return None
    covmat = np.atleast_2d(
        np.loadtxt(os.path.join(covmat_data["folder"], covmat_data["name"])))
    params_in_covmat = get_translated_params(info_sampled_params, covmat_data["params"])
    indices = [covmat_data["params"].index(p) for p in params_in_covmat.values()]
    covmat_data["covmat"] = covmat[indices][:, indices]
    covmat_data["params"] = params_in_covmat
    return covmat_data


def get_best_covmat_ext(covmat_dirs, params_info, likelihoods_info, random_state,
                        cached=True, msg_context="") -> Optional[dict]:
    """
    Actual covmat finder used by `get_best_covmat`. Call directly for more control on
    the parameters used.

    Returns the same dict as `get_best_covmat`, except for the covariance matrix itself.
    """
    if not (covmats_database := get_covmat_database_at_paths(covmat_dirs, cached=cached)):
        log.warning("No covariance matrices found at %s" % covmat_dirs)
        return None
    # Prepare params and likes aliases
    params_renames = set(chain(*[
        [p] + str_to_list(info.get("renames", [])) for p, info in
        params_info.items()]))
    likes_renames = set(chain(*[[like] + str_to_list((info or {}).get("aliases", []))
                                for like, info in likelihoods_info.items()]))
    delimiters = r"[_\.]"
    likes_regexps = [re.compile(delimiters + re.escape(_like) + delimiters)
                     for _like in likes_renames]

    # Match number of params
    def score_params(covmat):
        return len(set(covmat["params"]).intersection(params_renames))

    if not (best_p := get_best_score(covmats_database, score_params, 0)):
        log.warning(msg_context + (':\n' if msg_context else '') +
                    "No covariance matrix found including at least "
                    "one of the given parameters")
        return None

    # Match likelihood names / keywords
    # No debug print here: way too many!
    def score_likes(covmat):
        return len([0 for r in likes_regexps if r.search(covmat["name"])])

    best_p_l = get_best_score(best_p, score_likes)
    if is_debug(log):
        log.debug("Subset based on params + likes:\n - " +
                  "\n - ".join([b["name"] for b in best_p_l]))

    # Finally, in case there is more than one, select shortest #params and name (simpler!)
    # #params first, to avoid extended models with shorter covmat name
    def score_simpler_params(covmat):
        return -len(covmat["params"])

    best_p_l_sp = get_best_score(best_p_l, score_simpler_params)
    if is_debug(log):
        log.debug("Subset based on params + likes + fewest params:\n - " +
                  "\n - ".join([b["name"] for b in best_p_l_sp]))

    def score_simpler_name(covmat):
        return -len(covmat["name"].replace("_", " ").replace("-", " ").split())

    best_p_l_sp_sn = get_best_score(best_p_l_sp, score_simpler_name)
    if is_debug(log):
        log.debug("Subset based on params + likes + fewest params + shortest name:\n - " +
                  "\n - ".join([b["name"] for b in best_p_l_sp_sn]))
    # if there is more than one (unlikely), just pick one at random
    if len(best_p_l_sp_sn) > 1:
        log.warning(msg_context + (':\n' if msg_context else '') +
                    "WARNING: >1 possible best covmats: %r",
                    [b["name"] for b in best_p_l_sp_sn])
    random_state = np.random.default_rng(random_state)
    return best_p_l_sp_sn[random_state.choice(range(len(best_p_l_sp_sn)))].copy()


def get_best_score(covmats, score_func, min_score=None) -> List[dict]:
    scores = np.array([score_func(covmat) for covmat in covmats])
    if min_score is not None and np.max(scores) <= min_score:
        return []
    i_max = np.argwhere(scores == np.max(scores)).T[0]
    return [covmats[i] for i in i_max]
