# 安检流程规范多事业部隔离设计

## 1. 背景与目标

当前“安检流程规范检测”仅归属于通用电气事业部，`security_vlm` 使用一套全局摄像头注册表、全局历史和全局统计。现需将相同功能提供给以下四个事业部：

- 通用电气事业部：`general_electric`
- 电子电工事业部：`electronics_electrician`
- 电气部件事业部：`electrical_components`
- 贵金属回收事业部：`precious_metal_recycling`

目标不是复制四套代码或四个服务实例，而是复用一套页面、接口、模型和安检判定规则，同时按事业部隔离全部业务数据。

通用电气保留现有摄像头及业务数据；另外三个事业部首次进入时摄像头列表为空，之后各自独立添加和管理摄像头。

## 2. 已确认范围

每个事业部独立管理：

- 摄像头及 RTSP 凭据
- 每台摄像头的多个 ROI
- 摄像头启停和运行状态
- 安检历史记录
- 告警记录
- 统计数据

四个事业部共用：

- 检测模型
- VLM 判定规则和提示词
- 公共阈值与模型配置
- 页面组件、接口实现和服务进程

每个事业部最多配置 4 台摄像头，四个事业部理论上合计最多配置 16 台。

## 3. 总体架构

继续保留单个 `security_vlm` 服务，在服务内部增加事业部工作区抽象：

```text
请求
  → 登录身份与事业部权限校验
  → DepartmentWorkspace
      → CameraRegistry
      → RoiStore
      → RuntimeStore
      → HistoryStore
      → StatisticsStore
```

所有摄像头任务和检测结果必须携带：

```text
department + camera_id
```

事业部标识集中定义和校验，未知事业部直接拒绝，不在业务接口中自动创建目录。工作区负责返回当前事业部对应的摄像头、ROI、运行状态、历史和统计存储，避免各接口自行拼接路径。

## 4. 存储隔离

采用“单服务 + 每事业部独立工作区目录”，而不是把四个事业部的数据混合保存在同一注册文件中。

建议结构：

```text
security_vlm/
├── data/departments/
│   ├── general_electric/
│   │   ├── cameras.json
│   │   └── rois/
│   │       └── <camera_id>.json
│   ├── electronics_electrician/
│   │   ├── cameras.json
│   │   └── rois/
│   ├── electrical_components/
│   │   ├── cameras.json
│   │   └── rois/
│   └── precious_metal_recycling/
│       ├── cameras.json
│       └── rois/
└── runtime/departments/
    ├── general_electric/
    │   ├── cameras/<camera_id>/
    │   ├── vlm_history.json
    │   └── vlm_latest_stats.json
    ├── electronics_electrician/
    ├── electrical_components/
    └── precious_metal_recycling/
```

每份摄像头注册表包含事业部标识，作为路径隔离之外的附加一致性校验：

```json
{
  "version": 2,
  "department": "electronics_electrician",
  "cameras": []
}
```

摄像头名称只要求在同一事业部内唯一。内部通过 `department + camera_id` 定位，允许不同事业部使用相同显示名称。

## 5. 接口与权限

事业部业务接口显式携带事业部标识：

```text
GET    /security-vlm/api/departments/{department}/health
GET    /security-vlm/api/departments/{department}/cameras
POST   /security-vlm/api/departments/{department}/cameras
GET    /security-vlm/api/departments/{department}/history
POST   /security-vlm/api/departments/{department}/cameras/{camera_id}/rois
POST   /security-vlm/api/departments/{department}/cameras/{camera_id}/control/start
```

权限规则：

- `admin` 可以访问并管理四个事业部。
- `viewer` 只能访问账号所属事业部，并且只能读取。
- `viewer` 不能新增、修改、删除、启停摄像头，也不能读取 RTSP 凭据。
- 摄像头操作除校验事业部权限外，还必须校验 `camera_id` 属于当前事业部工作区。
- 跨事业部请求返回 `403`；当前事业部不存在的摄像头返回 `404`。
- 对外请求统一经过 `unified_backend` 权限网关，内部 `security_vlm` 服务不作为公共入口暴露。

文件目录隔离不能代替接口权限校验，两层隔离必须同时存在。

## 6. 前端入口与状态隔离

四个事业部目录下各显示一个“安检流程规范检测”入口。前端复用一个组件，通过属性传入事业部：

```tsx
<SecurityVlmSection department="general_electric" />
<SecurityVlmSection department="electronics_electrician" />
<SecurityVlmSection department="electrical_components" />
<SecurityVlmSection department="precious_metal_recycling" />
```

管理员从哪个事业部入口进入，就只加载该事业部的数据；普通用户只看到所属事业部入口。

页面标题或副标题显示当前事业部。事业部发生切换时，先清空当前摄像头、ROI、历史和统计状态，再加载目标工作区，避免短暂显示上一个事业部的数据。

