# unified_frontend 源码导览

## 项目定位

`unified_frontend` 是福达视觉平台的统一前端。它把多个视觉检测能力整合到一个 React 应用里，包括：

- 平台总览
- 保安行为规范检测
- 安检流程规范检测
- 区域入侵检测
- 大门开关异常检测
- 人脸检测
- 人员逗留检测
- 手机使用检测
- 报警记录
- 统计分析

技术栈：

- Node.js 20
- React 19
- TypeScript
- Vite 7
- Tailwind CSS 3
- shadcn/ui
- lucide-react 图标
- recharts 图表

## 渲染链路

最核心的执行顺序：

```text
浏览器加载 index.html
  -> 执行 /src/main.tsx
  -> AuthProvider 读取登录状态
  -> ProtectedRoute 决定显示 LoginPage 还是 App
  -> App 渲染 Sidebar、Topbar、当前 Section
  -> Section 通过 lib/* 请求后端接口
```

关键入口代码在 `src/main.tsx`：

```tsx
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <ProtectedRoute>
        <App />
      </ProtectedRoute>
    </AuthProvider>
  </StrictMode>,
)
```

这段代码说明：登录系统包住整个应用，所以任何业务页面默认都依赖登录状态。

## 主界面切页逻辑

`src/App.tsx` 负责保存当前页面：

```tsx
const [currentPage, setCurrentPage] = useState('overview')
const activePage = hasPageAccess(user, currentPage) ? currentPage : 'overview'
```

含义：

- `currentPage` 是用户点击的页面。
- `activePage` 是权限检查后的实际页面。
- 没权限时回到 `overview`。

页面映射由 `renderContent()` 决定：

```tsx
const renderContent = () => {
  switch (activePage) {
    case 'overview':
      return <HomeSection onNavigate={handlePageChange} />
    case 'guard-behavior':
      return <GuardBehaviorSection />
    case 'intrusion-detection':
      return <IntrusionDetectionSection />
    case 'door-detection':
      return <DoorDetectionSection />
    case 'face-detection':
      return <FaceDetectionSection />
    case 'human-detection':
      return <HumanDetectionSection />
    case 'phone-detection':
      return <PhoneDetectionSection />
    case 'security-vlm':
      return <SecurityVlmSection />
    case 'alarms':
      return <AlarmsSection />
    case 'statistics':
      return <StatisticsSection />
    default:
      return <HomeSection onNavigate={handlePageChange} />
  }
}
```

新增页面时，这里必须加一个 `case`。

## 菜单配置

菜单不写在 `Sidebar.tsx` 里，而是集中写在 `src/lib/nav.ts`。

核心结构：

```ts
export type NavItem = {
  id: string
  label: string
  icon: LucideIcon
  description?: string
}

export type NavGroup = {
  id: string
  label: string
  items: NavItem[]
}
```

菜单数据：

```ts
export const navGroups: NavGroup[] = [
  {
    id: 'overview',
    label: '',
    items: [
      { id: 'overview', label: '平台总览', icon: LayoutDashboard },
    ],
  },
  {
    id: 'modules',
    label: '能力中心',
    items: [
      { id: 'security-vlm', label: '安检流程规范检测', icon: ShieldAlert },
      { id: 'guard-behavior', label: '保安行为规范检测', icon: ShieldCheck },
      { id: 'intrusion-detection', label: '区域入侵检测', icon: Radar },
    ],
  },
]
```

`Sidebar.tsx` 会读取这个配置，并用权限过滤：

```tsx
const { user } = useAuth()
const visibleNavGroups = filterNavGroupsByPermission(user, navGroups)
```

## 登录系统

登录相关文件在 `src/auth/` 和 `src/pages/LoginPage.tsx`。

### `src/auth/AuthContext.tsx`

初始化时请求当前用户：

```ts
async function fetchCurrentUser() {
  const response = await fetch('/api/auth/me', {
    method: 'GET',
    credentials: 'include',
  })
  if (response.status === 401) return null
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const payload = (await response.json()) as { user: AuthUser }
  return payload.user
}
```

登录时请求：

```ts
const response = await fetch('/api/auth/login', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ employee_id: employeeId, password }),
})
```

重点：

- `credentials: 'include'` 表示请求会携带 cookie。
- 后端通过 cookie 维护登录状态。
- 其他接口返回 `401` 时，会触发 `aicv:unauthorized` 事件清空用户。

### `src/components/ProtectedRoute.tsx`

```tsx
if (loading) {
  return <div>正在校验登录状态...</div>
}

if (!user) {
  return <LoginPage />
}

return <>{children}</>
```

