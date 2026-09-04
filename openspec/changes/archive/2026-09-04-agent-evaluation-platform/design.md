## Context

这是一个从零开始、面向单项目自托管部署的 Agent Evaluation Workbench。平台需要同时处理评测前的 Dataset Case、执行中的 Trace 和执行后的 Score/Report。Prompt Agent、RAG Agent 和 Tool Agent 的执行形态不同，但成熟产品普遍使用同一条主链路：

```text
Input/Dataset -> Run/Trace -> Observation/Span -> Evaluator -> Score -> Experiment/Report
```

Langfuse、LangSmith、Phoenix、Opik、Braintrust 和 MLflow 主要提供平台对象模型与观测工作流；Weave、TruLens 和 Evidently 提供可组合的 Call/Feedback/Metric/Test 抽象；DeepEval、Ragas、Promptfoo、AgentEvals、Inspect AI 和 OpenAI Evals 提供评测器或任务执行抽象。设计采用这些项目的公开 API、数据模型和开源组件作为参考，不复制大型平台的完整后端或闭源实现。

## Goals / Non-Goals

**Goals:**

- 一等支持 Prompt Agent、RAG Agent、Tool Agent 和可扩展的 Custom Agent。
- 为 Prompt Agent 提供无需部署服务的 Prompt Runner，同时为任意技术栈提供 HTTP Agent Adapter。
- 用统一 Dataset Case 模型承载单轮、多轮、Prompt、RAG、Tool 和结构化输出测试数据。
- 通过异步 Worker 执行批量评测，隔离样本错误并提供进度、重试、取消和断点式重跑。
- 把确定性评估、LLM Judge、人工评分和第三方评估器统一为带证据的 Score。
- 兼容 OpenTelemetry/OpenInference 的核心 Trace 语义，保留未知扩展字段。
- 记录 Agent、Prompt、Dataset、Evaluator、模型、Judge 和随机参数版本，使实验可解释、可对比、可回归。
- 通过 Docker Compose 提供可复现的 Prompt、RAG、Tool 三类示例闭环。

**Non-Goals:**

- 第一版不运行用户上传的任意 Python/JavaScript 代码，不提供通用代码沙箱。
- 第一版不实现 WebArena、OSWorld、SWE-bench 等需要复杂外部环境的 Benchmark。
- 第一版不覆盖所有 Agent 框架、模型供应商、评测指标或所有安全攻击类型。
- 第一版不实现完整 SaaS 多租户、计费、组织权限和 Kubernetes 弹性调度。
- 第一版不把不同质量维度强行压缩为一个具有普适意义的总分。

## Decisions

### 1. 统一 Agent 类型和接入模式

Agent 类型为：

```text
prompt  # Prompt + Model + Variables -> LLM
rag     # Input -> Retrieval -> Context -> LLM
tool    # Input -> LLM -> Tool -> Tool Result -> ... -> Output
custom  # 使用统一 HTTP 协议自行定义执行过程
```

接入模式为：

```text
PromptRunner  # 平台直接调用 OpenAI-compatible LLM endpoint
HttpAgent     # 平台调用用户已经运行的 /run 服务
```

Prompt Runner 配置至少包含 `provider`、`model`、`system_prompt`、`user_template`、变量定义、采样参数和 `response_format`。HTTP Agent 请求和响应如下：

```text
POST /run

Request:
{
  "input": <string | object>,
  "variables": <object>,
  "messages": <optional list>,
  "metadata": {"case_id": "...", "run_id": "..."},
  "trace_id": "..."
}

Response:
{
  "output": <string | object>,
  "tool_calls": [{"name": "...", "arguments": {}}],
  "usage": {"input_tokens": 0, "output_tokens": 0, "cost": 0},
  "trace": <optional structured trace>
}
```

平台保存协议版本、原始响应和标准化执行结果。HTTP 方式可以接入 LangChain、LlamaIndex、LangGraph、自研服务或其他语言实现，且不会执行不可信代码。未来可在协议之上提供 Python/TypeScript SDK。

### 2. 统一 Dataset Case，但按类型校验

Dataset Case 的规范字段为：

```text
input             # 输入字符串或结构化对象
variables         # Prompt 模板变量
messages          # 多轮 Chat 消息
expected_output   # 参考答案或参考结构
output_schema     # JSON Schema/结构化输出约束
criteria          # 自然语言行为规则或 rubric
expected_tools    # 期望工具、参数和顺序
expected_state    # 期望业务状态或状态断言
retrieval_context # RAG 参考上下文及文档元数据
metadata          # 标签、分类、难度和自定义字段
```

