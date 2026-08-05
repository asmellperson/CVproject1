# 福达视觉平台企业科技风登录页设计

## 目标与范围

将 `unified_frontend` 当前单卡片登录页改造为“左侧品牌动画视频 + 右侧登录表单”的企业科技风页面。桌面端采用左深右浅的双栏方案：左侧使用从实际视频首帧边缘测得的深蓝背景，右侧使用浅蓝白渐变承载白色登录卡片。

本次只修改登录页展示层和登录页静态资源。`ProtectedRoute`、`AuthProvider`、登录接口、Cookie 鉴权、账号和密码提交结构、错误传播、登录成功后的用户状态更新及页面跳转机制均保持不变。不得修改后端代码。

## 已确认的视觉方向

- 采用用户确认的上一版：左侧深蓝视频区，右侧浅色登录区。
- 不采用整页统一深蓝版本。
- 页面铺满视口且隐藏页面级横向、纵向滚动条，内部内容最大宽度约 `1500px` 并水平居中。
- 大于 `1200px` 时按 `55% / 45%` 分栏；`768px–1200px` 时按 `45% / 55%` 分栏；小于 `768px` 时隐藏动画主体，保留深蓝品牌条并让登录卡片成为页面主体。
- 登录卡片宽度上限 `448px`，约 `22px` 圆角，使用半透明白色、浅蓝描边和柔和阴影。
- 标题为“福达视觉平台”，副标题为“统一登录鉴权”。输入框高 `52px`，按钮使用深蓝到亮蓝渐变并保留 hover、active、disabled/loading 状态。
- 左上角复用 `public/mascot.png` 作为现有平台标识，并显示中文名与英文名 `FUDA VISION PLATFORM`。

## 视频处理与颜色依据

源文件为 `unified_frontend/public/0671754d-914a-4c23-8bf3-0a4ad883edff.mp4`，探测结果为 `720×720`、HEVC 视频、AAC 音频、约 `7.03s`。

最终视频写入：

`unified_frontend/public/assets/login/login-mascot.mp4`

转换参数固定为 H.264、无音频、`yuv420p`、faststart：

```bash
ffmpeg -y \
  -i unified_frontend/public/0671754d-914a-4c23-8bf3-0a4ad883edff.mp4 \
  -an \
  -c:v libx264 \
  -preset medium \
  -crf 23 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  unified_frontend/public/assets/login/login-mascot.mp4
```

从转换后视频提取首帧到：

`unified_frontend/public/assets/login/login-video-cover.png`

实际首帧采样结果如下：

- 顶部边缘平均色：`#0B1B39`，作为左侧基础背景色。
- 左侧边缘平均色：`#1A2C50`，用于低透明度背景补偿。
- 四角区域平均色范围：`#1F3054` 至 `#485B82`；底角受视频平台光效影响，不作为基础色。

视频容器不设置白底、边框或矩形阴影。视频使用 `object-fit: cover`，通过裁剪容器和底部同色渐变遮挡源视频中的错误文字 “LOGION”，同时尽量保留吉祥物主体。四周同时应用 `mask-image` 与 `-webkit-mask-image` 的椭圆径向渐隐，使画面边缘融入 `#0B1B39` 背景。视频后方仅使用来自实测边缘色的低透明度径向补偿，不使用高饱和发光圆框。

## 组件与样式边界

### `unified_frontend/src/pages/LoginPage.tsx`

- 保留现有 `account`、`password`、`error`、`submitting` 状态和 `onSubmit` 实现。
- 保留 `login(account.trim(), password)` 调用、`try/catch/finally`、原错误文案及提交按钮禁用逻辑。
- 增加只影响输入呈现的 `showPassword` 状态。密码框默认 `type="password"`，点击眼睛切换为 `text`，再次点击恢复；按钮提供 `aria-label` 与 `aria-pressed`。
- 增加视频加载失败状态和减少动态效果偏好状态。加载失败或 `prefers-reduced-motion: reduce` 时展示首帧封面，不显示破损媒体占位。
- 视频固定使用 React 属性 `autoPlay`、`muted`、`loop`、`playsInline`、`preload="auto"`，不渲染原生控制条。

### `unified_frontend/src/pages/LoginPage.css`

- 承担登录页专属布局、背景、视频遮罩、输入框、按钮及响应式样式。
- 样式通过 `.login-*` 命名空间限定，避免影响应用内其他页面。
- 页面保持项目现有字体栈，不引入新字体或第三方样式依赖。

### 保持不变的文件

- `unified_frontend/src/auth/AuthContext.tsx`
- `unified_frontend/src/components/ProtectedRoute.tsx`
- `unified_frontend/src/main.tsx`
- 所有后端代码

## 数据流与错误处理

表单提交仍由 `onSubmit` 阻止默认行为，清空旧错误，设置提交中状态，调用现有 `login`，捕获接口错误并显示原错误消息，最后恢复按钮状态。登录成功由现有 `AuthProvider` 更新 `user`，`ProtectedRoute` 随之渲染应用主体；登录页不增加路由或跳转代码。

视频错误与登录错误完全隔离。视频失败只切换到本地首帧背景，不触发通知、不阻断输入、不改变登录按钮状态。密码显隐只修改输入框的 `type`，不修改密码值。

## 可访问性与性能

- 眼睛按钮可通过键盘聚焦和触发，并具有随状态变化的中文无障碍标签。
- 错误区域保留清晰的红色视觉反馈，并使用 `role="alert"` 让错误及时播报。
- 提交中按钮继续禁用并展示加载反馈，防止重复提交。
- H.264 视频启用 faststart，资源不转为 Base64。
- `prefers-reduced-motion: reduce` 下不自动播放视频，只显示本地封面。
- 移动端不加载可见动画主体，确保表单始终可操作。

## 验证与验收

1. 使用 `ffprobe` 确认最终视频仅包含 H.264 视频流、没有音频流，像素格式为 `yuv420p`。
2. 运行登录页结构与交互契约测试，确认视频属性、密码默认隐藏与显隐按钮存在，并确认 `onSubmit` 的现有登录调用和错误处理未改变。
3. 在 `unified_frontend` 运行 `npm run build`；如时间允许再运行 `npm run lint`。
4. 启动前端页面，分别在视频播放前、播放中和约 `7.03s` 循环衔接处截图。
5. 检查截图中的视频四角、底部、右侧边缘及 “LOGION” 区域。若仍可辨认矩形边界或错误文字，则只调整 `LoginPage.css` 中的背景补偿、遮罩范围和 `object-position`，不改变登录业务代码。
6. 分别检查大于 `1200px`、`768px–1200px` 和小于 `768px` 的布局，确保无页面级滚动条且表单可完整操作。

## 风险控制

源视频实际为深蓝背景而非浅色背景，因此最终采用已确认的左深右浅设计。视频底部文字与吉祥物在动画首尾位置接近，遮罩和底部补偿必须以三时点截图复核，避免过度裁切主体。若浏览器阻止自动播放，`muted` 属性和本地封面确保页面仍有完整视觉结果。
