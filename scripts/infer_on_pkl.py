import gc
import os
import warnings
from dataclasses import dataclass
import joblib
from pathlib import Path
import re
from typing import Optional

import hydra
import torch
from hydra.core.config_store import ConfigStore
from omegaconf import DictConfig, OmegaConf
from phalp.configs.base import CACHE_DIR, FullConfig
from phalp.models.hmar.hmr import HMR2018Predictor
from phalp.trackers.PHALP import PHALP
from phalp.utils import get_pylogger

warnings.filterwarnings('ignore')

log = get_pylogger(__name__)

class HMR2Predictor(HMR2018Predictor):
    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        # Setup our new model
        from hmr2.models import download_models, load_hmr2

        # Download and load checkpoints
        download_models()
        model, _ = load_hmr2()

        self.model = model
        self.model.eval()

    def forward(self, x):
        hmar_out = self.hmar_old(x)
        batch = {
            'img': x[:,:3,:,:],
            'mask': (x[:,3,:,:]).clip(0,1),
        }
        model_out = self.model(batch)
        out = hmar_out | {
            'pose_smpl': model_out['pred_smpl_params'],
            'pred_cam': model_out['pred_cam'],
        }
        return out

# create the tracker with hmr2 backend
class HMR2_4dhuman(PHALP):
    def __init__(self, cfg):
        super().__init__(cfg)

    def setup_hmr(self):
        self.HMAR = HMR2Predictor(self.cfg)

# create the tracker with action predictor
class LART(HMR2_4dhuman):
    def __init__(self, cfg):

        download_files = {
            "lart_mvit.config" : ["https://people.eecs.berkeley.edu/~jathushan/projects/phalp/ava/lart_mvit.config", os.path.join(CACHE_DIR, "phalp/ava")],
            "lart_mvit.ckpt"   : ["https://people.eecs.berkeley.edu/~jathushan/projects/phalp/ava/lart_mvit.ckpt", os.path.join(CACHE_DIR, "phalp/ava")],
            "mvit.yaml"        : ["https://people.eecs.berkeley.edu/~jathushan/projects/phalp/ava/mvit.yaml", os.path.join(CACHE_DIR, "phalp/ava")],
            "mvit.pyth"        : ["https://people.eecs.berkeley.edu/~jathushan/projects/phalp/ava/mvit.pyth", os.path.join(CACHE_DIR, "phalp/ava")],
        }
        self.cached_download_from_drive(download_files)
        super().__init__(cfg)

    def setup_detectron2(self): pass
    def setup_detectron2_with_RPN(self): pass

    def setup_predictor(self):
        # setup predictor model witch predicts actions from poses
        log.info("Loading Predictor model...")
        from lart.utils.wrapper_phalp import Pose_transformer
        self.pose_predictor = Pose_transformer(self.cfg, self)
        self.pose_predictor.load_weights(self.cfg.pose_predictor.weights_path)

@dataclass
class Human4DConfig(FullConfig):
    # override defaults if needed
    pass

cs = ConfigStore.instance()
cs.store(name="config", node=Human4DConfig)

@hydra.main(version_base="1.2", config_name="config")
def main(cfg: DictConfig) -> Optional[float]:
    """Main function for running the PHALP tracker."""

    # # Setup the tracker and track the video
    # cfg.phalp.low_th_c = 0.5
    cfg.phalp.small_w = 50
    cfg.phalp.small_h = 50
    cfg.render.enable = False
    #phalp_tracker = HMR2_4dhuman(cfg)
    #_, pkl_path = phalp_tracker.track()
    #del phalp_tracker
    #gc.collect()
    #with torch.no_grad():
    #    torch.cuda.empty_cache()

    pkl_path = cfg.pkl_path
    
    # Setup the LART model and run it on the tracked video to get the action predictions
    cfg = OmegaConf.structured(OmegaConf.to_yaml(cfg))
    #cfg.render.colors = 'slahmr'
    cfg.pose_predictor.config_path = f"{CACHE_DIR}/phalp/ava/lart_mvit.config"
    cfg.pose_predictor.weights_path = f"{CACHE_DIR}/phalp/ava/lart_mvit.ckpt"
    try:    cfg.pose_predictor.half = cfg.half
    except: cfg.pose_predictor.half = False
    log.info(f"Half precision: {cfg.pose_predictor.half}")

    lart_model = LART(cfg)
    lart_model.setup_postprocessor()
    
    log.info(f"Running LART on .pkl output from PHALP")
    lart_model.postprocessor.run_lart(pkl_path, save_fast_tracks=True)

    # log.info(f"Extracting action data to smaller, CPU-friendly .pkl file")

    # pkl_path_stem = re.sub(r'\.phalp(\.lart)?\.pkl.*$', '', Path(pkl_path).name)
    # lart_pkl_path = f"outputs/results_temporal/{pkl_path_stem}.phalp.lart.pkl"
    # friendly_pkl_path = f"outputs/results_temporal/{pkl_path_stem}.lart.pkl"

    # pkl_data = {} 
    # with open(lart_pkl_path, "rb") as pkl_file:
    #     phalp_data = joblib.load(pkl_file)
    # for frame_key in phalp_data:
    #     pkl_data[frame_key] = { "time": phalp_data[frame_key]["time"], "tracked_ids": phalp_data[frame_key]["tracked_ids"], "tid": phalp_data[frame_key]["tid"] }
    #     if "label" in phalp_data[frame_key]:
    #         pkl_data[frame_key]["label"] = phalp_data[frame_key]["label"]
    #     if "ava_action" in phalp_data[frame_key]:
    #         pkl_data[frame_key]["ava_action"] = phalp_data[frame_key]["ava_action"]

    # with open(friendly_pkl_path, "wb") as pkl_out:
    #     joblib.dump(pkl_data, pkl_out)


if __name__ == "__main__":
    main()
