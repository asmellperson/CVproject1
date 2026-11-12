# 外部报警列表与图片接口

人员逗留、警戒围栏和非法闯闸使用统一的外部报警入口。列表按 `violation_type` 数字筛选，详情和图片按报警 ID 获取，调用方无需传功能英文名，也无需按功能选择图片路径。

## 接入地址与类型

服务地址：`http://172.16.0.32:7862`。

接口前缀：`/api/external/alarms`。全部接口使用 GET，无需 API Key 或平台登录。除事业部目录外，请求必须携带单个 `department` 原始编码，并校验该事业部的功能分配及报警归属。

| `violation_type` | 报警类型 |
| --- | --- |
| `5` | 人员违规逗留 |
| `15` | 围栏禁入时段有人 |
| `16` | 围栏非白名单人员 |
| `17` | 非法闯闸（尾随） |

此入口提供上述四类报警。数据库保留原有 `feature_name` 字段，后台根据正式注册关系推导和核对功能；外部请求只需数字类型。

| 完整路径 | 用途 |
| --- | --- |
| `/api/external/alarms/departments` | 当前已分配上述报警功能的事业部 |
| `/api/external/alarms?department=general_electric&violation_type=5` | 报警总数与分页记录 |
| `/api/external/alarms/{id}?department=general_electric` | 单条报警详情 |
| `/api/external/alarms/{id}/image?department=general_electric` | 可直接显示的 PNG 原图 |

## HTTP 查询与图片

```http
GET http://172.16.0.32:7862/api/external/alarms?department=general_electric&violation_type=5&limit=20&offset=0

GET http://172.16.0.32:7862/api/external/alarms?department=general_electric&violation_type=5&violation_type=15&violation_type=16

GET http://172.16.0.32:7862/api/external/alarms/123?department=general_electric

GET http://172.16.0.32:7862/api/external/alarms/123/image?department=general_electric
```

`123` 为示例 ID，调用时使用实际记录的 ID。图片地址可直接作为 `<img src>` 或原图链接，无需再传 `violation_type`。

| 列表参数 | 说明 |
| --- | --- |
| `department` | 必填，单个事业部原始编码 |
| `violation_type` | 可选，报警类型数字；多类型重复传同名参数，不使用逗号拼接 |
| `camera_key` | 可选，摄像头的 `shm_name`，对应数据库 `camera_no` |
| `start`、`end` | 可选，带时区的 ISO 8601 时间，开始包含、结束不包含 |
| `limit` | 每页数量，默认 100，范围 1～500 |
| `offset` | 偏移量，默认 0，不得为负 |

省略 `violation_type` 时，返回所选事业部已分配的上述支持类型；明确请求尚未分配的类型返回 403。时间参数例如 `2026-11-12T00:00:00+08:00`，使用 `URLSearchParams` 编码，避免 `+` 被解释为空格。不传时间范围时查询当前留存记录。总数按完整筛选条件计算，不受当前页大小影响；记录按时间、ID 倒序返回。

JSON 响应没有 `code/data` 外层包装。列表结构为：

```json
{
  "total": 1,
  "items": [
    {
      "id": "123",
      "feature_name": "detect_human",
      "violation_type": 5,
      "event_type": "detect_human",
      "event_label": "人员违规逗留检测",
      "camera_key": "camera_32",
      "camera_name": "示例摄像头",
      "department": "general_electric",
      "reason": "人员违规逗留检测 - 示例摄像头",
      "created_at": "2026-11-12T10:00:00+08:00",
      "image_url": "/api/external/alarms/123/image?department=general_electric"
    }
  ]
}
```

详情直接返回 `items` 中的一条对象。报警 ID 按字符串使用，避免 JavaScript 大整数精度丢失。`feature_name`、`event_type` 是返回的业务说明字段，调用者无需将它们传回查询或图片接口。

| HTTP 字段 | 来源 |
| --- | --- |
| `id` | 数据库 `id` 的字符串形式 |
| `violation_type` | 数据库正式报警类型编号 |
| `camera_key` | `camera_no` |
| `camera_name` | `subject_name`，为空时使用摄像头标识 |
| `department` | 报警记录所属事业部 |
| `created_at` | `create_time`，补充服务器本地时区 |
| `reason` | 已保存的原因；为空时使用正式报警类型及摄像头名称 |
| `event_type`、`event_label` | 正式报警类型注册表中的标识与名称 |
| `image_url` | 同一报警的统一外部图片接口相对地址 |

显示图片时，在 `image_url` 前加服务地址。没有图片引用时为 `null`；有引用但文件不存在时，图片接口返回 404。HTTP 不返回服务器内部的 `image_path` 或 `video_path`。

## 直接查询数据库

报警表为 `ai_violation_image`。一厂对应 `general_electric` 和 `research_institute` 两个原始部门编码。下面的查询可返回一厂人员逗留及围栏报警，并生成统一图片地址：

```sql
SELECT
    CAST(e.id AS CHAR) AS alarm_id,
    e.create_time AS occurred_at,
    e.department AS department_code,
    e.camera_no AS camera_key,
    e.subject_name AS camera_name,
    e.violation_type,
    e.reason AS alarm_reason,
    CASE WHEN NULLIF(e.image_path, '') IS NOT NULL THEN CONCAT(
        'http://172.16.0.32:7862/api/external/alarms/',
        CAST(e.id AS CHAR), '/image?department=', e.department
    ) END AS image_url
FROM ai_violation_image AS e
WHERE e.department IN ('general_electric', 'research_institute')
  AND e.violation_type IN (5, 15, 16)
ORDER BY e.create_time DESC, e.id DESC
LIMIT 20 OFFSET 0;
```

只取人员逗留时使用 `e.violation_type = 5`；需要合并非法闯闸时将 `17` 加入数字列表，无需另外传入功能英文名。数据库内部仍保存 `feature_name`，HTTP 会根据正式类型归属核对记录一致性。

`SELECT *` 也能读取报警记录，但 `image_path` 是服务器磁盘文件路径，浏览器显示图片应使用上述 HTTP 地址。SQL 中的别名并非数据库物理列；HTTP 的 `camera_key`、`created_at` 等字段也不能直接当作表列名查询。查询连接应选择实际业务数据库。

HTTP 每次接受一个 `department`；展示整个一厂时分别请求两个已分配功能的事业部，再合并结果。数据库查询不会自动校验平台功能分配，图片接口会校验；可访问范围以 `/departments` 返回值为准。

## 返回状态

| 状态码 | 含义 |
| --- | --- |
| `200` | 返回 JSON 或完整 PNG 图片 |
| `400` | 部门编码错误、请求未支持的类型或起止时间范围错误 |
| `403` | 所选事业部未分配对应报警功能 |
| `404` | 报警、图片不存在，或报警不在所选事业部的已开放范围内 |
| `422` | 缺少必填参数、时间未携带时区或类型、分页参数无效 |

该入口只读，不提供检测配置、报警处置或设备操作。平台的 `/api/alarms` 与通知图片入口继续沿用各自的登录及签名校验。