这个组件负责决定展示登录页还是主系统。

## 权限系统

权限集中在`src/auth/permissions.ts`。

部门权限：

```ts
export const departmentPermissions = {
  general_electric: {
    pages: ['overview', 'security-vlm', 'guard-behavior', 'human-detection'],
  },
  research_institute: {
    pages: ['overview', 'intrusion-detection', 'face-detection', 'phone-detection'],
  },
}
```

权限判断：

```ts
export function hasPageAccess(user: AuthUser | null | undefined, pageId: string) {
  const normalizedPageId = normalizePageId(pageId)
  if (!normalizedPageId) return false
  const role = getUserRole(user)
  if (normalizedPageId === 'overview') return true
  if (role === 'admin') return true
  if (!user || role !== 'viewer') return false

  const department = getUserDepartment(user)
  if (!department) return false
  if (department === 'all') return true

  return departmentPermissions[department]?.pages.includes(normalizedPageId) ?? false
}
```

普通页面不要自己重复写权限逻辑，优先复用 `hasPageAccess()`、`filterNavGroupsByPermission()`、`filterHomeModulesByPermission()`。

## 接口封装

接口相关文件集中在 `src/lib/`。

### `src/lib/api.ts`

主后端 Guard Room 接口、统一告警、统计聚合在这里。

基础 GET：

