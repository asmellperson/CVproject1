# 警戒围栏大屏接口

围栏由平台管理员配置每日禁入时段、ROI 和独立白名单。大屏通过以下只读接口展示画面、运行状态和报警，不负责保存检测配置。接口直接返回 JSON 对象或数组，图片接口返回图片字节；没有 `code/data` 包装。

## 认证与接入

公共前缀为 `{服务地址}/api/external/security-fence`，完整字段可在服务的 `/docs` 或 `/openapi.json` 查看。每次请求携带一个 `X-API-Key` 请求头：

```http
GET /api/external/security-fence/cameras?department=general_electric
X-API-Key: <对接凭证>
```

凭证需要 `security_fence:read`，并明确授权所查询的事业部；平台也必须在“系统管理 → 功能分配”中为该事业部分配警戒围栏。安检读取权限不会自动授予围栏权限。平台页面使用账号登录 Cookie，不使用 API Key。

密钥由大屏的服务端或同源代理保管，从部署环境读取后附加请求头，不写入前端源码、URL 或浏览器长期存储。图片同样需要认证；浏览器 `<img>` 无法直接附加自定义请求头，应使用受控代理提供的图片地址，或由已授权请求取回 Blob 后展示。不要把密钥放在图片 URL 中。

管理员登录后，通过 `POST /api/admin/external-clients` 创建凭证，请求体例如：

```json
{
  "name": "室内围栏大屏",
  "departments": ["general_electric"],
  "scopes": ["security_fence:read"],
  "expires_at": "2027-01-01T00:00:00+08:00"
}
```

有效期必须晚于创建时间。返回 `client` 元数据和 `api_key`，明文只在创建或轮换时返回一次。沿用平台凭证管理接口查询、修改授权、停用和轮换；停用、撤权、过期和轮换在后续请求立即生效。数据库只保存密钥摘要。

## 接口目录

以下路径相对于 `/api/external/security-fence`。除 `/departments` 外，所有请求必须带 `department` 查询参数。摄像头路径只接受列表返回的 `shm_name`，拼接前进行 URL 编码，不接受显示名称或数字别名。

| 方法 | 路径 | 响应与参数 |
| --- | --- | --- |
| GET | `/departments` | `[{name, display_name}]`，只包含当前获准访问的围栏事业部 |
| GET | `/cameras` | 摄像头数组；`enabled_only=true` 默认只列摄像头和围栏均启用的设备；传 `false` 可查看该事业部全部摄像头 |
| GET | `/status` | 该事业部所有已绑定围栏摄像头的状态数组，包含停用或离线状态 |
| GET | `/cameras/{shm_name}/status` | 单个摄像头的围栏状态 |
| GET | `/cameras/{shm_name}/frame.jpg` | JPEG；`annotated=true` 默认返回标注帧，`false` 返回原始帧；`quality=85`，范围 1–100；`max_width/max_height` 可选，范围 1–4096 |
| GET | `/history` | 分页报警与原因统计，参数见下文 |
| GET | `/alarms/{alarm_id}` | 报警详情；ID 使用历史返回的字符串 |
| GET | `/alarms/{alarm_id}/image` | PNG 报警截图，按事件所属事业部授权 |

摄像头字段沿用平台：`id`、`camera_id`、`name`、`shm_name`、`department`、`enabled`、`fps`、`sort_order`、`feature_sort_orders` 和 `functions`。后两项只包含 `security_fence`；列表已按围栏排序排列，不返回 RTSP 地址。`enabled` 是配置开关，实时在线状态见 `/status`。

建议先读取事业部与摄像头，再串行轮询状态和画面；不要让上一请求未完成时继续累积相同请求。切换摄像头、离开页面或请求失败时清除旧画面及旧状态。

## 实时状态与判定

```json
{
  "camera_id": 1,
  "camera_key": "room_door",
  "camera_name": "房间入口",
  "department": "general_electric",
  "online": true,
  "state": "ready",
  "mode": "whitelist",
  "timezone": "Asia/Shanghai",
  "count": 1,
  "pending_count": 1,
  "alarm": false,
  "persons": [{
    "track_id": 1,
    "bbox": [120, 100, 340, 700],
    "in_roi": true,
    "identity": "pending",
    "person_id": null,
    "person_name": null,
    "similarity": null,
    "alarm": false,
    "reason": null
  }],
  "frame_width": 1920,
  "frame_height": 1080,
  "updated_at": "2026-10-12T04:00:00+00:00",
  "error": null
}
```

