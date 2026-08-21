# 福达视觉平台 - 新服务器部署清单

把项目整个目录拷到新机器后，按本清单一步步操作。完成后跑 `bash scripts/start.sh` 即可。

从旧版五服务目录原地升级并执行 `git pull` 后，先运行
`bash scripts/migrate_visual_integrations.sh`，把 Git 不管理的模型、真实配置和运行数据安全合并到
`AiVision/integrations/`。脚本遇到同名目标会停止，不会覆盖文件。

本清单中的路径以 `/srv/Fuda_CVPreject` 为例，请按实际位置替换。

---

## 0. 系统包

```bash
apt update && apt install -y tmux iproute2 curl wget vim nginx
```

## 1. 拷贝项目代码

从老机器同步代码（推荐 `rsync`）：

```bash
rsync -av --exclude '.venv' --exclude 'node_modules' --exclude '__pycache__' \
      --exclude '.git' --exclude 'db_backups' \
      <老机器>:/usr/zyy/Fuda_CVPreject/ /srv/Fuda_CVPreject/
```

## 2. Python：Conda（全部 Python 服务使用）

所有安装命令都必须带根目录的 `requirements-python311.lock`。该文件锁定当前生产目标：
Python 3.11、Linux x86_64，以及当前 PyTorch/CUDA 运行栈。不要在服务器上单独执行
无 `-c` 的 `pip install -r ...`，否则同一份代码可能安装出不同版本。

如果目标服务器不是 Linux x86_64，或 GPU 驱动不支持锁文件中的 CUDA 主版本，
需要先按目标平台重新生成锁文件并完成全量测试，不能直接绕过约束安装。

### 2.1 安装 Miniconda（如未装）

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
bash /tmp/miniconda.sh -b -p $HOME/miniconda3
source $HOME/miniconda3/etc/profile.d/conda.sh
conda init bash       # 让以后开新 shell 自动有 conda
```

### 2.2 创建 `aivision` 环境

```bash
source $HOME/miniconda3/etc/profile.d/conda.sh
conda create -n aivision python=3.11 -y
conda run -n aivision python -m pip install \
  -r /srv/Fuda_CVPreject/AiVision/requirements.txt \
  -c /srv/Fuda_CVPreject/requirements-python311.lock
```

Guard Room 的主进程依赖已经合并到 AiVision 项目依赖中，不再创建独立 Guard 环境。

### 2.3 创建 Security VLM 按需 worker 环境

```bash
conda create -n security_vlm python=3.11 -y
conda run -n security_vlm python -m pip install \
  -r /srv/Fuda_CVPreject/AiVision/integrations/security_vlm/requirements.txt \
  -c /srv/Fuda_CVPreject/requirements-python311.lock
```

这个环境只供 AiVision 在页面点击开启安检检测后拉起子进程，不运行 FastAPI、不监听端口。

### 2.4 安装 `unified_backend` 依赖

```bash
python3 -m pip install \
  -r /srv/Fuda_CVPreject/unified_backend/requirements.txt \
  -c /srv/Fuda_CVPreject/requirements-python311.lock
```

如需使用其他环境中的 Python，在 `scripts/cold_start.env` 中设置
`UNIFIED_BACKEND_PYTHON=/path/to/python`。

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

生产环境不要执行 `npm run dev` 或 `npm run preview`。`scripts/start.sh` 会调用
`scripts/build_frontend.sh`，在临时目录构建成功后原子切换 `dist`。

### 配置 Nginx 静态托管

示例配置中的项目路径是 `/usr/zyy/Fuda_CVPreject_V3`。如果实际部署在 `/srv/Fuda_CVPreject`，
安装时替换根目录：

```bash
sed 's#/usr/zyy/Fuda_CVPreject_V3#/srv/Fuda_CVPreject#g' \
  /srv/Fuda_CVPreject/deploy/nginx/aicv-unified-backend.conf \
  > /etc/nginx/conf.d/aicv-unified-backend.conf
