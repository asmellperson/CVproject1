# 福达视觉平台前端说明

这个目录是统一前端项目，技术栈是 React + TypeScript + Vite + Tailwind CSS + shadcn/ui。

前端新手可以先记住一条主线：

```text
index.html
  -> src/main.tsx
  -> 登录校验 AuthProvider / ProtectedRoute
  -> src/App.tsx
  -> Sidebar / Topbar / sections/*
  -> lib/* 调后端接口
```

## 开发启动

```bash
cd /usr/zyy/Fuda_CVPreject_V3/unified_frontend
npm install
npm run dev
```

默认监听：`0.0.0.0:3000`

本机访问：

```text
http://localhost:3000
```

服务器访问：

```text
http://<服务器IP>:3000
```

调试时可临时覆盖端口：

```bash
npm run dev -- --port <前端调试端口>
```

生产公网域名：

```text
https://aicv.fudar.com/
```

## 常用命令

```bash
npm run dev      # 启动开发服务
npm run build    # 构建生产版本，输出到 dist/
npm run lint     # 代码检查
npm run preview  # 预览构建后的 dist/
```

## 后端代理

开发环境里，浏览器请求会先到 Vite，再由 Vite 转发给后端。配置在 `vite.config.ts`。

已代理路径统一指向 `VITE_BACKEND_TARGET`，由统一后端再转发到各子系统：

- `/api` -> `VITE_BACKEND_TARGET`
- `/api/aivision`、`/api/ai` -> `VITE_BACKEND_TARGET`
- `/aivision` -> `VITE_BACKEND_TARGET`
- `/security-vlm` -> `VITE_BACKEND_TARGET`
- `/ws` -> `VITE_BACKEND_TARGET`

默认服务地址：

- 统一后端: `http://127.0.0.1:5000`
- Guard Room 内部服务: `http://127.0.0.1:5001`
- AiVision: `http://127.0.0.1:7862`
- Security VLM: `http://127.0.0.1:8000`

可以复制 `.env.example` 为 `.env` 或 `.env.local` 后调整：

```env
VITE_DEV_PORT=3000
VITE_PUBLIC_ORIGIN=https://aicv.fudar.com
VITE_BACKEND_TARGET=http://127.0.0.1:5000
VITE_API_BASE=https://aicv.fudar.com
VITE_WS_BASE=wss://aicv.fudar.com
VITE_AIVISION_URL=https://aicv.fudar.com/aivision/
```

## 目录怎么读

```text
unified_frontend/
  index.html              浏览器打开的 HTML 入口
  package.json            npm 命令和依赖
  vite.config.ts          Vite 服务、代理、路径别名配置
  tailwind.config.js      Tailwind 主题配置
  components.json         shadcn/ui 组件生成配置
  public/                 静态资源，代码里用 /mascot.png 这类路径访问
  dist/                   npm run build 生成的产物，不要手写改
  node_modules/           npm 依赖，不要手写改
  src/
    main.tsx              React 挂载入口
    App.tsx               主应用壳，负责菜单切页和整体布局
    index.css             全局样式和主题变量
    auth/                 登录状态和鉴权
    pages/                登录页等独立页面
    sections/             业务页面主体
    components/           可复用业务组件
    components/ui/        shadcn/ui 基础组件
    hooks/                自定义 hook
    lib/                  接口封装、导航等工具
    types/                TypeScript 类型定义
```

## 最重要的几个文件

### `src/main.tsx`

这是 React 的启动入口。它找到 `index.html` 里的 `root` 节点，然后把整个应用渲染进去。

重点代码：

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

含义：

- `AuthProvider`：全局提供当前登录用户、登录、退出等能力。
- `ProtectedRoute`：未登录时显示登录页，已登录才显示 `App`。
- `App`：真正的主界面。

### `src/App.tsx`

这是主界面壳，包含左侧菜单、顶部栏和中间内容区。

重点代码：

```tsx
const [currentPage, setCurrentPage] = useState('overview')
const activePage = hasPageAccess(user, currentPage) ? currentPage : 'overview'
```

含义：

- `currentPage`：当前想看的页面。
- `activePage`：经过权限检查后真正显示的页面。
- 如果用户没有权限，会退回 `overview`。

页面切换靠 `renderContent()`：

