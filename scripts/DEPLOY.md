# 福达视觉平台 - 新服务器部署清单

把项目整个目录拷到新机器后，按本清单一步步操作。完成后跑 `bash scripts/cold_start.sh` 即可。

本清单中的路径以 `/srv/Fuda_CVPreject` 为例，请按实际位置替换。

---

## 0. 系统包

```bash
apt update && apt install -y tmux iproute2 curl wget vim
```

## 1. 拷贝项目代码

从老机器同步代码（推荐 `rsync`）：

```bash
rsync -av --exclude '.venv' --exclude 'node_modules' --exclude '__pycache__' \
      --exclude '.git' --exclude 'db_backups' \
      <老机器>:/usr/zyy/Fuda_CVPreject/ /srv/Fuda_CVPreject/
```

## 2. Python：conda（guard_room 和 security_vlm 用）

### 2.1 安装 Miniconda（如未装）

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
bash /tmp/miniconda.sh -b -p $HOME/miniconda3
source $HOME/miniconda3/etc/profile.d/conda.sh
conda init bash       # 让以后开新 shell 自动有 conda
```

### 2.2 创建 `guard_room` 环境

```bash
source $HOME/miniconda3/etc/profile.d/conda.sh
conda create -n guard_room python=3.10 -y
conda activate guard_room
pip install -r /srv/Fuda_CVPreject/guard_room/requirements.txt
```

> 已知坑：如启动时报 `ModuleNotFoundError: No module named 'timm'`，说明
> requirements.txt 没列全。手动补：`pip install timm`。

### 2.3 创建 `security_vlm` 环境

```bash
conda create -n security_vlm python=3.10 -y
conda activate security_vlm
pip install -r /srv/Fuda_CVPreject/security_vlm/requirements.txt
```

## 3. Python：uv（AiVision 用）

```bash
# 装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env 2>/dev/null || export PATH=$HOME/.local/bin:$PATH

# 同步 AiVision 依赖
cd /srv/Fuda_CVPreject/AiVision
uv sync
```

## 4. Node（unified_frontend 用，任选一种）

### 方案 A：系统 node（推荐，最省事）

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
node -v   # 应输出 v20.x
```