```ts
export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'GET',
    credentials: 'include',
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status} ${response.statusText}`)
  }

  return response.json() as Promise<T>
}
```

常用导出：

```ts
export const getStatus = () => apiGet<BackendStatus>('/status')
export const getConfig = () => apiGet<AppConfigPayload>('/config')
export const saveConfig = (payload: Partial<AppConfigPayload>) => apiPost('/config', payload)
export const startRuntime = () => apiPost<ControlResponse>('/control/start')
export const stopRuntime = () => apiPost<ControlResponse>('/control/stop')
export const restartRuntime = () => apiPost<ControlResponse>('/control/restart')
```

告警合并：

```ts
export const getAlarms = async (limit = 100): Promise<AlarmEvent[]> => {
  const [aiVision, guardRoom, securityVlm] = await Promise.allSettled([
    getAiVisionAlarms(limit),
    getGuardRoomAlarms(limit),
    getSecurityVlmAlarms(limit),
  ])

  return [
    ...(aiVision.status === 'fulfilled' ? aiVision.value : []),
    ...(guardRoom.status === 'fulfilled' ? guardRoom.value : []),
    ...(securityVlm.status === 'fulfilled' ? securityVlm.value : []),
  ].sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime())
}
```

### `src/lib/aivision.ts`

AiVision 摄像头、模型、图片帧接口在这里。

示例：

```ts
export async function getAiVisionCameras() {
  const response = await fetch('/api/cameras', { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const payload = await response.json()
  return Array.isArray(payload) ? payload : payload.cameras || []
}
```

帧图片地址：

```ts
export function aiVisionFrameUrl(cameraKey: string, feature?: string, nonce?: number) {
  return `/api/cameras/${encodeURIComponent(cameraKey)}/frame.jpg`
}
```

实际代码里还会拼接 `feature`、刷新时间戳、图片尺寸和质量参数。

### `src/lib/security-vlm.ts`

安检流程规范检测接口在这里。

常用导出：

```ts
export const getSecurityVlmHealth = () => securityVlmGet('/health')
export const getSecurityVlmHistory = (limit = 100) => securityVlmGet(`/api/history?limit=${limit}`)
export const getSecurityVlmRois = () => securityVlmGet('/api/rois')
export const saveSecurityVlmRois = (staff_rois) => securityVlmPost('/api/rois', { staff_rois })
export const startSecurityVlmRuntime = () => securityVlmPost('/api/control/start')
export const stopSecurityVlmRuntime = () => securityVlmPost('/api/control/stop')
```

## 业务页面职责

### 首页

`src/sections/HomeSection.tsx`

负责平台总览，包括模块入口、今日告警、设备状态、最近告警等。它会调用：

- `getAlarms()`
- `getConfig()`
- `getAiVisionCameras()`
- `getSecurityVlmHealth()`

### 保安行为规范检测

`src/sections/GuardBehaviorSection.tsx`

它本身只是一个 tab 外壳：

```tsx
<Tabs defaultValue="monitor">
  <TabsContent value="monitor">
    <MonitorSection />
  </TabsContent>
  <TabsContent value="config">
    <ConfigSection />
  </TabsContent>
</Tabs>
```

真正的实时监控在 `MonitorSection.tsx`，配置管理在 `ConfigSection.tsx`。

### AiVision 类检测页面

这些页面结构很像：

- `IntrusionDetectionSection.tsx`
- `DoorDetectionSection.tsx`
- `FaceDetectionSection.tsx`
- `HumanDetectionSection.tsx`
- `PhoneDetectionSection.tsx`

它们通常包含：

- 功能开关
- 摄像头选择
- ROI 区域编辑
- 阈值参数
- 告警推送配置
- 实时画面预览
- 模型配置

常复用这些组件：

- `AiVisionMonitor`
- `AiVisionRoiEditor`
- `AiVisionModelConfig`
- `FeatureCameraManager`
- `AlarmPushConfig`

### 安检流程规范检测

`src/sections/SecurityVlmSection.tsx`

负责：

- 播放原始视频和规则视频
- 显示 worker 健康状态
- 显示 VLM 统计
- 显示检测历史
- 配置工作人员 ROI
- 启动/停止检测服务

### 报警和统计

- `AlarmsSection.tsx`：报警表格、搜索、筛选、查看图片/视频。
- `StatisticsSection.tsx`：统计卡片、趋势图、类型分布、摄像头排行。

## 可复用组件职责

- `Sidebar.tsx`：左侧菜单，读取 `navGroups` 并按权限过滤。
- `Topbar.tsx`：顶部栏，显示当前页面、主题切换、用户信息、退出按钮。
- `AiVisionMonitor.tsx`：按摄像头和功能刷新画面。
- `AiVisionRoiEditor.tsx`：在图片上画 ROI。
- `AiVisionModelConfig.tsx`：读取和保存模型路径。
- `FeatureCameraManager.tsx`：摄像头增删改和启用禁用。
- `AlarmPushConfig.tsx`：统一告警推送配置。
- `ScreenRecorder.tsx`：调用浏览器录屏能力。

## shadcn/ui 基础组件

`src/components/ui/` 是基础 UI 组件库。业务页面会这样使用：

```tsx
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
```

常见组件：

- `button.tsx`：按钮
- `card.tsx`：卡片
- `input.tsx`、`textarea.tsx`：输入框
- `select.tsx`：下拉选择
- `tabs.tsx`：标签页
- `table.tsx`：表格
- `dialog.tsx`、`alert-dialog.tsx`：弹窗
- `badge.tsx`：标签
- `switch.tsx`、`checkbox.tsx`、`slider.tsx`：表单控件
- `sonner.tsx`：提示消息

一般业务开发不需要改 `components/ui/`，除非要统一改变基础控件样式。

## 样式系统

### `src/index.css`

这里有三类内容：

1. Tailwind 入口：

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

2. 主题变量：

```css
:root {
  --background: 220 30% 98%;
  --foreground: 222 47% 11%;
  --card: 0 0% 100%;
}

.dark {
  --background: 222 47% 6%;
  --foreground: 210 40% 98%;
}
```

3. 全局和局部样式，比如 `sidebar-shell`。

### `tailwind.config.js`

把 CSS 变量映射成 Tailwind 类名：

```js
colors: {
  background: "hsl(var(--background))",
  foreground: "hsl(var(--foreground))",
  card: {
    DEFAULT: "hsl(var(--card))",
    foreground: "hsl(var(--card-foreground))",
  },
}
```

所以代码里可以写：

```tsx
<div className="bg-background text-foreground">
```

## 新增一个页面的步骤

假设要新增 `设备管理` 页面：

1. 在 `src/sections/DeviceSection.tsx` 新建页面组件。
2. 在 `src/lib/nav.ts` 添加菜单：

```ts
{ id: 'devices', label: '设备管理', icon: Camera, description: '设备列表与状态管理' }
```

3. 在 `src/auth/permissions.ts` 的 `PageId` 加 `'devices'`。
4. 在 `pageIds` 集合里加 `'devices'`。
5. 在 `departmentPermissions` 里给需要的部门加 `'devices'`。
6. 在 `src/App.tsx` 引入并添加：

```tsx
case 'devices':
  return <DeviceSection />
```

## 修改接口的建议

如果后端新增接口，建议先在 `src/lib/` 里封装函数，再让页面调用。例如：

```ts
export const getDevices = () => apiGet<Device[]>('/devices')
```

页面里再写：

```tsx
const data = await getDevices()
```

这样做的好处是：

- 请求地址集中管理。
- 登录失效处理一致。
- TypeScript 类型更清楚。
- 页面代码更容易读。

## 不建议手动修改的目录

- `node_modules/`：npm 依赖目录。
- `dist/`：构建产物。
- `package-lock.json`：依赖锁文件，安装依赖时自动更新。
