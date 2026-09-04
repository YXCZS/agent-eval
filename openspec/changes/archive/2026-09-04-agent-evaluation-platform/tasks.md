## 1. Project Bootstrap

- [x] 1.1 建立 `apps/web`、`apps/api`、`apps/worker`、`packages/contracts`、`examples/order-agent` 和测试目录，并配置 Python/TypeScript 格式化、Lint 和类型检查。
- [x] 1.2 创建 Docker Compose 开发拓扑，包含 Web、API、Worker、PostgreSQL 和 Redis，并通过服务健康检查验证启动。
- [x] 1.3 建立环境配置和密钥读取机制，区分开发、测试和运行时密钥，并验证密钥不会出现在 API 响应或 Trace 中。
- [x] 1.4 建立 Alembic 迁移、pytest、Playwright 和 CI 基线，并在 CI 中执行后端、前端与 Compose 健康检查。

## 2. Domain and Contracts

- [x] 2.1 定义 Agent、AgentVersion、PromptConfig、Dataset、DatasetVersion、DatasetCase、EvaluatorVersion、EvaluationRun、CaseExecution、Trace、TraceSpan、Score 和 AggregateMetric 的 Pydantic/API 合同。
- [x] 2.2 实现 PostgreSQL 数据模型、JSON 扩展字段、外键、唯一约束和常用查询索引，并验证版本不可变约束。
- [x] 2.3 实现单工作区开发登录和项目级 API Key，区分浏览器管理请求与 Agent/CI 请求，并验证项目边界。
- [x] 2.4 从 API 生成 OpenAPI 文档，并维护前端共享类型与合同编译检查。

## 3. Agent Connection

- [x] 3.1 实现 `prompt`、`rag`、`tool`、`custom` Agent 与 AgentVersion 的创建、查询、编辑、启停和版本 API。
- [x] 3.2 实现 Prompt Runner，支持 OpenAI-compatible endpoint、模型、系统 Prompt、用户模板、变量、采样参数、结构化输出与 Token/成本解析。
- [x] 3.3 实现 HTTP Agent Adapter，支持字符串/对象输入、项目 API Key、`run_id`/`case_id`、响应解析与原始响应保存。
- [x] 3.4 实现连接、供应商、认证、超时、限流、服务端和协议错误分类，以及有限重试和样本失败隔离。
- [x] 3.5 实现请求超时、最大响应体、最大工具调用数量和 Agent 并发限制，并覆盖边界测试。

## 4. Evaluation Datasets

- [x] 4.1 实现 Dataset、DatasetVersion 和 DatasetCase 的创建、查询、编辑、标签与版本 API，并保证编辑创建新版本。
- [x] 4.2 定义统一 Dataset Case 字段，覆盖 Prompt、单轮、Tool、RAG 和多轮样本。
- [x] 4.3 实现 CSV、JSON 数组和 JSONL 解析，支持大小、编码、行号、嵌套 JSON 和重复 ID 校验。
- [x] 4.4 实现字段映射、导入预览、逐行校验、部分成功导入和取消导入 API。
- [x] 4.5 实现 DatasetVersion 的 JSONL/CSV 导出，保留嵌套结构与版本元数据，并覆盖导出回导测试。
- [x] 4.6 实现从 Trace 选择字段创建 Dataset Case，支持将实际输出和工具调用转换为期望字段并保存来源 Trace。

## 5. Trace Observability

- [x] 5.1 实现 Trace 与 TraceSpan 持久化和父子关系查询，覆盖 Agent、LLM、Tool、Tool Result、Retrieval、Guardrail 和 Evaluator 节点。
- [x] 5.2 实现平台运行结果到 canonical Trace 的标准化，并映射 OpenTelemetry GenAI/OpenInference 核心字段且保留未知字段。
- [x] 5.3 实现统一 Trace JSON ingestion API，并预留外部 OTLP/OpenInference ingestion Adapter 边界。
- [x] 5.4 实现 Trace 输入/输出脱敏、凭据过滤、字段长度限制和大内容引用。
- [x] 5.5 实现 Trace 列表、详情、运行/样本/状态筛选和时间线 API。

## 6. Evaluation Engine

