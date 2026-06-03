# 生产公网入口说明

## 公网入口

运维侧只需要开放：

```text
80 / 443 -> 项目服务器 Nginx
```

不要把以下端口开放到公网：

```text
3000  Vite 开发服务
5000  unified_backend
5001  Guard Room
7862  AiVision
8000  Security VLM
```

## 项目服务器内部结构

```text
公网 80/443
  -> Nginx
      /                 -> /usr/zyy/Fuda_CVPreject_V3/unified_frontend/dist
      /api/             -> 127.0.0.1:5000
      /aivision/        -> 127.0.0.1:5000
      /security-vlm/    -> 127.0.0.1:5000

127.0.0.1:5000  unified_backend
127.0.0.1:5001  Guard Room
127.0.0.1:7862  AiVision
127.0.0.1:8000  Security VLM
```

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

内部检测服务只监听本机：

```bash
cd /usr/zyy/Fuda_CVPreject_V3/guard_room
python run_server.py --host 127.0.0.1 --port 5001

cd /usr/zyy/Fuda_CVPreject_V3/AiVision
uv run main.py --host 127.0.0.1 --port 7862

cd /usr/zyy/Fuda_CVPreject_V3/security_vlm
python src/main.py --config configs/config.yaml --host 127.0.0.1 --port 8000
```

统一后端只给 Nginx 本机访问：

```bash
cd /usr/zyy/Fuda_CVPreject_V3
python -m unified_backend.run_server --host 127.0.0.1 --port 5000
```

## 验证

本机验证统一后端：

```bash
curl -i http://127.0.0.1:5000/api/health
```

公网验证：

```bash
curl -i https://aicv.fudar.com/api/health
```

应返回：

```json
{"status":"ok","service":"unified_backend","port":5000}
```
