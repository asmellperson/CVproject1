# 福达 AI 模型服务部署

## Swift 部署与格式约束

独立入口为 `AiVision/connectors/qwen/swift_deploy.py`，适配 `ms-swift 4.4.2`、`vLLM 0.27.1`，启动参数使用 `--infer_backend vllm` 和异步引擎。该脚本可单独复制到模型服务器，依赖沿用模型环境中的 FastAPI、Pydantic 和 vLLM 已依赖的 `jsonschema`；不导入项目设置或业务数据库。版本不匹配时拒绝启动。

Swift 的 [4.4.2 请求协议](https://github.com/modelscope/ms-swift/blob/v4.4.2/swift/infer_engine/protocol.py)未声明标准 `response_format`，[vLLM 适配层](https://github.com/modelscope/ms-swift/blob/v4.4.2/swift/infer_engine/vllm_engine.py)只映射正则约束。部署入口严格校验该请求字段，使用 vLLM 的 `StructuredOutputsParams(json=完整Schema)` 或 `json_object=True`，经当前请求的 `pre_infer_hook` 设置生成参数。它保留原端口锁定、模型与适配器、采样和模板参数、模型鉴权及 logprobs 检查。非法 Schema、约束冲突、后端不支持或未执行约束钩子时明确失败。

校验响应只返回固定消息和错误类型，包装层异常日志不包含异常正文；上游后处理负责响应转换和统计，请求日志及 JSONL 中的正文使用脱敏占位。模型服务器其他框架、插件及启动日志需结合现场配置核对。

### 依赖与请求协议检查

进入模型服务实际使用的 Python 环境，在已同步代码的项目根目录执行：

```bash
cd /srv/Fuda_CVPreject
python AiVision/connectors/qwen/swift_deploy.py --check
```

`--check` 在加载模型前核对依赖版本、结构化输出参数和真实 SDK 请求类型，不创建推理引擎或启动 HTTP 服务。检查通过后，部署环境仍需通过实际生成请求验收。

### 部署与回滚

使用独立脚本启动模型服务的部署，可备份并替换对应入口：

```bash
cp -n -- /srv/fuda_llm/scripts/swift_deploy_fixed_port.py /srv/fuda_llm/scripts/swift_deploy_fixed_port.py.bak-schema
cp -- /srv/Fuda_CVPreject/AiVision/connectors/qwen/swift_deploy.py /srv/fuda_llm/scripts/swift_deploy_fixed_port.py
```

保持现场的模型、适配器、采样及显式 `--port` 参数，按原运行方式重启模型服务。业务前后端使用已保存的模型连接设置。

回滚时恢复备份，再按原方式重启模型服务：

```bash
cp -- /srv/fuda_llm/scripts/swift_deploy_fixed_port.py.bak-schema /srv/fuda_llm/scripts/swift_deploy_fixed_port.py
```

### 实际接口验收

向实际模型服务的 `/v1/chat/completions` 发送请求，使用服务接受的模型标识及部署环境要求的鉴权，分别核对：

- `response_format.type=json_object` 时，即使提示要求普通文字，输出仍应是有效 JSON 对象。
- `response_format.type=json_schema` 时，输出应满足请求中的完整严格 Schema，包括字段类型、必填字段和额外字段限制；提示与结构冲突时仍须符合 Schema。
- 非法 Schema 应被 HTTP 400/422 拒绝，格式约束冲突或后端不支持时应明确失败。
- 使用对照请求和服务实际返回的 `usage` 核对输出长度限制；缺少足够证据时保留未确认状态。

依赖检查通过、HTTP 200 和单次结构合规只证明对应检查结果。助手的任务分类、工具执行、配置回读及持续多轮语义需通过实际业务接口分别验收。
