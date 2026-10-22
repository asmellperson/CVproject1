# 非法闯闸数据与画面对接说明

报警列表可由对接方后端查询数据库；摄像头、实时画面、状态和报警抓拍图使用 HTTP 接口。也可使用 HTTP 报警列表代替数据库查询。

## 1. 接入地址与页面对应关系

| 名称 | 内容 |
| --- | --- |
| 服务地址 `BASE_URL` | `http://172.16.0.32:7862` |
| 接口前缀 `API_BASE` | `http://172.16.0.32:7862/api/external/tailgating` |
| 在线接口文档 | `http://172.16.0.32:7862/docs`，分组 `external-tailgating` |
| 数据库 | MySQL，库名以部署为准，当前项目通常为 `aivision`；连接地址和只读账号由对接负责人提供 |

**所有外部接口使用 GET，无需 API Key 或账号登录。** 图片可以直接放进 `<img src>`，也可通过链接打开原图。JSON 响应直接返回对象或数组，没有 `code/data` 外层包装。

除 `/departments` 外，所有请求均须携带单个 `department` 查询参数，并校验该事业部在平台已分配 `tailgating` 功能。摄像头和报警图片还会校验实际归属。

| 页面内容 | 数据来源 |
| --- | --- |
| 工厂或事业部下拉框 | `GET /departments` |
| 摄像头下拉框 | `GET /cameras?department=...` |
| 实时检测画面 | `GET /cameras/{shm_name}/frame.jpg?department=...` |
| 单台摄像头人数、通行事件和状态 | `GET /cameras/{shm_name}/status?department=...` |
| 一个事业部全部摄像头的状态 | `GET /status?department=...` |
| 报警列表和数量 | 第 2 节 SQL，或 `GET /history?department=...` |
| 报警详情 | `GET /alarms/{alarm_id}?department=...` |
| 报警抓拍图、列表缩略图 | `GET /alarms/{alarm_id}/image?department=...` |

上表路径均接在 `API_BASE` 后面。以下 `camera_101`、报警 ID `123` 和返回值均为字段示例，接入时使用真实数据。

### 工厂与部门编码

| 对接页面名称 | 平台事业部名称 | `department` |
| --- | --- | --- |
| 一厂 | 通用电气事业部 | `general_electric` |
| 一厂 | 福达新材院 | `research_institute` |
| 二厂 | 电子电工事业部 | `electronics_electrician` |
| 三厂 | 电气部件事业部 | `electrical_components` |
| 四厂 | 伟达子公司 | `precious_metal_recycling` |
| 皓达子公司 | 皓达子公司 | `haoda_company` |
| 福力达子公司 | 福力达子公司 | `fulida_company` |

工厂名称只用于对接页面展示和汇总。平台、数据库和 HTTP 参数继续使用原部门编码。可查询部门以 `/departments` 的实际返回为准。

一厂包含两个部门编码。HTTP 每次只接受一个 `department`，查询整个一厂时分别请求两个可访问部门后合并；报警图片始终使用该条记录的 `department_code`。数据库 SQL 可通过 `@factory = '一厂'` 一次查询两个部门，并统一排序、分页和计数。

## 2. 从数据库取得报警列表

由对接方后端连接数据库，再向页面返回查询结果。报警表为 `ai_violation_image`，必须同时限定：

```sql
feature_name = 'tailgating'
AND violation_type = 17
```

配置表 `ai_camera_config_tailgating` 保存检测规则，不是报警表。报警扩展数据保存在 `ai_violation_image.event_metadata` 的 `tailgating` 对象中。

非法闯闸基于人体轨迹判断，不提供姓名、工号或人脸身份；`track_ids` 是该摄像头运行期间的临时轨迹编号，不能作为员工编号或跨摄像头身份。

### 2.1 设置查询条件

选中实际业务数据库，在同一个数据库连接中执行。以下时间按北京时间示例，须与部署数据库写入 `create_time` 的时区保持一致。

