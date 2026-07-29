# 统一后端 Conda 环境自动发现设计

## 背景

生产服务器只允许拉取已发布代码，不能要求现场手工修改
`scripts/cold_start.env`。该服务器已经存在名为 `unified_backend`
的 Conda 环境，其 Python 路径为
`/root/miniconda3/envs/unified_backend/bin/python`。

当前 `scripts/start.sh` 默认选择调用脚本时 `PATH` 中的
`python3` 或 `python`，不会自动使用上述环境。

## 目标

拉取 V4 后执行 `bash scripts/start.sh` 时，统一后端按以下优先级选择运行时：

1. 用户显式配置的 `UNIFIED_BACKEND_PYTHON`；
2. 名为 `UNIFIED_BACKEND_ENV` 的 Conda 环境，默认名称为
   `unified_backend`；
3. 当前 `PATH` 中的系统 `python3` 或 `python`。

目标服务器不需要创建或修改项目内配置文件。

## 实现

在 `scripts/start.sh` 中复用现有 Conda 探测和
`conda_env_exists`，构造统一后端启动命令。Conda 环境存在时通过
`source <conda.sh> && conda activate <环境名> && python -m
unified_backend.run_server` 启动，避免硬编码 Conda 安装根目录。

显式 `UNIFIED_BACKEND_PYTHON` 保持最高优先级，兼容已经通过本地配置
指定 Python 的服务器。未安装 Conda或环境不存在时继续使用原有系统
Python 回退。

`scripts/start.env.example` 和 `run_guide.txt` 记录默认行为及可覆盖变量。

## 验证

新增不依赖 Bats 的 Bash 回归测试，通过受控的伪 Conda 环境检查三种
优先级分支生成的实际启动命令。随后执行：

- Shell 语法检查；
- 启动运行时选择回归测试；
- 统一后端测试；
- `scripts/start.sh --help` 冒烟测试。

