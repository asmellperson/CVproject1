# 导航栏父子选中配色交换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将一级目录选中态改为深蓝渐变，将二级检测功能选中态改为浅蓝底色。

**Architecture:** 保留现有 `childActive`、`activeChildGroupId`、`active` 和 `expanded` 状态逻辑，仅交换父子两个选中分支中的 Tailwind 配色类。一级目录箭头同步改为适合深色背景的浅色，其他样式和交互保持不变。

**Tech Stack:** React 19、TypeScript、Tailwind CSS 3、Vite 7

---

### Task 1: 交换父子选中配色

**Files:**
- Modify: `unified_frontend/src/components/Sidebar.tsx:149-331`

- [x] **Step 1: 运行修改前配色契约检查并确认失败**

Run:

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('unified_frontend/src/components/Sidebar.tsx','utf8');if(!/childActive\\s*\\? 'bg-gradient-to-r from-\\[#001b43\\]/.test(s))process.exit(1);if(!/active\\s*\\? 'bg-blue-50\\/90/.test(s))process.exit(1)"
```

Expected: 命令退出码为 1，因为当前一级目录仍为浅蓝选中态，二级检测功能仍为深蓝选中态。

- [x] **Step 2: 将一级目录选中态改为深蓝渐变**

保留一级目录未选中分支，将 `childActive` 的选中分支替换为：

```tsx
childActive
  ? 'bg-gradient-to-r from-[#001b43] to-[#063579] text-white shadow-[0_12px_26px_rgba(0,27,67,0.22)] dark:from-blue-600 dark:to-cyan-500 dark:shadow-blue-950/35'
  : 'text-[#09265a] hover:bg-white/70 dark:text-slate-100 dark:hover:bg-slate-800/60'
```

- [x] **Step 3: 调整一级目录箭头的深色背景对比度**

将箭头颜色分支改为：

```tsx
childActive ? 'text-blue-100 dark:text-white' : 'text-slate-400'
```

箭头旋转继续由 `expanded` 控制。

- [x] **Step 4: 将二级检测功能选中态改为浅蓝**

保留 `SidebarNavButton` 未选中分支，将 `active` 的选中分支替换为：

```tsx
active
  ? 'bg-blue-50/90 text-blue-700 shadow-[0_6px_16px_rgba(37,99,235,0.10)] ring-1 ring-inset ring-blue-200 dark:bg-blue-950/55 dark:text-blue-100 dark:ring-blue-800/80'
  : 'text-[#40557a] hover:bg-white hover:text-[#09265a] hover:shadow-[0_8px_20px_rgba(31,58,97,0.08)] dark:text-slate-300 dark:hover:bg-slate-800/80 dark:hover:text-white'
```

- [x] **Step 5: 重新运行完整配色契约检查并确认通过**

Run:

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('unified_frontend/src/components/Sidebar.tsx','utf8');const checks=[/childActive\\s*\\? 'bg-gradient-to-r from-\\[#001b43\\] to-\\[#063579\\] text-white/,/childActive \\? 'text-blue-100 dark:text-white' : 'text-slate-400'/,/active\\s*\\? 'bg-blue-50\\/90 text-blue-700/,/'bg-blue-50\\/90 text-blue-700[^']*ring-blue-200/,/'bg-gradient-to-r from-\\[#001b43\\][^']*dark:to-cyan-500/];for(const check of checks){if(!check.test(s))process.exit(1)}"
```

Expected: 命令退出码为 0，证明一级目录使用深蓝渐变，二级检测功能使用浅蓝底色，箭头对比度样式存在。

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
git add -- unified_frontend/src/components/Sidebar.tsx docs/superpowers/plans/2026-07-29-sidebar-selection-color-swap.md
git commit --only -m "style: 交换导航栏父子选中配色" -- unified_frontend/src/components/Sidebar.tsx docs/superpowers/plans/2026-07-29-sidebar-selection-color-swap.md
```

Expected: 仅提交本计划和 `Sidebar.tsx` 的配色交换，不包含工作区原有未跟踪文件。