```sql
SET time_zone = '+08:00';
SET @base_url = 'http://172.16.0.32:7862';
SET @end_time = NOW();
SET @start_time = DATE_SUB(@end_time, INTERVAL 31 DAY);
SET @factory = NULL;
SET @department = NULL;
SET @camera_key = NULL;
```

- `@base_url` 使用图片服务地址，末尾不加 `/`。
- `@factory = NULL` 查询下方列出的全部正式部门；仅查一厂使用 `SET @factory = '一厂';`，也可填写表中的其他页面名称。
- `@department = NULL` 不进一步限定部门；单部门查询使用例如 `SET @department = 'general_electric';`。
- `@camera_key = NULL` 查询全部摄像头；单摄像头使用接口返回的 `shm_name`。
- 时间范围为开始包含、结束不包含。刷新查询前重新设置 `@start_time/@end_time`。

SQL 不会自动检查平台功能分配。对接后端须按页面所选范围查询；HTTP 图片访问仍以 `/departments` 返回的事业部范围为准。

### 2.2 查询当前页

```sql
SELECT
    CAST(e.id AS CHAR) AS alarm_id,
    e.camera_no AS camera_key,
    e.subject_name AS camera_name,
    e.department AS department_code,
    CASE e.department
        WHEN 'general_electric' THEN '一厂'
        WHEN 'research_institute' THEN '一厂'
        WHEN 'electronics_electrician' THEN '二厂'
        WHEN 'electrical_components' THEN '三厂'
        WHEN 'precious_metal_recycling' THEN '四厂'
        WHEN 'haoda_company' THEN '皓达子公司'
        WHEN 'fulida_company' THEN '福力达子公司'
    END AS factory_name,
    e.create_time AS occurred_at,
    '非法闯闸（尾随）' AS abnormal_type,
    e.reason AS alarm_reason,
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(e.event_metadata, '$.tailgating.id')), 'null') AS event_id,
    JSON_EXTRACT(e.event_metadata, '$.tailgating.track_ids') AS track_ids,
    JSON_LENGTH(JSON_EXTRACT(e.event_metadata, '$.tailgating.track_ids')) AS event_person_count,
    CAST(NULLIF(JSON_UNQUOTE(
        JSON_EXTRACT(e.event_metadata, '$.tailgating.direction')
    ), 'null') AS SIGNED) AS direction,
    CAST(NULLIF(JSON_UNQUOTE(
        JSON_EXTRACT(e.event_metadata, '$.tailgating.overlap_seconds')
    ), 'null') AS DECIMAL(10, 3)) AS overlap_seconds,
    CASE WHEN NULLIF(e.image_path, '') IS NOT NULL THEN CONCAT(
        @base_url, '/api/external/tailgating/alarms/', CAST(e.id AS CHAR),
        '/image?department=', e.department
    ) END AS snapshot_url
FROM ai_violation_image AS e
WHERE e.feature_name = 'tailgating'
  AND e.violation_type = 17
  AND e.department IN (
      'general_electric', 'research_institute', 'electronics_electrician',
      'electrical_components', 'precious_metal_recycling', 'haoda_company', 'fulida_company'
  )
  AND e.create_time >= @start_time
  AND e.create_time < @end_time
  AND (
      @factory IS NULL OR CASE e.department
          WHEN 'general_electric' THEN '一厂'
          WHEN 'research_institute' THEN '一厂'
          WHEN 'electronics_electrician' THEN '二厂'
          WHEN 'electrical_components' THEN '三厂'
          WHEN 'precious_metal_recycling' THEN '四厂'
          WHEN 'haoda_company' THEN '皓达子公司'
          WHEN 'fulida_company' THEN '福力达子公司'
      END = @factory
  )
  AND (@department IS NULL OR e.department = @department)
  AND (@camera_key IS NULL OR e.camera_no = @camera_key)
ORDER BY e.create_time DESC, e.id DESC
LIMIT 20 OFFSET 0;
```

