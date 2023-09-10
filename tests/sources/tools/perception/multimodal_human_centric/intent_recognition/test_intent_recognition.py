# Copyright 2020-2023 OpenDR European Project
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
import unittest
import torch
import tempfile
import os
import time
# OpenDR imports
from opendr.engine.target import Category
from opendr.perception.multimodal_human_centric import IntentRecognitionLearner
from opendr.engine.datasets import DatasetIterator


DEVICE = os.getenv('TEST_DEVICE') if os.getenv('TEST_DEVICE') else 'cpu'


class DummyDataset(DatasetIterator):
    def __init__(self, args):
        super(DummyDataset, self).__init__()
        self.args = args

    def __len__(self,):
        return 1

    def __getitem__(self, i):

        sample = {
            'label_ids': torch.tensor(0).to(torch.long),
            'text_feats': torch.cat((torch.ones((1, self.args.max_seq_length_text)),
                                     torch.zeros(2, self.args.max_seq_length_text))).to(torch.long),
            'video_feats': torch.zeros(self.args.max_seq_length_video, self.args.video_feat_dim).to(torch.double),
            'audio_feats': torch.zeros(self.args.max_seq_length_audio, self.args.audio_feat_dim).to(torch.double)
        }
        return sample


class TestIntentRecognitionLearner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n\n**********************************\nTEST IntentRecognitionLearner\n"
              "**********************************")
        pass

    @classmethod
    def tearDownClass(cls):
        return

    def test_fit(self):
        print('testing fit')
        tmp_direc = tempfile.TemporaryDirectory()
        tmp_dir = tmp_direc.name
        learner = IntentRecognitionLearner(text_backbone='prajjwal1/bert-tiny', mode='joint', device=DEVICE,
                                           log_path=tmp_dir, cache_path=tmp_dir, results_path=tmp_dir,
                                           output_path=tmp_dir)
        print('dataset 1')
        train_set = DummyDataset(learner.train_config)
        val_set = DummyDataset(learner.train_config)
        learner.method.args.num_train_epochs = 1
        print('old weights')
        old_weight = list(learner.model.model.parameters())[0].clone()
        print('fit')
        learner.fit(train_set, val_set, silent=True, verbose=False)
        new_weight = list(learner.model.model.parameters())[0].clone()

        self.assertFalse(torch.equal(old_weight, new_weight),
                         msg="Model parameters did not change after running fit.")
        tmp_direc.cleanup()

    def test_eval_trim(self):
        print('testing eval')
        tmp_direc = tempfile.TemporaryDirectory()
        tmp_dir = tmp_direc.name
        learner = IntentRecognitionLearner(text_backbone='prajjwal1/bert-tiny', mode='joint', device=DEVICE,
                                           log_path=tmp_dir, cache_path=tmp_dir, results_path=tmp_dir,
                                           output_path=tmp_dir)
        print('learner created')
        dataset = DummyDataset(learner.train_config)
        print('dataste created')
        performance = learner.eval(dataset, modality='language', silent=True, verbose=False, restore_best_model=False)
        self.assertTrue('acc' in performance.keys())
        print('evaluated, started trim')
        learner.trim('language')
        print('evaluating trimmed')
        performance_trimmed = learner.eval(dataset, modality='language', silent=True, verbose=False, restore_best_model=False)
        self.assertTrue(performance['loss'] == performance_trimmed['loss'])
        print('starting cleanup')
        tmp_direc.cleanup()
        print('cleanedup')

    def test_infer(self):
        print('testing infer')
        test_text = 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt \
                     ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco \
                     laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in \
                     voluptate velit esse cillum dolore eu fugiat nulla pariatur.'
        tmp_direc = tempfile.TemporaryDirectory()
        tmp_dir = tmp_direc.name
        # create learner and download pretrained model
        learner = IntentRecognitionLearner(text_backbone='prajjwal1/bert-tiny', mode='joint', device=DEVICE,
                                           log_path=tmp_dir, cache_path=tmp_dir, results_path=tmp_dir,
                                           output_path=tmp_dir)

        # make inference
        pred = learner.infer({'text': test_text}, modality='language')
        self.assertTrue(isinstance(pred, list))
        self.assertTrue(len(pred) == 3)
        self.assertTrue(isinstance(pred[0], Category))

        self.assertTrue(pred[0].confidence <= 1,
                        msg="Confidence of prediction must be less or equal than 1")
        tmp_direc.cleanup()

    def test_save_load(self):
        print('testing save load')
        test_text = 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt \
                     ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco \
                     laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in \
                     voluptate velit esse cillum dolore eu fugiat nulla pariatur.'

        temp_dir = 'tmp_'+str(time.time())
        tmp_direc = tempfile.TemporaryDirectory()
        tmp_dir2 = tmp_direc.name
        learner = IntentRecognitionLearner(text_backbone='prajjwal1/bert-tiny', mode='joint', device=DEVICE,
                                           log_path=tmp_dir2, cache_path=tmp_dir2, results_path=tmp_dir2,
                                           output_path=tmp_dir2)
        train_set = DummyDataset(learner.train_config)
        learner.method.args.num_train_epochs = 1
        learner.fit(train_set, silent=True, verbose=False)

        learner.save(temp_dir)

        new_learner = IntentRecognitionLearner(text_backbone='prajjwal1/bert-tiny', mode='joint', device=DEVICE,
                                               log_path=tmp_dir2, cache_path=tmp_dir2, results_path=tmp_dir2,
                                               output_path=tmp_dir2)

        new_learner.load(temp_dir)
        old_pred = learner.infer({'text': test_text}, modality='language')[0].confidence
        new_pred = new_learner.infer({'text': test_text}, modality='language')[0].confidence

        self.assertEqual(old_pred, new_pred)
        os.remove(temp_dir)
        tmp_direc.cleanup()


if __name__ == "__main__":
    unittest.main()
