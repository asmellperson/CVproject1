# 福达 AI 助手分层诊断

诊断入口为 `AiVision/tests/assistant_diagnostics/`，在 CVproject1 项目根目录运行。使用项目现有 Python 环境和依赖，命令行入口不依赖 pytest，不启动 API、摄像头或推理 Worker。

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

默认 temperature 为 `0.0`，业务输出上限为 `2048` tokens，分类输出上限为 `256` tokens，单次模型超时为 `45` 秒。可通过 `--temperature`、`--max-tokens`、`--timeout` 指定固定参数；每例重复次数不得小于 3。请求沿用 `QwenClient` 的非思考模式、JSON 模式和并发名额限制。当前客户端不传递随机种子，重复结果用于观察稳定性。

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

逐轮记录分类、目标、参数、工具、保存结果、最终状态、请求字符数、服务实际返回的 Token 用量、模型调用数和耗时。服务不提供 `usage` 时 Token 数标为缺失，不用字符数冒充 Token 数。报告显示第 4、5、6 轮及后续轮次的结果，可以定位最早失败轮次；JSON 中的 `prior_failed_turns` 用于识别连带影响。

历史诊断同时记录原始目标绑定文本是否仍可见。模型在后续回复中复述目标绑定时，允许根据可见绑定继续查询，不强行要求澄清。字面片段可见性不等同于完整语义记忆能力。

## 分层运行

`--layers` 接收逗号分隔的下列值：

| 层 | 模型 | 业务执行 | 用途 |
|---|---|---|---|
| `model` | 真实 Qwen | 无 | 直接测试问候、分类、资源提取、参数提取和工具 JSON，共 14 个固定样例 |
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

真实模型连接检查失败时不会用模型替身代替，也不会把该层记为通过。程序先执行一次固定问候检查服务，该检查不计入场景指标。

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

每完成一个样本或一轮对话就原子保存报告。中断后已完成样本仍保留，未完成层保持 `running`；不能当成完整测试结果。

任务分类、资源识别、工具选择、参数提取、JSON 有效性、工具执行、最终配置、任务完成、报告正确性分别统计。不适用和没有响应的项目不放入相应分母。工具执行成功率包含预期拒绝，需结合“预期处理行为通过率”和注入标记理解。

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
