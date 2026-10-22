# 福达 AI 助手分层诊断

诊断入口为 `AiVision/tests/assistant_diagnostics/`，在 CVproject1 项目根目录运行。使用项目现有 Python 环境和依赖，命令行入口不依赖 pytest，不启动 API、摄像头或推理 Worker。

## 确认模型服务与参数合同

在监听 18100 的模型服务器上执行以下命令，无需启动或重启前后端、模型服务：

```bash
conda run --no-capture-output -n aivision \
  python -m AiVision.tests.assistant_diagnostics \
  --base-url http://127.0.0.1:18100/v1 \
  --model fuda-qwen38-27b \
  --layers service \
  --repeats 3 \
  --output /tmp/fuda-ai-service-inspection
```

`service` 层读取版本接口、模型目录及 OpenAPI 声明；本机回环地址还会读取监听 PID、程序入口摘要、解码参数标记和候选 Python 环境的安装包版本，包含 `ms_swift`。`inference_backend_hints` 仅记录 `--infer_backend` 中固定白名单内的后端名称，属于命令行证据。它不读取进程环境变量、不输出完整启动命令、源码、密钥、模型路径或响应正文，也不执行服务程序或加载模型。元数据请求禁止跟随重定向，并限制响应大小。

报告中的 HTTP Server、OpenAPI `application_version`、安装包版本及实际服务版本分别保留来源。`uvicorn`、应用版本 `0.1.0`、已安装的 vLLM 包或对外模型别名，均不能单独证明正在运行的推理引擎和权重。容器代理、权限不足或接口缺失时保留未确认状态。源码关键词仅检查直接 Python 入口，不代表完整调用链。

五项固定探针每项重复三次，共 15 次串行请求，复用原 QwenClient 的并发名额、超时及非思考请求参数：

| 探针 | 检查内容 |
|---|---|
| `json_object_conflict` | 用户要求普通文字时，JSON 对象模式是否实际约束输出 |
| `json_schema_conflict` | 同一要求下，输出是否满足固定的严格 Schema |
| `invalid_schema_rejection` | 非法 Schema 是否被 HTTP 400/422 拒绝；HTTP 200 不计为正确拒绝 |
| `max_tokens_control` | 固定英文单词请求在 128 token 上限下是否产生足够的对照输出 |
| `max_tokens_one` | 相同输入的 1 token 上限是否生效；没有 usage 或有效对照时标记 `inconclusive` |

报告根字段 `service_inspection` 保存脱敏身份和接口证据，`layers.service.rows` 保存逐次行为。`service_contract` 表示客户端可见的合同检查失败。未知与失败分别记录；预期的非法 Schema 拒绝属于探针通过，不代表模型调用故障。声明包含 `response_format` 不证明已透传，接口输出符合样例也不能证明所有 Schema 均受约束；温度及其他参数的内部透传仍需核对服务实现。

