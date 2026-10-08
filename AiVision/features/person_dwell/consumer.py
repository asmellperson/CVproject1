"""
features/person_dwell/consumer.py — 人员违规逗留检测

BaseFunctionConsumer
    ↓ 提供画面处理、配置管理、推理调用、告警分发等公共能力
DwellDetectionConsumer
    ↓ 实现目标跟踪和逗留时间判断
HumanConsumer
      通过 SPEC 配置使用人体检测模型
"""
from AiVision.features._shared.dwell_consumer import DwellDetectionConsumer

class HumanConsumer(DwellDetectionConsumer):
    """人员违规逗留检测 — 用 yolo_human 模型(person_phone.pt 过滤 class 0)"""
    REQUIRED_DETECTION_TYPE = None

    def _detection_options(self, cfg: dict) -> tuple:
        """将人体框筛选阈值和运动匹配参数交给公共逗留检测流程。"""
        return cfg["CONF_THRESHOLD"], cfg["MIN_BOX_AREA"], cfg["ASPECT_RATIO_RANGE"], {
            "center_dist_thr": cfg["CENTER_DIST_THR"],
            "area_ratio_thr": cfg["AREA_RATIO_THR"],
            "match_score_thr": cfg["MATCH_SCORE_THR"],
            "smooth_alpha": cfg["TRACK_SMOOTH_ALPHA"],
        }
