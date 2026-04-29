终端里输入：cd /usr/zyy/Fuda_CVPreject/guard_room && python run_server.py

验证：
# 看端口是否在监听
netstat -tlnp | grep -E "3000|5000"
# 生成 yolo11n.engine
models:
  detector_model: "yolo11n.engine"

## 代码说明

### 离岗逻辑
- 在 `post_roi` 内统计 person 的 track
- 若岗位区域持续无人员，则累计 `absent_seconds`
- 若累计超阈值，触发 `absent` 告警

### 玩手机逻辑
- 基于自训练的yolo11m的人体的手机检测
- 将手机框与人体框、头部位置做空间约束
- 短时手机出现不直接报警，而是累计 `phone_seconds`
- 若同时检测到 `bottle/cup` 且时长很短，则做喝水排除

### 睡岗逻辑（基础版）
- 姿态模块可选：优先使用 MediaPipe Pose Landmarker
- 使用鼻子与肩部的相对高度估计“低头”趋势
- 使用人体框中心的位移估计“低运动量”
- 两者同时持续才累计 `drowsy_seconds`

## 当前限制
- “吃零食”未纳入逻辑。
- “打电话”和“查看工作信息”暂不做精细豁免，建议进入人工复核。
