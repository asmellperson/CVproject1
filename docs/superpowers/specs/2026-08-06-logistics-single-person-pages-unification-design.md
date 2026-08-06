# 物流通道单人检测页面前端统一设计

## 目标

将电子电工、电气部件、贵金属回收三个“物流通道单人检测”页面的实时监控界面，统一为现有“通用电气物流通道单人检测”页面的视觉与布局标准。

## 明确边界

- 仅修改 `unified_frontend` 内的展示、布局和前端参数传递。
- 保留三个页面各自的业务标题、feature key、摄像头范围及配置管理内容。
- 不修改后端代码、检测算法、ROI、告警规则、接口字段、接口路由和视频播放逻辑。
- 不复制三套监控 JSX；复用现有物流单人检测监控组件，避免四张页面以后出现样式偏差。

## 页面变化

三个页面的实时监控区域使用与通用电气页面相同的：

- 页面背景、标题区和“实时监控 / 配置管理”圆角分段控件；
- 四张统计卡：摄像头状态、当前画面人数、摄像头数量、今日告警次数；
- 左侧“监控对象 / 判定说明 / 实时事件”卡片；
- 右侧占三分之二宽度的视频监控卡片；
- 当前人数、在线状态、告警状态与实时事件的现有展示规则；
- 已完成的日间/夜间主题样式。

三个页面保留各自名称：

- 物流通道单人检测（电子电工）
- 物流通道单人检测（电气部件）
- 物流通道单人检测（贵金属回收）

## 前端数据参数化

现有共享物流监控视图只绑定通用电气 feature。调整为由页面传入当前 feature：

- 状态轮询仍调用同一个通用状态接口结构，但路径中的 feature 使用当前页面的 feature key；
- 告警查询与前端筛选使用当前页面的 feature key；
- 摄像头列表、帧流、配置值和现有选中摄像头行为保持不变；
- 共享视频卡标题由页面传入，从而保留业务名称。

这只是把共享前端组件指向各页面原有的 feature，不改变任何数据来源或检测逻辑。

## 预计修改文件

- `unified_frontend/src/sections/LogisticsSinglePersonElectronicsElectricianDetectionSection.tsx`
- `unified_frontend/src/sections/LogisticsSinglePersonElectricalComponentsDetectionSection.tsx`
- `unified_frontend/src/sections/LogisticsSinglePersonPreciousMetalRecyclingDetectionSection.tsx`
- `unified_frontend/src/components/AiVisionMonitor.tsx`
- `unified_frontend/src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx`
- `unified_frontend/src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts`
- `unified_frontend/src/components/logistics_single_person/monitorState.ts`
- `unified_frontend/src/lib/aivision.ts`
- 对应前端单元测试文件（仅用于验证参数传递和筛选行为）

## 验证

- 运行物流单人检测相关单元测试；
- 运行前端 TypeScript/构建检查；
- 运行 lint，确认无新增错误；
- 不启动预览服务器，不创建测试 HTML，不占用端口。
