# 安检流程规范检测外部 API

## 1. 接入约定

后端为 AiVision，默认端口 `7862`。由部署方提供实际可达的 HTTPS 服务地址。

接口前缀：`/api/external/security-inspection`。接口不含版本路径。

外部请求使用 `X-API-Key` 系统凭证，不需要人员账号登录，也不接受人员 Cookie/JWT 替代此凭证。凭证由平台管理员预先创建，可以独立禁用、轮换、设置有效期和授权范围。

| 权限 | 允许操作 |
| --- | --- |
| `security_inspection:read` | 读取事业部、摄像头、画面、状态、历史及配置 |
| `security_inspection:config:write` | 保存摄像头安检配置、读取可绑定的喇叭选项；同时要求读取权限 |

访问范围取凭证授权事业部与平台当前安检功能分配的交集。保存时校验摄像头真实归属。凭证不能访问平台账号管理、其他检测功能或全局千问设置。

### 浏览器大屏的部署

长期凭证由受控服务端或反向代理保存并注入请求头；不要写进前端源码、构建环境变量、localStorage 或图片 URL。浏览器请求大屏同源的代理路径，代理转发至 AiVision。代理必须控制访问来源和允许的方法，尤其是配置写入入口；仅隐藏密钥不等于授权访问者修改配置。代理应覆盖浏览器传来的 `X-API-Key`，并且只转发批准的安检路径。

本后端提供凭证校验和业务接口，不自动部署大屏代理。对方若只有静态页面且没有可受控的代理或统一登录设施，需要先明确部署访问控制，不能把浏览器中的长期凭证视为保密。

服务端调用示例，`AIVISION_BASE` 和 `EXTERNAL_API_KEY` 由部署环境提供：

```bash
curl --fail-with-body \
  -H "X-API-Key: ${EXTERNAL_API_KEY}" \
  "${AIVISION_BASE}/api/external/security-inspection/departments"
```

请求体使用 `Content-Type: application/json`。JSON 接口直接返回下述对象或数组；图片接口返回 JPEG。外部响应带 `Cache-Control: no-store`。

## 2. 接口目录

以下路径均相对于上述前缀。

| 方法 | 路径 | 用途 | 额外要求 |
| --- | --- | --- | --- |
| GET | `/departments` | 可访问事业部 | 读取权限 |
| GET | `/cameras` | 事业部摄像头列表 | `department` |
| GET | `/status` | 检测及模型健康状态 | `department` |
| GET | `/history` | 会话历史与统计 | `department` |
| GET | `/cameras/{shm_name}/frame.jpg` | 标注帧或绘制 ROI 的原始帧 | `department` |
| GET | `/cameras/{shm_name}/config` | 当前摄像头的完整配置 | `department` |
| PUT | `/cameras/{shm_name}/config` | 完整保存配置 | `department`、配置写权限 |
| GET | `/config-schema` | 默认配置和字段 JSON Schema | 读取权限 |
| GET | `/horns` | 可绑定的共享喇叭选项 | `department`、配置写权限 |

`department` 必须使用事业部编码。`shm_name` 必须使用摄像头列表返回的同名字段，作为 URL 路径段时使用 `encodeURIComponent`；不接受摄像头展示名称、数字 ID 或其他别名。历史筛选的 `camera_id` 使用数字主键。

## 3. 展示接口

### 3.1 事业部

`GET /departments`

返回示例：

```json
[
  {"name": "general_electric", "display_name": "通用电气事业部"}
]
```

没有当前可访问的安检事业部时返回空数组。

### 3.2 摄像头

`GET /cameras?department=general_electric&enabled_only=true`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `department` | string | 是 | 获准事业部编码 |
| `enabled_only` | boolean | 否 | 默认 `false`；`true` 只返回平台摄像头和安检功能都已启用的项 |

返回数组，单项示例：

```json
{
  "id": "inspection_a",
  "camera_id": 1,
  "name": "安检入口",
  "shm_name": "inspection_a",
  "department": "general_electric",
  "enabled": true,
  "fps": 5,
  "sort_order": 0,
  "feature_sort_orders": {"security_inspection": 0},
  "functions": {"security_inspection": true}
}
```

摄像头列表按安检功能顺序及数字 ID 排列。`enabled` 是平台设备开关，`functions.security_inspection` 是安检功能开关，都不代表摄像头当前在线。接口不返回 RTSP 地址或其他检测功能的配置。

配置页使用 `enabled_only=false` 取得尚未启用安检的现有摄像头，再通过配置的 `enable` 字段开启安检。平台设备本身关闭时，应先由平台管理员开启设备。

### 3.3 运行状态

`GET /status?department=general_electric`

