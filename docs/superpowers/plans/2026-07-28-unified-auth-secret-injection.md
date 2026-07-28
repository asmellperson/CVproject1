# Unified Auth Secret Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让冷启动脚本完整管理统一后端，并让统一后端、保安行为检测和 AiVision 使用同一份 JWT 签名密钥。

**Architecture:** 保留 `scripts/auth_secret` 作为唯一运行时密钥源，复用
`start_service()` 已有的 tmux 环境注入逻辑；将 `unified_backend` 纳入服务列表，
使用 5000，将 `guard_room` 明确迁移到 5001。同步启动、状态、停止和部署说明，
不改变密钥文件管理方式。

**Tech Stack:** Bash、tmux、Git。

---

### Task 1: 完整管理统一后端与认证密钥

**Files:**
- Modify: `scripts/start.sh:22-25`
- Modify: `scripts/start.sh:143-148`
- Modify: `scripts/start.sh:238-325`
- Modify: `scripts/start.sh:230-236`
- Modify: `scripts/start.sh:655-663`
- Modify: `scripts/status.sh:3-22`
- Modify: `scripts/stop.sh:3-20`
- Modify: `scripts/start.env.example:12-42`
- Modify: `scripts/DEPLOY.md:131-158`

- [ ] **Step 1: 运行修改前行为检查**

断言 `unified_backend`、`guard_room`、`aivision` 均需要密钥，
`security_vlm` 不需要；断言启动和状态脚本包含统一后端 5000、保安后端 5001，
停止脚本包含统一后端。预期修改前失败。

- [ ] **Step 2: 实施最小修改**

将分支改为：

```bash
unified_backend|guard_room|aivision) return 0 ;;
```

新增统一后端服务和健康检查，修正保安后端端口，并把相关注释、配置示例和部署
文档更新为五服务与三认证服务。

- [ ] **Step 3: 运行行为与语法验证**

重新运行 Step 1，预期全部断言通过；再运行：

```bash
bash -n scripts/start.sh
bash -n scripts/status.sh
bash -n scripts/stop.sh
```

预期退出码为 0。

- [ ] **Step 4: 检查并交付**

用 `git status --short`、`git diff --check` 和目标文件 diff 检查范围与敏感信息；
只提交本计划涉及的文件，更新 `V4` 指向 HEAD，强制推送远程标签并核验本地
HEAD、本地 V4、远程 V4 一致。
