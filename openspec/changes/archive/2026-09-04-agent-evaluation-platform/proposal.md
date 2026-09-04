## Why

Agent 的质量不能只通过最终文本判断。Prompt 模板、模型参数、检索上下文、工具选择、工具参数、执行步骤、最终状态、回答质量、延迟、成本和安全策略都可能导致失败。现有生态通常只覆盖其中一部分：Langfuse、LangSmith、Phoenix、Opik、Braintrust 和 MLflow 偏向 Trace、数据集、实验与观测；DeepEval、Ragas、Promptfoo、AgentEvals、Inspect AI 和 OpenAI Evals 偏向评测器、断言与测试执行；AgentBench、WebArena、OSWorld 等则提供特定环境中的 Benchmark。

本项目建立一个面向 Prompt Agent、RAG Agent 和 Tool Agent 的 Trace 驱动可视化评测与回归分析工作台。用户可以直接测试自己的 Prompt 配置或已上线 Agent，建立测试集，批量运行，得到可解释的多维评分，并从失败分数追溯到具体的模型调用、检索、工具调用和运行错误。

项目不重写 Langfuse、LangSmith 或 DeepEval，而是站在成熟项目之上：采用 OpenTelemetry/OpenInference 的 Trace 思路，复用 DeepEval、Ragas、Promptfoo 等开源评测能力，通过 Adapter 统一成自己的 Dataset、Evaluator、Score 和 Experiment 工作流。

## What Changes

- 将 Agent 类型明确为 `prompt`、`rag`、`tool` 和 `custom`，三类 Agent 共用评测链路，但使用不同的配置、测试字段和指标。
- 新增 Prompt Runner：用户可以配置模型供应商、模型、系统 Prompt、用户 Prompt 模板、变量、采样参数和结构化输出格式，不需要先部署服务即可评测 Prompt Agent。
- 保留统一 HTTP Agent Adapter：用户可以接入已经运行的 Prompt/RAG/Tool Agent，平台只调用用户提供的 HTTP 服务，不运行用户上传的任意代码。
- 新增 Agent 注册、Agent Version、Prompt Version 和连接测试，记录每次运行实际使用的版本和配置快照。
- 新增多来源测试集管理：手动创建、CSV/JSON/JSONL 导入、API/SDK 写入、从生产 Trace 创建、人工反馈转测试用例，并支持未来合成数据生成。
- 新增统一 Dataset Case 模型，支持 `input`、`variables`、`messages`、`expected_output`、`output_schema`、`criteria`、`expected_tools`、`expected_state`、`retrieval_context` 和 `metadata`。
- 新增测试集预览、字段映射、JSON Schema/Pydantic 校验、逐行错误、去重、标签、版本管理和 JSONL/CSV 导出。
- 新增异步 Evaluation Run，对测试集逐样本调用 Agent 或 Prompt Runner，保存输出、错误、Trace、Token、成本和延迟。
- 新增基于 OpenTelemetry/OpenInference 思路的 canonical Trace，记录 Agent、Prompt、LLM、Tool、Tool Result、Retrieval、Guardrail 和 Evaluator 节点及父子关系，不依赖或保存隐藏思维链。
- 新增统一 Evaluator 合同，支持确定性规则、JSON Schema、状态断言、LLM-as-a-Judge、人工评分以及第三方评测库 Adapter。
- 第一版支持 Prompt 指标、RAG 指标、Tool 指标和通用运行指标，包括 Answer Correctness、Answer Relevance、Instruction Following、Faithfulness、Context Precision/Recall、Task Success、Tool Correctness、Argument Correctness、Policy Compliance、Latency、Token Usage 和 Cost。
- 新增 Score、Aggregate Metric、Evaluation Report 和 Regression Gate，保存分值、方向、阈值、解释、证据、评估器版本、Judge 模型和原始结果，不把缺失结果默认当作通过。
- 新增 Agent/Dataset/Evaluator/Prompt 版本实验、同数据集对比、样本级差异、新增失败、恢复成功案例和 CI 门禁。
- 新增 Web 工作台，覆盖 Prompt Agent 配置、HTTP Agent 管理、Dataset、Evaluator、Run、Report、Trace 详情、失败分析、版本对比和报告导出。
- 新增 Docker Compose 本地部署、示例 Prompt Agent、示例 RAG Agent、示例订单 Tool Agent、示例数据集、自动化测试和 CI 评测命令。
- 明确第一版不运行任意用户代码、不自建 WebArena/OSWorld 等高成本环境、不复制闭源 SaaS 内部实现、不实现完整商业多租户计费系统。

