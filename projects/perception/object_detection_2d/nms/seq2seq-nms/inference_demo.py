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


from opendr.perception.object_detection_2d.nms.seq2seq_nms.seq2seq_nms_learner import Seq2SeqNMSLearner
from opendr.engine.data import Image
from opendr.perception.object_detection_2d import SingleShotDetectorLearner
from opendr.perception.object_detection_2d import draw_bounding_boxes
import os
OPENDR_HOME = os.environ['OPENDR_HOME']

seq2SeqNMSLearner = Seq2SeqNMSLearner(fmod_map_type='EDGEMAP', iou_filtering=0.8, experiment_name='pets_exp0',
                                      app_feats='fmod', device='cpu')
seq2SeqNMSLearner.load(OPENDR_HOME + '/src/opendr/perception/object_detection_2d/nms/seq2seq_nms/temp/pets_exp0/'
                                     'checkpoints/checkpoint_epoch_7', verbose=True)
ssd = SingleShotDetectorLearner(device='cuda')
ssd.download(".", mode="pretrained")
ssd.load("./ssd_default_person", verbose=True)
img = Image.open(OPENDR_HOME + '/projects/perception/object_detection_2d/nms/img_temp/frame_0000.jpg')
if not isinstance(img, Image):
    img = Image(img)
boxes = ssd.infer(img, threshold=0.25, custom_nms=seq2SeqNMSLearner)
draw_bounding_boxes(img.opencv(), boxes, class_names=ssd.classes, show=True)
