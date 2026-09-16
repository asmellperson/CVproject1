"""
alarms/dispatcher.py
统一告警分发器 — 把"判断该不该告警 + 触发哪些通道"从 Consumer 里抽出来。
consumer只负责"我检测到了违规"。AlarmDispatcher负责:这个违规应该怎么样报警
流程:
    Consumer检测到违规->构造AlarmRequest -> alarm_dispatcher.maybe_dispatch()->cooldown_key()确定谁是哪一种告警 -> 检查冷却 -> execute()【创建告警视频任务->同步触发IP喇叭-> violationwriter有微信save_now,没微信enqueue,wechat queue->_wechat_loop()->JPEG编码->生成告警URL->wechatnotifier.send()】
"""
from __future__ import annotations
import queue
import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import numpy as np

from AiVision.core.logger import logger
from AiVision.core.settings import settings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from AiVision.alarms.devices.runtime_manager import HornRuntimeManager
from AiVision.alarms.notifications.wechat import WeChatNotifier
from AiVision.alarms.notifications.notification_image import issue_thumbnail_token
from AiVision.alarms.validation import validate_alarm_identity


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
    department: str = field(kw_only=True)
    # ====== 为了支持物流通道 ========
    subject_type: str = "camera"
    subject_id: str = ""                               
    subject_name: str = ""
    reason: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_alarm_identity(self.violation_type, self.feature_name, self.department)

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
    def __init__(self):
        # ---- 外部依赖（由 Orchestrator 通过 configure() 注入）----
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
        self._last_alarm: dict[tuple[str, str, str], float] = {}
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
    ) -> bool:
        """
        收到违规生成cooldown key查看上次报警事件，还在五秒人冷却不报警，超过五秒冷却时间就更新时间并且推送报警
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
        # 给这个告警生成一个冷却标识（生成谁发生了告警、这个对象是谁什么检测功能等）
        key = self._cooldown_key(request)
        now = time.time()

        with self._lock:
            last = self._last_alarm.get(key, 0.0)
            if now - last < alarm_interval:
                return False          # 冷却期内，跳过
            self._last_alarm[key] = now  # 更新时间戳，占位防并发重入
        # 报警冷却时间已过，真正执行告警
        self._execute(request)
        return True

    def reset_cooldown(self, camera_id: int, feature_name: str) -> None:
        """清除指定摄像头和功能的告警冷却状态。
        reset_cooldown:只针对camera
        reset_subject_cooldown:camera、logistics_channel等都能用
        """
        self.reset_subject_cooldown("camera", str(camera_id), feature_name)

    def reset_subject_cooldown(
        self,
        subject_type: str,
        subject_id: str,
        feature_name: str,
    ) -> None:
        """清除摄像头或通道主体的告警冷却状态。"""
        with self._lock:
            # 从字典里删除这个key
            self._last_alarm.pop((subject_type, str(subject_id), feature_name), None)

    @staticmethod
    def _cooldown_key(request: AlarmRequest) -> tuple[str, str, str]:
        """从ALarmRequest提取告警主体 + 主体ID + 检测功能得到唯一冷却标识"""
        subject_type = request.subject_type or "camera"
        subject_id = request.subject_id or str(request.camera_id)
        return subject_type, subject_id, request.feature_name

    # ------------------------------------------------------------------ #
    #  私有方法                                                             #
    # ------------------------------------------------------------------ #

    def _execute(self, req: AlarmRequest):
        """
        按 alarm_config 中各通道的 enable 开关，依次触发喇叭、微信、SQL 三条链路。
        读取alarm配置，判断微信是否可发送，判断SQL是否需要保存，判断是否需要告警证据录像
        EvidenceRecorder.start_aralm(),horn.play(),SQL(有微信save_now(),没有微信enqueue()),wechat(put_nowait()后台线程发送)


        设计原则:
            - 各通道相互独立，单个通道异常不影响其他通道执行。
            - 微信通过队列异步发送；喇叭同步调用；SQL 通过 ViolationWriter 异步入队。
            - SQL 遵循 sql.enable；旧请求未携带 sql 配置时保持原有写入行为。
        """
        # req.alarm_config就是这次检测功能的告警配置
        alarm = req.alarm_config or {}
        # 写入数据库后得到的告警记录对象
        alarm_record = None
        wechat_cfg = alarm.get("wechat") or {}             # 读取微信配置
        wechat_user = (wechat_cfg.get("parm") or {}).get("user", "")     # 微信发给谁
        # 企业微信真正可以发送，需要微信的enable为True、WeChatNotifier已经被orchestrator注入、配置接收用户
        should_send_wechat = bool(wechat_cfg.get("enable") and self.wechat is not None and wechat_user)
        sql_cfg = alarm.get("sql")
        # 满足下面三个之一就可以写入SQL(为了兼容旧配置)
        should_write_sql = (
            not isinstance(sql_cfg, dict)
            or "enable" not in sql_cfg
            or bool(sql_cfg.get("enable"))
        )
        # SQL关闭微信开启也要数据库告警记录
        should_persist_violation = should_write_sql or should_send_wechat
        video_path = None
        if should_persist_violation and self.evidence_recorder is not None:
            try:
                # 摄像头报警了，创建一段视频前后视频证据任务，生成的是告警视频路径
                video_path = self.evidence_recorder.start_alarm(
                    req.camera_key or req.camera_name,                  # 哪一路视频发生的告警
                    req.frame,
                )
            # 各报警通道相互独立，一个失败不能拖死其他通道
            except Exception as exc:
                logger.warning(f"[Alarm] 报警视频任务创建失败: {exc}")

        # ---- 通道 1: 喇叭（后台队列）----
        # 拿喇叭配置
        horn_cfg = alarm.get("horn") or {}
        if horn_cfg.get("enable"):
            # 从配置中解析喇叭 ID 与事件 ID
            horn_id  = (horn_cfg.get("parm") or {}).get("horn_id")           # 这次报警用哪一个IP喇叭报警
            event_id = (horn_cfg.get("parm") or {}).get("horn_event_id")     # 这个喇叭里面要播放哪一个预录语音事件
            # 管理器按设备 ID 查找当前有效实例，入队时不访问网络。
            if self.horn_runtime_manager is not None and horn_id is not None and event_id is not None:
                try:
                    # 后台通过HTTP请求告诉这个IP喇叭，播放指定event_id对应的预录告警语音
                    if not self.horn_runtime_manager.enqueue_play(horn_id, event_id):
                        logger.warning(f"[Alarm] 喇叭 #{horn_id} 未播放：设备已停用、不存在或运行服务暂不可用")
                except Exception as e:
                    logger.warning(f"[Alarm] 喇叭触发失败: {e}")
            else:
                logger.warning("[Alarm] 喇叭未播放：绑定缺少设备/语音任务 ID 或运行管理器未就绪")

        # ---- 通道 2: SQL 持久化 ----
        # 没微信：SQL记录入queue，异步写，性能优先。有微信：必须拿alarm_id,save_now,同步写得到record.id,微信卡片
        # 微信图文卡片需要 alarm_id；即使独立 SQL 通道关闭也必须同步保存卡片记录。
        # 这次需要保存告警记录，并且ViolationWriter有用
        if should_persist_violation and self.violation_writer is not None:
            try:
                if should_send_wechat and hasattr(self.violation_writer, "save_now"):
                    alarm_record = self._write_violation(
                        self.violation_writer.save_now,                 # 微信开启时调用self.violation_writer.save_now：save_now:同步立即写数据库，并返回写好的告警ORM对象
                        req,
                        video_path=video_path,
                    )
                # 如果不需要微信，不马上写数据库，而是把告警记录丢进后台写入队列
                else:
                    self._write_violation(
                        self.violation_writer.enqueue,
                        req,
                        video_path=video_path,
                    )
            # SQL失败，微信流程也要继续
            except Exception as e:
                logger.warning(f"[Alarm] SQL 入队失败: {e}")

        # ---- 通道 3: 微信（异步入队）----
        if should_send_wechat:
            try:
                # 把微信任务放到后台队列
                # put_nowait: 队列满时抛 queue.Full，记录日志后丢弃，不阻塞主流程
                self._wechat_queue.put_nowait((req, wechat_user, alarm_record))
            except queue.Full:
                logger.warning(f"[Alarm] 微信告警队列满，丢弃 {req.feature_name}")

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
            "frame": req.frame,                                # 违规截图
            "violation_type": req.violation_type,              # 违规类型编号
            "feature_name": req.feature_name,
            "department": req.department,      # 单部门历史字段
            "camera_no": (req.camera_key or req.camera_name) if subject_type == "camera" else None,   # 不强行填camera_no
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
        detail_id = quote(f"aivision:{raw_id}", safe="")
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
                image_url, detail_url = self._alarm_card_urls(
                    getattr(alarm_record, "id", None), feature_name=req.feature_name, department=req.department,
                )
                # 把告警类型、摄像头、截图、接收人和卡片连接交给企业微信客户端
                self.wechat.send(
                    feature_name=req.feature_name,
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
