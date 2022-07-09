import os
import warnings
import datetime
import cv2
import time

import onnx
import onnxsim

import pytorch_lightning as pl
import torch
from pytorch_lightning.callbacks import ProgressBar

from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.util.check_point import save_model_state
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.model.weight_averager import build_weight_averager
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.model.arch import build_model
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.data.collate import naive_collate
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.data.dataset import build_dataset
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.trainer.task import TrainingTask
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.evaluator import build_evaluator
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.inferencer.utilities import Predictor, get_image_list
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.util import (
    NanoDetLightningLogger,
    Logger,
    cfg,
    convert_old_model,
    load_config,
    load_model_weight,
    mkdir,
)


from opendr.engine.data import Image
from opendr.engine.target import BoundingBox, BoundingBoxList
from opendr.engine.constants import OPENDR_SERVER_URL
from opendr.perception.object_detection_2d.utils.vis_utils import draw_bounding_boxes

from opendr.engine.learners import Learner
from urllib.request import urlretrieve


class NanodetLearner(Learner):
    def __init__(self, config, lr=None, weight_decay=None, warmup_steps=None, warmup_ratio=None,
                 lr_schedule_T_max=None, lr_schedule_eta_min=None, grad_clip=None, iters=None,
                 batch_size=None, checkpoint_after_iter=None, checkpoint_load_iter=None,
                 temp_path='temp', device='cuda'):

        """Initialise the Nanodet Learner"""

        load_config(cfg, config)
        self.cfg = cfg
        self.lr_schedule_T_max = lr_schedule_T_max
        self.lr_schedule_eta_min = lr_schedule_eta_min
        self.warmup_steps = warmup_steps
        self.warmup_ratio = warmup_ratio
        self.grad_clip = grad_clip

        self.overwrite_config(lr=lr, weight_decay=weight_decay, iters=iters, batch_size=batch_size,
                             checkpoint_after_iter=checkpoint_after_iter, checkpoint_load_iter=checkpoint_load_iter,
                             temp_path=temp_path)

        self.lr = float(self.cfg.schedule.optimizer.lr)
        self.weight_decay = float(self.cfg.schedule.optimizer.weight_decay)
        self.iters = int(self.cfg.schedule.total_epochs)
        self.batch_size = int(self.cfg.device.batchsize_per_gpu)
        self.temp_path = self.cfg.save_dir
        self.checkpoint_after_iter = int(self.cfg.schedule.val_intervals)
        self.checkpoint_load_iter = int(self.cfg.schedule.resume)
        self.device = device

        super(NanodetLearner, self).__init__(lr=self.lr, iters=self.iters, batch_size=self.batch_size,
                                             checkpoint_after_iter=self.checkpoint_after_iter,
                                             checkpoint_load_iter=self.checkpoint_load_iter,
                                             temp_path=self.temp_path, device=self.device)

        self.model = build_model(self.cfg.model)
        self.weight_averager = None
        if "weight_averager" in cfg.model:
            self.weight_averager = build_weight_averager(
                cfg.model.weight_averager, device=self.device
            )
        self.logger = None

    def overwrite_config(self, lr=0.001, weight_decay=0.05, iters=10, batch_size=64, checkpoint_after_iter=0,
                         checkpoint_load_iter=0, temp_path='temp'):
        """
        Helping method for config file update to overwrite the cfg with arguments of OpenDR.
        :param lr: learning rate used in training
        :type lr: float, optional
        :param weight_decay: weight_decay used in training
        :type weight_decay: float, optional
        :param iters: max epoches that the training will be run
        :type iters: int, optional
        :param batch_size: batch size of each gpu in use, if device is cpu batch size
         will be used one single time for training
        :type batch_size: int, optional
        :param checkpoint_after_iter: after that number of epoches, evaluation will be
         performed and one checkpoint will be saved
        :type checkpoint_after_iter: int, optional
        :param checkpoint_load_iter: the epoch in which checkpoint we want to load
        :type checkpoint_load_iter: int, optional
        :param temp_path: path to a temporal dictionary for saving models, logs and tensorboard graphs
        :type temp_path: str, optional
        """
        self.cfg.defrost()

        # Nanodet specific parameters
        if self.cfg.model.arch.head.num_classes != len(self.cfg.class_names):
            raise ValueError(
                "cfg.model.arch.head.num_classes must equal len(cfg.class_names), "
                "but got {} and {}".format(
                    self.cfg.model.arch.head.num_classes, len(self.cfg.class_names)
                )
            )
        self.cfg.schedule.warmup.warmup_steps = 0.1
        if self.warmup_steps is not None:
            self.cfg.schedule.warmup.warmup_steps = self.warmup_steps
        if self.warmup_ratio is not None:
            self.cfg.schedule.warmup.warmup_ratio = self.warmup_ratio
        if self.lr_schedule_T_max is not None:
            self.cfg.schedule.lr_schedule.T_max = self.lr_schedule_T_max
        if self.lr_schedule_eta_min is not None:
            self.cfg.schedule.lr_schedule.eta_min = self.lr_schedule_eta_min
        if self.grad_clip is not None:
            self.cfg.grad_clip = self.grad_clip

        # OpenDR
        if lr is not None:
            self.cfg.schedule.optimizer.lr = lr
        if weight_decay is not None:
            self.cfg.schedule.optimizer.weight_decay = weight_decay
        if iters is not None:
            self.cfg.schedule.total_epochs = iters
        if batch_size is not None:
            self.cfg.device.batchsize_per_gpu = batch_size
        if checkpoint_after_iter is not None:
            self.cfg.schedule.val_intervals = checkpoint_after_iter
        if checkpoint_load_iter is not None:
            self.cfg.schedule.resume = checkpoint_load_iter
        if temp_path != '':
            self.cfg.save_dir = temp_path

        self.cfg.freeze()

    def save(self, path=None, verbose=True):
        """
        Method for saving the current model in the path provided.
        :param path: path to folder where model will be saved
        :type path: str, optional
        :param verbose: whether to print a success message or not, defaults to False
        :type verbose: bool, optional
        """
        path = path if path is not None else self.cfg.schedule.save_dir
        save_path = os.path.join(path, "saved_models")
        logger = self.logger if verbose else None
        save_model_state(save_path, self.model, self.weight_averager, logger)
        pass

    def load(self, path=None, verbose=True):
        """
        Loads the model from the path provided, based on the metadata .json file included.
        :param path: path of the directory where the model was saved
        :type path: str, optional
        :param verbose: whether to print a success message or not, defaults to False
        :type verbose: bool, optional
        """

        path = path if path is not None else self.cfg.schedule.load_model
        logger = self.logger if verbose else None
        ckpt = torch.load(path)
        if "pytorch-lightning_version" not in ckpt:
            warnings.warn(
                "Warning! Old .pth checkpoint is deprecated. "
                "Convert the checkpoint with tools/convert_old_checkpoint.py "
            )
            ckpt = convert_old_model(ckpt)

        self.model = load_model_weight(self.model, ckpt, logger)
        if verbose and logger:
            self.logger.info("Loaded model weight from {}".format(path))
        pass

    def download(self, path=None, mode="image", model=None, verbose=False,
                     url=OPENDR_SERVER_URL + "/perception/object_detection_2d/nanodet/"):

        """
        Downloads all files necessary for inference, evaluation and training. Valid mode options are: ["pretrained",
        "images", "test_data"].
        :param path: folder to which files will be downloaded, if None self.temp_path will be used
        :type path: str, optional
        :param mode: one of: ["pretrained", "images", "test_data"], where "pretrained" downloads a pretrained
        network depending on the network is choosed in config file, "images" downloads example inference data,
        and "test_data" downloads additional image,annotation file and pretrained network for training and testing
        :type mode: str, optional
        :param model: the specific name of the model to download, all pre-configured configs files have their pretrained
        model and can be selected, if None self.cfg.check_point_name will be used
        :param verbose: if True, additional information is printed on stdout
        :type verbose: bool, optional
        :param url: URL to file location on FTP server
        :type url: str, optional
        """
        valid_modes = ["pretrained", "images", "test_data"]
        if mode not in valid_modes:
            raise UserWarning("mode parameter not valid:", mode, ", file should be one of:", valid_modes)

        if path is None:
            path = self.temp_path
        if not os.path.exists(path):
            os.makedirs(path)

        if mode == "pretrained":
            if model is None:
                model = self.cfg.check_point_name
            path = os.path.join(path, "nanodet{}".format(model))
            if not os.path.exists(path):
                os.makedirs(path)

            if verbose:
                print("Downloading pretrained checkpoint...")

            file_url = os.path.join(url, "pretrained",
                                    "nanodet{}".format(model),
                                    "nanodet{}.ckpt".format(model))

            urlretrieve(file_url, os.path.join(path, "nanodet{}.ckpt".format(model)))

            if verbose:
                print("Downloading pretrain weights if provided...")
            file_url = os.path.join(url, "pretrained", "nanodet{}".format(model),
                                    "nanodet{}.pth".format(model))

            try:
                urlretrieve(file_url, os.path.join(path, "nanodet{}.pth".format(model)))
            except:
                print("Pretrain weights for this model are not provided!!!")

        elif mode == "images":
            file_url = os.path.join(url, "images", "default.jpg")
            if verbose:
                print("Downloading example image...")
            urlretrieve(file_url, os.path.join(path, "default.jpg"))

        elif mode == "test_data":
            os.makedirs(os.path.join(path, "test_data"), exist_ok=True)
            os.makedirs(os.path.join(path, "test_data", "Images"), exist_ok=True)
            os.makedirs(os.path.join(path, "test_data", "Annotations"), exist_ok=True)
            # download train.txt
            file_url = os.path.join(url, "test_data", "train.txt")
            if verbose:
                print("Downloading filelist...")
            urlretrieve(file_url, os.path.join(path, "test_data", "train.txt"))
            # download image
            file_url = os.path.join(url, "test_data", "Images", "default.jpg")
            if verbose:
                print("Downloading image...")
            urlretrieve(file_url, os.path.join(path, "test_data", "Images", "default.jpg"))
            # download annotations
            file_url = os.path.join(url, "test_data", "Annotations", "default.json")
            if verbose:
                print("Downloading annotations...")
            urlretrieve(file_url, os.path.join(path, "test_data", "Annotations", "default.json"))

    def reset(self):
        """This method is not used in this implementation."""
        return NotImplementedError

    def optimize(self, model_path=None, output_path=None, input_shape=None):
        """
        Method for optimizing the model with onnx.
        :param model_path: path to the chkp file of the model to optimize (e.x. ./path/to/nanodet.ckpt)
        :type model_path: str, optional
        :param output_path: path to the saved onnx model (e.x. ./nanodet.onnx)
        :type output_path: str, optional
        :param input_shape: the input shape of the model in [w,h] format (e.x. 416,416)
        :type input_shape: str, optional
        """

        if input_shape is None:
            input_shape = self.cfg.data.train.input_size
        else:
            input_shape = tuple(map(int, input_shape.split(",")))
            assert len(input_shape) == 2
        if model_path is None:
            model_path = os.path.join(self.cfg.save_dir, "chechpoint_iters/model_best.ckpt")
        if output_path is None:
            output_path = os.path.join(self.cfg.save_dir, "nanodet.onnx")

        self.logger = Logger(-1, self.cfg.save_dir, False)

        checkpoint = torch.load(model_path, map_location=lambda storage, loc: storage)
        load_model_weight(self.model, checkpoint, self.logger)

        if self.cfg.model.arch.backbone.name == "RepVGG":
            deploy_config = self.cfg.model
            deploy_config.arch.backbone.update({"deploy": True})
            deploy_model = build_model(deploy_config)
            from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.model.backbone.repvgg import \
                repvgg_det_model_convert

            self.model = repvgg_det_model_convert(self.model, deploy_model)

        dummy_input = torch.autograd.Variable(
            torch.randn(1, 3, input_shape[0], input_shape[1])
        )

        torch.onnx.export(
            self.model,
            dummy_input,
            output_path,
            verbose=True,
            keep_initializers_as_inputs=True,
            opset_version=11,
            input_names=["data"],
            output_names=["output"],
        )
        self.logger.log("finished exporting onnx ")

        self.logger.log("start simplifying onnx ")
        input_data = {"data": dummy_input.detach().cpu().numpy()}
        model_sim, flag = onnxsim.simplify(output_path, input_data=input_data)
        if flag:
            onnx.save(model_sim, output_path)
            self.logger.log("simplify onnx successfully")
        else:
            self.logger.log("simplify onnx failed")

    def fit(self, dataset, val_dataset=None, logging_path='', silent=False, verbose=True, local_rank=-1, seed=123):
        """
        This method is used to train the detector on the COCO dataset. Validation is performed in a val_dataset if
        provided, else validation is performed in training dataset.
        :param dataset: training dataset; COCO and Pascal VOC are supported as ExternalDataset types,
        with 'coco' or 'voc' dataset_type attributes. custom DetectionDataset types are not supported at the moment.
        Any xml type dataset can be use if voc is used in datatype.
        :type dataset: ExternalDataset, DetectionDataset not implemented yet
        :param val_dataset: validation dataset object
        :type val_dataset: ExternalDataset, DetectionDataset not implemented yet
        :param logging_path: subdirectory in temp_path to save logger outputs
        :type logging_path: str, optional
        :param silent: ignored
        :type silent: str, optional
        :param verbose: if set to True, additional information is printed to STDOUT and logger txt output,
        defaults to True
        :type verbose: bool
        :param local_rank: node rank for distributed training
        :type local_rank: int
        :param seed: seed for reproducibility
        :type seed: int
        """

        torch.backends.cudnn.enabled = True
        torch.backends.cudnn.benchmark = True

        mkdir(local_rank, self.cfg.save_dir)

        if verbose:
            self.logger = NanoDetLightningLogger(self.temp_path + "/" + logging_path)
            self.logger.dump_cfg(self.cfg)

        if seed !='' or seed is not None:
            if verbose:
                self.logger.info("Set random seed to {}".format(seed))
            pl.seed_everything(seed)

        if verbose:
            self.logger.info("Setting up data...")

        train_dataset = build_dataset(self.cfg.data.val, dataset, self.cfg.class_names, "train")
        val_dataset = train_dataset if val_dataset is None else build_dataset(self.cfg.data.val, val_dataset, self.cfg.class_names, "test")

        evaluator = build_evaluator(self.cfg.evaluator, val_dataset)

        train_dataloader = torch.utils.data.DataLoader(
            train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.cfg.device.workers_per_gpu,
            pin_memory=True,
            collate_fn=naive_collate,
            drop_last=True,
        )
        val_dataloader = torch.utils.data.DataLoader(
            val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.cfg.device.workers_per_gpu,
            pin_memory=True,
            collate_fn=naive_collate,
            drop_last=False,
        )

        # Load only weights
        if self.cfg.schedule.load_model is not None:
            self.load(self.cfg.schedule.load_model)

        # Load state dictionary
        model_resume_path = (
            os.path.join(self.temp_path, "model_iter{}.ckpt".format(self.checkpoint_load_iter))
            if self.checkpoint_load_iter > 0 else None
        )

        if verbose:
            self.logger.info("Creating task...")
        task = TrainingTask(self.cfg, self.model, self.weight_averager, evaluator)

        if self.device == "cpu":
            gpu_ids = None
            accelerator = None
        elif self.device == "cuda":
            gpu_ids = self.cfg.device.gpu_ids
            accelerator = None if len(gpu_ids) <= 1 else "ddp"

        trainer = pl.Trainer(
            default_root_dir=self.temp_path,
            max_epochs=self.iters,
            gpus=gpu_ids,
            check_val_every_n_epoch=self.checkpoint_after_iter,
            accelerator=accelerator,
            log_every_n_steps=self.cfg.log.interval,
            num_sanity_val_steps=0,
            resume_from_checkpoint=model_resume_path,
            callbacks=[ProgressBar(refresh_rate=0)],  # disable tqdm bar
            logger=self.logger,
            benchmark=True,
            gradient_clip_val=self.cfg.get("grad_clip", 0.0),
        )

        trainer.fit(task, train_dataloader, val_dataloader)

    def eval(self, dataset):
        """
        This method performs evaluation on a given dataset and returns a dictionary with the evaluation results.
        :param dataset: dataset object, to perform evaluation on
        :type dataset: ExternalDataset, DetectionDataset not implemented yet
        """

        local_rank = -1
        torch.backends.cudnn.enabled = True
        torch.backends.cudnn.benchmark = True

        timestr = datetime.datetime.now().__format__("%Y_%m_%d_%H:%M:%S")
        save_dir = os.path.join(self.cfg.save_dir, timestr)
        mkdir(local_rank, save_dir)
        logger = NanoDetLightningLogger(save_dir)

        self.cfg.update({"test_mode": "test"})

        logger.info("Setting up data...")

        val_dataset = build_dataset(self.cfg.data.val, dataset, self.cfg.class_names, "test")

        val_dataloader = torch.utils.data.DataLoader(
            val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.cfg.device.workers_per_gpu,
            pin_memory=True,
            collate_fn=naive_collate,
            drop_last=False,
        )
        evaluator = build_evaluator(self.cfg.evaluator, val_dataset)

        logger.info("Creating task...")
        # self.load(self.cfg.schedule.load_model)
        task = TrainingTask(self.cfg, self.model, self.weight_averager, evaluator)

        if self.device == "cpu":
            gpu_ids = None
            accelerator = None
        elif self.device == "cuda":
            gpu_ids = self.cfg.device.gpu_ids
            accelerator = None if len(gpu_ids) <= 1 else "ddp"

        trainer = pl.Trainer(
            default_root_dir=save_dir,
            gpus=gpu_ids,
            accelerator=accelerator,
            log_every_n_steps=self.cfg.log.interval,
            num_sanity_val_steps=0,
            logger=logger,
        )
        logger.info("Starting testing...")
        trainer.test(task, val_dataloader)

    def infer(self, path="", mode="image", camid="0", threshold=0.35):
        """
        Performs inference
        :param path: path to a directory of images, a single image or a video to perform inference
        :type path: str, optional
        :param mode: mode of the inference, it can be ["image", "video", "webcam"] and will perform inference
        in an image or all images in a directory of the path, in a video in the path, or the feed of a camera with camid
        :type mode: str
        :param camid: the camid of webcam in use for inference if mode is webcam
        :type camid: str, optional
        :param threshold: confidence threshold
        :type threshold: float, optional
        :return: list of bounding boxes
        :rtype: BoundingBoxList
        """
        local_rank = 0
        torch.backends.cudnn.enabled = True
        torch.backends.cudnn.benchmark = True

        self.logger = Logger(local_rank, use_tensorboard=False)
        predictor = Predictor(self.cfg, self.model, self.logger, device=self.device)
        self.logger.log('Press "Esc", "q" or "Q" to exit.')
        if mode == "image":
            if os.path.isdir(path):
                files = get_image_list(path)
            else:
                files = [path]
            files.sort()
            for image_name in files:
                img = Image.open(image_name)
                meta, res = predictor.inference(img.opencv())

                time1 = time.time()
                bounding_boxes = BoundingBoxList([])
                for label in res[0]:
                    for box in res[0][label]:
                        score = box[-1]
                        if score > threshold:
                            bbox = BoundingBox(left=box[0], top=box[1],
                                               width=box[2] - box[0],
                                               height=box[3] - box[1],
                                               name=label,
                                               score=score)
                            bounding_boxes.data.append(bbox)
                bounding_boxes.data.sort(key=lambda v: v.confidence)

                result_image = draw_bounding_boxes(img.opencv(), bounding_boxes, class_names=self.cfg.class_names, show=False)
                cv2.imshow('detections', result_image)
                print("visualize time: {:.3f}s".format(time.time() - time1))
                ch = cv2.waitKey(0)
                if ch == 27 or ch == ord("q") or ch == ord("Q"):
                    break
        elif mode == "video" or mode == "webcam":
            cap = cv2.VideoCapture(path if mode == "video" else camid)
            width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)  # float
            height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)  # float
            fps = cap.get(cv2.CAP_PROP_FPS)
            while True:
                ret_val, frame = cap.read()
                frame = Image(frame, guess_format=False)
                if ret_val:
                    meta, res = predictor.inference(frame.data)
                    time1 = time.time()
                    bounding_boxes = BoundingBoxList([])
                    for label in res[0]:
                        for box in res[0][label]:
                            score = box[-1]
                            if score > threshold:
                                bbox = BoundingBox(left=box[0], top=box[1],
                                                   width=box[2] - box[0],
                                                   height=box[3] - box[1],
                                                   name=label,
                                                   score=score)
                                bounding_boxes.data.append(bbox)
                    bounding_boxes.data.sort(key=lambda v: v.confidence)

                    result_image = draw_bounding_boxes(frame, bounding_boxes, class_names=self.cfg.class_names,
                                                       show=False)
                    cv2.imshow('detections', result_image)
                    print("visualize time: {:.3f}s".format(time.time() - time1))
                    ch = cv2.waitKey(1)
                    if ch == 27 or ch == ord("q") or ch == ord("Q"):
                        break
                else:
                    break
