"""按已授权摄像头读取非阻塞检测快照，不持有推理锁。"""
from datetime import datetime, timezone
import time

from .schema import FEATURE, STATUS_STALE_SECONDS, TailgatingStatus


def camera_status(camera: dict, orchestrator) -> TailgatingStatus:
    key = camera["shm_name"]
    online = bool(orchestrator and orchestrator.camera_runtime_manager.is_running(key))
    status = TailgatingStatus(camera_key=key, camera_name=camera["name"], department=camera["department"],
                             online=online, state="waiting", reason="waiting")
    if not camera["enabled"] or not camera["functions"].get(FEATURE):
        return status.model_copy(update={"state": "disabled", "reason": "disabled"})
    if not online:
        return status.model_copy(update={"state": "offline" if orchestrator else "waiting", "reason": "offline" if orchestrator else "waiting"})
    consumer = orchestrator.consumers.get(FEATURE)
    detail = consumer.get_monitor_status(key) if consumer else None
    if detail is None:
        return status
    age = time.time() - detail["updated_at_s"]
    if not 0 <= age <= STATUS_STALE_SECONDS:
        return status.model_copy(update={"state": "stale", "reason": "stale"})
    return TailgatingStatus.model_validate({**status.model_dump(),
        "state": "error" if detail["error"] else "waiting" if detail["reason"] == "unconfigured" else "ready",
        "reason": detail["reason"], "count": detail["count"], "alarm": detail["alarm"],
        "persons": detail["persons"], "events": detail["events"], "error": detail["error"],
        "sample_interval_seconds": detail["sample_interval_seconds"],
        "updated_at": datetime.fromtimestamp(detail["updated_at_s"], timezone.utc).isoformat(),
    })