服务端合同参考：[vLLM 结构化输出](https://docs.vllm.ai/en/stable/features/structured_outputs/)、[llama.cpp 服务接口](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)、[Ollama 兼容接口](https://docs.ollama.com/api/openai-compatibility)。应结合实际服务及版本判断参数格式；诊断不会自动更改生产客户端或服务配置。

## Swift 部署与格式约束

独立入口为 `AiVision/connectors/qwen/swift_deploy.py`，适配 `ms-swift 4.4.2`、`vLLM 0.27.1`，要求原启动参数使用 `--infer_backend vllm` 和异步引擎。该脚本不导入项目设置或业务数据库，可单独复制到模型服务器；依赖沿用模型环境中的 FastAPI、Pydantic 和 vLLM 已依赖的 `jsonschema`。版本不匹配时拒绝启动。

Swift 的 [4.4.2 请求协议](https://github.com/modelscope/ms-swift/blob/v4.4.2/swift/infer_engine/protocol.py)未声明标准 `response_format`，[vLLM 适配层](https://github.com/modelscope/ms-swift/blob/v4.4.2/swift/infer_engine/vllm_engine.py)只映射正则约束。部署入口补充该请求字段的严格校验，使用 vLLM 的 `StructuredOutputsParams(json=完整Schema)` 或 `json_object=True`，经当前请求的 `pre_infer_hook` 设置生成参数。它保留原端口锁定、模型与适配器、采样和模板参数、模型鉴权及 logprobs 检查。非法 Schema、约束冲突、后端不支持或未执行约束钩子时明确失败，不回退到普通生成。

校验响应只返回固定消息和错误类型，包装层异常日志不包含异常正文；上游后处理仍负责响应转换和统计，但请求日志及 JSONL 中的正文使用脱敏占位。模型服务器其他框架、插件及启动日志需结合现场配置检查。该入口的本地回归使用真实 ASGI/Pydantic 与模拟引擎，不能替代 GPU 解码验收。

在项目代码已同步到 `/srv/Fuda_CVPreject` 后，先使用正在运行的模型服务的 Python 解释器检查依赖和真实 SDK 请求类型。以下示例 PID 为 `497332`，如已重启应使用当前监听 PID；不要改用业务后端的 Python 环境。

```bash
cd /srv/Fuda_CVPreject
python - <<'PY'
from pathlib import Path
import subprocess

process = Path('/proc/497332')
arguments = (process / 'cmdline').read_bytes().decode(errors='replace').split('\0')
interpreter = Path(arguments[0])
if not interpreter.is_absolute():
    interpreter = process / 'exe'
script = Path('AiVision/connectors/qwen/swift_deploy.py').resolve()
subprocess.run([str(interpreter), str(script), '--check'], check=True)
PY
```

`--check` 不创建推理引擎、不加载模型或启动 HTTP 服务。检查通过后，备份并替换原独立脚本，保持原启动命令及参数：

```bash
cp -n -- /srv/fuda_llm/scripts/swift_deploy_fixed_port.py /srv/fuda_llm/scripts/swift_deploy_fixed_port.py.bak-schema
cp -- /srv/Fuda_CVPreject/AiVision/connectors/qwen/swift_deploy.py /srv/fuda_llm/scripts/swift_deploy_fixed_port.py
```

按原运行方式重启 18100 模型服务，使部署脚本生效，业务前后端无需重启。先运行 15 项服务探针，再根据报告继续模型分类和持续多轮测试：

```bash
cd /srv/Fuda_CVPreject
conda run --no-capture-output -n aivision \
  python -m AiVision.tests.assistant_diagnostics \
  --base-url http://127.0.0.1:18100/v1 \
  --model fuda-qwen38-27b --layers service --repeats 3 \
  --output /tmp/fuda-ai-swift-format-check
```

格式验收检查 JSON 对象约束、Schema 约束和非法 Schema 拒绝各 `3/3`，并保持输出长度两组对照通过。HTTP 200、依赖检查通过和结构合规均不能替代任务分类、工具行为及多轮语义指标。

报告保存在 `/tmp/fuda-ai-swift-format-check/report.md` 和 `results.json`。报告已转存后，可用 `rm -rf -- /tmp/fuda-ai-swift-format-check` 清理该次输出。回滚时将备份复制回原脚本，再按原方式重启模型服务：

```bash
cp -- /srv/fuda_llm/scripts/swift_deploy_fixed_port.py.bak-schema /srv/fuda_llm/scripts/swift_deploy_fixed_port.py
```

## 在 Qwen 所在服务器运行

```bash
python -m AiVision.tests.assistant_diagnostics \
  --base-url http://127.0.0.1:18100/v1 \
  --model fuda-qwen38-27b \
  --repeats 3 \
  --output /tmp/fuda-ai-diagnostics
```

`--base-url` 填写当前可访问的 OpenAI 兼容模型接口，包含 `/v1`。`--model` 必须使用服务实际接受的模型标识；示例为项目连接设置中的默认标识，不能据此证明实际加载的权重版本。

需要鉴权时，由当前进程环境变量 `SECURITY_VLM_API_KEY` 提供。程序不加载生产 `.env`，不把认证头、密钥、请求正文或模型完整输出写入报告。无需提供生产 MySQL 连接参数。

默认 temperature 为 `0.0`，业务输出上限为 `2048` tokens，分类输出上限为 `1024` tokens，单次模型超时为 `45` 秒。分类使用 `ASSISTANT_PLAN_MAX_TOKENS` 与 `--max-tokens` 的较小值，可通过该环境变量固定分类预算。`--temperature`、`--max-tokens`、`--timeout` 指定生成参数；每例重复次数不得小于 3。分类、业务工具与直接字段提取请求携带 JSON Schema，服务须支持 `response_format=json_schema`，普通聊天不施加格式约束。请求沿用 `QwenClient` 的非思考模式和并发名额限制。当前客户端不传递随机种子，重复结果用于观察稳定性。

## 重点检查聊到第 4～5 轮后的表现

```bash
python -m AiVision.tests.assistant_diagnostics \
  --base-url http://127.0.0.1:18100/v1 \
  --model fuda-qwen38-27b \
  --layers conversation-live \
  --conversations mixed,window,pressure \
  --repeats 3 \
  --output /tmp/fuda-ai-conversations
```

三组对话都在各自的同一个 session 中连续执行，各重复 3 次：

| 对话 | 默认轮数 | 重点 |
|---|---:|---|
| `mixed` | 13 | 查询、修改、第 4～6 轮指代、切换摄像头、批量修改、任务后问候、澄清后续办 |
| `window` | 10 | 初始目标绑定经过闲聊后是否还在历史中、窗口外指代是否澄清、重述目标后能否恢复 |
| `pressure` | 10 | 连续查询两台虚构摄像头完整配置，观察历史和请求体增长 |

`window` 的闲聊轮数会随运行环境的 `ASSISTANT_HISTORY_TURNS` 增加，保证能跨过历史窗口；默认值为 6。`mixed` 和 `pressure` 的轮数固定。

逐轮记录分类、目标、参数、工具、保存结果、最终状态、请求字符数、服务实际返回的 Token 用量、模型调用数和耗时。`first_plan_valid` 区分首次规划与纠正后成功；逐请求统计包含输出预算、格式约束、完成原因、校验类别和思考内容存在标记，不保存思考正文。服务不提供 `usage` 时 Token 数标为缺失，不用字符数冒充 Token 数。报告显示第 4、5、6 轮及后续轮次的结果，可以定位最早失败轮次；JSON 中的 `prior_failed_turns` 用于识别连带影响。

`response_metadata` 和 `request_statistics` 记录 `thinking_wrapper`（无、已闭合、未闭合）、`thinking_characters`、`reasoning_characters`、`answer_format` 和 `object_shape`。这些字段只包含固定类别与长度。`has_thinking=true` 包括空的 `<think></think>` 标签，不能直接据此判断模型正在思考或服务忽略了非思考设置。分类校验错误保留脱敏的 `validation_issues`，不记录错误输出全文或未知字段原名。

历史诊断同时记录原始目标绑定文本是否仍可见。模型在后续回复中复述目标绑定时，允许根据可见绑定继续查询，不强行要求澄清。字面片段可见性不等同于完整语义记忆能力。

## 分层运行

`--layers` 接收逗号分隔的下列值：

| 层 | 模型 | 业务执行 | 用途 |
|---|---|---|---|
| `service` | 真实服务，固定短请求 | 无 | 只读识别监听进程、版本和接口声明，15 次格式与长度合同探针 |
| `model` | 真实 Qwen | 无 | 直接测试格式约束、问候、分类、资源提取、参数提取和工具 JSON，共 16 个固定样例 |
| `agent` | 固定模型替身 | 模拟工具 | 验证工具顺序、结果传递、连续调用、上下文和错误处理 |
| `tools` | 无 | 真实服务＋临时 SQLite | 10 项资源、校验、权限、版本、局部保存及回读验证 |
| `e2e-scripted` | 固定模型替身 | 真实服务＋临时 SQLite | 18 个场景的完整程序链路 |
| `e2e-live` | 真实 Qwen | 真实服务＋临时 SQLite | 同一组 18 个场景的实际模型表现 |
| `probes` | 主动构造的模型输出 | 真实服务＋临时 SQLite | 检查额外字段、批量漏目标、纠错后报告三项约束 |
| `conversation-scripted` | 固定模型替身 | 真实服务＋临时 SQLite | 持续多轮的程序和历史传递基线 |
| `conversation-live` | 真实 Qwen | 真实服务＋临时 SQLite | 持续多轮的实际模型效果 |

不指定 `--layers` 时运行全部层。不提供 `--base-url` 时，真实模型层明确标为 `blocked`，其他层仍可运行：

```bash
python -m AiVision.tests.assistant_diagnostics \
  --output /tmp/fuda-ai-offline-diagnostics
```

真实模型连接检查失败时不会用模型替身代替，也不会把该层记为通过。程序先发送固定问候及分类 Schema 请求，检查服务是否接受接口参数，这两次预检不计入场景指标。Schema 请求被服务拒绝时，真实模型层标为 `blocked`，避免重复执行整套对话；服务接受请求不代表返回格式正确，正确率仍按场景实测。

模型层的 `schema_aligned`、`schema_conflicting` 使用相同的严格输出 Schema，分别提供格式一致和格式冲突的固定提示。返回结果必须真正符合 Schema，HTTP 200 不计为格式通过。它们用于排查结构化输出约束，不调用业务工具，也不表示业务任务分类准确。少量探针通过不能证明服务支持全部 Schema；失败仍需结合模型服务实现、模板和实际格式排查。

只检查模型和输出格式时，在项目根目录运行：

```bash
python -m AiVision.tests.assistant_diagnostics \
  --base-url http://127.0.0.1:18100/v1 \
  --model fuda-qwen38-27b \
  --layers model \
  --repeats 3 \
  --output /tmp/fuda-ai-model-format
```

## 安全边界

- 业务数据库为每次测试新建的临时 SQLite，结束后自动清理；数据库引擎连接被限制为本次 SQLite，其他引擎连接直接拒绝。
- 摄像头、功能配置、助手设置、会话和操作审计都是虚构数据。摄像头名称为“诊断闸机一号”“诊断闸机二号”和一个外部门样例，不接入视频源。
- 保留真实 Pydantic Schema、部门权限、读取版本、局部合并、业务保存、回读及审计。缓存刷新和运行事件被替换，避免触发现场运行设施。
- 后台任务采用同步投递，保留 `submit`、重复请求和取消流程；不模拟线程池吞吐，也不证明 MySQL 行锁和 GPU 行为。
- 非法 JSON、截断、工具错误、版本变化、错误最终答复和取消均标记为人工注入。不能把注入结果归因为模型自然出错。
- 本工具不运行浏览器。前端轮询、Cookie、页面卸载、网络代理和会话切换仍需另行观察。

## 报告和判断口径

输出目录包含：

- `report.md`：调用链、测试方法、分层统计、逐场景结果、多轮请求长度及失败证据。
- `results.json`：脱敏逐次指标、工具名称、错误类型、故障归属、逐轮请求统计和运行参数。

报告同时记录 Git 提交和实际源码的 SHA-256 指纹。直接覆盖压缩包不会改变 Git HEAD，应使用源码指纹区分实际运行版本。

每完成一个样本或一轮对话就原子保存报告。中断后已完成样本仍保留，未完成层保持 `running`；不能当成完整测试结果。

任务分类、资源识别、工具选择、参数提取、JSON 有效性、工具执行、最终配置、任务完成、报告正确性分别统计。不适用和没有响应的项目不放入相应分母。工具执行成功率包含预期拒绝，需结合“预期处理行为通过率”和注入标记理解。

`schema_output_ok` 单独统计模型输出是否通过对应的 Pydantic 输出合同，与模式、资源及参数取值是否符合用户请求分开。模型独立分类使用与运行时相同的 `parse_plan()`，无效 JSON 与字段错误分别保留 `plan_json`、`plan_schema` 类别。

多轮查询和修改可以复用权限可见的 `last_read_resources`，不强制每轮再次调用 `list_resources`。`resource_resolution_ok` 核对读取目标是否来自可见上下文或本轮真实搜索；本轮仍须读取全部预期目标及配置，实际写入必须取得新的版本。猜测资源标识、目标错误、批量漏读和未重新读取即写入均不能通过。

参数提取和资源识别的端到端指标可能受上游分类截断或服务超时影响，应结合逐轮错误与是否实际进入工具阶段分析，不能全部归为语义提取错误。已定位目标后的数值澄清不强制再次读取配置；测试同时核对目标引用和澄清问题，不能把重新索要已明确目标当作正确的数值澄清。实际写入仍必须重新读取配置及版本。

“任务成功”只统计明确且合法、能够完成的业务请求。无权限时正确拒绝、目标歧义时正确澄清、取消时正确停止，计为保护行为通过，不计为修改任务成功。模型替身的成功率不能代表真实 Qwen 的成功率。

`failure_layers` 区分 `model_output`、`model_service`、`agent_scheduling`、`business_execution`、`result_reporting` 和 `context_transfer`。`diagnostic_harness` 表示诊断设施本身异常，不能当成 Agent 故障。

退出码 `0` 表示诊断及报告生成完成，不代表所有样例通过；具体失败须查看报告。退出码 `2` 表示初始化或诊断设施异常，`130` 表示用户中断。

## 本地验证入口

```bash
python -m pytest -q \
  AiVision/tests/test_assistant_diagnostics.py \
  AiVision/tests/test_assistant_planning.py \
  AiVision/tests/test_qwen_client.py
```

测试中的三个 `xfail` 是对现有 Agent 缺口的保护性探针，不是修复完成标记：额外修改合法字段、批量只处理一个目标、错误恢复后仍报失败。诊断入口会将它们作为真实失败样例写入报告。本机脚本模型的实测基线见 [诊断基线报告](assistant-diagnostics-baseline.md)。

## 清理测试输出

报告保存到其他位置后，删除本次命令指定的输出目录即可：

```bash
rm -rf -- /tmp/fuda-ai-diagnostics /tmp/fuda-ai-conversations /tmp/fuda-ai-model-format /tmp/fuda-ai-service-inspection
```

`AiVision/assistant/context.py`、`AiVision/tests/assistant_diagnostics/` 及正式测试均属于项目代码，随 Git 同步保留。运行诊断不会修改这些源码；临时 SQLite 在每次隔离测试结束时自动清理。