```json
{
  "running": true,
  "queue": 0,
  "active": 1,
  "error": null,
  "vlm": {
    "reachable": true,
    "checking": false,
    "last_success": "2026-10-09T08:00:00Z",
    "last_error": null,
    "consecutive_failures": 0,
    "circuit_state": "closed",
    "retry_after_sec": null
  }
}
```

`queue`、`active` 是指定事业部的排队和处理中任务数量。`running` 表示安检处理器运行状态；`vlm` 是共用模型服务的健康状态。`reachable=null` 表示尚未得到可达性结论；`circuit_state` 为 `closed`、`open` 或 `half_open`。

检测未启动时，此接口仍返回 HTTP 200，包含 `running=false` 和明确的 `error`。前端应根据业务字段显示未就绪，不能仅凭 HTTP 200 显示检测正常。

### 3.4 历史及统计

`GET /history?department=general_electric&limit=20&offset=0`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `department` | string | 是 | 事业部编码 |
| `camera_id` | integer | 否 | 正整数摄像头 ID；不传则查询事业部全部历史 |
| `limit` | integer | 否 | 默认 100，范围 1～500 |
| `offset` | integer | 否 | 默认 0，必须大于等于 0 |

```json
{
  "stats": {
    "total": 12,
    "compliant": 8,
    "non_compliant": 2,
    "error": 1,
    "cancelled": 1,
    "rate": 80.0
  },
  "items": [
    {
      "session_id": "example-session",
      "camera_id": 1,
      "camera_name": "安检入口",
      "roi_name": "security_staff_1",
      "started_at": "2026-10-09T16:00:00",
      "ended_at": "2026-10-09T16:00:10",
      "duration_sec": 10.0,
      "status": "non_compliant",
      "verdict": {"compliant": false, "confidence": 0.92, "reason": "安检动作不完整"},
      "error": null,
      "latency_sec": 2.5
    }
  ]
}
```

- `stats` 覆盖事业部及可选摄像头的全部匹配历史，不受分页影响。
- `total` 包含四种状态；`rate = compliant / (compliant + non_compliant) × 100`，保留一位小数，没有成功判定时为 0。
- `status`：`compliant` 合规、`non_compliant` 不合规、`error` 判定失败、`cancelled` 已取消。失败和取消不应显示为不合规。
- `verdict`、`error`、`latency_sec` 可为空；摄像头删除后历史保留，`camera_id` 可为空。
- 按 `started_at` 降序排列，相同时间按 `session_id` 排列。`started_at`、`ended_at` 沿用后端本地时间，无时区后缀；部署时应约定服务器时区，前端不要擅自追加 `Z`。
- 本接口不提供日期筛选或每日趋势，累计数不能标注为“今日数量”。不支持的查询参数不能用于改变统计口径。

### 3.5 实时画面与 ROI 底图

`GET /cameras/inspection_a/frame.jpg?department=general_electric&max_width=1280`

| 参数 | 类型 | 默认值 / 范围 |
| --- | --- | --- |
| `department` | string | 必填 |
| `annotated` | boolean | 默认 `true` 返回安检标注帧；`false` 返回原始帧，供 ROI 绘制使用 |
| `quality` | integer | 默认 85，范围 1～100 |
| `max_width` | integer | 可选，范围 1～4096 |
| `max_height` | integer | 可选，范围 1～4096 |

响应为 `Content-Type: image/jpeg` 的单张图片，保持画面比例。它不是 RTSP、HLS 或连续视频流。

建议沿用平台刷新节奏：画面约每 500 毫秒请求一次，状态和统计约每 2 秒刷新一次；上一轮完成后再发下一轮，避免慢请求堆积。页面卸载时取消请求，替换 Blob URL 时调用 `URL.revokeObjectURL`。

画面不存在返回 404；画面过期或运行时未就绪可能返回 503。前端应显示等待画面或离线状态。

## 4. 配置读写

### 4.1 读取配置

`GET /cameras/inspection_a/config?department=general_electric`

响应结构：

```json
{
  "camera": {"id": 1, "name": "安检入口", "shm_name": "inspection_a", "enable": true},
  "feature": "security_inspection",
  "config": {
    "enable": true,
    "value": {
      "staff_rois": {"security_staff_1": [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8], [0.1, 0.8]]},
      "cap_interval": 0.1,
      "alarm_interval": 30.0,
      "conf": 0.35,
      "iou": 0.6,
      "imgsz": 640,
      "pair_start_hold_frames": 8,
      "fingerprint_lost_seconds": 3.0,
      "no_interact_seconds": 4.0,
      "max_session_seconds": 90.0,
      "keyframe_interval_sec": 0.6,
      "keyframes_per_session": 8,
      "roi_crop_padding": 100,
      "fp_match_threshold": 0.55,
      "interact_distance_max_ratio": 1.5,
      "interact_motion_min_pixels": 8.0,
      "roi_enter_overlap_ratio": 0.3,
      "roi_hold_overlap_ratio": 0.1
    },
    "alarm": {
      "sql": {"enable": false, "parm": {}},
      "horn": {"enable": false, "parm": {"horn_id": null, "horn_event_id": null}},
      "wechat": {"enable": false, "parm": {"user": ""}}
    }
  }
}
```

