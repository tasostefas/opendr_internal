# Copyright 2020-2022 OpenDR European Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
from typing import Dict, Tuple

import torch
import numpy as np
import matplotlib as mpl
from matplotlib import pyplot as plt

from opendr.engine.constants import OPENDR_SERVER_URL
from opendr.engine.data import Image
from opendr.engine.learners import Learner

from opendr.perception.continual_slam.algorithm.depth_pose_prediction import DepthPosePredictor
from opendr.perception.continual_slam.configs.config_parser import ConfigParser

class ContinualSLAMLearner(Learner):
    def __init__(self,
                 config_file: Path,
                 mode: str = 'predictor',
                 ros: bool = False
                 ):
        self.config_file = ConfigParser(config_file)
        self.dataset_config = self.config_file.dataset
        self.model_config = self.config_file.depth_pose
        super(ContinualSLAMLearner, self).__init__(lr=self.model_config.learning_rate)

        self.mode = mode

        if self.mode == 'predictor':
            # Create the predictor object
            self.predictor = DepthPosePredictor(self.model_config, self.dataset_config, use_online=False)
            self.predictor.load_model()
            if not ros:
                self.predictor._create_dataset_loaders(training=False, validation=True)
        elif self.mode == 'learner':
            self.learner = DepthPosePredictor(self.model_config, self.dataset_config, use_online=True)
            self.learner.load_model()
            if not ros:
                self.learner._create_dataset_loaders(training=False, validation=True)
        else:
            raise ValueError('Mode should be either predictor or learner')

    def fit(self, batch: Tuple[Dict, None]):
        """
        In the context of CL-SLAM, we implemented fit method as adapt method, which updates the weights of learner
        based on coming input
        """
        if self.mode == 'learner':
            return self._fit(batch)
        else:
            raise ValueError('Fit is only available in learner mode')

    def infer(self, batch: Tuple[Dict, None]):
        """
        :param batch: tuple of (input, target)
        """
        if self.mode == 'predictor':
            return self._predict(batch)
        else:
            raise ValueError('Inference is only available in predictor mode')

    def _fit(self, batch: Tuple[Dict, None]):
        """
        :param batch: tuple of (input, target)
        """
        input_dict = self._input_formatter(batch)
        # Adapt
        prediction, losses = self.learner.adapt(input_dict)
        # Convert the prediction to opendr format
        return self._output_formatter(prediction)

    def _predict(self, batch: Tuple[Dict, None]):
        """
        :param batch: tuple of (input, target)
        """
        input_dict = self._input_formatter(batch)
        # Get the prediction
        prediction = self.predictor.predict(input_dict)
        # Convert the prediction to opendr format
        return self._output_formatter(prediction)
    
    def _input_formatter(self, batch: Tuple[Dict, None]):
        """
        Format the input for the prediction
        :param batch: tuple of (input, target)
        """
        if type(batch) == dict:
            inputs = batch
        else:
            inputs = batch[0]

        # Create a dictionary with frame ids as [-1, 0, 1]
        input_dict = {}
        for frame_id, id in zip([-1, 0 ,1], inputs.keys()):
            input_dict[(frame_id, 'image')] = torch.Tensor(inputs[id][0].data)
            input_dict[(frame_id, 'distance')] = torch.Tensor([inputs[id][1]])
        return input_dict

    def _output_formatter(self, prediction: Dict):
        """
        Format the output of the prediction
        :param prediction: dictionary of predictions which has items of:
        frame_id -> (depth, pose)
        depth -> Tensors of shape (1, 1, H, W). The number of tensors is equal to scales
        pose -> 6 Tensors, which we will only use cam_T_cam for 0->1 since it is the odometry
        """
        # Convert the prediction to opendr format
        for item in prediction:
            if item[0] == 'depth':
                if item[1] == 0:
                    depth = self._colorize_depth(prediction[item].squeeze().cpu().detach().numpy())
            if item[0] == 'cam_T_cam':
                if item[2] == 1:
                    odometry = prediction[item].cpu().detach().numpy()
        return depth, odometry

    def _colorize_depth(self, depth):
        vmax = np.percentile(depth, 95)
        normalizer = mpl.colors.Normalize(vmin=depth.min(), vmax=vmax)
        mapper = plt.cm.ScalarMappable(norm=normalizer, cmap="magma_r")
        colormapped_img = (mapper.to_rgba(depth.squeeze())[:, :, :3] * 255).astype(np.uint8)
        # fig = plt.figure(figsize=(12.8, 9.6))
        # plt.imshow(depth, cmap='magma_r', vmax=vmax)
        return Image(colormapped_img)
        # return colormapped_img
        # return None

    def eval(self, dataset, *args, **kwargs):
        raise NotImplementedError
    
    def save(self, path: str, verbose: bool = True):
        raise NotImplementedError
    
    def load(self, path: str, verbose: bool = True):
        raise NotImplementedError

    def optimize(self, target_device):
        raise NotImplementedError
    
    def reset(self):
        raise NotImplementedError

if __name__ == "__main__":
    local_path = Path(__file__).parent / 'configs'
    learner = ContinualSLAMLearner(local_path / 'singlegpu_kitti.yaml', mode='learner')

    # Test the learner
    from opendr.perception.continual_slam.datasets.kitti import KittiDataset
    dataset_config_file = ConfigParser(local_path / 'singlegpu_kitti.yaml').dataset.dataset_path
    dataset = KittiDataset(str(dataset_config_file))

    from PIL import Image as imgg 
    import time

    for i, batch in enumerate(dataset):
        depth, odometry = learner.fit(batch)
        # if i%100 == 0:
        #     print(i)
        #     original_image = list(batch[0].values())[1][0].numpy().transpose(1, 2, 0)
        #     x = np.vstack((original_image, depth))
        #     imgg.fromarray(x).show()
        #     time.sleep(0.5)