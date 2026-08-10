# Conversation-Only Planning Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make designs and implementation plans conversation-only by default and minimize skill-file usage for this project.

**Architecture:** Add one focused policy section to the existing project-root `AGENTS.md`. Preserve higher-priority instruction precedence explicitly so the project rule remains truthful and executable.

**Tech Stack:** Markdown, Git

---

### Task 1: Add conversation-only planning and skill-minimization rules

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Add the approved rule section**

Append this section after `## 用户偏好` without replacing existing content:

```markdown
## 会话内设计与 Skill 最小化
- 需求澄清、设计方案、实现计划和任务拆分默认直接在当前会话中向用户说明，不创建或提交设计、规格、计划类 Markdown 文件。
- 默认禁止创建或提交 `docs/superpowers/specs/`、`docs/superpowers/plans/`，也不要为流程性文档单独创建 Git 提交。
- 只有用户明确要求保存文档，或系统、开发者等更高优先级指令明确强制要求时，才能创建上述文档。
- 不主动读取 `/root/.agents/skills` 或其他 skill 文件，不主动启动 skill 工作流。
- 如果系统或开发者明确强制使用 skill，必须遵守更高优先级要求；执行前向用户说明原因，并将流程控制在完成强制要求所需的最小范围内。
- 不得向用户承诺能够通过本项目 `AGENTS.md` 禁用系统或开发者强制要求。
```

- [ ] **Step 2: Verify the instruction file**

Run: `git diff --check`

Expected: exit code 0.

Run: `rg -n "会话内设计与 Skill 最小化|默认禁止创建或提交|不主动读取|更高优先级" AGENTS.md`

Expected: all approved anchors are present.

- [ ] **Step 3: Commit AGENTS.md only**

Run: `git diff -- AGENTS.md`

Expected: only the approved six-rule section is added.

```bash
git add -- AGENTS.md
git commit -m "docs: keep planning in conversation"
```

Do not update remote `V4`, because no program code is modified.