字段不是全部必填。Evaluator 在注册时声明 `requires`，运行前检查 Dataset Case 是否提供所需字段。Prompt Agent 主要使用 `variables`、`messages`、`expected_output`、`output_schema` 和 `criteria`；RAG 使用 `retrieval_context`；Tool 使用 `expected_tools` 和 `expected_state`。

测试集支持手动创建、CSV、JSON、JSONL、API/SDK、从生产 Trace 创建、人工标注转样本，未来支持合成数据。CSV 适合扁平 Prompt 样本，JSONL 适合嵌套消息、工具调用和 RAG context，JSON 支持完整导入导出。

### 3. 采用规范化内部模型并保留原始 JSON

```text
Project
├── Agent -> AgentVersion
│          └── PromptConfig/EndpointConfig snapshot
├── Dataset -> DatasetVersion -> DatasetCase
├── Evaluator -> EvaluatorVersion
└── EvaluationRun
    ├── CaseExecution -> Trace -> TraceSpan
    ├── Score
    └── AggregateMetric
```

`DatasetVersion`、`AgentVersion`、`EvaluatorVersion` 和 Prompt 配置在 Run 创建时冻结为不可变快照。`CaseExecution` 分离 Agent 调用状态和评估状态，避免把网络错误误认为质量失败。关系型字段保证查询与约束，输入输出、工具参数、上下文和扩展字段使用 JSONB；原始大字段经脱敏和大小限制后进入文件存储，并由 TraceSpan 保存引用。

### 4. Trace 采用 OTel/OpenInference 兼容的 canonical schema

Trace 由层级 Span 组成，节点类型至少包括：

```text
agent
prompt
llm
tool
tool_result
retrieval
guardrail
evaluator
```

每个节点使用 `trace_id`、`span_id`、`parent_span_id`、`kind`、时间、状态、错误、输入、输出和 JSONB payload。可获得时保存模型、Prompt 版本、工具名称、参数、token、成本、检索文档引用和 response format。平台记录可观察执行事实，不要求 Agent 暴露或保存隐藏思维链。

平台自产 Trace 直接写入 canonical schema；外部 OTLP/OpenInference 通过独立 Adapter 映射。未知标准字段和原始来源信息必须保留，避免第三方 Trace 因字段不认识而丢失。

### 5. Evaluator 分层并通过 Adapter 复用成熟生态

统一接口为：

```python
class Evaluator:
    name: str
    version: str
    requires: list[str]
    score_range: tuple[float, float] | None
    direction: str

    def evaluate(self, case, execution, trace) -> list[Score]: ...
```

评估器分为：

1. 确定性评估：Exact Match、JSON Schema、Tool Selection、Argument Correctness、State Assertion、Latency、Cost。
2. LLM Judge：Answer Quality、Instruction Following、完整性、策略合规和轨迹质量；保存 Judge 模型、rubric、Prompt、原始判断和结构化解析结果。
3. 第三方 Adapter：DeepEval、Ragas、Promptfoo、AgentEvals 等结果转换为统一 Score，并保存库版本和原始结果。
4. Human Review：人工评分、标签和解释作为 Score/Feedback，未来支持 Annotation Queue。

指标按 Agent 类型提供默认集合：

```text
Prompt: Answer Correctness, Relevance, Instruction Following,
        JSON Schema, Semantic Similarity, Safety, Latency, Cost
RAG:    Faithfulness, Context Relevance, Context Precision/Recall,
        Answer Correctness, Citation Correctness, Latency, Cost
Tool:   Task Success, Tool Selection, Tool Call F1, Argument Correctness,
        Trajectory Match, Policy Compliance, Recovery, Latency, Cost
```

没有跨领域统一的 Agent 总分。报告展示多维指标；综合分只用于排序。Task Success、Policy Compliance 等关键指标可配置为硬门槛。

### 6. Evaluation Run 使用可恢复 Pipeline

```text
Validate config
  -> Freeze versions/configuration
  -> Enqueue one job per Dataset Case
  -> Run PromptRunner or HttpAgent
  -> Normalize result and persist Trace
  -> Run selected Evaluators
  -> Persist sample Scores
  -> Aggregate metrics
  -> Evaluate Regression Gates
  -> Publish Report and CI result
```

每个 Case Job 使用 `run_id + case_id` 幂等。网络错误有限重试并指数退避，协议错误和业务错误不无限重试。数据库 Run/CaseExecution 状态是事实来源，支持最大并发、单 Agent 速率限制、取消、Worker 重启恢复和部分失败隔离。缺失 Score、评估错误或未完成运行不得默认通过门禁。