`camera.enable` 是平台摄像头状态；`config.enable` 是此摄像头的安检功能状态。没有已保存的安检配置时返回完整默认配置，安检默认关闭。

### 4.2 保存配置

`PUT /cameras/inspection_a/config?department=general_electric`

请求体是 GET 返回的**完整 `config` 对象**，不包含外层 `camera`、`feature` 或额外 `config` 包装。所有配置字段及报警通道子字段均应保留，JSON 数字和布尔值不能改为字符串。缺少字段、增加未知字段或字段格式不合法返回 422。

成功返回 HTTP 200，结构与读取配置一致。使用响应中的 `config` 刷新表单；保存复用平台数据库事务，并重新加载缓存、发布配置事件。原有前端重新读取后会看到相同配置。多个客户端并发保存采用完整配置覆盖，编辑前应读取最新配置并协调操作，接口没有配置版本号冲突检测。

如果保存返回 5xx，可能是数据库已经提交、后续缓存刷新或事件处理失败。应先重新读取配置并核对状态，再决定是否重试，不能把错误响应直接解释为数据库已回滚。

通过同源受控代理调用的浏览器示例：

```js
const base = '/api/external/security-inspection';
const query = new URLSearchParams({ department: 'general_electric' });
const path = `${base}/cameras/${encodeURIComponent(camera.shm_name)}/config?${query}`;

const loaded = await fetch(path, { cache: 'no-store' });
if (!loaded.ok) throw new Error(await loaded.text());
const { config } = await loaded.json();

config.value.conf = 0.4;
const response = await fetch(path, {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(config),
});
if (!response.ok) throw new Error(await response.text());
const saved = await response.json();
// 使用 saved.config 更新表单；系统凭证由代理注入。
```

### 4.3 ROI 规则

`value.staff_rois` 是“工位名称 → 多边形顶点数组”的映射：

- 顶点为 `[x, y]`，两者范围均为 0～1，相对于完整摄像头画面宽高归一化。
- 绘制界面应扣除图片留白和缩放偏移，再计算相对坐标，不能直接提交屏幕像素。
- 每台摄像头最多 16 个工位；名称为 1～100 个字符，不含首尾空白。
- 每个工位 3～64 个顶点，面积必须大于零，不允许自交或重叠边。
- 删除所有工位提交 `{}`；不能保留顶点为空的工位。没有工位时无法形成工位安检会话。

### 4.4 检测参数

`GET /config-schema` 返回 `feature`、`default_config` 和 `config_schema`，供表单获取默认值及字段限制。保存时仍需要提交完整配置。

| `value` 字段 | 含义 | 范围 / 约束 |
| --- | --- | --- |
| `cap_interval` | 检测间隔，秒 | 0.05～5 |
| `alarm_interval` | 报警间隔，秒 | 0～86400 |
| `conf` | 人体检测置信度 | 大于 0，且不超过 1 |
| `iou` | 检测框重叠阈值 | 大于 0，且不超过 1 |
| `imgsz` | 推理输入尺寸 | 整数，160～1920，32 的倍数 |
| `pair_start_hold_frames` | 配对持续帧数 | 整数，1～300 |
| `fingerprint_lost_seconds` | 人员丢失结束时间，秒 | 大于 0，且不超过 60 |
| `no_interact_seconds` | 停止交互结束时间，秒 | 大于 0，且不超过 60 |
| `max_session_seconds` | 会话最长时间，秒 | 1～600 |
| `keyframe_interval_sec` | 关键帧间隔，秒 | 0.1～30，且小于会话最长时间 |
| `keyframes_per_session` | 关键帧数量上限 | 整数，2～32 |
| `roi_crop_padding` | 关键帧外扩距离，像素 | 整数，0～1000 |
| `fp_match_threshold` | 人员指纹匹配阈值 | 0～1 |
| `interact_distance_max_ratio` | 交互距离与身高比上限 | 大于 0.2，且不超过 10 |
| `interact_motion_min_pixels` | 交互最小位移，像素 | 0～1000 |
| `roi_enter_overlap_ratio` | 进入工位重叠比例 | 0～1 |
| `roi_hold_overlap_ratio` | 保持工位重叠比例 | 0～1，且不大于进入比例 |

