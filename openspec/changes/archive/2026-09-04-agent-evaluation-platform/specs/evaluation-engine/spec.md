## Purpose

以可重试、可观测的方式批量执行 Prompt、RAG 和 Tool Agent 测试，并用统一评估器协议连接确定性规则、程序状态检查、LLM Judge 和第三方评测库。

## ADDED Requirements

### Requirement: Evaluation provides type-appropriate default metrics
系统 SHALL 根据 Agent 类型提供可选的默认指标集合：Prompt Agent 至少包括 Answer Correctness、Answer Relevance、Instruction Following、JSON Schema、Latency 和 Cost；RAG Agent 至少包括 Faithfulness、Context Relevance、Context Precision/Recall；Tool Agent 至少包括 Task Success、Tool Selection、Argument Correctness 和 Policy Compliance。用户 MUST 能在启动前增删指标。

#### Scenario: Evaluate a Prompt Agent with a schema metric
- **WHEN** 用户选择 Prompt Agent、包含 `output_schema` 的 Dataset 和 JSON Schema Evaluator
- **THEN** 系统检查字段兼容性，运行 Prompt Runner，并保存结构化输出通过或失败的 Score 及证据

### Requirement: User can start an Evaluation Run
系统 SHALL 允许用户选择 Agent 版本、Dataset 版本和一个或多个 Evaluator 后启动评测。运行 MUST 具有排队、运行、完成、部分完成、失败和取消等可查询状态。

#### Scenario: Start a valid run
- **WHEN** 用户选择可用的 Agent、Dataset 和 Evaluator 并确认运行
- **THEN** 系统创建 Evaluation Run，返回运行标识，并异步处理样本

#### Scenario: Start run with incompatible evaluator
- **WHEN** 用户选择所需字段不在 Dataset Case 或 Trace 中的评估器
- **THEN** 系统在启动前提示缺失字段，并拒绝创建无法产生有效结果的运行

### Requirement: Run evaluates samples independently
系统 SHALL 为每个 Dataset Case 产生独立执行结果和评估结果。单个样本的 Agent 错误或评估器错误 MUST 被记录，并不得覆盖其他样本结果。

#### Scenario: Some cases fail during a batch run
- **WHEN** 批量运行中部分 Agent 调用超时或返回协议错误
- **THEN** 系统完成其余样本，并将整体运行标记为部分完成或带失败样本的完成状态

### Requirement: Evaluators return normalized Scores
系统 SHALL 为每个评估器提供统一输出，至少包含指标名称、数值或分类值、是否通过、解释、样本标识和评估器元数据。数值指标 MUST 明确分值范围和“越高越好”或“越低越好”的方向。

#### Scenario: Run a deterministic evaluator
- **WHEN** 任务成功评估器检查期望状态并得到通过结果
- **THEN** 系统保存确定性来源、分数、通过状态和检查证据

#### Scenario: Run an LLM Judge evaluator
- **WHEN** 回答质量评估器使用配置的 Judge 模型和规则完成评估
- **THEN** 系统保存 Judge 模型、规则版本、原始判断、解析后的分数和解释

### Requirement: Evaluation supports third-party adapters
系统 SHALL 能将第三方评估库的结果适配为统一 Score，并保留第三方评估器名称、版本和原始结果引用。第三方库不可用时，系统 MUST 返回明确的适配器错误而不是伪造分数。

#### Scenario: DeepEval adapter returns a result
- **WHEN** DeepEval 评估器成功计算 Agent 轨迹指标
- **THEN** 系统保存统一格式的 Task Completion 或 Tool Correctness Score，并保留第三方结果元数据

#### Scenario: Ragas adapter evaluates RAG data
- **WHEN** Ragas 评估器使用包含检索上下文的 Dataset Case 计算 Faithfulness 或 Context 指标
- **THEN** 系统保存统一 Score，并保留 Ragas 指标名称、版本、输入字段和原始结果

#### Scenario: Promptfoo adapter evaluates assertions
- **WHEN** Promptfoo 对 Prompt Agent 输出执行 JSON、Latency、Cost 或 LLM Rubric assertion
- **THEN** 系统将每项 assertion 转换为独立 Score，并保留 assertion 类型、配置和组件结果
