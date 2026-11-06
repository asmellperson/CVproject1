"""统一告警冷却、证据选择与喇叭、数据库、企业微信分发。

消费者负责提交已成立的业务异常，分发器按显式冷却主体控制重复通知。
喇叭和微信使用后台队列；记录通道或微信到期时保存当前告警与证据。
微信卡片使用本次保存的记录，不受独立记录通道开关和冷却的限制。
"""
from __future__ import annotations
import queue
import inspect
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from typing import Literal, Optional
from urllib.parse import quote

import numpy as np

from AiVision.core.logger import logger
from AiVision.core.settings import settings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from AiVision.alarms.devices.runtime_manager import HornRuntimeManager
from AiVision.alarms.notifications.wechat import WeChatNotifier
from AiVision.alarms.notifications.notification_image import issue_thumbnail_token
from AiVision.alarms.validation import validate_alarm_identity, validate_cooldown_identity


CooldownKey = tuple[str, str, int | None, str]


@dataclass(frozen=True)
class AlarmEvidenceRequest:
    """证据源与物理 Camera 身份分离；开放时长事件由公共 Recorder 的 token 引用。"""

    source_key: str
    mode: Literal["clip", "episode", "snapshot"] = "clip"
    episode_token: str | None = None

    def __post_init__(self) -> None:
        """校验证据源、模式和事件令牌，禁止普通片段或截图携带事件令牌。"""
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise ValueError("证据源必须是非空字符串")
        if self.mode not in ("clip", "episode", "snapshot"):
            raise ValueError("证据模式必须是 clip、episode 或 snapshot")
        if self.mode != "episode" and self.episode_token is not None:
            raise ValueError("仅完整事件可以携带 episode token")
        if self.episode_token is not None and (not isinstance(self.episode_token, str) or not self.episode_token.strip()):
            raise ValueError("episode token 必须是非空字符串")


