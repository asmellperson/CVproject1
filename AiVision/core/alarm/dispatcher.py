# 文件说明：实现事件分发相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
core/alarm/dispatcher.py
统一告警分发器 — 把"判断该不该告警 + 触发哪些通道"从 Consumer 里抽出来。

旧代码: 每个 Consumer 都把 _should_alarm / _execute_alarm / _send_wechat_alert /
        _save_to_sql / wechat 后台线程 缠在一起,~150 行重复散落在 5 个子类。
新代码: Consumer 只管业务判断,告警分发交给 AlarmDispatcher。
"""
from __future__ import annotations
import queue
import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import cv2
import numpy as np

from core.logger import logger
from core.settings import settings
from core.alarm.horn import Horn
from core.alarm.wechat import WeChatNotifier


# 功能：单次告警请求的数据载体，由 Consumer 构造后提交给 AlarmDispatcher；输入与输出详见下方说明
# 参数：
#   - `feature_name`（str）：`feature_name` 对应的业务输入值
#   - `camera_id`（int）：摄像头唯一标识
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
#   - `frame`（np.ndarray）：待处理的视频图像帧
#   - `violation_type`（int）：`violation_type` 对应的业务输入值
#   - `alarm_config`（dict）：`alarm_config` 对应的业务输入值
#   - `camera_key`（str）：`camera_key` 对应的业务输入值
#   - `subject_type`（str）：`subject_type` 对应的业务输入值
#   - `subject_id`（str）：`subject_id` 对应业务对象的唯一标识
#   - `subject_name`（str）：`subject_name` 对应的业务输入值
#   - `reason`（str）：`reason` 对应的业务输入值
#   - `metadata`（dict）：`metadata` 对应的业务输入值
# 返回：AlarmRequest；返回新建的 `AlarmRequest` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_dispatcher_cooldown_uses_logistics_channel_subject::request`
#         实例化本符号；`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_dispatcher_forwards_subject_metadata_to_violation_writer`
#         实例化本符号；`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_dispatcher_attaches_pending_shared_evidence_video`
#         实例化本符号；`AiVision/tests/test_alarm_config_hot_update.py` 的
#         `test_dispatcher_respects_explicit_sql_channel_switch_and_keeps_legacy_default::request` 实例化本符号；另有 5 处静态调用
#   - 内部调用：`field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class AlarmRequest:
    """
    单次告警请求的数据载体，由 Consumer 构造后提交给 AlarmDispatcher。

    字段说明:
        feature_name   : 触发告警的功能名称。
        camera_id      : 摄像头数字 ID，作为冷却表的 key 之一。
        camera_name    : 摄像头展示名称，写入告警消息与数据库。
        frame          : 违规帧的 BGR 图像（np.ndarray），用于截图保存与微信推图。
        violation_type : 违规类型编号，对应数据库中的枚举值。
        alarm_config   : 告警通道配置字典，结构为
                         {"horn": {...}, "wechat": {...}, "sql": {...}}，
                         每个通道包含 enable 开关与 parm 参数子字典。
        camera_key     : 共享内存标识（shm_name），优先用于数据库写入；
                         为空时回退到 camera_name。
    """
    feature_name: str
    camera_id: int
    camera_name: str
    frame: np.ndarray
    violation_type: int
    alarm_config: dict
    camera_key: str = ""
    subject_type: str = "camera"
    subject_id: str = ""
    subject_name: str = ""
    reason: str = ""
    metadata: dict = field(default_factory=dict)


# 功能：全局告警分发器（单例）；输入与输出详见下方说明
# 参数：无。
# 返回：AlarmDispatcher；返回新建的 `AlarmDispatcher` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_dispatcher_cooldown_uses_logistics_channel_subject`
#         实例化本符号；`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_dispatcher_forwards_subject_metadata_to_violation_writer`
#         实例化本符号；`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_dispatcher_attaches_pending_shared_evidence_video`
#         实例化本符号；`AiVision/tests/test_alarm_config_hot_update.py` 的
#         `test_dispatcher_respects_explicit_sql_channel_switch_and_keeps_legacy_default` 实例化本符号；另有 5 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AlarmDispatcher:
    """
    全局告警分发器（单例）。

    职责:
        1. 冷却控制  — 同一摄像头 × 功能维度，在 alarm_interval 秒内只触发一次。
        2. 通道分发  — 按 alarm_config 中各通道的 enable 开关，分别调用
                       喇叭 / 微信 / SQL 三条告警链路。
        3. 异步解耦  — 微信发送通过内部队列 + 守护线程异步执行，
                       避免网络延迟阻塞主检测流程。

    生命周期:
        系统启动时由 Orchestrator 调用 configure() 注入依赖，之后各 Consumer
        通过全局单例 alarm_dispatcher.maybe_dispatch() 提交告警请求。
    """

    # 功能：初始化或配置 `__init__` 对应的事件分发逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`queue.Queue`、`threading.Thread`、`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self):
        # ---- 外部依赖（由 Orchestrator 通过 configure() 注入）----
        self.horn_dict: dict[int, Horn] = {}          # horn_id → Horn 实例映射
        self.wechat: Optional[WeChatNotifier] = None  # 微信推送客户端
        self.violation_writer = None                  # ViolationWriter，负责 SQL 持久化
        self.evidence_recorder = None                 # 公共报警前后视频录制器

        # ---- 微信异步发送队列 ----
        # 微信 API 存在网络延迟，使用独立队列 + 守护线程，防止阻塞检测主循环。
        # maxsize=100：队列满时丢弃新请求（见 _execute 中的 put_nowait 处理）。
        self._wechat_queue: queue.Queue = queue.Queue(maxsize=100)
        self._wechat_thread = threading.Thread(target=self._wechat_loop, daemon=True)
        self._wechat_started = False  # 防止 configure() 被重复调用时二次启动线程

        # ---- 冷却状态 ----
        # key: (subject_type, subject_id, feature_name)，value: 上次实际触发时间。
        # 使用 _lock 保护，避免多 Consumer 线程并发写入时的竞态条件。
        self._last_alarm: dict[tuple[str, str, str], float] = {}
        self._lock = threading.Lock()

    # 功能：注入运行时依赖，并启动微信后台发送线程；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `horn_dict`（dict[int, Horn]）：`horn_dict` 对应的业务输入值
    #   - `wechat`（Optional[WeChatNotifier]）：`wechat` 对应的业务输入值
    #   - `violation_writer`（未显式标注）：`violation_writer` 对应的业务输入值
    #   - `evidence_recorder`（未显式标注）：`evidence_recorder` 对应的业务输入值；默认值为 `None`
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._wechat_thread.start`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源。
    def configure(
        self,
        horn_dict: dict[int, Horn],
        wechat: Optional[WeChatNotifier],
        violation_writer,
        evidence_recorder=None,
    ):
        """
        注入运行时依赖，并启动微信后台发送线程。

        应在系统启动阶段由 Orchestrator 调用且只调用一次。
        重复调用时依赖会被覆盖，但后台线程不会重复创建（_wechat_started 守护）。
        """
        self.horn_dict = horn_dict
        self.wechat = wechat
        self.violation_writer = violation_writer
        self.evidence_recorder = evidence_recorder
        if not self._wechat_started:
            self._wechat_thread.start()
            self._wechat_started = True

    # ------------------------------------------------------------------ #
    #  核心入口                                                             #
    # ------------------------------------------------------------------ #

    # 功能：冷却检查 + 告警分发的统一入口，Consumer 检测到违规时调用此方法；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `request`（AlarmRequest）：当前 HTTP 请求及上下文
    #   - `alarm_interval`（float）：`alarm_interval` 对应的时间间隔或时长；默认值为 `5.0`
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._cooldown_key`、`time.time`、`self._last_alarm.get`、`self._execute`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def maybe_dispatch(
        self,
        request: AlarmRequest,
        alarm_interval: float = 5.0,
    ) -> bool:
        """
        冷却检查 + 告警分发的统一入口，Consumer 检测到违规时调用此方法。

        冷却逻辑:
            以 (subject_type, subject_id, feature_name) 为粒度记录上次触发时间；
            若距上次触发不足 alarm_interval 秒，静默丢弃并返回 False。

        Args:
            request        : 封装本次违规信息的 AlarmRequest 对象。
            alarm_interval : 同一摄像头×功能的告警冷却秒数，默认 5 秒。

        Returns:
            True  — 冷却已过，告警已提交各通道执行。
            False — 仍在冷却期，本次告警被静默丢弃。
        """
        key = self._cooldown_key(request)
        now = time.time()

        with self._lock:
            last = self._last_alarm.get(key, 0.0)
            if now - last < alarm_interval:
                return False          # 冷却期内，跳过
            self._last_alarm[key] = now  # 更新时间戳，占位防并发重入

        self._execute(request)
        return True

    # 功能：清除指定摄像头和功能的告警冷却状态；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.reset_subject_cooldown`、`str`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def reset_cooldown(self, camera_id: int, feature_name: str) -> None:
        """清除指定摄像头和功能的告警冷却状态。"""
        self.reset_subject_cooldown("camera", str(camera_id), feature_name)

    # 功能：清除摄像头或通道主体的告警冷却状态；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `subject_type`（str）：`subject_type` 对应的业务输入值
    #   - `subject_id`（str）：`subject_id` 对应业务对象的唯一标识
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/dispatcher.py` 的 `AlarmDispatcher::reset_cooldown` 调用本符号
    #   - 内部调用：`self._last_alarm.pop`、`str`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def reset_subject_cooldown(
        self,
        subject_type: str,
        subject_id: str,
        feature_name: str,
    ) -> None:
        """清除摄像头或通道主体的告警冷却状态。"""
        with self._lock:
            self._last_alarm.pop((subject_type, str(subject_id), feature_name), None)

    # 功能：实现 `_cooldown_key` 对应的事件分发逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（AlarmRequest）：当前 HTTP 请求及上下文
    # 返回：tuple[str, str, str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/dispatcher.py` 的 `AlarmDispatcher::maybe_dispatch` 调用本符号
    #   - 内部调用：`str`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _cooldown_key(request: AlarmRequest) -> tuple[str, str, str]:
        subject_type = request.subject_type or "camera"
        subject_id = request.subject_id or str(request.camera_id)
        return subject_type, subject_id, request.feature_name

    # ------------------------------------------------------------------ #
    #  私有方法                                                             #
    # ------------------------------------------------------------------ #

    # 功能：按 alarm_config 中各通道的 enable 开关，依次触发喇叭、微信、SQL 三条链路；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `req`（AlarmRequest）：`req` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/dispatcher.py` 的 `AlarmDispatcher::maybe_dispatch`
    #         调用本符号；`AiVision/tests/test_alarm_config_hot_update.py` 的
    #         `test_dispatcher_forwards_subject_metadata_to_violation_writer` 调用本符号；`AiVision/tests/test_alarm_config_hot_update.py`
    #         的 `test_dispatcher_attaches_pending_shared_evidence_video` 调用本符号；`AiVision/tests/test_alarm_config_hot_update.py` 的
    #         `test_dispatcher_respects_explicit_sql_channel_switch_and_keeps_legacy_default` 调用本符号；另有 3 处静态调用
    #   - 内部调用：`alarm.get`、`(wechat_cfg.get('parm') or
    #          {}).get`、`wechat_cfg.get`、`bool`、`isinstance`、`sql_cfg.get`、`self.evidence_recorder.start_alarm`、`logger.warning`、`horn_cfg.get`、`(horn_cfg.get('parm')
    #          or {}).get` 等共 15 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def _execute(self, req: AlarmRequest):
        """
        按 alarm_config 中各通道的 enable 开关，依次触发喇叭、微信、SQL 三条链路。

        设计原则:
            - 各通道相互独立，单个通道异常不影响其他通道执行。
            - 微信通过队列异步发送；喇叭同步调用；SQL 通过 ViolationWriter 异步入队。
            - SQL 遵循 sql.enable；旧请求未携带 sql 配置时保持原有写入行为。
        """
        alarm = req.alarm_config or {}
        alarm_record = None
        wechat_cfg = alarm.get("wechat") or {}
        wechat_user = (wechat_cfg.get("parm") or {}).get("user", "")
        should_send_wechat = bool(wechat_cfg.get("enable") and self.wechat is not None and wechat_user)
        sql_cfg = alarm.get("sql")
        should_write_sql = (
            not isinstance(sql_cfg, dict)
            or "enable" not in sql_cfg
            or bool(sql_cfg.get("enable"))
        )
        should_persist_violation = should_write_sql or should_send_wechat
        video_path = None
        if should_persist_violation and self.evidence_recorder is not None:
            try:
                video_path = self.evidence_recorder.start_alarm(
                    req.camera_key or req.camera_name,
                    req.frame,
                )
            except Exception as exc:
                logger.warning(f"[Alarm] 报警视频任务创建失败: {exc}")

        # ---- 通道 1: 喇叭（同步）----
        horn_cfg = alarm.get("horn") or {}
        if horn_cfg.get("enable"):
            # 从配置中解析喇叭 ID 与事件 ID
            horn_id  = (horn_cfg.get("parm") or {}).get("horn_id")
            event_id = (horn_cfg.get("parm") or {}).get("horn_event_id")
            horn = self.horn_dict.get(horn_id) if horn_id is not None else None
            if horn is not None and event_id is not None:
                try:
                    horn.play(event_id)
                except Exception as e:
                    logger.warning(f"[Alarm] 喇叭触发失败: {e}")

        # ---- 通道 2: SQL 持久化 ----
        # 微信图文卡片需要 alarm_id；即使独立 SQL 通道关闭也必须同步保存卡片记录。
        if should_persist_violation and self.violation_writer is not None:
            try:
                if should_send_wechat and hasattr(self.violation_writer, "save_now"):
                    alarm_record = self._write_violation(
                        self.violation_writer.save_now,
                        req,
                        video_path=video_path,
                    )
                else:
                    self._write_violation(
                        self.violation_writer.enqueue,
                        req,
                        video_path=video_path,
                    )
            except Exception as e:
                logger.warning(f"[Alarm] SQL 入队失败: {e}")

        # ---- 通道 3: 微信（异步入队）----
        if should_send_wechat:
            try:
                # put_nowait: 队列满时抛 queue.Full，记录日志后丢弃，不阻塞主流程
                self._wechat_queue.put_nowait((req, wechat_user, alarm_record))
            except queue.Full:
                logger.warning(f"[Alarm] 微信告警队列满，丢弃 {req.feature_name}")

    # 功能：向支持新字段的 writer 传通道元数据，并兼容旧式 writer 适配器；输入与输出详见下方说明
    # 参数：
    #   - `writer_method`（未显式标注）：`writer_method` 对应的业务输入值
    #   - `req`（AlarmRequest）：`req` 对应的业务输入值
    #   - `video_path`（str | None）：`video_path` 对应的业务输入值；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/dispatcher.py` 的 `AlarmDispatcher::_execute` 调用本符号
    #   - 内部调用：`str`、`inspect.signature`、`any`、`signature.parameters.values`、`values.items`、`writer_method`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    @staticmethod
    def _write_violation(
        writer_method,
        req: AlarmRequest,
        *,
        video_path: str | None = None,
    ):
        """向支持新字段的 writer 传通道元数据，并兼容旧式 writer 适配器。"""
        values = {
            "frame": req.frame,
            "violation_type": req.violation_type,
            "camera_no": req.camera_key or req.camera_name,
            "subject_type": req.subject_type or "camera",
            "subject_id": req.subject_id or str(req.camera_id),
            "subject_name": req.subject_name or req.camera_name,
            "reason": req.reason,
            "event_metadata": req.metadata,
            "video_path": video_path,
            "video_status": "pending" if video_path else None,
        }
        try:
            signature = inspect.signature(writer_method)
            accepts_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            if not accepts_kwargs:
                values = {
                    key: value
                    for key, value in values.items()
                    if key in signature.parameters
                }
        except (TypeError, ValueError):
            pass
        return writer_method(**values)

    # 功能：实现 `_alarm_card_urls` 对应的事件分发逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `alarm_id`（object | None）：`alarm_id` 对应业务对象的唯一标识
    # 返回：tuple[str, str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/dispatcher.py` 的 `AlarmDispatcher::_wechat_loop` 调用本符号；`AiVision/tests/test_wechat_news_card.py`
    #         的 `test_dispatcher_persists_card_record_when_sql_is_disabled` 调用本符号；`AiVision/tests/test_wechat_news_card.py` 的
    #         `test_dispatcher_builds_public_image_and_detail_urls` 调用本符号
    #   - 内部调用：`settings.alarm.wechat_card_base_url.rstrip`、`str`、`quote`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    def _alarm_card_urls(self, alarm_id: object | None) -> tuple[str, str]:
        if not alarm_id:
            return "", ""
        base_url = settings.alarm.wechat_card_base_url.rstrip("/")
        if not base_url:
            return "", ""
        raw_id = str(alarm_id)
        image_url = f"{base_url}/api/public/aivision/alarms/{quote(raw_id)}/image"
        detail_id = quote(f"aivision:{raw_id}", safe="")
        detail_url = f"{base_url}/?page=alarms&alarmId={detail_id}"
        return image_url, detail_url

    # 功能：微信后台发送线程的主循环（守护线程，随主进程退出自动结束）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._wechat_queue.get`、`len`、`cv2.imencode`、`logger.warning`、`self._alarm_card_urls`、`getattr`、`self.wechat.send`、`buffer.tobytes`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；会向日志系统输出运行或异常信息。
    def _wechat_loop(self):
        """
        微信后台发送线程的主循环（守护线程，随主进程退出自动结束）。

        处理流程:
            1. 阻塞等待 _wechat_queue 中的 (AlarmRequest, user) 元组。
            2. 将 frame（BGR ndarray）编码为 JPEG 字节流。
            3. 调用 WeChatNotifier.send() 推送消息与图片。

        异常处理:
            编码失败或网络异常仅记录警告日志，不中断循环，保证线程持续运行。
        """
        while True:
            item = self._wechat_queue.get()  # 阻塞直到有新任务
            if len(item) == 3:
                req, user, alarm_record = item
            else:
                req, user = item
                alarm_record = None

            if self.wechat is None:
                continue  # wechat 客户端未注入，跳过（理论上不应发生）

            try:
                # 将 BGR 帧编码为 JPEG，传输体积远小于原始 ndarray
                ok, buffer = cv2.imencode(".jpg", req.frame)
                if not ok:
                    logger.warning(f"[Alarm] 帧编码失败，跳过微信推送: {req.feature_name}")
                    continue

                image_url, detail_url = self._alarm_card_urls(getattr(alarm_record, "id", None))
                self.wechat.send(
                    feature_name=req.feature_name,
                    camera_name=req.camera_name,
                    image_jpeg_bytes=buffer.tobytes(),
                    recipients=user,
                    image_url=image_url,
                    detail_url=detail_url,
                )
            except Exception as e:
                logger.warning(f"[Alarm] 微信发送失败: {e}")


# 模块级全局单例
# 大多数场景直接 `from core.alarm import alarm_dispatcher` 使用；
# 需要独立实例时才直接实例化 AlarmDispatcher。
alarm_dispatcher = AlarmDispatcher()
