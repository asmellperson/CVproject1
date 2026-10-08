"""对人体裁图执行制服分类，向保安感知层提供 uniform 概率。

模型架构固定且离线加载，检查 checkpoint 类别映射与参数一致性，优先使用可用 CUDA。
是否认定为保安、概率保持多久属于业务规则，本模块只返回分类置信度。
"""
from __future__ import annotations

from typing import Any

from AiVision.inference.base_worker import BaseModelWorker


_MODEL_ARCHITECTURE = "convnextv2_tiny.fcmae_ft_in22k_in1k"


class UniformClassifierWorker(BaseModelWorker):
    """封装离线分类权重、图像预处理和制服正类索引的 Worker。"""
    def load_model(self) -> Any:
        """验证 checkpoint 字段与连续类别索引，严格载入本地模型并准备推理变换；无效权重报错。"""
        from AiVision.inference.model_paths import validate_model_path

        path = validate_model_path(self.model_path, model_type="timm_classifier")
        import torch
        import timm
        from timm.data import create_transform, resolve_data_config

        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        if not isinstance(checkpoint, dict):
            raise ValueError("制服 checkpoint 必须为字典")
        for field in ("model_state_dict", "class_to_idx"):
            if field not in checkpoint:
                raise ValueError(f"制服 checkpoint 缺少 {field}")
        classes = checkpoint["class_to_idx"]
        if not isinstance(classes, dict) or "uniform" not in classes:
            raise ValueError("制服 checkpoint 的 class_to_idx 必须包含 uniform 类")
        if (any(not isinstance(name, str) or type(index) is not int for name, index in classes.items())
                or set(classes.values()) != set(range(len(classes)))):
            raise ValueError("制服 checkpoint 的 class_to_idx 必须使用连续且唯一的整数索引")
        state = checkpoint["model_state_dict"]
        if not isinstance(state, dict) or not state or any(not isinstance(key, str) for key in state):
            raise ValueError("制服 checkpoint 的 model_state_dict 无效")
        state_dict = {key.removeprefix("module."): value for key, value in state.items()}
        if len(state_dict) != len(state):
            raise ValueError("制服 checkpoint 去除 module. 前缀后存在重复参数")

        # 固定本地架构，不通过 hf_hub 查配置，也不下载预训练权重。
        model = timm.create_model(_MODEL_ARCHITECTURE, pretrained=False, num_classes=len(classes))
        model.load_state_dict(state_dict, strict=True)
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(self._device).eval()
        self._transform = create_transform(**resolve_data_config({}, model=model), is_training=False)
        self._uniform_index = classes["uniform"]
        self._num_classes = len(classes)
        return model

    def infer(self, model: Any, frame, task_meta: dict) -> list[dict]:
        """将 BGR 人体 crop 转成 RGB 并分类，校验 logits 形状后返回 uniform 的 softmax 概率。"""
        import cv2
        import torch
        from PIL import Image

        # 输入已是人体 crop；不在模型层扩框或作制服判定。
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        tensor = self._transform(image).unsqueeze(0).to(self._device)
        with torch.inference_mode():
            logits = model(tensor)
            if tuple(logits.shape) != (1, self._num_classes):
                raise ValueError("制服模型分类输出形状异常")
            probability = float(torch.softmax(logits, dim=1)[0, self._uniform_index].item())
        return [{"type": "uniform", "confidence": probability}]