@dataclass
class AlarmRequest:
    """
    单次告警请求的数据载体，由 Consumer 构造后提交给 AlarmDispatcher。

    字段说明:
        feature_name   : 触发告警的功能名称。
        camera_id      : 告警来源摄像头数字 ID。
        camera_name    : 摄像头展示名称，写入告警消息与数据库。
        frame          : 完整违规帧的 BGR 图像，用于录像触发；未指定 snapshot_frame 时也用于截图。
        snapshot_frame : 可选的独立截图帧，用于保存图片与微信推图，不参与录像。
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
    department: str = field(kw_only=True)
    # 冷却作用域必须明确提供，不从业务主体或摄像头推导。
    cooldown_subject_type: str = field(kw_only=True)
    cooldown_subject_id: str = field(kw_only=True)
    # 报警记录的业务主体，用于持久化和检索。
    subject_type: str = "camera"
    subject_id: str = ""                               
    subject_name: str = ""
    reason: str = ""
    metadata: dict = field(default_factory=dict)
    evidence: AlarmEvidenceRequest | None = field(default=None, kw_only=True)
    # 截图可使用业务裁剪图；frame 继续作为完整录像的触发帧。
    snapshot_frame: np.ndarray | None = field(default=None, kw_only=True, repr=False)
    on_horn_complete: Callable[[bool], None] | None = field(default=None, kw_only=True, repr=False)
    # 记录与企微可显式使用稳定范围，避免业务事件、身份或报警原因变化绕过间隔。
    notification_cooldown_subject: tuple[str, str] | None = field(default=None, kw_only=True)
    on_notification_enqueued: Callable[[str], None] | None = field(default=None, kw_only=True, repr=False)

    def __post_init__(self) -> None:
        """在请求创建时校验功能、事业部、告警类型与显式冷却身份。"""
        validate_alarm_identity(self.violation_type, self.feature_name, self.department)
        validate_cooldown_identity(self.cooldown_subject_type, self.cooldown_subject_id, self.violation_type)
        if self.notification_cooldown_subject is not None:
            scope = self.notification_cooldown_subject
            if not isinstance(scope, tuple) or len(scope) != 2:
                raise ValueError("通知冷却范围必须是明确的主体类型与标识")
            validate_cooldown_identity(scope[0], scope[1], self.violation_type)
        if self.evidence is not None and not isinstance(self.evidence, AlarmEvidenceRequest):
            raise ValueError("证据选择必须使用 AlarmEvidenceRequest")

class AlarmDispatcher:
    """
    全局告警分发器（单例）。

    职责:
        1. 冷却控制  — 同一冷却主体 × 报警类型的记录、喇叭、微信分别计时。
        2. 通道分发  — 按 alarm_config 中各通道的 enable 开关，分别调用
                       喇叭 / 微信 / SQL 三条告警链路。
        3. 异步解耦  — 微信发送通过内部队列 + 守护线程异步执行，
                       避免网络延迟阻塞主检测流程。

    生命周期:
        系统启动时由 Orchestrator 调用 configure() 注入依赖，之后各 Consumer
        通过全局单例 alarm_dispatcher.maybe_dispatch() 提交告警请求。
    """
    def __init__(self):
        # ---- 外部依赖（由 Orchestrator 通过 configure() 注入）----
        """初始化未配置依赖的分发器，以及有界微信队列和受锁冷却表。"""
        self.horn_runtime_manager: HornRuntimeManager | None = None  # 统一管理实例与异步播放
        self.wechat: Optional[WeChatNotifier] = None  # 微信推送客户端
        self.violation_writer = None                  # ViolationWriter，负责 SQL 持久化
        self.evidence_recorder = None                 # 公共报警前后视频录制器

        # 先把任务放进队列，然后另外一条线程从Queue中取消息，慢慢请求企业微信API
        self._wechat_queue: queue.Queue = queue.Queue(maxsize=100)
        self._wechat_thread: threading.Thread | None = None
        self._wechat_stop_event = threading.Event()
        self._wechat_lifecycle_lock = threading.Lock()
        self._wechat_started = False  # 防止 configure() 被重复调用时二次启动线程
        # 告警冷却表
        self._last_alarm: dict[CooldownKey, float] = {}
        self._horn_attempts: dict[tuple[str, str, int, str], object] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        horn_runtime_manager: HornRuntimeManager | None,
        wechat: Optional[WeChatNotifier],
        violation_writer,
        evidence_recorder=None,
    ):
        """
        注入运行时依赖，并启动微信后台发送线程。

        应在系统启动阶段由 Orchestrator 调用且只调用一次。
        重复调用时依赖会被覆盖，但后台线程不会重复创建（_wechat_started 守护）。
        """
        self.horn_runtime_manager = horn_runtime_manager
        self.wechat = wechat
        self.violation_writer = violation_writer
        self.evidence_recorder = evidence_recorder
        with self._wechat_lifecycle_lock:
            if self._wechat_thread is None or not self._wechat_thread.is_alive():
                self._wechat_stop_event.clear()
                self._wechat_thread = threading.Thread(
                    target=self._wechat_loop,
                    daemon=True,
                    name="alarm-wechat",
                )
                self._wechat_thread.start()
                self._wechat_started = True

    def stop(self):
        """通知微信线程停止并限时等待，仍在运行时保留已启动标志。"""
        with self._wechat_lifecycle_lock:
            self._wechat_stop_event.set()
            thread = self._wechat_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._wechat_lifecycle_lock:
            if self._wechat_thread is thread and (thread is None or not thread.is_alive()):
                self._wechat_started = False

    # ------------------------------------------------------------------ #
    #  核心入口                                                             #
    # ------------------------------------------------------------------ #

    def maybe_dispatch(
        self,
        request: AlarmRequest,
        alarm_interval: float = 5.0,
        *,
        channels: set[str] | None = None,
    ) -> bool:
        """各通道分别冷却，0 秒不额外等待；alarm_interval 控制记录及未单设的通知。

        返回是否有通道本次到期。喇叭到期不会提前触发微信或重复保存记录。
        """
        key = self._cooldown_key(request)
        alarm = request.alarm_config or {}
        intervals = {"sql": alarm_interval}
        for channel in ("horn", "wechat"):
            interval = (alarm.get(channel) or {}).get("interval")
            intervals[channel] = alarm_interval if interval is None else interval
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not isfinite(value) or value < 0 for value in intervals.values()):
            raise ValueError("报警通道间隔必须是有限的非负秒数")
        now = time.monotonic()
        due = set()
        horn_token = None
        selected = {"sql", "horn", "wechat"} if channels is None else channels
        with self._lock:
            for channel, interval in intervals.items():
                config = alarm.get(channel) or {}
                enabled = config.get("enable", channel == "sql")
                channel_key = self._channel_cooldown_key(request, channel)
                last = self._last_alarm.get(channel_key)
                if channel in selected and enabled and (last is None or now - last >= interval):
                    # 围栏语音以实际播放成功为准，失败不能消耗长周期冷却。
                    if channel != "horn" or request.on_horn_complete is None:
                        self._last_alarm[channel_key] = now
                    else:
                        horn_token = object()
                        self._horn_attempts[channel_key] = horn_token
                    due.add(channel)
        completion = self._horn_completion(request.on_horn_complete, (*key, "horn"), horn_token, now)
        if not due:
            self._cancel_episode(request)
            if completion is not None:
                completion(False)
            return False
        self._execute(request, due, on_horn_complete=completion)
        return True

    def _horn_completion(self, callback, cooldown_key, token, started_at):
        """完成通知只保留轻量回调和冷却键，不把原始告警图片留在播放队列。"""
        if callback is None:
            return None
        completed = False
        lock = threading.Lock()

        def complete(success):
            nonlocal completed
            with lock:
                if completed:
                    return
                completed = True
            with self._lock:
                # 清理或更新后的同名主体不能被旧任务的晚到回调重新加上冷却。
                if token is not None and self._horn_attempts.get(cooldown_key) is token:
                    self._horn_attempts.pop(cooldown_key, None)
                    if success:
                        self._last_alarm[cooldown_key] = started_at
            callback(bool(success))

        return complete

    def reset_cooldown(self, camera_id: int, violation_type: int) -> None:
        """清除指定摄像头与报警类型的冷却状态。"""
        self.reset_subject_cooldown("camera", str(camera_id), violation_type)

    def reset_subject_cooldown(
        self,
        cooldown_subject_type: str,
        cooldown_subject_id: str,
        violation_type: int,
    ) -> None:
        """清除指定冷却主体与报警类型的状态，不使用 SQL 业务主体。"""
        validate_cooldown_identity(cooldown_subject_type, cooldown_subject_id, violation_type)
        with self._lock:
            for channel in ("sql", "horn", "wechat"):
                self._last_alarm.pop((cooldown_subject_type, cooldown_subject_id, violation_type, channel), None)
                self._horn_attempts.pop((cooldown_subject_type, cooldown_subject_id, violation_type, channel), None)

    @staticmethod
    def _cooldown_key(request: AlarmRequest) -> tuple[str, str, int]:
        """仅使用显式冷却身份，业务主体不参与冷却范围推导。"""
        validate_cooldown_identity(request.cooldown_subject_type, request.cooldown_subject_id, request.violation_type)
        return request.cooldown_subject_type, request.cooldown_subject_id, request.violation_type

    @staticmethod
    def _channel_cooldown_key(request: AlarmRequest, channel: str) -> CooldownKey:
        """通知与喇叭分别选取冷却范围，各通道仍单独计时。"""
        if channel in {"sql", "wechat"} and request.notification_cooldown_subject is not None:
            subject_type, subject_id = request.notification_cooldown_subject
            return subject_type, subject_id, None, channel
        return (*AlarmDispatcher._cooldown_key(request), channel)

    # ------------------------------------------------------------------ #
    #  私有方法                                                             #
    # ------------------------------------------------------------------ #

    def _cancel_episode(self, req: AlarmRequest) -> None:
        """取消不再需要的完整事件证据，清理失败仅记录告警。"""
        evidence = req.evidence
        if evidence is not None and evidence.mode == "episode" and evidence.episode_token and self.evidence_recorder:
            try:
                self.evidence_recorder.cancel_episode(evidence.episode_token)
            except Exception as exc:
                logger.warning(f"[Alarm] 事件证据取消失败: {exc}")

    def _start_evidence(self, req: AlarmRequest) -> str | None:
        """按截图、固定片段或完整事件选择取证入口。

        完整事件缺少令牌时不生成替代短片，避免将不完整视频标为完整事件。
        """
        evidence = req.evidence
        if evidence is None:
            return self.evidence_recorder.start_alarm(req.camera_key or req.camera_name, req.frame)
        if evidence.mode == "snapshot":
            return None
        if evidence.mode == "episode":
            # 采集失败不能替换成普通前后片段，否则会把截短录像误称为完整事件。
            if evidence.episode_token is None:
                return None
            return self.evidence_recorder.finish_episode(evidence.episode_token)
        return self.evidence_recorder.start_alarm(evidence.source_key, req.frame)

    def _execute(self, req: AlarmRequest, channels: set[str], *, on_horn_complete=None):
        """按各通道设置提交喇叭、持久化与微信任务，并隔离通道异常。

        喇叭播放只入队；微信到期时同步保存卡片记录，其他记录异步入队。
        数据库或证据失败会记录原因，后续通道仍按各自前置条件继续处理。
        """
        # req.alarm_config就是这次检测功能的告警配置
        alarm = req.alarm_config or {}
        # 写入数据库后得到的告警记录对象
        alarm_record = None
        wechat_cfg = alarm.get("wechat") or {}             # 读取微信配置
        wechat_user = (wechat_cfg.get("parm") or {}).get("user", "")     # 微信发给谁
        # 企业微信真正可以发送，需要微信的enable为True、WeChatNotifier已经被orchestrator注入、配置接收用户
        should_send_wechat = bool("wechat" in channels and wechat_cfg.get("enable")
                                  and self.wechat is not None and wechat_user)
        sql_cfg = alarm.get("sql")
        # 满足下面三个之一就可以写入SQL(为了兼容旧配置)
        should_write_sql = "sql" in channels and (
            not isinstance(sql_cfg, dict)
            or "enable" not in sql_cfg
            or bool(sql_cfg.get("enable"))
        )
        # 企微详情和截图依赖本次记录 ID，不能因独立记录通道关闭或冷却而降为文字。
        should_persist_violation = should_write_sql or should_send_wechat
        video_path = None
        if should_persist_violation and self.evidence_recorder is not None:
            try:
                # 摄像头报警了，创建一段视频前后视频证据任务，生成的是告警视频路径
                video_path = self._start_evidence(req)
            # 各报警通道相互独立，一个失败不能拖死其他通道
            except Exception as exc:
                self._cancel_episode(req)
                logger.warning(f"[Alarm] 报警视频任务创建失败: {exc}")
        elif not should_persist_violation:
            self._cancel_episode(req)

        # ---- 通道 1: 喇叭（后台队列）----
        # 拿喇叭配置
        horn_cfg = alarm.get("horn") or {}
        if "horn" in channels and horn_cfg.get("enable"):
            # 从配置中解析喇叭 ID 与事件 ID
            horn_id  = (horn_cfg.get("parm") or {}).get("horn_id")           # 这次报警用哪一个IP喇叭报警
            event_id = (horn_cfg.get("parm") or {}).get("horn_event_id")     # 这个喇叭里面要播放哪一个预录语音事件
            # 管理器按设备 ID 查找当前有效实例，入队时不访问网络。
            if self.horn_runtime_manager is not None and horn_id is not None and event_id is not None:
                try:
                    # 后台通过HTTP请求告诉这个IP喇叭，播放指定event_id对应的预录告警语音
                    kwargs = {"on_complete": on_horn_complete} if on_horn_complete is not None else {}
                    if not self.horn_runtime_manager.enqueue_play(horn_id, event_id, **kwargs):
                        if on_horn_complete is not None:
                            on_horn_complete(False)
                        logger.warning(f"[Alarm] 喇叭 #{horn_id} 音频 #{event_id} 未入队：设备不可用、任务繁忙或队列已满")
                except Exception as e:
                    if on_horn_complete is not None:
                        on_horn_complete(False)
                    logger.warning(f"[Alarm] 喇叭 #{horn_id} 音频 #{event_id} 触发失败（{type(e).__name__}）")
            else:
                if on_horn_complete is not None:
                    on_horn_complete(False)
                logger.warning("[Alarm] 喇叭未播放：绑定缺少设备/语音任务 ID 或运行管理器未就绪")
        elif on_horn_complete is not None:
            on_horn_complete(False)

        # ---- 通道 2: SQL 持久化 ----
        # 两个通道同时到期也只保存一次；企微单独到期时保存其当前卡片所需记录。
        if should_persist_violation and self.violation_writer is not None:
            try:
                if should_send_wechat and hasattr(self.violation_writer, "save_now"):
                    alarm_record = self._write_violation(
                        self.violation_writer.save_now,                 # 微信开启时调用self.violation_writer.save_now：save_now:同步立即写数据库，并返回写好的告警ORM对象
                        req,
                        video_path=video_path,
                    )
                    record_submitted = alarm_record is not None
                # 如果不需要微信，不马上写数据库，而是把告警记录丢进后台写入队列
                else:
                    record_submitted = self._write_violation(
                        self.violation_writer.enqueue,
                        req,
                        video_path=video_path,
                    )
                if record_submitted:
                    self._notification_enqueued(req, "sql")
            # SQL失败，微信流程也要继续
            except Exception as e:
                logger.warning(f"[Alarm] SQL 入队失败: {e}")

        # ---- 通道 3: 微信（异步入队）----
        if should_send_wechat:
            try:
                # 把微信任务放到后台队列
                # put_nowait: 队列满时抛 queue.Full，记录日志后丢弃，不阻塞主流程
                self._wechat_queue.put_nowait((req, wechat_user, alarm_record))
                self._notification_enqueued(req, "wechat")
            except queue.Full:
                logger.warning(f"[Alarm] 微信告警队列满，丢弃 {req.feature_name}")

    @staticmethod
    def _notification_enqueued(req: AlarmRequest, channel: str) -> None:
        """分别确认记录与推送的提交，喇叭到期不能替其他通道标记完成。"""
        if req.on_notification_enqueued is not None:
            try:
                req.on_notification_enqueued(channel)
            except Exception as exc:
                logger.warning(f"[Alarm] {channel} 通道提交通知失败（{type(exc).__name__}）")

    @staticmethod
    def _write_violation(
        writer_method,          # 会传self.violation.save_now或者self.violation_writer.enqueue
        req: AlarmRequest,
        *,
        video_path: str | None = None,
    ):
        """向支持新字段的 writer 传通道元数据，并兼容旧式 writer 适配器。"""
        subject_type = req.subject_type or "camera"
        # 准备传给ViolationWriter的参数
        values = {
            "frame": req.snapshot_frame if req.snapshot_frame is not None else req.frame,
            "violation_type": req.violation_type,              # 违规类型编号
            "feature_name": req.feature_name,
            "department": req.department,      # 单部门历史字段
            "camera_no": None if subject_type == "logistics_channel" else (req.camera_key or req.camera_name),
            "subject_type": subject_type,
            "subject_id": (req.subject_id or str(req.camera_id)) if subject_type == "camera" else req.subject_id,
            "subject_name": req.subject_name or req.camera_name,
            "reason": req.reason,
            "event_metadata": req.metadata,                       # 额外业务信息
            "video_path": video_path,
            "video_status": "pending" if video_path else None,
        }
        try:
            # 运行时查看writer_method到底接受哪些参数
            signature = inspect.signature(writer_method)
            # 检查函数有没有**kwargs
            accepts_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            # 如果没有**kwargs，writer支持什么参数就只传什么参数
            if not accepts_kwargs:
                values = {
                    key: value
                    for key, value in values.items()
                    if key in signature.parameters
                }
        except (TypeError, ValueError):
            pass
        return writer_method(**values)

    def _alarm_card_urls(self, alarm_id: object | None, *, feature_name: str = "", department: str = "") -> tuple[str, str]:
        """根据数据库告警ID，生成企业微信卡片需要的告警截图地址和点击卡片以后进入前端告警详情页的两个网址"""
        if not alarm_id:
            return "", ""
        base_url = settings.alarm.wechat_card_base_url.rstrip("/")
        if not base_url:
            return "", ""
        raw_id = str(alarm_id)
        image_url = f"{base_url}/api/public/alarms/{quote(raw_id)}/image"
        if feature_name == "detect_human":
            image_url += "?thumbnail_token=" + issue_thumbnail_token(int(raw_id), department)
        detail_id = quote(raw_id, safe="")
        detail_url = f"{base_url}/?page=alarms&alarmId={detail_id}"
        return image_url, detail_url

    def _wechat_loop(self):
        """
        微信后台发送线程的主循环（守护线程（daemon=True），随主进程退出自动结束）。

        处理流程:
            1. 阻塞等待 _wechat_queue 中的 (AlarmRequest, user) 元组。
            2. 根据已保存的报警生成卡片 URL；人员缩略图附带短期签名。
            3. 调用 WeChatNotifier.send() 推送消息与图片。

        异常处理:
            编码失败或网络异常仅记录警告日志，不中断循环，保证线程持续运行。
        """
        while not self._wechat_stop_event.is_set():
            # 阻塞等待（队列没东西时线程睡在那里，不占CPU疯狂轮询，直到put_nowait()放一条告警进来）
            try:
                req, user, alarm_record = self._wechat_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self.wechat is None:
                continue  # wechat 客户端未注入，跳过（理论上不应发生）

            try:
                if alarm_record is None:
                    # 仅保存失败或写入器未就绪时退为文字，不能链接其他事件的旧记录。
                    logger.warning(f"[Alarm] 微信卡片记录未保存，发送文字告警: feature={req.feature_name}")
                    self.wechat.send_alarm_text(
                        violation_type=req.violation_type,
                        camera_name=req.camera_name,
                        recipients=user,
                    )
                    continue
                image_url, detail_url = self._alarm_card_urls(
                    getattr(alarm_record, "id", None), feature_name=req.feature_name, department=req.department,
                )
                # 把告警类型、摄像头、截图、接收人和卡片连接交给企业微信客户端
                self.wechat.send(
                    violation_type=req.violation_type,
                    camera_name=req.camera_name,
                    recipients=user,
                    image_url=image_url,
                    detail_url=detail_url,
                )
            except Exception as e:
                logger.warning(f"[Alarm] 微信发送失败: {e}")


# 模块级全局单例
# 大多数场景直接 `from AiVision.alarms.dispatcher import alarm_dispatcher` 使用；
# 需要独立实例时才直接实例化 AlarmDispatcher。
alarm_dispatcher = AlarmDispatcher()
