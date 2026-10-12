# 安检流程规范检测接口对接说明

这组接口用于展示摄像头安检画面、安检结果和合规统计，以及修改检测区域、检测参数和报警设置。

## 1. 如何调用

调用接口需要以下信息：

| 内容 | 用途 |
| --- | --- |
| 接口地址 `API_BASE` | 所有接口的公共地址，已包含 `/api/external/security-inspection` |
| 调用凭证 `API_KEY` | 调用接口时放在请求头 `X-API-Key` 中 |
| 在线文档地址 | [http://172.16.0.32:7862/docs](http://172.16.0.32:7862/docs)，在浏览器中打开，可查看字段和调试接口 |

### 访问地址

以下为完整访问地址：

| 用途 | HTTP 地址 |
| --- | --- |
| 在线接口文档（浏览器打开） | [http://172.16.0.32:7862/docs](http://172.16.0.32:7862/docs) |
| 业务接口公共地址 `API_BASE` | `http://172.16.0.32:7862/api/external/security-inspection` |
| 获取事业部列表的完整请求地址 | `http://172.16.0.32:7862/api/external/security-inspection/departments` |

`/docs` 接在服务地址后面，不接在 `API_BASE` 后面。

后续示例中的 `{API_BASE}` 替换为 `http://172.16.0.32:7862/api/external/security-inspection`，`{API_KEY}` 替换为后端提供的调用凭证。**不需要调用账号登录接口。** 修改配置需要开通配置修改权限，对接时说明需要修改配置即可。

例如，获取事业部列表的请求是：

```http
GET {API_BASE}/departments
X-API-Key: {API_KEY}
```

保存配置时增加请求头：

```http
Content-Type: application/json
```

除画面接口返回 JPEG 图片外，其余接口直接返回 JSON 对象或数组，没有统一的 `code`、`data` 外层包装。

### 页面与接口的对应关系

以下路径都接在 `API_BASE` 后面。

| 页面要做什么 | 请求方式 | 接口路径 |
| --- | --- | --- |
| 获取事业部选项 | GET | `/departments` |
| 获取所选事业部的摄像头 | GET | `/cameras` |
| 显示摄像头画面 | GET | `/cameras/{shm_name}/frame.jpg` |
| 显示安检记录、合规数量和合规率 | GET | `/history` |
| 获取不合规记录的抓拍图像 | GET | `/history/{session_id}/image.jpg` |
| 显示检测运行状态 | GET | `/status` |
| 打开配置表单，读取当前配置 | GET | `/cameras/{shm_name}/config` |
| 保存检测开关、区域、参数和报警设置 | PUT | `/cameras/{shm_name}/config` |
| 获取配置默认值和字段限制 | GET | `/config-schema` |
| 获取报警喇叭选项 | GET | `/horns` |

建议先完成事业部和摄像头选择，再对接画面、记录和统计，最后对接配置表单。

## 2. 获取事业部列表

事业部用于对摄像头分组。先取得列表，再把选中项的 `name` 作为后续请求的 `department` 参数。

```http
GET {API_BASE}/departments
X-API-Key: {API_KEY}
```

返回示例：

```json
[
  {
    "name": "general_electric",
    "display_name": "通用电气事业部"
  }
]
```

| 字段 | 类型 | 前端怎么用 |
| --- | --- | --- |
| `name` | string | 请求其他接口时传给 `department`，不要传中文名称 |
| `display_name` | string | 页面显示的事业部名称 |

返回空数组 `[]` 时，显示“暂无可用事业部”。示例中的编码仅用于说明，实际使用接口返回的值。

## 3. 获取摄像头列表

用于摄像头选择、画面卡片列表和配置页的摄像头选择。

```http
GET {API_BASE}/cameras?department=general_electric&enabled_only=true
X-API-Key: {API_KEY}
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `department` | string | 是 | 上一步选中事业部的 `name` |
| `enabled_only` | boolean | 否 | 默认 `false`；传 `true` 只返回摄像头和安检检测都已启用的项 |

展示页可传 `enabled_only=true`。配置页传 `enabled_only=false`，这样也能选到尚未开启安检的摄像头。

返回示例：

```json
[
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
]
```

| 字段 | 类型 | 含义 / 用法 |
| --- | --- | --- |
| `id` | string | 摄像头列表项标识，可用作组件的 `key` |
| `camera_id` | integer | 摄像头数字 ID，按摄像头查询安检记录时使用 |
| `name` | string | 摄像头显示名称 |
| `shm_name` | string | 请求画面、读取配置、保存配置时使用的摄像头标识 |
| `department` | string | 摄像头所属事业部编码 |
| `enabled` | boolean | 摄像头是否启用，不代表当前是否在线 |
| `fps` | number / null | 摄像头配置的帧率，不作为页面刷新频率 |
| `sort_order` | integer | 摄像头排序值 |
| `feature_sort_orders.security_inspection` | integer | 安检展示排序值，越小越靠前 |
| `functions.security_inspection` | boolean | 是否开启安检检测 |

接口已经按安检展示顺序排列，可以直接按返回顺序展示。空数组表示没有符合条件的摄像头。

**注意两个标识的用途：** `/history` 的 `camera_id` 用数字 `1`；画面和配置路径中的 `{shm_name}` 用字符串 `inspection_a`。不要把摄像头中文名称放进路径。拼接路径时，对 `shm_name` 使用 `encodeURIComponent()`；查询参数用 `URLSearchParams` 编码。

## 4. 显示摄像头画面

该接口每次返回一张当前画面的 JPEG 图片。连续刷新图片即可展示实时画面。

```http
GET {API_BASE}/cameras/inspection_a/frame.jpg?department=general_electric&annotated=true&max_width=1280
X-API-Key: {API_KEY}
```

| 参数 | 类型 | 必填 | 默认值 / 说明 |
| --- | --- | --- | --- |
| `department` | string | 是 | 所选摄像头所属事业部编码 |
| `annotated` | boolean | 否 | 默认 `true`，返回带检测标注的画面；`false` 返回原始画面 |
| `quality` | integer | 否 | JPEG 图片质量，默认 85，范围 1～100 |
| `max_width` | integer | 否 | 返回图片最大宽度，范围 1～4096 像素 |
| `max_height` | integer | 否 | 返回图片最大高度，范围 1～4096 像素 |

成功返回 HTTP 200，`Content-Type: image/jpeg`，响应体是图片二进制，缩放时保持原图比例。

- 大屏展示使用 `annotated=true`。
- 绘制检测区域使用 `annotated=false`，避免检测标注遮挡底图。
- 图片不能调用 `response.json()`，应使用 `response.blob()`，再通过 `URL.createObjectURL()` 赋给图片元素。
- 直接请求时需要携带 `X-API-Key` 请求头，普通 `<img src="接口地址">` 不能设置这个请求头。
- 可以在上一次请求完成后，间隔约 500 毫秒请求下一张；不要让未完成的请求不断堆积。替换图片时释放旧的 Blob URL，离开页面时停止刷新。

本接口返回连续刷新的单张图片，不提供视频播放地址。返回 404 时可以显示“等待画面”；返回 503 时显示“画面暂不可用”，稍后重试。

## 5. 获取安检记录和统计

一次安检过程对应一条记录。这个接口同时提供最近 31 天的统计卡片数据和记录列表，按安检开始时间计算滚动窗口。

```http
GET {API_BASE}/history?department=general_electric&limit=20&offset=0
X-API-Key: {API_KEY}
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `department` | string | 是 | 事业部编码 |
| `camera_id` | integer | 否 | 摄像头列表中的 `camera_id`，必须大于 0；不传则查询该事业部全部摄像头 |
| `limit` | integer | 否 | 每页条数，默认 100，范围 1～500 |
| `offset` | integer | 否 | 跳过的记录数，默认 0，必须大于等于 0 |

例如，每页 20 条时，第一页传 `offset=0`，第二页传 `offset=20`，第三页传 `offset=40`。

返回示例：

```json
{
  "retention_days": 31,
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
      "verdict": {
        "compliant": false,
        "confidence": 0.92,
        "reason": "安检动作不完整"
      },
      "error": null,
      "latency_sec": 2.5,
      "has_image": true
    }
  ]
}
```

### 统计卡片怎么取值

| 字段 | 页面含义 |
| --- | --- |
| `stats.total` | 安检记录总数，包含合规、不合规、判定失败和已取消 |
| `stats.compliant` | 合规次数 |
| `stats.non_compliant` | 不合规次数 |
| `stats.error` | 判定失败次数 |
| `stats.cancelled` | 已取消次数 |
| `stats.rate` | 合规率，`80.0` 显示为 `80.0%`，不要再乘 100 |

合规率计算方式：`合规次数 ÷（合规次数 + 不合规次数）× 100`，保留一位小数；没有成功判定的记录时为 `0`。

**统计和列表采用同一滚动保留窗口，默认最近 31 天，不是自然月或全部历史。** `retention_days` 返回实际保留天数；翻页只影响 `items`，不影响 `stats`。接口没有自定义日期筛选和每日趋势数据。

### 记录列表怎么展示

| 字段 | 类型 | 页面含义 |
| --- | --- | --- |
| `session_id` | string | 记录唯一标识，可用作列表 `key` |
| `camera_id` | integer / null | 摄像头数字 ID；历史对应的摄像头被删除后可能为空 |
| `camera_name` | string | 摄像头名称 |
| `roi_name` | string | 发生安检的工位名称，对应配置中的检测区域名称 |
| `started_at` | string | 安检开始时间 |
| `ended_at` | string | 安检结束时间 |
| `duration_sec` | number | 安检持续时长，单位秒 |
| `status` | string | 安检结果状态，见下表 |
| `verdict` | object / null | AI 判定结果；为空时不要访问它的子字段 |
| `verdict.compliant` | boolean | `true` 表示合规，`false` 表示不合规 |
| `verdict.confidence` | number | 判定置信度，范围 0～1，例如 `0.92` 可显示为 `92%` |
| `verdict.reason` | string | 判定原因，可直接显示在详情或结果说明中 |
| `error` | string / null | 判定失败时的错误信息 |
| `latency_sec` | number / null | AI 判定耗时，单位秒，不是安检持续时长 |
| `has_image` | boolean | 是否有数据库抓拍图像，列表响应不携带图片二进制 |

| `status` | 建议显示文字 |
| --- | --- |
| `compliant` | 合规 |
| `non_compliant` | 不合规 |
| `error` | 判定失败 |
| `cancelled` | 已取消 |

失败和取消不能计入“不合规”。没有记录时 `items` 为 `[]`。记录按开始时间从新到旧返回。

`started_at` 和 `ended_at` 是不带时区后缀的时间，例如 `2026-10-09T16:00:00`。页面可显示为 `2026-10-09 16:00:00`；不要自行追加 `Z` 当作 UTC 时间转换。

展示页可在上一次请求完成后，间隔约 2 秒刷新一次统计和第一页记录。

### 获取不合规抓拍图像

```http
GET {API_BASE}/history/{session_id}/image.jpg?department=general_electric
X-API-Key: {API_KEY}
```

仅当 `has_image=true` 时请求，`session_id` 应进行 URL 编码。成功返回 JPEG 二进制和 `Cache-Control: no-store`；不存在、过期或指定事业部内找不到图片时返回 404。请求未授权事业部返回 403。外部前端可通过受控后端代理，或带请求头获取 Blob 后展示；普通 `<img>` 不能设置 API Key。

图像是该次安检关键帧拼图，与不合规 session 在同一事务保存，报警冷却或通知开关不影响留存。已有历史原图不存在时 `has_image=false`，应显示“无留存图片”。

### 数据库只读对接

受控后端也可使用授权的只读数据库连接，自行筛选事业部和最近 31 天。统计以 `ai_security_inspection_session` 为准，具体原因取 JSON 字段 `verdict.reason`，时长为 `ended_at - started_at`；总量包含四种状态，合规率分母只含合规与不合规。查询的本地时区须与服务一致。

不合规明细筛选 `status='non_compliant'`，按 `session_id` 左关联 `ai_security_inspection_session_image`；`image_data` 是 JPEG 字节，`media_type` 是 `image/jpeg`。先分页查询文字和是否有图，再按需读取单条图片，避免列表一次加载大量 BLOB。过滤条件使用 `started_at >= NOW() - INTERVAL 31 DAY`，不要依赖每小时清理任务恰好已经执行。

## 6. 获取检测运行状态

用于显示“运行中”“未就绪”和待处理任务数量。

```http
GET {API_BASE}/status?department=general_electric
X-API-Key: {API_KEY}
```

查询参数 `department` 必填，使用事业部编码。

返回示例：

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

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `running` | boolean | 检测服务是否运行，不代表每个摄像头都在线 |
| `queue` | integer | 所选事业部等待判定的任务数 |
| `active` | integer | 所选事业部正在判定的任务数，不是画面人数 |
| `error` | string / null | 当前错误信息，无错误时为 `null` |
| `vlm` | object | AI 判定服务的状态信息 |
| `vlm.reachable` | boolean / null | AI 判定服务是否可用；`null` 表示尚未确认 |
| `vlm.checking` | boolean | 是否正在检查 AI 判定服务 |
| `vlm.last_success` | string / null | 最近成功时间，带时区；为空表示还没有成功记录 |
| `vlm.last_error` | string / null | 最近一次 AI 判定服务错误 |
| `vlm.consecutive_failures` | integer | 连续失败次数 |
| `vlm.circuit_state` | string | `closed`：正常接收任务；`open`：暂时暂停请求；`half_open`：尝试恢复 |
| `vlm.retry_after_sec` | integer / null | 暂停请求后距离下次重试的秒数；没有等待时为 `null` |

页面至少检查 `running`、`error` 和 `vlm.reachable`：`running=false` 时显示未就绪；`error` 有值或 `vlm.reachable=false` 时提示异常；可用性尚未确认时显示检查中。即使 HTTP 状态为 200，也不能直接显示“检测正常”。

可在上一次请求完成后，间隔约 2 秒刷新一次。

## 7. 读取和修改配置

配置按摄像头保存。每台摄像头可分别设置检测开关、检测区域、检测参数和报警方式。

### 7.1 读取当前配置

打开某个摄像头的配置页时，先调用：

```http
GET {API_BASE}/cameras/inspection_a/config?department=general_electric
X-API-Key: {API_KEY}
```

路径使用摄像头的 `shm_name`，查询参数 `department` 必填。

返回示例：

```json
{
  "camera": {
    "id": 1,
    "name": "安检入口",
    "shm_name": "inspection_a",
    "enable": true
  },
  "feature": "security_inspection",
  "config": {
    "enable": true,
    "value": {
      "staff_rois": {
        "security_staff_1": [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8], [0.1, 0.8]]
      },
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

| 字段 | 含义 / 用法 |
| --- | --- |
| `camera` | 当前摄像头信息，其中 `id` 是数字 ID |
| `camera.enable` | 摄像头本身是否启用，仅用于展示 |
| `feature` | 固定为 `security_inspection`，表示安检流程规范检测 |
| `config.enable` | 安检检测开关，配置页的“开启检测”开关绑定这个字段 |
| `config.value` | 检测区域和检测参数 |
| `config.alarm` | 报警设置 |

没有保存过配置的摄像头也会返回完整默认配置，默认 `config.enable=false`。如果 `camera.enable=false`，仅打开安检开关不能启动该摄像头，需要联系后端对接人处理。

### 7.2 保存配置

```http
PUT {API_BASE}/cameras/inspection_a/config?department=general_electric
X-API-Key: {API_KEY}
Content-Type: application/json
```

**请求体只提交读取结果中的完整 `config` 对象。** 不要提交外层 `camera`、`feature`，也不要再包一层 `config`。

前端处理顺序：

1. 读取当前配置，保留返回的完整 `config` 对象。
2. 将表单修改写入这个对象，例如修改 `enable`、`value.staff_rois` 或 `alarm`。
3. 将整个对象序列化为 JSON，作为 PUT 请求体发送。
4. 成功后，用响应中的 `config` 更新表单并提示“保存成功”。

例如，已经将读取接口的 JSON 保存到变量 `configResponse`，只修改检测开关和区域时：

```js
const config = structuredClone(configResponse.config);

config.enable = true;
config.value.staff_rois = {
  security_staff_1: [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8], [0.1, 0.8]],
};

// 将 body 作为上述 PUT 接口的请求体，其他配置字段会完整保留。
const body = JSON.stringify(config);
```

即使只修改一个开关，也必须保留完整配置及报警子字段；只传 `{"enable":true}` 会返回 422。数字传 JSON 数字，开关传 `true` / `false`，不要传字符串。不要添加表单自身的辅助字段。

成功返回 HTTP 200，结构与读取配置完全相同。保存失败时保留当前表单并显示错误原因。

多人编辑同一摄像头时，后保存的完整配置会覆盖之前的配置，因此每次打开编辑页应读取最新值。保存返回 5xx 或网络中断时，先重新读取配置确认是否已保存，再决定是否重试。

### 7.3 检测区域怎么画、怎么保存

检测区域也称 ROI，这里用于标出安检员所在的工位区域。`config.value.staff_rois` 保存“工位名称 → 多边形顶点”的对应关系：

```json
{
  "security_staff_1": [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8], [0.1, 0.8]],
  "security_staff_2": [[0.6, 0.2], [0.9, 0.2], [0.9, 0.8], [0.6, 0.8]]
}
```

每个点是 `[x, y]`，使用相对坐标：左上角为 `[0, 0]`，右下角为 `[1, 1]`，`x` 向右增加，`y` 向下增加。

绘制步骤：

1. 调用画面接口，传 `annotated=false`，作为绘制底图。
2. 在图片上依次点击多边形顶点；保存时按照绘制顺序排列。
3. 将点相对于图片左上角的横坐标除以图片显示宽度，纵坐标除以图片显示高度。
4. 将结果写入 `config.value.staff_rois`，随完整配置一起保存。

例如，图片显示宽 1000 像素、高 500 像素，某个点距图片左侧 100 像素、顶部 100 像素，则提交 `[0.1, 0.2]`。图片有黑边或留白时，按实际图片内容区域计算，不把留白计入宽高或点坐标。

| 项目 | 限制 |
| --- | --- |
| 工位数量 | 每台摄像头最多 16 个 |
| 工位名称 | 1～100 个字符，不能有首尾空格 |
| 每个区域的顶点数 | 3～64 个 |
| 顶点坐标 | `x`、`y` 均在 0～1 之间 |
| 区域形状 | 面积大于 0，边不能交叉或重叠 |

删除某个区域时，移除对应的工位键。删除全部区域时提交 `staff_rois: {}`，不要保留顶点为空的区域。没有工位区域时无法生成工位安检记录。

### 7.4 检测参数说明

下面字段都位于 `config.value`。页面可以只开放需要编辑的参数，未展示的字段保留读取到的值即可。

| 字段 | 表单含义 | 范围 / 约束 |
| --- | --- | --- |
| `cap_interval` | 检测间隔，秒 | 0.05～5 |
| `alarm_interval` | 报警间隔，秒 | 0～86400 |
| `conf` | 人体检测置信度阈值 | 大于 0，且不超过 1 |
| `iou` | 人体检测框重叠阈值 | 大于 0，且不超过 1 |
| `imgsz` | 人体检测输入尺寸 | 整数，160～1920，32 的倍数 |
| `pair_start_hold_frames` | 开始安检前，人员配对需持续的帧数 | 整数，1～300 |
| `fingerprint_lost_seconds` | 人员丢失多久后结束本次安检，秒 | 大于 0，且不超过 60 |
| `no_interact_seconds` | 停止交互多久后结束本次安检，秒 | 大于 0，且不超过 60 |
| `max_session_seconds` | 单次安检最长时长，秒 | 1～600 |
| `keyframe_interval_sec` | 送交 AI 判定的画面采样间隔，秒 | 0.1～30，且小于单次安检最长时长 |
| `keyframes_per_session` | 单次安检最多采样的图片数 | 整数，2～32 |
| `roi_crop_padding` | 采样图片裁剪区域向外扩展的距离，像素 | 整数，0～1000 |
| `fp_match_threshold` | 判断是否为同一人员的特征匹配阈值 | 0～1 |
| `interact_distance_max_ratio` | 判断人员交互时，距离与身高的比值上限 | 大于 0.2，且不超过 10 |
| `interact_motion_min_pixels` | 判断人员交互的最小移动距离，像素 | 0～1000 |
| `roi_enter_overlap_ratio` | 判定人员进入工位的重叠比例阈值 | 0～1 |
| `roi_hold_overlap_ratio` | 判定人员仍在工位内的重叠比例阈值 | 0～1，且不大于进入工位阈值 |

### 7.5 报警设置

报警设置位于 `config.alarm`，三个方式可分别开关：

| 配置项 | 含义 | 怎么填写 |
| --- | --- | --- |
| `sql.enable` | 是否保存违规报警记录 | `true` / `false`；`sql.parm` 固定保留 `{}` |
| `horn.enable` | 是否开启喇叭报警 | `true` / `false` |
| `horn.parm.horn_id` | 报警喇叭 ID | 从第 9 节喇叭列表选择；开启时必须指定已启用的喇叭 |
| `horn.parm.horn_event_id` | 喇叭播放的语音任务 ID | 由后端对接人提供，开启时必须填写 |
| `wechat.enable` | 是否开启企业微信通知 | `true` / `false` |
| `wechat.parm.user` | 企业微信接收人标识 | 由后端对接人提供，开启时不能为空 |

两项喇叭 ID 均为 1～2147483647 的整数。关闭喇叭报警且尚未选择设备时，两项 ID 可为 `null`；关闭企业微信且尚未设置接收人时，`user` 可为 `""`。

`sql.enable` 不控制第 5 节的安检记录列表；安检记录与违规报警记录是两类数据。保存报警配置不会立即播放语音或发送通知。

## 8. 获取配置默认值和字段限制

需要读取默认参数、制作“恢复默认值”操作或按字段限制生成表单时使用：

```http
GET {API_BASE}/config-schema
X-API-Key: {API_KEY}
```

此接口不需要查询参数。

| 返回字段 | 类型 | 用法 |
| --- | --- | --- |
| `feature` | string | 固定为 `security_inspection` |
| `default_config` | object | 完整默认配置，结构与第 7 节的 `config` 相同 |
| `config_schema` | object | JSON Schema，包含字段类型、默认值、数值范围等规则 |

编辑已有摄像头时，先用配置读取接口加载已保存的值。默认配置中的检测开关为关闭、检测区域为空；应用默认配置时会重置这些设置。获取默认值本身不会保存，需要再调用 PUT 配置接口。

## 9. 获取报警喇叭选项

配置页开启喇叭报警时，调用此接口填充下拉选项。该接口需要配置修改权限。

```http
GET {API_BASE}/horns?department=general_electric
X-API-Key: {API_KEY}
```

查询参数 `department` 必填，使用当前摄像头所属事业部编码。

返回示例：

```json
[
  {"id": 1, "name": "入口喇叭", "enable": true}
]
```

| 字段 | 类型 | 前端怎么用 |
| --- | --- | --- |
| `id` | integer | 选中后写入 `config.alarm.horn.parm.horn_id` |
| `name` | string | 下拉选项显示名称 |
| `enable` | boolean | 只有 `true` 的喇叭可用于开启报警；`false` 的选项应禁选 |

空数组表示暂无喇叭可选。语音任务 ID 不在此列表中，由后端对接人提供后填写到 `horn_event_id`。

## 10. 请求失败时怎么处理

普通错误示例：

```json
{"detail": "错误原因"}
```

参数校验错误示例：

```json
{
  "detail": [
    {
      "loc": ["query", "limit"],
      "msg": "Input should be greater than or equal to 1",
      "type": "greater_than_equal"
    }
  ]
}
```

`detail` 是字符串时，可直接展示；是数组时，读取各项的 `loc` 和 `msg`，提示哪个字段需要修改。网络异常或 5xx 响应可能没有这个 JSON 结构，应显示通用的请求失败提示。

| HTTP 状态 | 含义 | 前端处理 |
| --- | --- | --- |
| 400 | 事业部编码或配置内容不正确 | 根据 `detail` 修改请求 |
| 401 | 调用凭证缺失或已失效 | 检查 `X-API-Key` 请求头，联系后端对接人确认凭证 |
| 403 | 当前凭证不能访问此数据或不能修改配置 | 联系后端对接人确认可访问数据和配置修改权限 |
| 404 | 摄像头不存在，或暂时没有画面 | 检查 `shm_name`；画面接口可显示“等待画面” |
| 409 | 保存期间摄像头所属事业部发生变化 | 重新获取摄像头列表及配置后再操作 |
| 422 | 参数类型、范围、检测区域或配置完整性不符合要求 | 根据错误字段修正表单，完整提交配置 |
| 500 | 服务处理失败 | 提示请求失败；保存操作先重新读取配置确认结果 |
| 503 | 检测服务或画面暂不可用 | 显示未就绪，稍后重试 |

需要在线调试时，在浏览器打开 [http://172.16.0.32:7862/docs](http://172.16.0.32:7862/docs)，找到 `external-security-inspection` 分组。在 **Authorize → ExternalApiKey** 中填入调用凭证，再展开对应接口填写参数并执行。
