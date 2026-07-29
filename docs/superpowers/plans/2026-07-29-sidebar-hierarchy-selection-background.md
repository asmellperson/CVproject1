# 导航栏层级选中底色 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让当前检测功能所属的一级目录显示浅蓝选中底色，同时保留检测功能现有的深蓝选中底色。

**Architecture:** 继续由 `currentPage` 推导 `activeChildGroupId`，并在渲染每个一级目录时计算 `childActive`。选中样式仅由 `childActive` 控制，展开状态 `expanded` 仍只控制箭头与子菜单显示，因此多个目录可以展开但只会有一个一级目录高亮。

**Tech Stack:** React 19、TypeScript、Tailwind CSS 3、Vite 7

---

### Task 1: 增加一级目录选中底色

**Files:**
- Modify: `unified_frontend/src/components/Sidebar.tsx:150-173`

- [x] **Step 1: 运行修改前样式契约检查并确认失败**

Run:

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('unified_frontend/src/components/Sidebar.tsx','utf8');if(!s.includes('const childActive = activeChildGroupId === child.id'))process.exit(1);if(!s.includes('bg-blue-50/90')||!s.includes('ring-blue-200'))process.exit(1)"
```

Expected: 命令退出码为 1，因为一级目录尚未根据 `activeChildGroupId` 添加浅蓝选中样式。

- [x] **Step 2: 为一级目录计算选中状态**

在 `group.children?.map((child) => {` 内、现有 `expanded` 变量之前加入：

```tsx
const childActive = activeChildGroupId === child.id
```

保留现有 `expanded` 计算，不使用 `expanded` 判断底色。

- [x] **Step 3: 添加浅蓝父级选中样式**

将一级目录按钮的固定 `className` 改为以下条件样式：

```tsx
className={cn(
  'mb-2 flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-lg font-black tracking-[0] transition',
  childActive
    ? 'bg-blue-50/90 text-blue-700 shadow-[0_6px_16px_rgba(37,99,235,0.10)] ring-1 ring-inset ring-blue-200 dark:bg-blue-950/55 dark:text-blue-100 dark:ring-blue-800/80'
    : 'text-[#09265a] hover:bg-white/70 dark:text-slate-100 dark:hover:bg-slate-800/60',
)}
```

检测功能的 `SidebarNavButton` 保持现有深蓝渐变选中样式：

```tsx
bg-gradient-to-r from-[#001b43] to-[#063579] text-white
```

- [x] **Step 4: 让一级目录箭头跟随选中颜色**

将一级目录箭头类名改为：

```tsx
<ChevronRight
  className={cn(
    'h-4 w-4 shrink-0 transition-transform',
    childActive ? 'text-blue-500 dark:text-blue-300' : 'text-slate-400',
    expanded && 'rotate-90',
  )}
/>
```

箭头旋转仍由 `expanded` 控制，颜色由 `childActive` 控制。

- [x] **Step 5: 重新运行完整样式契约检查并确认通过**

Run:

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('unified_frontend/src/components/Sidebar.tsx','utf8');const required=['const childActive = activeChildGroupId === child.id','childActive','bg-blue-50/90','ring-blue-200','dark:bg-blue-950/55',\"childActive ? 'text-blue-500 dark:text-blue-300' : 'text-slate-400'\",'bg-gradient-to-r from-[#001b43] to-[#063579] text-white'];for(const value of required){if(!s.includes(value))process.exit(1)}"
```

Expected: 命令退出码为 0，证明父级浅蓝选中态、箭头选中颜色及子项深蓝选中态同时存在。

- [x] **Step 6: 执行统一前端构建验证**

Run:

```bash
cd unified_frontend
npm run build
```

Expected: TypeScript 编译和 Vite 构建成功，命令退出码为 0。

- [x] **Step 7: 执行统一前端代码检查**

Run:

```bash
cd unified_frontend
npm run lint
```

Expected: ESLint 命令退出码为 0；若存在与本次修改无关的历史警告，记录结果且不扩大修改范围。

- [x] **Step 8: 核对并提交本次实现**

Run:

```bash
git diff --check -- unified_frontend/src/components/Sidebar.tsx
git diff -- unified_frontend/src/components/Sidebar.tsx
git add -- unified_frontend/src/components/Sidebar.tsx docs/superpowers/plans/2026-07-29-sidebar-hierarchy-selection-background.md
git commit --only -m "style: 增加导航栏层级选中底色" -- unified_frontend/src/components/Sidebar.tsx docs/superpowers/plans/2026-07-29-sidebar-hierarchy-selection-background.md
```

Expected: 仅提交本计划和 `Sidebar.tsx` 的层级选中样式，不包含工作区原有未跟踪文件。
