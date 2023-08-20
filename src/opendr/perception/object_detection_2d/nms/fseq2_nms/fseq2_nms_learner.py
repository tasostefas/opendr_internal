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

from opendr.engine.learners import Learner
from opendr.engine.constants import OPENDR_SERVER_URL
from opendr.engine.target import BoundingBox, BoundingBoxList
from opendr.perception.object_detection_2d.nms.fseq2_nms.algorithm.fseq2_model import FSeq2Net
from opendr.perception.object_detection_2d.nms.utils import NMSCustom
from opendr.perception.object_detection_2d.nms.utils.nms_dataset import Dataset_NMS
from opendr.perception.object_detection_2d.nms.utils.nms_utils import drop_dets, det_matching, \
    run_coco_eval, filter_iou_boxes, bb_intersection_over_union, compute_class_weights, apply_torchNMS
import torch
import torch.nn.functional as F
import pickle
import numpy as np
import os
from urllib.request import urlretrieve
import torch.nn as nn
from tensorboardX import SummaryWriter
import torch.optim as optim
from tqdm import tqdm
import collections
import json
import zipfile


class FSeq2NMSLearner(Learner, NMSCustom):
    def __init__(self, lr=0.0001, epochs=8, device='cuda', temp_path='./temp', checkpoint_after_iter=0,
                 checkpoint_load_iter=0, log_after=10000, iou_filtering=0.8, dropout=0.025, app_input_dim=315):
        super(FSeq2NMSLearner, self).__init__(lr=lr, batch_size=1, checkpoint_after_iter=checkpoint_after_iter,
                                              checkpoint_load_iter=checkpoint_load_iter, temp_path=temp_path,
                                              device=device)
        self.epochs = epochs
        self.app_input_dim = app_input_dim

        self.lq_dim = 256
        self.sq_dim = 128
        self.geom_input_dim = 14
        self.num_JPUs = 4
        self.geom_input_dim = 14
        self.dropout = dropout
        self.temp_path = temp_path
        if not os.path.isdir(self.temp_path):
            os.mkdir(self.temp_path)
        self.checkpoint_load_iter = checkpoint_load_iter
        self.log_after = log_after
        self.iou_filtering = iou_filtering
        self.classes = None
        self.class_ids = None

        self.init_model()
        if "cuda" in self.device:
            self.model = self.model.to(self.device)

    def fit(self, dataset, logging_path='', logging_flush_secs=30, silent=True,
            verbose=True, nms_gt_iou=0.5, max_dt_boxes=400, datasets_folder='./datasets',
            use_ssd=True, ssd_model=None, lr_step=True):

        dataset_nms = Dataset_NMS(path=datasets_folder, dataset_name=dataset, split='train', use_ssd=use_ssd,
                                  ssd_model=ssd_model, device=self.device, use_maps=True)
        if self.classes is None:
            self.classes = dataset_nms.classes
            self.class_ids = dataset_nms.class_ids

        if logging_path != '' and logging_path is not None:
            logging = True
            file_writer = SummaryWriter(logging_path, flush_secs=logging_flush_secs)
        else:
            logging = False
            file_writer = None

        checkpoints_folder = self.temp_path
        if self.checkpoint_after_iter != 0 and not os.path.exists(checkpoints_folder):
            os.makedirs(checkpoints_folder)

        if not silent and verbose:
            print("Model trainable parameters:", self.count_parameters())

        self.model.train()
        if "cuda" in self.device:
            self.model = self.model.to(self.device)

        if self.epochs is None:
            raise ValueError("Training epochs not specified")
        elif self.epochs <= self.checkpoint_load_iter:
            raise ValueError("Training epochs are less than those of the loaded model")

        start_epoch = 0
        drop_after_epoch = []
        if lr_step and self.epochs > 1:
            drop_after_epoch = [int(self.epochs * 0.5)]
            if self.epochs > 3:
                drop_after_epoch.append(int(self.epochs * 0.7))

        train_ids = np.arange(len(dataset_nms.src_data))
        total_loss_iter = 0
        total_loss_epoch = 0
        optimizer = optim.Adam(self.model.parameters(), lr=self.lr, betas=(0.9, 0.99), eps=1e-9)  # HERE
        scheduler = None
        if len(drop_after_epoch) > 0:
            scheduler = optim.lr_scheduler.MultiStepLR(optimizer, milestones=drop_after_epoch, gamma=0.1)

        num_iter = 0
        training_weights = compute_class_weights(pos_weights=[0.9, 0.1], max_dets=max_dt_boxes, dataset_nms=dataset_nms)
        # Single class NMS only.
        class_index = 1
        training_dict = {"cross_entropy_loss": []}
        for epoch in range(start_epoch, self.epochs):
            pbar = None
            if not silent:
                pbarDesc = "Epoch #" + str(epoch) + " progress"
                pbar = tqdm(desc=pbarDesc, total=len(train_ids))
            np.random.shuffle(train_ids)
            for sample_id in train_ids:

                if self.log_after != 0 and num_iter > 0 and num_iter % self.log_after == 0:
                    if logging:
                        file_writer.add_scalar(tag="cross_entropy_loss",
                                               scalar_value=total_loss_iter/self.log_after,
                                               global_step=num_iter)
                    if verbose:
                        print(''.join(['\nEpoch: {}',
                                       ' Iter: {}, cross_entropy_loss: {}']).format(epoch, num_iter,
                                                                                    total_loss_iter/self.log_after))
                    total_loss_iter = 0
                if len(dataset_nms.src_data[sample_id]['dt_boxes'][class_index]) > 0:
                    dt_boxes = torch.tensor(
                        dataset_nms.src_data[sample_id]['dt_boxes'][class_index][:, 0:4]).float()
                    dt_scores = torch.tensor(dataset_nms.src_data[sample_id]['dt_boxes'][class_index][:, 4]).float()
                    dt_scores, dt_scores_ids = torch.sort(dt_scores, descending=True)
                    dt_boxes = dt_boxes[dt_scores_ids]
                else:
                    if not silent:
                        pbar.update(1)
                    num_iter = num_iter + 1
                    continue
                gt_boxes = torch.tensor([]).float()
                if len(dataset_nms.src_data[sample_id]['gt_boxes'][class_index]) > 0:
                    gt_boxes = torch.tensor(dataset_nms.src_data[sample_id]['gt_boxes'][class_index]).float()
                img_res = dataset_nms.src_data[sample_id]['resolution'][::-1]

                if "cuda" in self.device:
                    dt_boxes = dt_boxes.to(self.device)
                    dt_scores = dt_scores.to(self.device)
                    gt_boxes = gt_boxes.to(self.device)

                val_ids = torch.logical_and((dt_boxes[:, 2] - dt_boxes[:, 0]) > 4,
                                            (dt_boxes[:, 3] - dt_boxes[:, 1]) > 4)
                dt_boxes = dt_boxes[val_ids, :]
                dt_scores = dt_scores[val_ids]

                dt_boxes, dt_scores = drop_dets(dt_boxes, dt_scores)
                if dt_boxes.shape[0] < 1:
                    if not silent:
                        pbar.update(1)
                    num_iter = num_iter + 1
                    continue
                if self.iou_filtering is not None and 1.0 > self.iou_filtering > 0:
                    dt_boxes, dt_scores = apply_torchNMS(boxes=dt_boxes, scores=dt_scores,
                                                         iou_thres=self.iou_filtering)

                dt_boxes = dt_boxes[:max_dt_boxes]
                dt_scores = dt_scores[:max_dt_boxes]
                msk = self.compute_mask(dt_boxes, iou_thres=0.2, extra=0.1)
                q_geom_feats, k_geom_feats = self.compute_geometrical_feats(boxes=dt_boxes, scores=dt_scores,
                                                                            resolution=img_res)
                preds = self.model(q_geom_feats=q_geom_feats, k_geom_feats=k_geom_feats, msk=msk,
                                   maps=map)
                preds = torch.clamp(preds, 0.001, 1 - 0.001)

                labels = det_matching(scores=preds, dt_boxes=dt_boxes, gt_boxes=gt_boxes,
                                      iou_thres=nms_gt_iou, device=self.device)
                weights = (training_weights[class_index][1] * labels + training_weights[class_index][0] * (
                        1 - labels))

                e = torch.distributions.uniform.Uniform(0.001, 0.005).sample([labels.shape[0], 1])
                if "cuda" in self.device:
                    weights = weights.to(self.device)
                    e = e.to(self.device)
                labels = labels * (1 - e) + (1 - labels) * e
                ce_loss = F.binary_cross_entropy(preds, labels, reduction="none")
                loss = (ce_loss * weights).sum()

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                # Memory leak if not loss not detached in total_loss_iter and total_loss_epoch computations
                loss_t = loss.detach().cpu().numpy()
                total_loss_iter = total_loss_iter + loss_t
                total_loss_epoch = total_loss_epoch + loss_t
                num_iter = num_iter + 1
                if not silent:
                    pbar.update(1)
            if not silent:
                pbar.close()
            if verbose:
                print(''.join(['\nEpoch: {}',
                               ' cross_entropy_loss: {}\n']).format(epoch,
                                                                    total_loss_epoch/len(train_ids)))
            training_dict['cross_entropy_loss'].append(total_loss_epoch/len(train_ids))
            if self.checkpoint_after_iter != 0 and epoch % self.checkpoint_after_iter == self.checkpoint_after_iter - 1:
                snapshot_name = '{}/checkpoint_epoch_{}'.format(checkpoints_folder, epoch)
                self.save(path=snapshot_name, optimizer=optimizer, scheduler=scheduler,
                          current_epoch=epoch, max_dt_boxes=max_dt_boxes)
                snapshot_name_lw = '{}/last_weights'.format(checkpoints_folder)
                self.save(path=snapshot_name_lw, optimizer=optimizer, scheduler=scheduler,
                          current_epoch=epoch, max_dt_boxes=max_dt_boxes)
            total_loss_epoch = 0
            if scheduler is not None:
                scheduler.step()
        if logging:
            file_writer.close()
        return training_dict

    def eval(self, dataset, split='test', verbose=True, max_dt_boxes=400, threshold=0.0,
             datasets_folder='./datasets', use_ssd=True, ssd_model=None):

        dataset_nms = Dataset_NMS(path=datasets_folder, dataset_name=dataset, split=split, use_ssd=use_ssd,
                                  device=self.device, use_maps=True, ssd_model=ssd_model)

        if self.classes is None:
            self.classes = dataset_nms.classes
            self.class_ids = dataset_nms.class_ids

        annotations_filename = dataset_nms.annotation_file

        eval_folder = self.temp_path
        if not os.path.isdir(os.path.join(self.temp_path)):
            os.mkdir(os.path.join(self.temp_path))
        if not os.path.isdir(eval_folder):
            os.mkdir(eval_folder)
        output_file = os.path.join(eval_folder, 'detections.json')
        self.model = self.model.eval()
        if "cuda" in self.device:
            self.model = self.model.to(self.device)

        eval_ids = np.arange(len(dataset_nms.src_data))
        nms_results = []
        pbar_eval = None
        if verbose:
            pbarDesc = "Evaluation progress"
            pbar_eval = tqdm(desc=pbarDesc, total=len(eval_ids))
        for sample_id in eval_ids:
            maps_fln = dataset_nms.src_data[sample_id]['ssd_maps']
            with open(os.path.join(datasets_folder, dataset, maps_fln), 'rb') as f:
                map = pickle.load(f)
            map = torch.tensor(map).to(self.device)
            img_res = dataset_nms.src_data[sample_id]['resolution'][::-1]
            # Single class NMS only.
            class_index = 1
            if len(dataset_nms.src_data[sample_id]['dt_boxes'][class_index]) > 0:
                dt_boxes = torch.tensor(dataset_nms.src_data[sample_id]['dt_boxes'][class_index][:, 0:4]).float()
                dt_scores = torch.tensor(dataset_nms.src_data[sample_id]['dt_boxes'][class_index][:, 4]).float()
                dt_scores, dt_scores_ids = torch.sort(dt_scores, descending=True)
                dt_boxes = dt_boxes[dt_scores_ids]
            else:
                pbar_eval.update(1)
                continue

            if "cuda" in self.device:
                dt_boxes = dt_boxes.to(self.device)
                dt_scores = dt_scores.to(self.device)

            val_ids = torch.logical_and((dt_boxes[:, 2] - dt_boxes[:, 0]) > 4,
                                        (dt_boxes[:, 3] - dt_boxes[:, 1]) > 4)
            dt_boxes = dt_boxes[val_ids, :]
            dt_scores = dt_scores[val_ids]

            if self.iou_filtering is not None and 1.0 > self.iou_filtering > 0:
                dt_boxes, dt_scores = apply_torchNMS(boxes=dt_boxes, scores=dt_scores, iou_thres=self.iou_filtering)

            dt_boxes = dt_boxes[:max_dt_boxes]
            dt_scores = dt_scores[:max_dt_boxes]

            msk = self.compute_mask(dt_boxes, iou_thres=0.2, extra=0.1)
            q_geom_feats, k_geom_feats = self.compute_geometrical_feats(boxes=dt_boxes, scores=dt_scores,
                                                                        resolution=img_res)
            with torch.no_grad():
                preds = self.model(q_geom_feats=q_geom_feats, k_geom_feats=k_geom_feats, msk=msk,
                                   maps=map, img_res=img_res, boxes=dt_boxes)
                bboxes = dt_boxes.cpu().numpy().astype('float64')
            preds = preds.cpu().detach()
            if threshold > 0.0:
                ids = (preds > threshold)
                preds = preds[ids]
                bboxes = bboxes[ids.numpy().squeeze(-1), :]
            for j in range(len(preds)):
                nms_results.append({
                    'image_id': dataset_nms.src_data[sample_id]['id'],
                    'bbox': [bboxes[j][0], bboxes[j][1], bboxes[j][2] - bboxes[j][0], bboxes[j][3] - bboxes[j][1]],
                    'category_id': class_index,
                    'score': np.float64(preds[j])
                })
            pbar_eval.update(1)
        pbar_eval.close()
        if verbose:
            print('Writing results json to {}'.format(output_file))
        with open(output_file, 'w') as fid:
            json.dump(nms_results, fid, indent=2)
        eval_result = run_coco_eval(gt_file_path=os.path.join(dataset_nms.path, 'annotations', annotations_filename),
                                    dt_file_path=output_file, only_classes=[1],
                                    verbose=verbose, max_dets=[max_dt_boxes])
        os.remove(output_file)
        if verbose:
            for i in range(len(eval_result)):
                print('Evaluation results (num_dets={})'.format(str(eval_result[i][1])))
                print(eval_result[i][0][0][1])
                print(eval_result[i][0][1][1])
                print(eval_result[i][0][2][1])
                print(eval_result[i][0][3][1])
                print('\n')
        return eval_result

    def save(self, path, verbose=False, optimizer=None, scheduler=None, current_epoch=None, max_dt_boxes=400):
        fname = path.split('/')[-1]
        dir_name = path.replace('/' + fname, '')
        if not os.path.isdir(dir_name):
            os.makedirs(dir_name)
        custom_dict = {'state_dict': self.model.state_dict(), 'current_epoch': current_epoch}
        if optimizer is not None:
            custom_dict['optimizer'] = optimizer.state_dict()
        if scheduler is not None:
            custom_dict['scheduler'] = scheduler.state_dict()
        torch.save(custom_dict, path + '.pth')

        metadata = {"model_paths": [fname + '.pth'], "framework": "pytorch", "has_data": False,
                    "inference_params": {}, "optimized": False, "optimizer_info": {}, "backbone": {},
                    "format": "pth", "classes": self.classes, "app_feats": self.app_feats,
                    "lq_dim": self.lq_dim, "sq_dim": self.sq_dim, "num_JPUs": self.num_JPUs,
                    "geom_input_dim": self.geom_input_dim, "app_input_dim": self.app_input_dim,
                    "max_dt_boxes": max_dt_boxes}

        with open(path + '.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=4)
        if verbose:
            print("Saved Pytorch model.")

    def init_model(self):
        if self.model is None:
            self.model = FSeq2Net(dropout=self.dropout, app_input_dim=self.app_input_dim,
                                  geom_input_dim=self.geom_input_dim, lq_dim=self.lq_dim, sq_dim=self.sq_dim,
                                  num_JPUs=self.num_JPUs, device=self.device)
            for p in self.model.parameters():
                if p.dim() > 1:
                    nn.init.xavier_uniform_(p)
        else:
            raise UserWarning("Tried to initialize model while model is already initialized.")

    def load(self, path, verbose=False):
        if os.path.isdir(path):
            model_name = 'last_weights'
            dir_path = path
        else:
            model_name = os.path.basename(os.path.normpath(path)).split('.')[0]
            dir_path = os.path.dirname(os.path.normpath(path))

        if verbose:
            print("Model name:", model_name, "-->", os.path.join(dir_path, model_name + ".json"))
        with open(os.path.join(dir_path, model_name + ".json"), encoding='utf-8-sig') as f:
            metadata = json.load(f)
        pth_path = os.path.join(dir_path, metadata["model_paths"][0])
        if verbose:
            print("Loading checkpoint:", pth_path)
        try:
            checkpoint = torch.load(pth_path, map_location=torch.device(self.device))
        except FileNotFoundError as e:
            e.strerror = "File " + pth_path + "not found."
            raise e
        self.assign_params(metadata=metadata, verbose=verbose)
        self.load_state(checkpoint)
        if verbose:
            print("Loaded parameters and metadata.")
        return True

    def assign_params(self, metadata, verbose):
        if verbose and self.geom_input_dim is not None and self.geom_input_dim != metadata["geom_input_dim"]:
            print("Incompatible value for the attribute \"geom_input_dim\". It is now set to: " +
                  str(metadata["geom_input_dim"]))
        self.geom_input_dim = metadata["geom_input_dim"]
        if verbose and self.app_input_dim is not None and self.app_input_dim != metadata["app_input_dim"]:
            print("Incompatible value for the attribute \"app_input_dim\". It is now set to: " +
                  str(metadata["app_input_dim"]))
        self.app_input_dim = metadata["app_input_dim"]
        if verbose and self.lq_dim is not None and \
                self.lq_dim != metadata["lq_dim"]:
            print("Incompatible value for the attribute \"lq_dim\". It is now set to: " +
                  str(metadata["lq_dim"]))
        self.lq_dim = metadata["lq_dim"]
        if verbose and self.sq_dim is not None and self.sq_dim != metadata["sq_dim"]:
            print("Incompatible value for the attribute \"sq_dim\". It is now set to: " +
                  str(metadata["sq_dim"]))
        self.sq_dim = metadata["sq_dim"]
        if verbose and self.num_JPUs is not None and self.num_JPUs != metadata["num_JPUs"]:
            print("Incompatible value for the attribute \"num_JPUs\". It is now set to: " +
                  str(metadata["num_JPUs"]))
        self.num_JPUs = metadata["num_JPUs"]
        if verbose and 'max_dt_boxes' in metadata:
            print('Model is trained with ' + str(metadata['max_dt_boxes']) + ' as the maximum number of detections.')

    def load_state(self, checkpoint=None):
        if checkpoint is None:
            for p in self.model.parameters():
                if p.dim() > 1:
                    nn.init.xavier_uniform_(p)
        else:
            try:
                source_state = checkpoint['state_dict']
            except KeyError:
                source_state = checkpoint
            target_state = self.model.state_dict()
            new_target_state = collections.OrderedDict()
            for target_key, target_value in target_state.items():
                if target_key in source_state and source_state[target_key].size() == target_state[target_key].size():
                    new_target_state[target_key] = source_state[target_key]
                else:
                    new_target_state[target_key] = target_state[target_key]

            self.model.load_state_dict(new_target_state)

    def count_parameters(self):

        if self.model is None:
            raise UserWarning("Model is not initialized, can't count trainable parameters.")
        return sum(p.numel() for p in self.model.parameters() if p.requires_grad)

    def download(self, path=None, model_name='fseq2_pets_ssd_pets', verbose=False,
                 url=OPENDR_SERVER_URL + "perception/object_detection_2d/nms/"):

        supported_pretrained_models = ["fseq2_pets_ssd_pets"]

        if model_name not in supported_pretrained_models:
            str_error = model_name + " pretrained model is not supported. The available pretrained models are: "
            for i in range(len(supported_pretrained_models)):
                str_error = str_error + supported_pretrained_models[i] + ", "
            str_error = str_error[:-2] + '.'
            raise ValueError(str_error)

        if path is None:
            path = self.temp_path

        if not os.path.exists(path):
            os.makedirs(path)

        if verbose:
            print("Downloading pretrained model...")

        file_url = os.path.join(url, "pretrained", model_name + '.zip')
        try:
            urlretrieve(file_url, os.path.join(path, model_name + '.zip'))
            with zipfile.ZipFile(os.path.join(path, model_name + '.zip'), 'r') as zip_ref:
                zip_ref.extractall(path)
            os.remove(os.path.join(path, model_name + '.zip'))
        except:
            raise UserWarning('Pretrained model not found on server.')

    def infer(self, boxes=None, scores=None, boxes_sorted=False, max_dt_boxes=400, img_res=None, threshold=0.1):
        bounding_boxes = BoundingBoxList([])
        if scores.shape[0] == 0:
            return bounding_boxes
        if scores.shape[1] > 1:
            raise ValueError('Multi-class NMS is not supported in Seq2Seq-NMS yet.')
        if boxes.shape[0] != scores.shape[0]:
            raise ValueError('Scores and boxes must have the same size in dim 0.')
        if "cuda" in self.device:
            boxes = boxes.to(self.device)
            scores = scores.to(self.device)

        scores = scores.squeeze(-1)
        keep_ids = torch.where(scores > 0.05)[0]
        scores = scores[keep_ids]
        boxes = boxes[keep_ids, :]
        if not boxes_sorted:
            scores, scores_ids = torch.sort(scores, dim=0, descending=True)
            boxes = boxes[scores_ids]

        val_ids = torch.logical_and((boxes[:, 2] - boxes[:, 0]) > 4,
                                    (boxes[:, 3] - boxes[:, 1]) > 4)
        boxes = boxes[val_ids, :]
        scores = scores[val_ids]

        if self.iou_filtering is not None and 1.0 > self.iou_filtering > 0:
            boxes, scores = apply_torchNMS(boxes=boxes, scores=scores, iou_thres=self.iou_filtering)

        boxes = boxes[:max_dt_boxes]
        scores = scores[:max_dt_boxes]
        app_feats = None

        msk = self.compute_mask(boxes, iou_thres=0.2, extra=0.1)
        q_geom_feats, k_geom_feats = self.compute_geometrical_feats(boxes=boxes, scores=scores,
                                                                    resolution=img_res)

        with torch.no_grad():
            preds = self.model(q_geom_feats=q_geom_feats, k_geom_feats=k_geom_feats, msk=msk,
                               app_feats=app_feats)

        mask = torch.where(preds > threshold)[0]
        if mask.size == 0:
            return BoundingBoxList([])
        preds = preds[mask].cpu().detach().numpy()
        boxes = boxes[mask, :].cpu().numpy()

        for idx, box in enumerate(boxes):
            bbox = BoundingBox(left=box[0], top=box[1],
                               width=box[2] - box[0],
                               height=box[3] - box[1],
                               name=0,
                               score=preds[idx])
            bounding_boxes.data.append(bbox)
        return bounding_boxes, [boxes, np.zeros(scores.shape[0]), preds]

    def optimize(self, **kwargs):
        """This method is not used in this implementation."""
        raise NotImplementedError

    def reset(self):
        """This method is not used in this implementation."""
        return NotImplementedError

    def run_nms(self, boxes=None, scores=None, boxes_sorted=False, top_k=400, img=None, threshold=0.2):
        if isinstance(boxes, np.ndarray):
            boxes = torch.tensor(boxes, device=self.device)
        elif torch.is_tensor(boxes):
            if "cuda" in self.device:
                boxes = boxes.to(self.device)

        if isinstance(scores, np.ndarray):
            scores = torch.tensor(scores, device=self.device)
        elif torch.is_tensor(scores):
            if "cuda" in self.device:
                scores = scores.to(self.device)
        boxes = self.infer(boxes=boxes, scores=scores, boxes_sorted=boxes_sorted, max_dt_boxes=top_k,
                           img_res=img.opencv().shape[::-1][1:])
        return boxes

    def compute_mask(self, boxes=None, iou_thres=0.2, extra=0.1):
        relations = filter_iou_boxes(boxes, iou_thres=iou_thres)
        mask1 = torch.tril(relations).float()
        mask2 = extra * torch.triu(relations, diagonal=1).float()
        mask = mask1 + mask2
        return mask

    def compute_geometrical_feats(self, boxes, scores, resolution):
        boxBs = boxes.clone().unsqueeze(0).repeat(boxes.shape[0], 1, 1)
        boxAs = boxes.unsqueeze(1).repeat(1, boxes.shape[0], 1)
        scoresBs = scores.unsqueeze(0).unsqueeze(-1).repeat(scores.shape[0], 1, 1)
        scoresAs = scores.unsqueeze(1).unsqueeze(1).repeat(1, scores.shape[0], 1)

        scale_div = [resolution[1] / 20, resolution[0] / 20]
        dx = ((boxBs[:, :, 0] - boxAs[:, :, 0] + boxBs[:, :, 2] - boxAs[:, :, 2]) / 2).unsqueeze(-1)
        dy = ((boxBs[:, :, 1] - boxAs[:, :, 1] + boxBs[:, :, 3] - boxAs[:, :, 3]) / 2).unsqueeze(-1)
        dxy = dx * dx + dy * dy
        dxy = dxy / (scale_div[0] * scale_div[0] + scale_div[1] * scale_div[1])
        dx = (dx / scale_div[0])
        dy = (dy / scale_div[1])
        sx = boxBs[:, :, 2] - boxBs[:, :, 0]
        sx_1 = (sx / (boxAs[:, :, 2] - boxAs[:, :, 0])).unsqueeze(-1)
        sx_2 = (sx / scale_div[0]).unsqueeze(-1)
        sy = boxBs[:, :, 3] - boxBs[:, :, 1]
        sy_1 = (sy / (boxAs[:, :, 3] - boxAs[:, :, 1])).unsqueeze(-1)
        sy_2 = (sy / scale_div[1]).unsqueeze(-1)
        scl = (boxBs[:, :, 2] - boxBs[:, :, 0]) * (boxBs[:, :, 3] - boxBs[:, :, 1])
        scl_1 = (scl / ((boxAs[:, :, 2] - boxAs[:, :, 0]) * (boxAs[:, :, 3] - boxAs[:, :, 1]))).unsqueeze(-1)
        scl_2 = (scl / (scale_div[0] * scale_div[1])).unsqueeze(-1)
        del scl

        scr_1 = 5 * scoresBs
        scr_2 = scr_1 - 5 * scoresAs

        sr_1 = torch.unsqueeze((boxBs[:, :, 3] - boxBs[:, :, 1]) / (boxBs[:, :, 2] - boxBs[:, :, 0]), dim=-1)
        sr_2 = torch.unsqueeze(((boxBs[:, :, 3] - boxBs[:, :, 1]) / (boxBs[:, :, 2] - boxBs[:, :, 0])) / (
                (boxAs[:, :, 3] - boxAs[:, :, 1]) / (boxAs[:, :, 2] - boxAs[:, :, 0])), dim=-1)

        ious = 5 * (bb_intersection_over_union(boxes.unsqueeze(1).repeat(1, boxes.shape[0], 1),
                                               boxes.clone().unsqueeze(0).repeat(boxes.shape[0], 1, 1))).unsqueeze(-1)
        enc_vers_all = torch.cat((dx, dy, dxy, sx_1, sx_2, sy_1, sy_2, ious, scl_1, scl_2, scr_1, scr_2, sr_1, sr_2),
                                 dim=2)
        enc_vers = enc_vers_all.diagonal(dim1=0, dim2=1).transpose(0, 1).unsqueeze(1)
        return enc_vers, enc_vers_all