| 返回字段 | 页面用法 |
| --- | --- |
| `alarm_id` | 报警唯一 ID，按字符串使用，避免 JavaScript 大整数精度丢失 |
| `factory_name` / `department_code` | 展示工厂名称；HTTP 请求使用原部门编码 |
| `camera_name` / `camera_key` | 摄像头名称 / `shm_name` |
| `occurred_at` | 报警落库时间；`DATETIME` 本身不携带时区，按部署约定显示 |
| `abnormal_type` / `alarm_reason` | 异常类型 / 具体原因 |
| `event_id` | 该次通行事件标识；列表去重使用 `alarm_id` |
| `track_ids` | JSON 轨迹数组，部分数据库驱动返回 JSON 字符串，后端解析后返回数组 |
| `event_person_count` | 该条报警关联的人数，不是当前 ROI 人数 |
| `direction` | `1` 为配置过闸判定线的正法向，`-1` 为反向，不能直接等同进厂或出厂 |
| `overlap_seconds` | 此事件共同出现时长，秒 |
| `snapshot_url` | 可直接访问的 PNG 图片完整地址，详见第 3 节 |

每页 20 条，第二页使用 `OFFSET 20`。记录按发生时间和 ID 从新到旧排列。扩展字段缺失时返回空值，页面显示“--”。`snapshot_url` 不为空仍可能因证据文件过期而返回 404；不要把服务器内部 `image_path` 当作浏览器地址。

### 2.3 查询相同范围的总条数

```sql
SELECT COUNT(*) AS total
FROM ai_violation_image AS e
WHERE e.feature_name = 'tailgating'
  AND e.violation_type = 17
  AND e.department IN (
      'general_electric', 'research_institute', 'electronics_electrician',
      'electrical_components', 'precious_metal_recycling', 'haoda_company', 'fulida_company'
  )
  AND e.create_time >= @start_time
  AND e.create_time < @end_time
  AND (
      @factory IS NULL OR CASE e.department
          WHEN 'general_electric' THEN '一厂'
          WHEN 'research_institute' THEN '一厂'
          WHEN 'electronics_electrician' THEN '二厂'
          WHEN 'electrical_components' THEN '三厂'
          WHEN 'precious_metal_recycling' THEN '四厂'
          WHEN 'haoda_company' THEN '皓达子公司'
          WHEN 'fulida_company' THEN '福力达子公司'
      END = @factory
  )
  AND (@department IS NULL OR e.department = @department)
  AND (@camera_key IS NULL OR e.camera_no = @camera_key);
```

总数查询与列表使用相同筛选，不受当前页影响。`COUNT(*)` 表示报警事件条数，不能用来统计所有过闸人数或实际尾随人数。同组人员的一次通行通常只保存一条报警，三人及以上同行可合并为同一事件。

## 3. 显示报警抓拍图和缩略图

直接使用 SQL 返回的 `snapshot_url`。HTTP 接口为：

```http
GET http://172.16.0.32:7862/api/external/tailgating/alarms/123/image?department=general_electric
```

返回 `image/png`，无需额外请求头。缩略图的 `<img src>` 和点击打开原图的 `<a href>` 使用同一个完整地址，列表通过 CSS 或 `width` 缩小显示：

```html
<a href="http://172.16.0.32:7862/api/external/tailgating/alarms/123/image?department=general_electric"
   target="_blank" rel="noopener">
  <img src="http://172.16.0.32:7862/api/external/tailgating/alarms/123/image?department=general_electric"
       alt="非法闯闸抓拍图" width="160">
</a>
```

报警图片接口返回留存原图，`max_width/max_height` 缩放参数只适用于第 5 节实时画面。图片不存在、证据已清理、报警不属于所选事业部或不是非法闯闸记录时返回 404，页面显示“无留存图片”。证据默认保留 31 天，以部署的 `ALARM_MEDIA_RETENTION_DAYS` 为准。

## 4. 获取事业部和摄像头

```http
GET http://172.16.0.32:7862/api/external/tailgating/departments

GET http://172.16.0.32:7862/api/external/tailgating/cameras?department=general_electric
```