告警和统计记录必须同时包含 `department` 与 `camera_id`。四个事业部产生相同的安检事件类型，因此告警过滤不能只依赖 `security_vlm_non_compliant` 或 `security_vlm_error`，还必须叠加事业部条件。

## 7. ROI 交互与数据格式

安检 ROI 复用 AiVision 人体逗留检测的无模式绘制逻辑：

- 拖动距离超过阈值时生成矩形。
- 单击时添加一个多边形顶点。
- 不显示“矩形”或“多边形”模式切换按钮。
- 已有顶点可以直接拖动调整。
- 支持撤销、清空、全画面和保存。
- 保存前校验顶点数量、坐标范围和最小面积。
- 一台摄像头可以创建多个命名 ROI，每个 ROI 独立选择、编辑和删除。

矩形和多边形统一保存为顶点数组，不额外保存形状类型：

```json
{
  "version": 2,
  "department": "general_electric",
  "camera_id": "camera-uuid",
  "regions": {
    "security_staff_1": [[120, 80], [620, 80], [620, 430], [120, 430]],
    "security_staff_2": [[700, 90], [980, 120], [1050, 380], [760, 440]]
  }
}
```

后端必须重复执行关键校验，不能只依赖前端。

## 8. 旧数据兼容与迁移

旧 ROI 矩形格式：

```json
{
  "security_staff_1": [120, 80, 620, 430]
}
```

加载时转换为四个顶点：

```json
{
  "security_staff_1": [[120, 80], [620, 80], [620, 430], [120, 430]]
}
```

只有用户实际保存该 ROI 时才写成新格式，未编辑的旧数据不批量改写。

首次升级时：

- 现有摄像头、ROI、历史和统计归入 `general_electric` 工作区。
- 另外三个事业部创建空摄像头注册表和空数据目录，不复制通用电气摄像头。
- 迁移使用临时文件和原子替换，并保留原始文件或备份。
- 迁移具有幂等性，重复启动不会重复导入摄像头或历史。
- 旧文件损坏或迁移未完成时明确记录错误，不能把通用电气误显示成空配置。

## 9. 运行、删除与异常处理

检测任务在摄像头启动时绑定 `department + camera_id`。检测结果只写入对应工作区。

删除摄像头时：

1. 停止对应 worker。
2. 从当前事业部活动注册表中移除摄像头。
3. 保留历史告警。
4. ROI 和运行数据归档，不立即永久删除。

异常处理要求：

- 某个事业部数据损坏时，仅将该工作区标记为异常，其他事业部继续运行。
- 不静默吞掉摄像头、ROI、历史或迁移错误。
- 关键日志包含 `department` 和 `camera_id`。
- “全部启动”和“全部停止”只作用于当前事业部。

## 10. 资源控制与公平调度

配置容量扩大到最多 16 台不代表允许 16 台无限并发调用 VLM。

- 每个事业部摄像头数量上限为 4。
- 同时运行数量、推理并发数和 VLM 调用并发数由统一配置控制。
- 公共任务队列携带事业部信息，并按事业部公平调度，避免单个事业部长时间占满队列。
- 队列长度、处理延迟和失败次数按事业部分开统计。
- 某事业部任务失败不能停止其他事业部 worker。

## 11. 验证方案

最小验证覆盖：

- 通用电气旧摄像头、ROI、历史和统计无损迁移。
- 另外三个事业部首次进入时摄像头列表为空。
- 四个事业部分别可以添加 4 台摄像头，第 5 台被明确拒绝。
- 不同事业部可以使用相同摄像头名称。
- `viewer` 不能读取或修改其他事业部数据。
- `admin` 切换事业部后不残留上一个事业部页面状态。
- 一台摄像头可以保存多个矩形或多边形 ROI。
- 旧矩形 ROI 可以加载、编辑并保存为顶点格式。
- 点击生成多边形顶点，拖拽生成矩形，顶点拖动、撤销、清空和全画面正常。
- 相同安检事件类型下，告警、历史和统计仍按事业部正确隔离。
- 一个工作区文件损坏或一个 worker 异常时，其他事业部仍可运行。
- 前端构建、后端单元测试和最小接口集成测试通过。

## 12. 风险与非目标

主要风险：

- 当前 VLM 历史和统计使用全局存储，实施时必须完整追踪全部写入点。
- 现有系统只面向最多 4 台安检摄像头，扩展到 16 台后可能出现推理或外部 VLM 调用瓶颈。
- 数据迁移和兼容读取必须避免把损坏数据误判为空数据。

本次非目标：

- 不复制四套前端组件或后端服务。
- 不为各事业部创建独立模型和判定规则。
- 不自动复制通用电气摄像头到其他事业部。
- 不永久删除摄像头历史告警。
