# uniform.py
from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
import torch
import torch.nn.functional as F
import timm
from PIL import Image
from timm.data import create_transform, resolve_data_config


class UniformClassifier:
    def __init__(
        self,
        model_path: str,
        device: str = "0",
        imgsz: int = 224,
        conf_thres: float = 0.80,
        expand_ratio: float = 0.10,
        model_name: str = "hf_hub:timm/convnextv2_tiny.fcmae_ft_in22k_in1k",
        positive_class_name: str = "uniform",
    ):
        if device and device != "cpu" and torch.cuda.is_available():
            self.device = torch.device(f"cuda:{device}")
        else:
            self.device = torch.device("cpu")

        self.imgsz = imgsz
        self.conf_thres = conf_thres
        self.expand_ratio = expand_ratio
        self.model_name = model_name
        self.positive_class_name = positive_class_name

        ckpt = torch.load(model_path, map_location="cpu")

        if not isinstance(ckpt, dict):
            raise ValueError(f"不支持的 checkpoint 格式: {type(ckpt)}")

        if "model_state_dict" not in ckpt:
            raise KeyError("checkpoint 中缺少 'model_state_dict'")
        if "class_to_idx" not in ckpt:
            raise KeyError("checkpoint 中缺少 'class_to_idx'")

        self.class_to_idx = ckpt["class_to_idx"]
        self.idx_to_class = {v: k for k, v in self.class_to_idx.items()}

        if self.positive_class_name not in self.class_to_idx:
            raise ValueError(
                f"正类名 '{self.positive_class_name}' 不在 class_to_idx 中: {self.class_to_idx}"
            )

        self.positive_class_idx = self.class_to_idx[self.positive_class_name]
        self.num_classes = len(self.class_to_idx)

        # 按训练时结构还原模型
        self.model = self._build_model(self.model_name, self.num_classes)

        state_dict = ckpt["model_state_dict"]

        clean_state_dict = {}
        for k, v in state_dict.items():
            if k.startswith("module."):
                clean_state_dict[k[len("module."):]] = v
            else:
                clean_state_dict[k] = v

        missing, unexpected = self.model.load_state_dict(clean_state_dict, strict=False)
        if missing:
            print("[WARN] missing keys:", missing[:20], "... total =", len(missing))
        if unexpected:
            print("[WARN] unexpected keys:", unexpected[:20], "... total =", len(unexpected))

        self.model.to(self.device)
        self.model.eval()

        # 使用 timm 官方同款推理预处理
        data_config = resolve_data_config({}, model=self.model)
        self.transform = create_transform(**data_config, is_training=False)

        print("[INFO] UniformClassifier loaded")
        print("[INFO] model_path =", model_path)
        print("[INFO] model_name =", model_name)
        print("[INFO] class_to_idx =", self.class_to_idx)
        print("[INFO] positive_class_idx =", self.positive_class_idx)
        print("[INFO] conf_thres =", self.conf_thres)

    @staticmethod
    def _build_model(model_name: str, num_classes: int):
        candidates = [
            model_name,
            model_name.replace("hf_hub:timm/", ""),
            "convnextv2_tiny.fcmae_ft_in22k_in1k",
            "convnextv2_tiny",
        ]

        last_err = None
        for name in candidates:
            try:
                model = timm.create_model(
                    name,
                    pretrained=False,
                    num_classes=num_classes,
                )
                print(f"[INFO] 使用模型结构: {name}")
                return model
            except Exception as e:
                last_err = e

        raise RuntimeError(f"无法构建模型结构，最后错误: {last_err}")

    def predict_person(self, frame: np.ndarray, bbox: tuple[int, int, int, int]) -> Tuple[bool, float]:
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]

        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)

        pad_w = int(bw * self.expand_ratio)
        pad_h = int(bh * self.expand_ratio)

        x1 = max(0, x1 - pad_w)
        y1 = max(0, y1 - pad_h)
        x2 = min(w, x2 + pad_w)
        y2 = min(h, y2 + pad_h)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return False, 0.0

        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(crop_rgb)
        tensor = self.transform(image).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.model(tensor)
            probs = F.softmax(logits, dim=1)[0]
            conf = float(probs[self.positive_class_idx].item())

        is_guard = conf >= self.conf_thres
        # print(f"[uniform-cls] conf={conf:.4f}, is_guard={is_guard}")
        return is_guard, conf