```tsx
const renderContent = () => {
  switch (activePage) {
    case 'overview':
      return <HomeSection onNavigate={handlePageChange} />
    case 'guard-behavior':
      return <GuardBehaviorSection />
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

如果以后新增一个页面，通常要同时改：

1. `src/lib/nav.ts` 加菜单项。
2. `src/auth/permissions.ts` 加权限。
3. `src/App.tsx` 的 `renderContent()` 加页面映射。
4. `src/sections/` 新建对应页面文件。

### `src/lib/nav.ts`

这里定义左侧菜单。

重点代码：

```ts
export const navGroups: NavGroup[] = [
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

每个菜单项最关键的是：

- `id`：页面唯一编号，要和 `App.tsx`、`src/auth/permissions.ts` 对上。
- `label`：显示在菜单里的中文名称。
- `icon`：来自 `lucide-react` 的图标。
- `description`：顶部栏或首页里用的说明文字。

### `src/auth/permissions.ts`

这里控制不同角色、不同部门能看哪些页面。

重点代码：

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

含义：

- 首页 `overview` 所有人都能看。
- `admin` 管理员所有页面都能看。
- `viewer` 普通用户按部门权限看。
- 部门权限由 `departmentPermissions` 决定。

### `src/lib/api.ts`

这里封装主后端接口。业务页面不要到处手写 `fetch('/api/xxx')`，优先通过这里提供的函数调用。

重点代码：

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

含义：

- 自动带上 cookie：`credentials: 'include'`。
- 如果后端返回 `401`，会通知登录系统清空用户。
- 返回 JSON 并按 TypeScript 类型推断。

## 各类文件负责什么

### `auth/`

- `auth-context.ts`：定义用户和登录上下文类型。
- `AuthContext.tsx`：管理登录状态，请求 `/api/auth/me`、`/api/auth/login`、`/api/auth/logout`。
- `useAuth.ts`：给页面和组件调用登录信息的快捷 hook。

### `sections/`

这里是业务页面主体：

- `HomeSection.tsx`：平台总览首页。
- `GuardBehaviorSection.tsx`：保安行为规范检测页面外壳。
- `MonitorSection.tsx`：保安行为实时监控。
- `ConfigSection.tsx`：保安行为配置管理。
- `SecurityVlmSection.tsx`：安检流程规范检测。
- `IntrusionDetectionSection.tsx`：区域入侵检测。
- `DoorDetectionSection.tsx`：大门开关异常检测。
- `FaceDetectionSection.tsx`：人脸检测。
- `HumanDetectionSection.tsx`：人员逗留检测。
- `PhoneDetectionSection.tsx`：手机使用检测。
- `AlarmsSection.tsx`：报警记录。
- `StatisticsSection.tsx`：统计分析。
- `AiVisionSection.tsx`：AiVision 独立入口说明，目前主菜单未直接使用。

### `components/`

这里是可复用业务组件：

- `Sidebar.tsx`：左侧菜单栏。
- `Topbar.tsx`：顶部栏。
- `ProtectedRoute.tsx`：登录保护。
- `AiVisionMonitor.tsx`：AiVision 实时画面。
- `AiVisionRoiEditor.tsx`：AiVision ROI 区域编辑器。
- `AiVisionModelConfig.tsx`：AiVision 模型配置。
- `FeatureCameraManager.tsx`：摄像头管理。
- `AlarmPushConfig.tsx`：告警推送配置。
- `ROIDrawer.tsx`：通用 ROI 多边形绘制组件。
- `ScreenRecorder.tsx`：浏览器录屏。

### `components/ui/`

这是 shadcn/ui 的基础 UI 积木，比如按钮、卡片、表格、弹窗、输入框、下拉框、标签页等。平时业务开发主要使用它们，少直接改它们。

### `lib/`

- `api.ts`：Guard Room 主后端接口、告警合并、统计聚合。
- `aivision.ts`：AiVision 摄像头、模型、帧图片接口。
- `security-vlm.ts`：Security VLM 健康状态、ROI、历史记录、控制接口。
- `alarm-config.ts`：告警配置规范化。
- `nav.ts`：菜单配置。
- `utils.ts`：通用 className 合并工具 `cn()`。

### `src/auth/permissions.ts`

- `departmentPermissions`：部门可访问页面。
- `hasPageAccess()`：判断当前用户是否能进入某个页面。
- `getAccessibleAlarmEventTypes()`：报警和统计页按部门过滤事件类型。

## 前端新手建议先看哪些

建议顺序：

1. `src/main.tsx`：看懂应用怎么启动。
2. `src/App.tsx`：看懂页面怎么切换。
3. `src/lib/nav.ts`：看懂菜单怎么配置。
4. `src/auth/permissions.ts`：看懂权限怎么过滤。
5. `src/components/Sidebar.tsx`：看懂菜单怎么渲染。
6. `src/sections/HomeSection.tsx`：看懂一个真实页面怎么写。
7. 再看某个具体业务页，比如 `PhoneDetectionSection.tsx` 或 `SecurityVlmSection.tsx`。

## 哪些文件不要手写改

- `node_modules/`：第三方依赖，重新 `npm install` 会生成。
- `dist/`：构建产物，重新 `npm run build` 会生成。
- `package-lock.json`：除非安装或更新依赖，否则不要手动编辑。