`/departments` 返回 `[{"name":"general_electric","display_name":"通用电气事业部"}]` 形式的数组，仅包含平台当前已分配非法闯闸功能的事业部。

摄像头返回示例：

```json
[
  {
    "id": "camera_101",
    "camera_id": 101,
    "name": "闸机入口",
    "shm_name": "camera_101",
    "department": "general_electric",
    "enabled": true,
    "fps": 5,
    "sort_order": 0,
    "feature_sort_orders": {"tailgating": 0},
    "functions": {"tailgating": true}
  }
]
```

`name` 用于显示；画面和状态路径使用 `shm_name`，拼接前执行 `encodeURIComponent`。`camera_id` 是数据库数字 ID，不能替代路径中的 `shm_name`。响应不包含 RTSP 地址。

默认 `enabled_only=true`，只列摄像头和非法闯闸检测均启用的设备；传 `false` 可查看该事业部全部摄像头及其检测开关。列表已按非法闯闸顺序和摄像头 ID 排列。配置启用不代表实时在线，在线和检测状态以第 6 节接口为准。

## 5. 显示当前检测画面

```http
GET http://172.16.0.32:7862/api/external/tailgating/cameras/camera_101/frame.jpg?department=general_electric&annotated=true&max_width=1280
```

| 参数 | 说明 |
| --- | --- |
| `department` | 必填，摄像头所属原部门编码 |
| `annotated` | 默认 `true`，显示 ROI、过闸判定线及有效检测结果；`false` 返回原始帧 |
| `quality` | JPEG 质量，默认 85，范围 1–100 |
| `max_width` / `max_height` | 可选，范围 1–4096，按原始比例缩小，不放大 |

返回 `image/jpeg`。例如使用 `max_width=320` 获取画面缩略尺寸，或不传尺寸限制获取原始尺寸。图片地址可直接放进 `<img src>`。

该接口每次返回一张当前图片，连续刷新用于展示画面，不是视频播放地址。画面来自最新采集帧，更新不等待推理；检测结果过期或配置不完整时可保留实时底图，通行结论以状态接口为准。

## 6. 实时人数和通行状态

```http
GET http://172.16.0.32:7862/api/external/tailgating/cameras/camera_101/status?department=general_electric

GET http://172.16.0.32:7862/api/external/tailgating/status?department=general_electric
```

第一个返回单台摄像头对象，第二个返回该事业部已启用非法闯闸功能的摄像头状态数组，也包含摄像头停用、离线和等待结果的状态。

```json
{
  "camera_key": "camera_101",
  "camera_name": "闸机入口",
  "department": "general_electric",
  "online": true,
  "state": "ready",
  "reason": "tailgating",
  "count": 2,
  "alarm": true,
  "persons": [
    {"track_id": 1, "bbox": [100, 80, 220, 430], "in_roi": true, "direction": 1},
    {"track_id": 2, "bbox": [240, 90, 360, 440], "in_roi": true, "direction": 1}
  ],
  "events": [
    {"id": "gate-event-1", "track_ids": [1, 2], "direction": 1, "overlap_seconds": 0.5}
  ],
  "sample_interval_seconds": 0.1,
  "updated_at": "2026-10-22T09:00:00+08:00",
  "error": null
}
```

| 字段 | 页面用法 |
| --- | --- |
| `online` | 摄像头采集是否运行；不代表检测结论有效 |
| `state` | `ready` 检测结果有效；`disabled` 停用；`offline` 离线；`waiting` 等待；`stale` 结果过期；`error` 检测异常 |
| `reason` | `clear` 未形成尾随事件；`tailgating` 已形成事件；`unconfigured` 尚未配置完整 ROI 和过闸判定线；`sampling_gap` 采样中断后重新跟踪；其余与状态或具体错误对应 |
| `count` | 当前 ROI 内人数，空值显示“--” |
| `alarm` | 当前是否形成尾随事件；先检查 `state`，非 `ready` 时不能把 `false` 当成正常通行 |
| `persons` | 全画面人体轨迹；`in_roi` 区分是否在检测区域内，`direction=null` 表示尚未确定过线方向 |
| `persons[].bbox` | 原始帧像素坐标 `[x1,y1,x2,y2]`，缩放展示时按图片比例换算 |
| `events` | 当前已确认的通行事件，轨迹 ID、方向和共同出现时长同数据库扩展字段 |
| `sample_interval_seconds` | 相邻有效采样间隔，秒；空值表示尚无连续观测 |
| `updated_at` / `error` | 带时区的结果时间 / 具体异常原因 |

