# uniform.py
"""
制服识别分类器模块。

基于 ConvNeXtV2（timm）的二分类模型，判断检测到的人体目标是否穿着保安制服。
推理前对人体框做等比例外扩（expand_ratio），容纳因检测框偏紧导致制服特征被裁剪的情况。

模型格式（checkpoint 必须包含）：
    model_state_dict  —— 模型权重（支持 DataParallel 的 "module." 前缀自动去除）；
    class_to_idx      —— 类别名到索引的映射，如 {"uniform": 0, "civilian": 1}。

预处理：使用 timm.data.create_transform 按训练时的数据配置还原，
确保推理与训练的归一化参数完全一致。
"""
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
    """单人制服识别分类器。

    调用方式：每次调用 predict_person() 传入原始帧和人体框，
    返回 (is_guard, confidence) 二元组；UniformCache 负责缓存结果以避免重复推理。
    """

    def __init__(
        self,
        model_path: str,
        device: str = "0",
        imgsz: int = 224,
        conf_thres: float = 0.80,
        expand_ratio: float = 0.10,
        model_name: str = "hf_hub:timm/convnextv2_tiny.fcmae_ft_in22k_in1k",
        positive_class_name: str = "uniform",
        use_half: bool = False,
    ):
        """
        Args:
            model_path:          checkpoint 文件路径（.pt），必须包含 model_state_dict 和 class_to_idx。
            device:              推理设备，"0"/"1" 表示 GPU 索引，"cpu" 强制使用 CPU，
                                 GPU 不可用时自动回落到 CPU。
            imgsz:               分类模型输入边长（正方形，像素），应与训练时一致。
            conf_thres:          正类（制服）置信度阈值；低于此值视为非保安。
            expand_ratio:        人体框向外扩展比例（相对于框的宽/高），
                                 补偿检测框偏紧导致的制服特征截断。
            model_name:          timm 模型名称；_build_model 会按多个候选名依次尝试，
                                 容忍 hf_hub: 前缀在离线环境下不可用的情况。
            positive_class_name: checkpoint 中代表"保安制服"的类别名，
                                 必须存在于 class_to_idx 中。
            use_half:            CUDA 推理时是否使用 FP16，降低显存占用。
        """
        # 设备选择：device 为数字字符串时映射到对应 GPU，否则 CPU
        if device and device != "cpu" and torch.cuda.is_available():
            self.device = torch.device(f"cuda:{device}")
        else:
            self.device = torch.device("cpu")

        self.imgsz = imgsz
        self.conf_thres = conf_thres
        self.expand_ratio = expand_ratio
        self.model_name = model_name
        self.positive_class_name = positive_class_name
        self.use_half = bool(use_half and self.device.type == "cuda")

        # ── 加载 checkpoint ──────────────────────────────────────────────
        ckpt = torch.load(model_path, map_location="cpu")   # 先加载到 CPU，再按需移到 GPU

        if not isinstance(ckpt, dict):
            raise ValueError(f"不支持的 checkpoint 格式: {type(ckpt)}")
        if "model_state_dict" not in ckpt:
            raise KeyError("checkpoint 中缺少 'model_state_dict'")
        if "class_to_idx" not in ckpt:
            raise KeyError("checkpoint 中缺少 'class_to_idx'")

        self.class_to_idx = ckpt["class_to_idx"]
        self.idx_to_class = {v: k for k, v in self.class_to_idx.items()}   # 反向映射，供调试

        if self.positive_class_name not in self.class_to_idx:
            raise ValueError(
                f"正类名 '{self.positive_class_name}' 不在 class_to_idx 中: {self.class_to_idx}"
            )

        self.positive_class_idx = self.class_to_idx[self.positive_class_name]
        self.num_classes = len(self.class_to_idx)

        # ── 构建模型结构并加载权重 ────────────────────────────────────────
        self.model = self._build_model(self.model_name, self.num_classes)

        # 去除 DataParallel 训练产生的 "module." 前缀，使权重可加载到单卡/CPU
        clean_state_dict = {
            (k[len("module."):] if k.startswith("module.") else k): v
            for k, v in ckpt["model_state_dict"].items()
        }

        missing, unexpected = self.model.load_state_dict(clean_state_dict, strict=False)
        if missing:
            print("[WARN] missing keys:", missing[:20], "... total =", len(missing))
        if unexpected:
            print("[WARN] unexpected keys:", unexpected[:20], "... total =", len(unexpected))

        self.model.to(self.device)
        if self.use_half:
            self.model.half()
        self.model.eval()   # 关闭 dropout / BN 的训练模式

        # ── 推理预处理：与训练时完全对齐 ────────────────────────────────
        # resolve_data_config 从模型元数据读取 mean/std/resize 等参数，
        # 确保不因手动填写归一化参数而引入推理-训练不一致的隐患
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
        """尝试多个候选模型名构建 timm 模型结构。

        为兼容离线部署（hf_hub: 前缀需要网络）和不同版本的 timm，
        按优先级依次尝试候选名称，全部失败时才抛出异常。

        Args:
            model_name:   原始模型名称（来自配置或 checkpoint）。
            num_classes:  分类头的输出类别数，需与训练时一致。

        Returns:
            构建成功的 timm 模型（未加载权重，eval 模式由调用方设置）。
        """
        candidates = [
            model_name,
            model_name.replace("hf_hub:timm/", ""),    # 去除 hub 前缀，适用于离线环境
            "convnextv2_tiny.fcmae_ft_in22k_in1k",     # 完整官方名
            "convnextv2_tiny",                          # 最短回落名，兼容旧版 timm
        ]

        last_err = None
        for name in candidates:
            try:
                model = timm.create_model(name, pretrained=False, num_classes=num_classes)
                print(f"[INFO] 使用模型结构: {name}")
                return model
            except Exception as e:
                last_err = e

        raise RuntimeError(f"无法构建模型结构，最后错误: {last_err}")

    def predict_person(
        self,
        frame: np.ndarray,
        bbox: tuple[int, int, int, int],
    ) -> Tuple[bool, float]:
        """对单个人体目标进行制服识别推理。

        推理流程：
          1. 按 expand_ratio 向外扩展人体框（钳位在画面范围内）；
          2. 裁图 → BGR 转 RGB → PIL Image → timm 预处理 → GPU tensor；
          3. 模型前向推理 → softmax → 取正类置信度；
          4. 与阈值比较，返回 (is_guard, confidence)。

        裁图为空（框越界或面积为零）时返回 (False, 0.0)，不抛出异常。

        Args:
            frame: BGR 格式的原始视频帧。
            bbox:  人体检测框 (x1, y1, x2, y2)，像素坐标。

        Returns:
            (is_guard, confidence)：
                is_guard    —— 置信度是否达到 conf_thres；
                confidence  —— 正类（制服）的 softmax 概率值（0~1）。
        """
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]

        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)

        # 向外扩展人体框，容纳检测框偏紧时被截断的制服区域
        pad_w = int(bw * self.expand_ratio)
        pad_h = int(bh * self.expand_ratio)
        x1 = max(0, x1 - pad_w)
        y1 = max(0, y1 - pad_h)
        x2 = min(w, x2 + pad_w)
        y2 = min(h, y2 + pad_h)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return False, 0.0   # 扩展后仍为空（极端情况），安全返回

        # BGR → RGB → PIL → timm 预处理 → batch 维度 → 移到推理设备
        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(crop_rgb)
        tensor = self.transform(image).unsqueeze(0).to(self.device)
        if self.use_half:
            tensor = tensor.half()

        with torch.no_grad():   # 推理阶段不计算梯度，节省显存和计算
            logits = self.model(tensor)
            probs = F.softmax(logits, dim=1)[0]
            conf = float(probs[self.positive_class_idx].item())

        is_guard = conf >= self.conf_thres
        return is_guard, conf

    def close(self) -> None:
        """释放模型引用，便于运行时停止后回收显存。"""
        self.model = None