| 字段 / 值 | 含义 |
| --- | --- |
| `state=ready` | 当前检测快照有效，仍需读取各人的身份和报警状态 |
| `disabled` / `offline` | 摄像头或功能停用 / 采集离线 |
| `waiting` / `stale` | 检测尚未产出结果 / 快照超过 5 秒或已跨规则时段 |
| `error` | 人体推理、人脸推理或人员特征库异常，说明在 `error` 字段 |
| `mode=forbidden` | 当前为禁入时段，ROI 有人即形成异常时间报警，包括白名单；同时执行全库身份识别 |
| `mode=whitelist` | 其余时段，全库识别后白名单放行，确认库内非白名单或库外未知人员时形成异常人员报警 |
| `count` / `pending_count` | ROI 内人体数 / 其中待核验人数；无有效人数结果时为 `null` |
| `alarm` | 当前是否存在确定违规；无有效判定或识别异常且无确定报警时为 `null` |
| `persons` | 全画面可见轨迹；通过 `in_roi` 区分是否位于警戒区 |
| `identity=pending` | 尚无充分身份依据，既不等于白名单，也不等于非白名单 |
| `identity=allowed` / `unauthorized` | 已确认当前摄像头白名单人员 / 已确认非白名单人员 |
| `bbox` | 原始帧像素坐标 `[x1,y1,x2,y2]`，缩放叠加时使用 `frame_width/height` |
| `similarity` | 身份证据的匹配分数，不是身份正确概率 |
| `track_id` | 当前摄像头运行中的临时轨迹编号，不能用作永久人员 ID 或跨摄像头身份 |

库内身份采用与人脸身份识别相同的匹配结论，在同一可靠轨迹内累计有效观测确认，单次无人脸不清空证据。未匹配且质量不足、无脸或相似度不确定时保持待核验，不按等待时间触发身份报警；库外未知身份仍需合格的人脸质量与低相似度依据。已确认身份只在可靠连续跟踪期间保留；轨迹丢失、多人关联不明、配置变化或推理故障时重新核验。人体重叠时，唯一关联的有效人脸仍可确认身份。人脸检测独立执行，标注画面同时显示人体框和人脸框；ROI 外也可能识别人脸，但只在 ROI 内按规则报警。

禁入区间按摄像头配置时区每日重复，开始包含、结束不包含，允许跨午夜；起止相同表示全天禁入。状态轮询中断时，前端应在结果超过 5 秒后显示过期，不能持续展示上一次“无报警”为当前结论。`alarm=false` 且存在 `pending` 人员表示尚未触发报警，不代表所有人已获准进入。

## 报警历史

```http
GET /api/external/security-fence/history?department=general_electric&camera_key=room_door&start=2026-10-12T00%3A00%3A00%2B08%3A00&end=2026-10-13T00%3A00%3A00%2B08%3A00&limit=100&offset=0
X-API-Key: <对接凭证>
```

- `camera_key` 可选，使用 `shm_name`，省略查询该事业部全部围栏报警。
- `start/end` 可选，必须为带时区 ISO 8601 时间；范围为开始包含、结束不包含，开始必须早于结束。使用 `URLSearchParams` 等正确编码 `+08:00`。
- `limit` 默认 100，范围 1–500；`offset` 默认 0，不能为负。
- 返回 `{total, by_reason, items}`；统计针对完整筛选范围，不仅统计当前页，记录按时间和 ID 倒序。

单条记录包含 `id`、`camera_key`、`camera_name`、`department`、`reason`、`created_at`、`person`、`image_url`。`person` 结构同状态中的人员项，位置与违规原因来自首次报警快照；禁入报警首次身份待核验时，持续违规期间确认的身份会补全到同一记录，`id`、`created_at` 和证据不变。库外人员的 `person_id=null`、`person_name="未知人员"`；待核验人员的姓名仍为 `null`，不能当作已确认库外人员。`image_url` 是需要同一凭证授权的相对地址，`created_at` 含时区。禁止把响应中的图片路径改为平台公开截图地址来绕过鉴权。

| `reason` | 含义 | 统一报警类型 |
| --- | --- | --- |
| `forbidden_time` | 禁入时段 ROI 内有人 | 15 / `security_fence_forbidden` |
| `unauthorized` | 匹配到库内人员，但不在当前围栏白名单 | 16 / `security_fence_unauthorized` |
| `unknown_face` | 多次合格人脸均与人员库低相似度，确认库外人员 | 16 / `security_fence_unauthorized` |

历史只返回已持久化的围栏报警，不能用于统计所有进出人员。同一轨迹的持续异常只记录一次，持续报警状态仍由 `/status` 返回；离开区域、规则原因变化或轨迹重建后可以产生下一次事件。不同人员独立冷却。图片受平台证据保留策略影响，记录存在但证据过期时图片返回 404。

## 错误处理

| HTTP 状态 | 处理 |
| --- | --- |
| 400 / 422 | 查询参数、事业部编码或时间格式不正确，修正请求 |
| 401 | 缺少、错误、重复、停用、过期或已轮换的 API Key，停止重试并更新凭证 |
| 403 | 凭证缺少围栏读取权限、事业部越权或平台未分配围栏功能 |
| 404 | 摄像头 / 报警不存在、截图不存在，或请求了未提供的写入接口 |
| 503 | 视频帧或运行服务暂不可用，显示不可用并稍后重试 |

错误响应使用 FastAPI 的 `detail` 字段。有效业务数据和图片响应使用 `Cache-Control: private, no-store`。外部接口不提供配置、白名单、全局人员库、模型设置或报警处置的写入权限。
