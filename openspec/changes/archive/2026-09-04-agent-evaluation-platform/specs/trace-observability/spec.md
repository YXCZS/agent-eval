## Purpose

记录 Prompt、RAG、Tool Agent 评测和线上调试所需的完整执行过程，让用户能够从最终分数追溯到具体的 Prompt 渲染、模型调用、工具调用、检索、错误和时间消耗。

## ADDED Requirements

### Requirement: System records a hierarchical Trace
系统 SHALL 为每次 Agent 或 Prompt Runner 执行创建 Trace，并支持表示父子关系的执行节点。节点至少能够区分 Agent、Prompt、LLM、Tool、Tool Result、Retrieval、Guardrail 和 Evaluator 操作。

#### Scenario: Display a multi-step Agent Trace
- **WHEN** Agent 依次执行模型调用、工具调用和最终回答
- **THEN** 系统保存一条包含这些节点及其父子关系的 Trace，并可按时间顺序查看

#### Scenario: Display a Prompt Agent Trace
- **WHEN** Prompt Runner 渲染模板并调用模型返回回答
- **THEN** 系统保存 Prompt 模板、变量脱敏快照、渲染结果、LLM 调用和最终输出节点，并可从 Score 导航到这些节点

### Requirement: Trace records diagnostic execution data
系统 SHALL 为可见节点保存输入、输出、开始时间、结束时间、状态和错误信息，并在可获得时保存模型、工具名称、工具参数、token 使用量、成本和检索文档引用。

#### Scenario: Inspect a failed tool call
- **WHEN** 一个工具调用返回错误
- **THEN** Trace 详情显示工具名称、参数、错误响应、耗时及其前后关联节点

### Requirement: Trace ingestion supports standard semantic fields
系统 SHALL 接受平台自身运行产生的 Trace，并为 OpenTelemetry GenAI Semantic Conventions 或 OpenInference 中可识别的核心字段提供标准化映射。无法识别的字段 MUST 保留在扩展元数据中，而不得静默丢弃。

#### Scenario: Ingest a trace with external semantic fields
- **WHEN** 用户提交包含 Agent、LLM、Tool 或 Retrieval 语义字段的 Trace
- **THEN** 系统将可识别字段映射为统一节点，同时保留原始字段和来源信息

### Requirement: Trace content has access and retention controls
系统 SHALL 限制 Trace 内容仅对有权限的项目用户可见，并支持对输入、输出、凭据和大体积内容进行脱敏或截断配置。系统 MUST 不记录用户提交的认证凭据。

#### Scenario: Trace contains sensitive input
- **WHEN** Trace 输入匹配项目配置的敏感字段规则
- **THEN** 系统在页面和普通导出中隐藏或脱敏该字段，并保留字段已被处理的标记
