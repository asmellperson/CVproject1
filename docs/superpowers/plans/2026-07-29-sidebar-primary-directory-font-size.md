# 导航栏一级目录字号调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将侧边栏六个事业部一级目录统一从 16px 放大至 18px，并保持二级检测能力名称为 15px。

**Architecture:** 复用 `Sidebar` 中六个一级目录共用的按钮样式，只替换该样式上的 Tailwind 字号类。菜单数据、权限过滤、折叠状态和二级导航组件均不改动。

**Tech Stack:** React 19、TypeScript、Tailwind CSS 3、Vite 7

---

### Task 1: 调整一级目录字号

**Files:**
- Modify: `unified_frontend/src/components/Sidebar.tsx:162`

- [x] **Step 1: 运行修改前样式契约检查并确认失败**

Run:

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('unified_frontend/src/components/Sidebar.tsx','utf8');const button=s.match(/className=\"mb-2 flex w-full[^\\n]+\"/);if(!button||!button[0].includes('text-lg'))process.exit(1)"
```

Expected: 命令退出码为 1，因为一级目录按钮当前使用 `text-base`。

- [x] **Step 2: 实现最小样式修改**

将一级目录按钮类名中的：

```tsx
text-base
```

替换为：

```tsx
text-lg
```

不要修改同一文件中 `SidebarNavButton` 的 `text-[15px]`，从而保持二级检测能力名称为 15px。

- [x] **Step 3: 重新运行样式契约检查并确认通过**

Run:

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('unified_frontend/src/components/Sidebar.tsx','utf8');const button=s.match(/className=\"mb-2 flex w-full[^\\n]+\"/);if(!button||!button[0].includes('text-lg')||button[0].includes('text-base'))process.exit(1);if(!s.includes(\"'group relative flex w-full items-center gap-4 rounded-xl px-4 py-3 text-[15px] font-semibold transition-all'\"))process.exit(1)"
```

Expected: 命令退出码为 0，证明一级目录为 `text-lg`，二级导航仍为 `text-[15px]`。

- [x] **Step 4: 执行统一前端构建验证**

Run:

```bash
cd unified_frontend
npm run build
```

Expected: TypeScript 编译和 Vite 构建成功，命令退出码为 0。

- [x] **Step 5: 执行统一前端代码检查**

Run:

```bash
cd unified_frontend
npm run lint
```

Expected: ESLint 检查成功，命令退出码为 0；若项目存在与本次修改无关的历史问题，记录完整错误且不扩大本次修改范围。

- [x] **Step 6: 核对并提交本次实现**

Run:

```bash
git diff --check -- unified_frontend/src/components/Sidebar.tsx
git diff -- unified_frontend/src/components/Sidebar.tsx
git add -- unified_frontend/src/components/Sidebar.tsx docs/superpowers/plans/2026-07-29-sidebar-primary-directory-font-size.md
git commit --only -m "style: 放大导航栏一级目录字号" -- unified_frontend/src/components/Sidebar.tsx docs/superpowers/plans/2026-07-29-sidebar-primary-directory-font-size.md
```

Expected: 仅提交本计划与 `Sidebar.tsx` 的字号修改，不包含工作区原有的未跟踪文件。
