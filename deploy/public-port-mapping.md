# 生产公网入口说明

## 公网入口

运维侧只需要开放：

```text
80 / 443 -> 项目服务器 Nginx
```

以下两个应用端口都只允许本机访问，不要开放到公网：

```text
5000  unified_backend
7862  AiVision（含 Guard Room 与 Security VLM API）
```

`3000` 仅供开发人员手动执行 `npm run dev` 时使用，生产启动脚本不会监听该端口。

Guard Room 和 Security VLM 不再监听 5001、8000。

## 项目服务器内部结构

```text
公网 80/443
  -> Nginx
      /                 -> unified_frontend/dist
      /api/             -> 127.0.0.1:5000
      /aivision/        -> 127.0.0.1:5000
      /security-vlm/    -> 127.0.0.1:5000

127.0.0.1:5000  unified_backend
127.0.0.1:7862  AiVision 统一视觉业务层
```

统一后端把保安、安检和其他检测请求统一转给 AiVision；AiVision 在同一进程内调用对应模块，
不会再发起到 Guard Room 或 Security VLM Web 服务的 HTTP 请求。

## 项目侧构建

```bash
cd /usr/zyy/Fuda_CVPreject_V3/unified_frontend
npm run build
```

构建产物目录：

```text
/usr/zyy/Fuda_CVPreject_V3/unified_frontend/dist
```

## 服务启动方式

```bash
cd /usr/zyy/Fuda_CVPreject_V3
bash scripts/start.sh
```

启动脚本会先在临时目录完成前端构建，再原子切换 `dist`；构建失败时保留旧版本，
也不会启动后端，避免前后端版本不一致。前端不再创建 tmux 会话。

手动排障时，AiVision 必须使用 Conda：

```bash
cd /usr/zyy/Fuda_CVPreject_V3/AiVision
conda activate aivision
python main.py --host 127.0.0.1 --port 7862
```

## 验证

```bash
curl -i http://127.0.0.1:5000/api/health
curl -i https://aicv.fudar.com/api/health
```

统一后端应返回：

```json
{"status":"ok","service":"unified_backend","port":5000}
```
