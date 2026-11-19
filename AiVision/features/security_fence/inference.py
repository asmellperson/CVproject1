"""围栏单帧请求的就绪状态；人体与身份结果始终对应同一张原图。"""
from dataclasses import dataclass

import numpy as np

from AiVision.features._shared.consumer import SubmittedInference


def inference_ready(request: SubmittedInference, now: float) -> bool:
    """只检查结果或期限，不在摄像头轮询线程等待模型。"""
    return (request.result is not None
            or (request.pending is not None and request.pending.event.is_set())
            or now >= request.deadline_at)


@dataclass
class FenceInference:
    frame: np.ndarray
    config: dict
    captured_at: float
    observed_at: float
    mode: str
    people: SubmittedInference
    face: SubmittedInference | None = None
    people_result: dict | None = None
    early_published: bool = False

    def ready(self, now: float) -> bool:
        people_ready = self.people_result is not None or inference_ready(self.people, now)
        # 禁入时段先发布人体判定，随后只补全同一帧的身份，不重复播报旧画面。
        if self.mode == "forbidden" and not self.early_published:
            return people_ready
        # 白名单模式的空画面没有身份核验需求。人体结果已被 Consumer 领取后可立即
        # 发布人数为零，不能被慢人脸任务拖到监控状态过期。
        if self.mode == "whitelist" and not self.early_published:
            # 人体请求超时或失败也必须尽快发布明确错误并释放名额，不能因为尚未
            # 创建人脸请求而永远停在在途状态。
            if self.people_result is None:
                return people_ready and self.face is None
            if self.people_result.get("status") != "ok" or not self.people_result.get("detections"):
                return True
        return people_ready and self.face is not None and inference_ready(self.face, now)
