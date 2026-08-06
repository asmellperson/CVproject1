# 物流单人检测变体实时状态快照设计

## 目标

为电子电工、电气部件、贵金属回收三种物流通道单人检测消费者补充与通用电气版本一致的实时状态快照，使现有前端统计卡、人数状态和告警状态能够通过通用只读状态接口实时显示。

## 范围

仅修改以下三个消费者及对应测试：

- `detect_logistics_single_person_electronics_electrician`
- `detect_logistics_single_person_electrical_components`
- `detect_logistics_single_person_precious_metal_recycling`

不修改通用电气消费者、Orchestrator、API 路由、前端、检测判断、ROI、画框、视频、缓冲阈值或告警处理逻辑。

## 实现

每个消费者增加与现有通用电气消费者相同的展示快照能力：

1. 初始化每摄像头的 `monitor_status` 内存字典。
2. 在 `post_process` 开始处，使用现有检测结果生成快照并按 `shm_name` 保存。
3. 快照包含：
   - `count`：所有有效 ROI 的 `person_count` 之和；没有有效人数时为 `None`；
   - `alarm`：任一 ROI 已进入现有告警状态时为 `True`；
   - `reason`：按 `multiple`、`empty`、`normal`、`unknown` 选择当前状态；
   - `updated_at_s`：快照生成时间。
4. 增加 `get_monitor_status(camera_key)`，返回快照副本，避免接口调用方修改消费者内部状态。

快照只读取 `_process` 已经生成的结果，不参与或改变检测决策。

## 复用策略

三个变体从现有通用电气消费者模块导入纯函数 `build_monitor_snapshot`，避免复制聚合规则。本次不抽取新基类，也不重构四个消费者，控制修改范围。

## 验证

- 为三个消费者分别验证快照写入、人数聚合、告警状态和防御性副本；
- 运行物流单人检测相关后端测试；
- 运行现有状态接口测试，确认通用接口契约不变；
- 检查 diff，确认无前端及其他后端模块改动。
