启动方案：
在 VS Code 中按下 Ctrl + ~（或者点击菜单栏的“终端” -> “新建终端”）。
开分屏终端：
在第一个终端里输入：cd /usr/zyy/SecurityDutyDetect/guard_room/app && npm run dev -- --host 0.0.0.0 --port 3000
点击终端面板右上角的 “拆分终端”（那个一分为二的图标），在右边的新终端里输入：cd /usr/zyy/Fuda_CVPreject/guard_room && python run_server.py


yolo export \
  model=/usr/zyy/SecurityDutyDetect/guard_room/models/person_phone.pt \
  format=engine \
  imgsz=640 \
  half=True \
  dynamic=True \
  batch=8 \
  workspace=4 \
  device=0

第一步：启动前端（后台稳定运行）
cd /usr/zyy/SecurityDutyDetect/guard_room/app
nohup npm run dev -- --host 0.0.0.0 --port 3000 > frontend.log 2>&1 &
echo "前端已启动，日志在 frontend.log"
cd /usr/zyy/SecurityDutyDetect/guard_room
nohup python run_server.py > backend.log 2>&1 &
echo "后端已启动，日志在 backend.log"
第二步：启动后端（后台稳定运行）
cd /usr/zyy/SecurityDutyDetect/guard_room
nohup python run_server.py > backend.log 2>&1 &
echo "后端已启动，日志在 backend.log"

你直接按下面这一组来：

# 1. 先加载 nvm
source ~/.nvm/nvm.sh

# 2. 使用你之前装好的 Node 20
nvm use 20

# 3. 看 npm 全局目录
npm prefix -g
echo "$(npm prefix -g)/bin"

# 4. 确认 PATH 是否包含 npm 全局 bin
echo $PATH | tr ':' '\n' | grep "$(npm prefix -g)/bin" || echo "PATH里没有npm全局bin"

# 5. 重新安装 Codex
npm i -g @openai/codex@latest

# 6. 刷新命令缓存
hash -r

# 7. 检查
which codex
codex --version

# 8. 启动
codex

第三步：验证
# 看端口是否在监听
netstat -tlnp | grep -E "3000|5000"
# 或者
lsof -i:3000
lsof -i:5000

# 看日志确认正常
tail -f frontend.log
tail -f backend.log

按端口查杀
# 停止前端（3000端口）
kill -9 $(lsof -ti:3000)

# 停止后端（5000端口）
kill -9 $(lsof -ti:5000)

# 或者两个一起杀
kill -9 $(lsof -ti:3000) $(lsof -ti:5000)
# 停止前端（3000端口），去掉 -9
kill $(lsof -ti:3000)

# 停止后端（5000端口），去掉 -9
kill $(lsof -ti:5000)

方法 2：按进程名查杀
# 杀掉所有 node 进程（前端）
pkill node

# 杀掉 python run_server.py（后端）
pkill -f "python run_server.py"

# 或者精确匹配
pkill -f "uvicorn"  # 如果你用的是 uvicorn

3080 是 Ampere 架构,TensorRT FP16 支持完美,YOLO11n 转 TRT 后推理速度通常 2-3x。
导出:
yolo export model=yolo11n.pt format=engine half=True device=0
# 生成 yolo11n.engine
models:
  detector_model: "yolo11n.engine"



## 代码说明

### 离岗逻辑
- 在 `post_roi` 内统计 person 的 track
- 若岗位区域持续无人员，则累计 `absent_seconds`
- 若累计超阈值，触发 `absent` 告警

### 玩手机逻辑
- 基于 COCO `cell phone` 类检测
- 将手机框与人体框、头部位置做空间约束
- 短时手机出现不直接报警，而是累计 `phone_seconds`
- 若同时检测到 `bottle/cup` 且时长很短，则做喝水排除

### 睡岗逻辑（基础版）
- 姿态模块可选：优先使用 MediaPipe Pose Landmarker
- 使用鼻子与肩部的相对高度估计“低头”趋势
- 使用人体框中心的位移估计“低运动量”
- 两者同时持续才累计 `drowsy_seconds`

## 当前限制

- 只适合单摄像头、固定机位。
- 默认按一个主要保安员目标做时长累计，多人值守需要增加岗位角色绑定。
- “吃零食”未纳入第一版硬逻辑。
- “打电话”和“查看工作信息”暂不做精细豁免，建议进入人工复核。

## 后续扩展

1. 增加值班交接班白名单时间窗
2. 增加自定义手机/工牌/记录本/零食袋数据集
3. 增加证据视频片段回放
4. 增加 ONNX / TensorRT / OpenVINO 部署脚本
