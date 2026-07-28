# 统一认证密钥注入设计

## 问题

`scripts/start.sh` 把 `scripts/auth_secret` 注入 `guard_room` 和
`aivision`，但遗漏了签发登录 Token 的 `unified_backend`。当统一后端从
`.env` 或开发默认值读取另一份密钥时，下游服务会以
`invalid token signature` 拒绝请求，前端收到 401 后退出登录。

## 设计

继续以已忽略且权限为 600 的 `scripts/auth_secret` 作为唯一运行时密钥源。
冷启动脚本当前没有管理 `unified_backend`，并把 `guard_room` 的端口错误地保留
为 5000。将 `unified_backend` 作为第五个服务加入启动、停止、状态和健康检查，
固定使用 5000；将 `guard_room` 明确启动在 5001，并同步其健康检查端口。

将 `unified_backend` 加入 `needs_auth_secret()`，使启动脚本通过现有 tmux 环境
注入逻辑为 `unified_backend`、`guard_room`、`aivision` 提供同一密钥。
`security_vlm` 不直接校验 JWT，不加入注入范围。

统一后端默认使用系统 `python3`，允许通过 `UNIFIED_BACKEND_PYTHON` 覆盖；
缺少依赖时沿用现有启动失败诊断，并提示安装
`unified_backend/requirements.txt`。同步更新启动配置示例和部署说明。不修改、
读取、提交或输出 `scripts/auth_secret` 的内容，不新增项目依赖。

## 验证

1. 修改前运行脚本级行为检查，确认统一后端缺失、端口映射错误。
2. 修改后确认三个认证服务返回成功，`security_vlm` 返回失败。
3. 确认启动、状态、停止脚本包含统一后端，并分别使用 5000/5001。
4. 执行三个 Shell 脚本的 `bash -n`。
5. 检查 Git diff、提交范围和敏感信息，再更新并推送 V4 标签。