### 方案 B：nvm

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source ~/.nvm/nvm.sh
nvm install 20
nvm use 20
```

### 安装前端依赖

```bash
cd /srv/Fuda_CVPreject/unified_frontend
npm ci          # 用 package-lock.json 严格安装；首次也可用 npm install
```

## 5. 业务配置文件（**必须从老机器拷贝**）

这些文件含密码/密钥/本地路径，**不在 git 里**，必须单独拷贝。

| 源（老机器） | 目标（新机器） | 用途 | 拷贝后需要改？ |
|-------------|---------------|------|---------------|
| `/usr/zyy/Fuda_CVPreject/AiVision/.env` | `/srv/Fuda_CVPreject/AiVision/.env` | MySQL 连接 | **是**，按新机器 MySQL 改 |
| `/usr/zyy/Fuda_CVPreject/guard_room/config/auth_users.json` | 同路径 | 用户授权 | 否 |
| `/usr/zyy/Fuda_CVPreject/guard_room/config/*.yaml`（如有自定义 `config.yaml`） | 同路径 | guard 配置 | 视情况 |
| `/usr/zyy/Fuda_CVPreject/security_vlm/configs/config.yaml` | 同路径 | VLM 配置 | 视情况 |
| `/usr/zyy/Fuda_CVPreject/unified_frontend/.env.local` | 同路径（可选） | 前端端口/接口 | 视情况 |

示例：

```bash
# 拷 AiVision .env（含 MySQL）
scp <老机器>:/usr/zyy/Fuda_CVPreject/AiVision/.env /srv/Fuda_CVPreject/AiVision/.env
vi /srv/Fuda_CVPreject/AiVision/.env   # 改 MYSQL_DB_URL 等

# 拷 guard_room 用户授权
mkdir -p /srv/Fuda_CVPreject/guard_room/config
scp <老机器>:/usr/zyy/Fuda_CVPreject/guard_room/config/auth_users.json \
    /srv/Fuda_CVPreject/guard_room/config/auth_users.json

# 拷 security_vlm 配置
scp <老机器>:/usr/zyy/Fuda_CVPreject/security_vlm/configs/config.yaml \
    /srv/Fuda_CVPreject/security_vlm/configs/config.yaml
```

## 6. 外部服务

- **MySQL**：AiVision 依赖。新机器要么本地装 MySQL（`apt install mysql-server`），要么 `.env` 里指向远端。务必能用 `.env` 中的账号 telnet 通端口。

## 6.5 AUTH_SECRET 管理

`guard_room` 和 `aivision` 共用一个 JWT 签名密钥 `AUTH_SECRET`，由冷启动脚本统一管理：

| 项 | 说明 |
|---|------|
| 存储位置 | `scripts/auth_secret`（独立文件，已加入 `.gitignore`） |
| 文件权限 | `-rw-------`（600，仅 owner 可读） |
| 密钥长度 | 64 字符 hex（32 字节熵） |
| 生成方式 | `openssl rand -hex 32`，缺则降级为 `python3 secrets.token_hex(32)` 或 `/dev/urandom` |
| 注入范围 | 仅 `guard_room` 和 `aivision` 两个 tmux 会话；前端和 VLM 不注入 |
| 注入方式 | tmux ≥ 3.2 用 `new -e KEY=VAL`，否则降级为 `export` prepend；自动判定 |

### 首次启动

```bash
bash scripts/cold_start.sh
# → 检测到 scripts/auth_secret 不存在
# → 弹出确认提示（"会踢所有在线用户下线"），输入 yes 确认
# → 生成新密钥并写入文件
```

非交互场景（CI/自动化）跳过确认：

```bash
bash scripts/cold_start.sh --yes
```

### 后续启动

脚本会自动复用 `scripts/auth_secret`，**用户登录态不受影响**。
启动汇总中会显示 `AUTH_SECRET = 复用 (sha256:xxxxxxxx)`，sha256 前 8 位是指纹（不暴露原文）。

### 跨服务器迁移（保持登录态一致）

如果想让新老服务器共享同一登录态（避免用户重登）：

```bash
# 在老机器上
scp /usr/zyy/Fuda_CVPreject/scripts/auth_secret \
    <新机器>:/srv/Fuda_CVPreject/scripts/auth_secret

# 在新机器上确认权限
chmod 600 /srv/Fuda_CVPreject/scripts/auth_secret
```

之后 `bash scripts/cold_start.sh` 会复用该密钥。

### 强制刷新密钥（会踢下线所有用户）

```bash
rm scripts/auth_secret
bash scripts/cold_start.sh    # 会再次弹出确认提示
```

### 验证注入是否正确

```bash
# guard_room 应有
tmux show-environment -t guard_room AUTH_SECRET

# aivision 应有
tmux show-environment -t aivision AUTH_SECRET

# security_vlm / unified_frontend 应报 unknown variable
tmux show-environment -t security_vlm AUTH_SECRET 2>&1
tmux show-environment -t unified_frontend AUTH_SECRET 2>&1
```

### 注意

- **未注入时业务代码回落到 dev 默认值** `dev-aicv-auth-secret-change-me`（仅打 warning，不阻断启动）。生产部署务必让脚本生成或迁移过来。
- **`ps` / shell 历史 / `tmux capture-pane` 均不会泄漏密钥**：tmux 3.2+ 用 `-e` 时密钥仅作为子进程环境变量；降级模式下走 `send-keys` 直接进入会话内部，不进入父 shell 历史。

## 7. （可选）覆盖默认路径

如果上面有任何路径和默认不一致（比如 conda 装在 `/opt/conda`），创建 `cold_start.env`：

```bash
cp scripts/cold_start.env.example scripts/cold_start.env
vi scripts/cold_start.env
```

## 8. 验证

```bash
bash scripts/cold_start.sh
```

观察输出：
- **环境探测结果** 一段全是 `[ OK ]` 就说明 4 个依赖都对上了
- 任一服务出现 `[MISSING DEPS]` / `[MISSING CONFIG]` / `[FAIL]`，**控制台会直接给出修复命令**，按提示执行后再跑一次
- 最后 **启动汇总** 表里 4 个服务都是 `READY` 即部署成功

后续日常运维：

```bash
bash scripts/cold_status.sh    # 查询状态（含 health 就绪探测）
bash scripts/cold_stop.sh      # 关停全部
bash scripts/cold_start.sh --force   # 全部重启
```

## 8.5 健康检查与就绪状态

冷启动脚本在端口监听后会进一步探测每个服务的 health 接口，判断**模型/runtime 是否真正就绪**：

| 服务 | Health URL | 判定规则 | 就绪条件 |
|------|-----------|---------|---------|
| guard_room | `GET /api/health` | `json:ready=true` | runtime 运行中且无错误 |
| aivision | `GET /api/v2/runtime/health` | `json:ok=true` | orchestrator 已启动 + 至少 1 个推理模型在跑 |
| security_vlm | `GET /health` | `json:running=true` | 服务主循环已启动 |
| unified_frontend | `GET /` | `http2xx` | HTTP 200 即可 |

### 三种启动状态

| 状态 | 含义 | 颜色 |
|------|------|------|
| **READY** | 端口监听 + health 通过 | 绿 |
| **DEGRADED** | 端口监听但 health 未就绪（模型可能还在加载） | 黄 |
| **CRASHED** | tmux 起了但端口未监听 | 红 |

DEGRADED 不算启动失败（exit 0），因为模型加载通常需要几十秒到几分钟。
如果持续 DEGRADED，说明模型加载失败或外部依赖不可达，需 `tmux attach` 排查。

### 探测参数（可在 cold_start.env 覆盖）

```bash
HEALTH_PROBE_MAX=10          # 最多轮询次数
HEALTH_PROBE_INTERVAL=2      # 每次间隔秒
HEALTH_PROBE_TIMEOUT=3       # 单次 HTTP 超时秒
```

### cold_status.sh 的健康列

`bash scripts/cold_status.sh` 输出中的"健康"列：

- **就绪**：health 接口返回预期值
- **降级**：端口在但 health 不通过（模型未加载 / runtime 未就绪）
- **HTTPxxx**：health 请求返回非 2xx（503 = 服务自检失败）
- **-**：端口未监听，跳过探测

### 注意

- health 探测依赖 `curl` 或 `python3`（优先 curl）。两者都没有时退化为仅端口检查。
- `guard_room` 的 health 接口在 runtime 出错时返回 HTTP 503 + `{"status": "error", ...}`，便于负载均衡器自动摘除。
- 如需跳过 health 探测只用端口检查：`bash scripts/cold_start.sh --no-check`
