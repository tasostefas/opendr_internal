import os
import time

import torch

from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.data.batch_process import stack_batch_img
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.data.collate import naive_collate
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.data.transform import Pipeline
from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.model.arch import build_model

image_ext = [".jpg", ".jpeg", ".webp", ".bmp", ".png"]
video_ext = ["mp4", "mov", "avi", "mkv"]

class Predictor(object):
    def __init__(self, cfg, model, device="cuda:0"):
        self.cfg = cfg
        self.device = device

        if self.cfg.model.arch.backbone.name == "RepVGG":
            deploy_config = self.cfg.model
            deploy_config.arch.backbone.update({"deploy": True})
            deploy_model = build_model(deploy_config)
            from opendr.perception.object_detection_2d.nanodet.algorithm.nanodet.model.backbone.repvgg import repvgg_det_model_convert
            model = repvgg_det_model_convert(model, deploy_model)

        self.model = model.to(device).eval()

        # TODO: pipeline check
        self.pipeline = Pipeline(self.cfg.data.val.pipeline, self.cfg.data.val.keep_ratio)

    def inference(self, img):
        img_info = {"id": 0}
        height, width = img.shape[:2]
        img_info["height"] = height
        img_info["width"] = width
        meta = dict(img_info=img_info, raw_img=img, img=img)
        meta = self.pipeline(None, meta, self.cfg.data.val.input_size)
        meta["img"] = torch.from_numpy(meta["img"].transpose(2, 0, 1)).to(self.device)
        meta = naive_collate([meta])
        meta["img"] = stack_batch_img(meta["img"], divisible=32)
        with torch.no_grad():
            results = self.model.inference(meta)
        return meta, results

    def visualize(self, dets, meta, class_names, score_thres):
        time1 = time.time()
        all_box = []
        for label in dets:
            for box in dets[label]:
                score = box[-1]
                if score > score_thres:
                    x0, y0, x1, y1 = [int(i) for i in box[:4]]
                    all_box.append([label, x0, y0, x1, y1, score])
        all_box.sort(key=lambda v: v[5])
        result_img = self.model.head.show_result(
            meta["raw_img"][0], dets, class_names, score_thres=score_thres, show=True
        )
        print("viz time: {:.3f}s".format(time.time() - time1))
        return result_img


def get_image_list(path):
    image_names = []
    for maindir, subdir, file_name_list in os.walk(path):
        for filename in file_name_list:
            apath = os.path.join(maindir, filename)
            ext = os.path.splitext(apath)[1]
            if ext in image_ext:
                image_names.append(apath)
    return image_names