### 7. 参考产品到本项目的能力映射

| 本项目能力 | 主要参考 | 复用方式 |
|---|---|---|
| Trace/Span | Phoenix, Langfuse, LangSmith, Opik | OTel/OpenInference 语义 + 自有 canonical schema |
| Dataset/Example | Langfuse, LangSmith, Braintrust, MLflow, Opik | 借鉴版本、来源 Trace 和不可变样本关系 |
| Score/Feedback | Langfuse, Braintrust, Weave, TruLens | 统一数值/分类/解释/证据模型 |
| Metric/Test/Report | Evidently, MLflow, Weave | Metric、Preset、Test、Report 分层 |
| Prompt Runner/Assertions | Promptfoo, LangSmith Playground | Provider、变量、结构化输出和断言 |
| Agent/RAG Evaluator | DeepEval, Ragas, AgentEvals | 可选依赖 + Adapter + 固定金样本契约测试 |
| Human Review | Langfuse, LangSmith, Opik, Braintrust | 后续 Annotation Queue 和人工 Score |
| Safety Scan | Promptfoo, Giskard, garak, Galileo | 后续 Probe/Detector/Policy 扩展 |
| CI Regression | Braintrust, Langfuse, Promptfoo | 机器可读 Gate 和 GitHub Actions 示例 |
| Benchmark | AgentBench, WebArena, BrowserGym, OSWorld | 后续环境 Adapter，不内置复杂环境 |

闭源产品的内部后端、商业 Judge、私有存储协议和完整 UI 不直接复制。开源项目也优先通过依赖、SDK 或 Adapter 使用，并锁定版本、记录许可证和结果来源。

### 8. 技术选型和仓库结构

- API：Python、FastAPI、Pydantic、OpenAPI。
- Web：Next.js、TypeScript、Tailwind CSS、shadcn/ui、图表组件。
- Worker：Redis + Celery；按 Case 独立执行足以覆盖第一版。
- Storage：PostgreSQL；核心查询列 + JSONB 扩展；文件存储抽象预留 S3/MinIO。
- Deployment：Docker Compose，包含 Web、API、Worker、PostgreSQL、Redis 和三个示例 Agent。

```text
apps/web
apps/api
apps/worker
packages/contracts
examples/prompt-agent
examples/rag-agent
examples/order-agent
tests/unit
tests/integration
tests/e2e
infra/docker-compose.yml
```

### 9. 安全、隐私和可解释性

平台不执行上传源码；HTTP Agent 的 URL、API Key 和 Judge Key 与 Trace 分离保存。输入、输出和 Trace 支持字段脱敏、内容截断、项目级保留策略和导出权限。报告中的每个 Score 必须能追溯到 Dataset Case、Evaluator、证据和 Trace 节点。LLM Judge 结果需标注为模型判断，不宣称绝对客观。

## Risks / Trade-offs

- LLM Judge 有偏差：确定性评估优先，保存完整 Judge 元数据，允许重复运行。
- 评估成本高：限制并发和样本量，支持选择指标，统计 Token/Cost。
- Prompt/RAG/Tool 字段差异：统一 Case + `requires` 声明，运行前校验。
- 供应商响应格式不同：Provider/HTTP Adapter 标准化，并保存原始响应。
- 第三方库升级改变结果：锁定版本，使用固定金样本契约测试。
- Trace 含 PII 或密钥：凭据不进入 Trace，默认脱敏和截断。
- 只做 UI 包装：必须展示真实 Trace、异步执行、失败证据、版本对比和 CI 门禁。

## Migration Plan

这是绿地项目，无旧数据迁移。发布顺序为：初始化基础设施 -> Prompt Runner 垂直闭环 -> HTTP Agent -> RAG/Tool Trace 和确定性评估 -> LLM Judge 与第三方 Adapter -> 报告、版本对比、人工 Review 和 CI 门禁。历史 Run、Trace 和 Score 不删除；新增字段通过向前兼容迁移完成。

## Open Questions

- LLM Provider 是否只支持 OpenAI-compatible endpoint，还是使用 LiteLLM 统一多个供应商。
- 外部 OTLP ingestion 是第一版演示能力，还是在自产 Trace 稳定后加入。
- 本地单用户是否需要最小 JWT，还是先使用开发账号和项目 API Key。
- 人工 Annotation Queue、合成数据和安全 Probe 是否在首个可演示版本之后加入。