- [x] 6.1 定义可插拔 Evaluator 合同、EvaluatorVersion 注册、输入要求、适用 Agent 类型、分值范围、方向和默认阈值。
- [x] 6.2 实现 EvaluationRun 创建、配置快照、状态机、CaseExecution 和数据库事实状态。
- [x] 6.3 实现 Celery/Redis Case Job，按 `run_id + case_id` 幂等执行 Agent、写入 Trace 并隔离样本错误。
- [x] 6.4 实现有限重试、指数退避、取消、最大并发和单 Agent 限速。
- [x] 6.5 实现确定性 Evaluator：Task Success、Tool Correctness、Argument Correctness、Policy Compliance、JSON Schema、Latency 和 Cost。
- [x] 6.6 实现 OpenAI-compatible LLM Judge Provider 与结构化判断，支持答案质量、指令遵循、完整性和自然语言规则。
- [x] 6.7 实现 Prompt 确定性 Evaluator：Exact Match、Semantic Similarity、JSON Schema、Latency、Token 和 Cost。
- [x] 6.8 实现 DeepEval、Ragas、Promptfoo 和 AgentEvals Adapter，保留第三方名称、版本和原始结果引用。
- [x] 6.9 持久化统一 Score，包含数值、标签、通过状态、解释、证据、评估器版本、rubric、Judge 模型、阈值和方向。
- [x] 6.10 为人工 Score/Feedback 和 Annotation Queue 预留持久化与服务接口，并实现人工评分审计。

## 7. Scores, Reports and Regression

- [x] 7.1 实现按指标聚合有效样本、缺失、错误、通过率、平均分和聚合方式。
- [x] 7.2 实现报告 API，支持类别、难度、标签、错误类型、运行状态和指标筛选。
- [x] 7.3 实现 JSON/CSV 报告导出，包含版本、指标定义、阈值、方向、生成时间和样本级结果。
- [x] 7.4 实现同 DatasetVersion 上多次运行的 Agent 版本比较，展示指标差值、分组差异、新增失败和恢复成功。
- [x] 7.5 实现 Regression Gate 和机器可读 CI 结果，支持最低/最高阈值与策略违规硬门槛。

## 8. Evaluation Workbench UI

- [x] 8.1 创建工作台导航和基础页面状态，覆盖 Agents、Datasets、Evaluators、Runs、Reports 和 Traces。
- [x] 8.2 实现 Agent 管理页面，支持 Prompt 配置、渲染预览、HTTP 配置、连接测试、版本选择和错误展示。
- [x] 8.3 实现 Dataset 创建页面，支持手动表格、CSV/JSONL 上传、字段映射、预览、错误行和确认导入。
- [x] 8.4 实现 Evaluation Run 配置和进度页面，支持 Agent/Dataset/Evaluator 选择、进度计数和取消。
- [x] 8.5 实现报告和样本详情页面，展示多维指标、失败原因、实际输出、Score 证据和 Trace 时间线。
- [x] 8.6 实现版本比较、报告导出和门禁结果页面，并覆盖端到端流程。

## 9. Examples and Security

- [x] 9.1 实现示例 Prompt Agent、RAG Agent 和订单客服 Tool Agent，并覆盖查询、禁止取消、退款前置条件和缺失订单号场景。
- [x] 9.2 准备版本化示例 Dataset、Evaluator 配置和 Agent v1/v2，构造可观察的质量回归。
- [x] 9.3 完成 API 输入校验、项目边界、速率限制、文件大小限制、敏感信息过滤和审计日志。
- [x] 9.4 完成 Dataset 导入到 Regression Gate 的全链路回归测试，覆盖 Playwright、pytest 和 Compose CI。
- [x] 9.5 为 Promptfoo/Giskard/garak 安全扫描与 AgentBench/WebArena/OSWorld Benchmark 定义后续 Adapter 合同和能力声明。

## 10. Documentation and Delivery

- [x] 10.1 编写产品使用文档，说明 Prompt Runner、HTTP 协议、Dataset 字段、Trace 转样本、评估器和评分口径。
- [x] 10.2 编写架构与技术取舍文档，说明 canonical schema、队列幂等、确定性评估与 LLM Judge 边界、隐私策略和第三方 Adapter。
- [x] 10.3 提供一键启动、示例环境变量、数据库迁移和故障排查命令，并验证全新目录可复现启动。
- [x] 10.4 完成 CI 门禁：Lint、类型检查、单元/集成/E2E 测试和示例回归评测。