### 4.5 报警配置

三种通道分别使用 `alarm.sql`、`alarm.horn`、`alarm.wechat` 的 `enable` 和 `parm`。

- SQL：`parm` 为 `{}`，控制违规告警入库；安检会话历史由安检服务独立保存。
- 企业微信：启用时 `parm.user` 必须非空，接收对象由平台管理员提供。
- 喇叭：启用时必须绑定存在且启用的 `horn_id`，并填写有效的正整数 `horn_event_id`；两项 ID 上限均为 2147483647。语音任务 ID 由设备管理员提供。
- 喇叭与微信通知还受平台全局通道开关及部署配置影响，保存配置不等于已经发送或播放。

`GET /horns?department=general_electric` 返回共享喇叭的绑定选项：

```json
[{"id": 1, "name": "入口喇叭", "enable": true}]
```

该接口要求配置写权限，不返回设备地址、账号或密码，也不提供设备控制和创建操作。

## 5. 错误处理

| HTTP 状态 | 含义与处理 |
| --- | --- |
| 400 | 事业部编码或业务配置不合法，检查 `detail` |
| 401 | 缺少凭证，或凭证错误、过期、被禁用、已轮换；联系凭证维护方 |
| 403 | 没有对应事业部、功能或写权限；不要持续重试写入 |
| 404 | 摄像头不存在、标识不匹配，或当前画面尚不可用 |
| 409 | 保存过程中摄像头归属发生变化，重新读取资源和权限 |
| 422 | 参数类型、范围、ROI 或完整配置校验失败 |
| 500 | 服务内部错误；保存操作需重新读取核对结果 |
| 503 | 运行时或画面不可用，提示未就绪并延后重试 |

业务错误响应形如 `{"detail":"错误原因"}`；参数校验错误的 `detail` 为错误数组，包含 `loc`、`msg`、`type` 等字段。前端不能假定 `detail` 总是字符串。

## 6. 平台管理员：凭证管理

本节接口由平台管理员使用现有人员登录会话调用。外部大屏不调用这些管理接口，也不需要平台管理员账号。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/external-clients` | 凭证元数据列表，隐藏密钥及摘要 |
| POST | `/api/admin/external-clients` | 创建，返回一次性明文密钥 |
| PUT | `/api/admin/external-clients/{id}` | 完整更新授权信息 |
| PUT | `/api/admin/external-clients/{id}/enabled` | 单独停用或启用 |
| POST | `/api/admin/external-clients/{id}/rotate` | 轮换密钥，旧密钥立即失效 |

创建请求示例，`expires_at` 必须替换为计划中的未来时间，且包含时区：

```json
{
  "name": "综合安防大屏",
  "departments": ["general_electric"],
  "scopes": ["security_inspection:read", "security_inspection:config:write"],
  "expires_at": "2026-12-31T15:59:59Z"
}
```

创建成功为 HTTP 201，响应为 `{"client": {...}, "api_key": "<一次性明文密钥>"}`。保存明文后交由受控代理配置；后端仅保存摘要，不能找回原文。轮换返回相同结构，保留当前停用状态、有效期和授权范围，不会自动续期或启用。

更新授权提交创建请求中的全部字段以及 `enabled`。单独启停提交 `{"enabled":false}` 或 `{"enabled":true}`。启用过期凭证不会延长有效期。

元数据字段为 `id/name/departments/scopes/enabled/expires_at/created_by/created_at/updated_at`。时间按 UTC 返回。`scopes` 默认只读，不允许未知权限、重复权限或只有写权限；事业部不接受 `all` 或通配符。

数据库表为 `auth_external_clients`。正式启动的 `bootstrap_database()` 会创建缺失表并核验结构；也可由数据库管理员执行 `AiVision/migrations/external_clients_20261009.sql`。代码发布不等于现场数据库和代理已经部署完成。

## 7. 联调顺序

1. 部署方启动 AiVision、准备有效凭证并配置受控代理；确保授权事业部已经分配安检功能。
2. 读取 `/departments` 和 `/cameras`，确认实际编码与摄像头标识。
3. 对接 `/status`、`/history` 和图片刷新，正确区分未就绪、合规、不合规及执行失败。
4. 读取 `/config-schema` 和摄像头配置，用原始帧绘制 ROI，完整提交配置并回读核对。
5. 在现场验证真实画面、检测判定和实际报警渠道。平板、大屏布局及触摸交互由前端实现。

运行实例的 `/docs` 中，`external-security-inspection` 标签提供交互式接口说明；`ExternalApiKey` 安全方案对应 `X-API-Key`。完整接口契约可从 `/openapi.json` 获取。