状态超过 2 秒失效。前端轮询中断时也应根据 `updated_at` 清除当前结论，避免持续显示旧的“无报警”。实时事件不等于全部已落库报警，历史列表和总数以数据库或 `/history` 为准。

## 7. 使用 HTTP 获取报警列表和详情

```http
GET http://172.16.0.32:7862/api/external/tailgating/history?department=general_electric&limit=20&offset=0

GET http://172.16.0.32:7862/api/external/tailgating/alarms/123?department=general_electric
```

| 列表参数 | 说明 |
| --- | --- |
| `department` | 必填，单个原部门编码 |
| `camera_key` | 可选，摄像头 `shm_name` |
| `start` / `end` | 可选，带时区的 ISO 8601 时间，开始包含、结束不包含；开始须早于结束 |
| `limit` | 默认 100，范围 1–500 |
| `offset` | 默认 0，不得为负 |

时间示例 `2026-10-22T00:00:00+08:00`，使用 `URLSearchParams` 编码，避免 `+` 被误读为空格。HTTP 时间边界转换为服务进程本地时间后与数据库比较。不传时间时查询当前保存的记录；需要与第 2 节最近 31 天 SQL 一致时明确传入相同的时间范围。

列表返回示例：

```json
{
  "total": 1,
  "items": [
    {
      "id": "123",
      "camera_key": "camera_101",
      "camera_name": "闸机入口",
      "department": "general_electric",
      "reason": "过闸判定线检测到多人同向通行且在闸机区域内共同出现",
      "created_at": "2026-10-22T09:00:00+08:00",
      "tailgating": {"id": "gate-event-1", "track_ids": [1, 2], "direction": 1, "overlap_seconds": 0.5},
      "image_url": "/api/external/tailgating/alarms/123/image?department=general_electric"
    }
  ]
}
```

详情接口直接返回 `items` 中的一条对象。`id` 与 SQL 的 `alarm_id` 对应，`created_at` 携带时区。`tailgating` 缺失时为 `null`；没有图片引用时 `image_url=null`。`image_url` 为相对地址，前面加 `BASE_URL` 后即可显示图片。总数按完整筛选范围计算，不受分页影响，排序与 SQL 一致。

## 8. 刷新与错误处理

- 画面和状态可每 500 毫秒串行请求，上一请求完成后再开始下一次；报警列表可每 5 秒刷新当前页。
- 新图加载并解码完成后再替换旧图。短暂失败可保留上一帧并提示刷新异常，旧画面不能作为实时在线依据。
- 切换摄像头、事业部、离开页面或功能分配失效时，清除旧图片与旧状态，停止对应轮询。
- 所有外部响应使用 `Cache-Control: no-store`；使用 `fetch` 时也可设置 `cache: 'no-store'`。

| HTTP 状态 | 处理方式 |
| --- | --- |
| `400` | 部门编码或时间范围不正确，检查响应 `detail` |
| `403` | 部门未分配非法闯闸功能，或摄像头不属于所选部门 |
| `404` | 摄像头、报警或图片不存在；也可能尚无画面，图片显示“暂无图片” |
| `422` | 缺少参数、时间未带时区、尺寸或分页参数超出范围 |
| `503` | 检测编排器或采集画面暂不可用，显示等待后重试 |

错误 JSON 的说明在 `detail` 字段；网络或服务器错误显示请求失败。外部接口只提供读取；摄像头配置、ROI、方向、模型和报警策略由平台管理员维护。