## Research Basis and Reuse Boundaries

- Langfuse 的 `Trace -> Observation -> Score`、Dataset Item、Dataset Run、Prompt Version 和 Annotation Queue 用于参考核心对象关系、生产 Trace 反哺测试集和评分证据。
- LangSmith 的 `Run/Thread -> Dataset Example -> Experiment -> Feedback` 用于参考多轮运行、Prompt Playground、线上评测和样本与 Trace 绑定。
- Phoenix 的 OpenTelemetry/OpenInference Span、Dataset、Experiment 和 Annotation 用于参考跨框架 Trace 语义。
- Opik 的 Trace/Span/Thread、Dataset/Test Suite、Experiment、Metrics 和失败 Trace 转测试用例用于参考测试套件与实验关系。
- Braintrust 的 `Dataset + Task + Scorer -> Experiment`、不可变实验、线上评分、人工 Review 和 CI 用于参考 Scorer 与回归门禁。
- MLflow GenAI、W&B Weave、TruLens、Evidently 和 Galileo 分别用于参考评测结果与模型版本、Op/Call、组件级 Feedback、Metric/Test/Report、Agentic Tool 指标与运行时策略的拆分。
- DeepEval 的 `LLMTestCase`/`BaseMetric`、Ragas 的 `EvaluationDataset`/`EvaluationResult`、Promptfoo 的 Provider/Assertion/Result、AgentEvals 的 Trajectory Grader、Inspect AI 的 Task/Solver/Scorer 和 OpenAI Evals 的 Registry/Grader 用于第三方 Adapter 设计。
- Giskard 和 NVIDIA garak 作为后续安全扫描与攻击测试来源；AgentBench、WebArena、BrowserGym、OSWorld、SWE-bench、TAU-bench 等作为后续 Benchmark Adapter，而不是第一版内置环境。

成熟平台的闭源服务端、私有 ingestion 协议、商业 Judge、完整 UI 和大规模存储实现不直接复制。优先复用开源 SDK、评测器、OTel/OpenInference 标准和公开 API，并锁定版本、保留来源及许可证信息。

## Capabilities

### New Capabilities

- `agent-connection`: 注册 Prompt Runner 和 HTTP Agent，管理连接、版本、鉴权、超时、重试和响应标准化。
- `evaluation-datasets`: 创建、导入、编辑、校验、版本化和导出 Prompt/RAG/Tool/多轮评测数据集。
- `trace-observability`: 采集、标准化、查询和展示 Agent、Prompt、LLM、Tool、Retrieval 等执行 Trace。
- `evaluation-engine`: 编排批量评测，执行确定性评估、LLM Judge、人工评分和第三方评估器 Adapter。
- `scores-and-reports`: 保存样本级 Score，计算聚合指标，生成带证据的报告和可导出结果。
- `experiments-and-regression`: 管理 Agent/Prompt/Dataset/Evaluator 版本，进行实验对比并执行回归门禁。
- `evaluation-workbench-ui`: 提供 Prompt、Agent、Dataset、Evaluator、Run、Trace、Report 和版本对比页面。

### Modified Capabilities

- None.

## Impact

- 新增 Next.js Web、FastAPI API、Python Worker、PostgreSQL、Redis 和 Docker Compose 运行拓扑。
- 新增 Prompt Provider Adapter、HTTP Agent Adapter、canonical Trace、统一 Score 和第三方 Evaluator Adapter。
- Python 侧优先复用 DeepEval、Ragas、OpenInference 等生态；Promptfoo、AgentEvals 等通过可选依赖或独立 Adapter 接入。
- 需要处理 Prompt/Agent 网络不可达、模型供应商错误、超时、限流、重复执行、敏感数据、大体积输入输出和第三方评估失败。
- 评估结果必须保存 evaluator、rubric、prompt、模型、版本、方向、阈值和聚合元数据，避免同名指标被错误比较。
- 第一版面向单用户或单项目自托管；后续再扩展多项目、多租户、对象存储和分布式执行。
