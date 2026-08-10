# Project Frontend and V4 Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-level instructions that enforce frontend consistency with existing detection pages and automatically publish verified program-code changes to remote tag `V4`.

**Architecture:** Extend the existing root `AGENTS.md` with two focused policy sections. Keep the rules project-local, preserve all existing instructions, and explicitly exclude documentation-only changes from automatic `V4` publication.

**Tech Stack:** Markdown, Git

---

### Task 1: Add the project rules

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Add frontend consistency rules after the existing frontend rules**

Add this section without replacing existing content:

```markdown
## 前端一致性与参考实现
- 修改或新增前端页面、组件、交互或功能前，必须先查找并阅读项目中业务最相近的检测功能页面和内部逻辑实现。
- 对照内容至少包括：页面布局、组件结构、命名方式、状态管理、接口调用、加载与错误状态、权限控制和保存流程。
- 用户描述不完整时，默认沿用同类检测功能的现有模式，不要自行发明新的布局、按钮、弹窗、编辑模式或交互层级。
- 优先复用共享组件和现有实现。若同类功能存在多种不同模式，或确实需要偏离现有模式，修改前先说明参考对象、计划保持一致的部分、差异及原因，并取得用户确认。
- 修复问题时优先定位并修复根因，不要通过新增界面元素或额外操作步骤来掩盖原有错误。
- 修改完成后，必须说明本次参考了哪些同类页面或功能、哪些部分保持一致，以及是否存在经过确认的差异。
```

- [ ] **Step 2: Add automatic V4 publication rules**

Add this section near the existing Git worktree rules:

```markdown
## 程序代码完成后的 V4 自动发布
- 只有本次任务修改了程序代码，并且已完成相应验证和本地提交后，才自动更新远程 `V4` 标签。
- 程序代码包括前后端源代码、可执行脚本，以及直接影响运行行为的代码文件。仅修改 `AGENTS.md`、Markdown 文档、设计规格、实现计划或说明性配置时，不更新 `V4`。
- 发布时不要创建新分支：执行 `git tag -f V4 HEAD`，再执行 `git push --force origin HEAD:refs/tags/V4`。
- 推送后必须比较 `git rev-parse HEAD` 与 `git ls-remote --tags origin refs/tags/V4` 返回的提交；两者完全一致后才能说明发布成功。
- 如果提交、推送或远程校验失败，必须明确报告失败原因，不得宣称已经发布，也不得修改远程分支或其他标签来规避问题。
- 提交与发布只包含当前任务范围内的程序代码，不得夹带用户已有的无关工作区修改。
```

- [ ] **Step 3: Verify wording and scope**

Run: `git diff --check`

Expected: exit code 0.

Run: `rg -n "前端一致性与参考实现|程序代码完成后的 V4 自动发布|git push --force origin HEAD:refs/tags/V4|仅修改.*不更新" AGENTS.md`

Expected: all policy anchors are present.

- [ ] **Step 4: Inspect and commit documentation only**

Run: `git diff -- AGENTS.md docs/superpowers/plans/2026-08-10-project-frontend-and-v4-rules.md`

Expected: only the existing worktree preference plus the two approved rule sections and this plan are present.

```bash
git add -- AGENTS.md
git commit -m "docs: enforce frontend consistency and V4 publishing"
```

Do not move or push `V4`, because this task changes project instructions and documentation only.