nginx -t
systemctl enable --now nginx
systemctl reload nginx
```

生产公网只开放 Nginx 的 80/443；不再开放或监听前端开发端口 3000。

## 5. 业务配置文件（**必须从老机器拷贝**）

这些文件含密码/密钥/本地路径，**不在 git 里**，必须单独拷贝。

| 源（老机器） | 目标（新机器） | 用途 | 拷贝后需要改？ |
|-------------|---------------|------|---------------|
| `/usr/zyy/Fuda_CVPreject/AiVision/.env` | `/srv/Fuda_CVPreject/AiVision/.env` | MySQL 连接 | **是**，按新机器 MySQL 改 |
| `/usr/zyy/Fuda_CVPreject/auth/auth_users.json` | 同路径 | 首次迁移用的旧用户授权 | 否 |
| `/usr/zyy/Fuda_CVPreject/AiVision/integrations/guard_room/config/*.yaml`（如有自定义 `config.yaml`） | 同路径 | guard 配置 | 视情况 |
| `/usr/zyy/Fuda_CVPreject/AiVision/integrations/security_vlm/configs/config.yaml` | 同路径 | VLM 配置 | 视情况 |
| `/usr/zyy/Fuda_CVPreject/unified_frontend/.env.local` | 同路径（可选） | 前端端口/接口 | 视情况 |

示例：

```bash
# 拷 AiVision .env（含 MySQL）
scp <老机器>:/usr/zyy/Fuda_CVPreject/AiVision/.env /srv/Fuda_CVPreject/AiVision/.env
vi /srv/Fuda_CVPreject/AiVision/.env   # 改 MYSQL_DB_URL 等

# 拷首次迁移用的共享用户授权
mkdir -p /srv/Fuda_CVPreject/auth
scp <老机器>:/usr/zyy/Fuda_CVPreject/auth/auth_users.json \
    /srv/Fuda_CVPreject/auth/auth_users.json

# 拷 security_vlm 配置
scp <老机器>:/usr/zyy/Fuda_CVPreject/AiVision/integrations/security_vlm/configs/config.yaml \
    /srv/Fuda_CVPreject/AiVision/integrations/security_vlm/configs/config.yaml
```

## 6. 外部服务

- **MySQL**：AiVision 依赖。新机器要么本地装 MySQL（`apt install mysql-server`），要么 `.env` 里指向远端。务必能用 `.env` 中的账号 telnet 通端口。

## 6.5 AUTH_SECRET 管理

`unified_backend` 和 `aivision` 共用一个 JWT 签名密钥
`AUTH_SECRET`，由冷启动脚本统一管理：

| 项 | 说明 |
|---|------|
| 存储位置 | `scripts/auth_secret`（独立文件，已加入 `.gitignore`） |
| 文件权限 | `-rw-------`（600，仅 owner 可读） |
| 密钥长度 | 64 字符 hex（32 字节熵） |
| 生成方式 | `openssl rand -hex 32`，缺则降级为 `python3 secrets.token_hex(32)` 或 `/dev/urandom` |
| 注入范围 | `unified_backend` 和 `aivision` 两个 tmux 会话；前端不注入 |
| 注入方式 | tmux ≥ 3.2 用 `new -e KEY=VAL`，否则降级为 `export` prepend；自动判定 |

### 首次启动

```bash
bash scripts/start.sh
# → 检测到 scripts/auth_secret 不存在
# → 弹出确认提示（"会踢所有在线用户下线"），输入 yes 确认
# → 生成新密钥并写入文件
```

非交互场景（CI/自动化）跳过确认：

```bash
bash scripts/start.sh --yes
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

之后 `bash scripts/start.sh` 会复用该密钥。

### 强制刷新密钥（会踢下线所有用户）

```bash
rm scripts/auth_secret
bash scripts/start.sh    # 会再次弹出确认提示
```

### 验证注入是否正确

```bash
# unified_backend 应有
tmux show-environment -t unified_backend AUTH_SECRET

# aivision 应有
tmux show-environment -t aivision AUTH_SECRET

# 前端是 Nginx 静态文件，不存在 unified_frontend tmux 会话
tmux has-session -t unified_frontend 2>&1
```

### 注意

- **未注入时业务代码回落到 dev 默认值** `dev-aicv-auth-secret-change-me`（仅打 warning，不阻断启动）。生产部署务必让脚本生成或迁移过来。
- **`ps` / shell 历史 / `tmux capture-pane` 均不会泄漏密钥**：tmux 3.2+ 用 `-e` 时密钥仅作为子进程环境变量；降级模式下走 `send-keys` 直接进入会话内部，不进入父 shell 历史。

## 7. （可选）覆盖默认路径

如果上面有任何路径和默认不一致（比如 conda 装在 `/opt/conda`），创建 `cold_start.env`：

```bash
cp scripts/start.env.example scripts/cold_start.env
vi scripts/cold_start.env
```

## 8. 验证

```bash
bash scripts/start.sh
```

观察输出：
- **环境探测结果** 一段全是 `[ OK ]` 就说明依赖都对上了
- 任一服务出现 `[MISSING DEPS]` / `[MISSING CONFIG]` / `[FAIL]`，**控制台会直接给出修复命令**，按提示执行后再跑一次
- 最后启动汇总中 `aivision`、`unified_backend` 为 `READY`，
  `unified_frontend` 为 `BUILT` 即代码侧启动成功
- 再运行 `bash scripts/status.sh`，确认 Nginx 静态前端为“就绪”

后续日常运维：

```bash
bash scripts/status.sh         # 查询状态（含 health 就绪探测）
bash scripts/stop.sh           # 关停两个后端 tmux；不关 Nginx
bash scripts/start.sh --force  # 重建前端并重启两个后端
```

## 8.5 健康检查与就绪状态

冷启动脚本在端口监听后会进一步探测每个服务的 health 接口，判断**模型/runtime 是否真正就绪**：

| 服务 | Health URL | 判定规则 | 就绪条件 |
|------|-----------|---------|---------|
| aivision（含 Guard Room / Security VLM API） | `GET /api/v2/runtime/health` | `json:ok=true` | orchestrator 已启动 + 至少 1 个推理模型在跑 |
| unified_backend（5000） | `GET /api/health` | `json:status=ok` | 统一 API 服务已启动 |
| unified_frontend（Nginx 静态文件） | `GET http://127.0.0.1/` | `http2xx` | `dist/index.html` 存在且 Nginx 返回 2xx |

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

### status.sh 的健康列

`bash scripts/status.sh` 输出中的"健康"列：

- **就绪**：health 接口返回预期值
- **降级**：端口在但 health 不通过（模型未加载 / runtime 未就绪）
- **HTTPxxx**：health 请求返回非 2xx（503 = 服务自检失败）
- **-**：端口未监听，跳过探测

### 注意

- health 探测依赖 `curl` 或 `python3`（优先 curl）。两者都没有时退化为仅端口检查。
- Guard Room 与 Security VLM 子应用初始化失败时，AiVision 整体启动会失败，不会留下伪健康的独立端口。
- 如需跳过 health 探测只用端口检查：`bash scripts/start.sh --no-check`
