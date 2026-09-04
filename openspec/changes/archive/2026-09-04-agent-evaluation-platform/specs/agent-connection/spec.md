## Purpose

为 Prompt Agent、RAG Agent、Tool Agent 和不同技术栈实现的用户 Agent 提供统一、可诊断且可重复的评测接入方式，使平台能够直接运行 Prompt 配置或在不运行用户任意代码的前提下调用 HTTP Agent 并记录结果。

## ADDED Requirements

### Requirement: Agent registration declares its execution type
系统 SHALL 允许用户将 Agent 标记为 `prompt`、`rag`、`tool` 或 `custom`，并根据类型保存 Prompt Runner 配置或 HTTP Endpoint 配置。系统 MUST 在启动评测时使用与 Agent 类型匹配的执行适配器。

#### Scenario: Register a Prompt Agent
- **WHEN** 用户选择 `prompt` 类型并提交模型、Prompt 模板和变量配置
- **THEN** 系统创建可由 Prompt Runner 执行的 Agent Version，而不要求 HTTP 地址

#### Scenario: Register a Tool Agent
- **WHEN** 用户选择 `tool` 类型并提交 HTTP Endpoint 配置
- **THEN** 系统创建可由 HTTP Adapter 执行的 Agent Version，并在运行前检查协议能力

### Requirement: System can run a Prompt Agent without a deployed service
系统 SHALL 支持通过 Prompt Runner 配置 `provider`、`model`、系统 Prompt、用户 Prompt 模板、变量、采样参数和可选 `response_format`，直接调用 OpenAI-compatible LLM endpoint。系统 MUST 为每次运行保存渲染后的 Prompt、模型配置、变量快照和原始响应。

#### Scenario: Run a valid Prompt Agent
- **WHEN** 用户配置合法模型、Prompt 模板和测试变量并启动评测
- **THEN** 系统调用 LLM，保存 Prompt 节点、LLM 节点、实际输出和使用量，并将样本标记为执行成功

#### Scenario: Prompt Agent returns invalid structured output
- **WHEN** Prompt Agent 配置了 JSON Schema 但模型返回无法解析的内容
- **THEN** 系统保存原始输出，将样本标记为结构化输出错误，并允许后续 JSON Schema 评估器读取该错误证据

### Requirement: User can register an Agent endpoint
系统 SHALL 允许用户创建 Agent 配置，配置至少包含名称、请求地址、请求方式、认证信息引用和请求/响应协议版本。认证凭据 MUST 以不可直接读取的方式保存，页面和普通 API 响应不得返回明文凭据。

#### Scenario: Register a valid Agent
- **WHEN** 用户提交名称、可访问的 HTTP 地址和合法协议配置
- **THEN** 系统创建 Agent，并显示可用于评测的 Agent 标识和当前版本

#### Scenario: Reject invalid registration
- **WHEN** 用户提交缺少地址、协议版本或名称的配置
- **THEN** 系统拒绝保存，并指出缺失或非法字段，不创建部分有效的 Agent

### Requirement: System can invoke a registered Agent
系统 SHALL 能使用 Dataset Case 的输入调用已登记 Agent，并为每次调用生成关联标识。调用结果 MUST 能表示最终输出、结构化工具调用、错误、开始时间、结束时间和使用量等信息。

#### Scenario: Agent returns a successful response
- **WHEN** 评测运行向 Agent 发送合法输入且 Agent 在超时时间内返回合法响应
- **THEN** 系统保存实际输出和可用的工具调用信息，并将该样本标记为执行成功

#### Scenario: Agent returns an invalid response
- **WHEN** Agent 返回无法解析、缺少必需输出字段或不符合协议版本的响应
- **THEN** 系统将样本标记为协议错误，保存可诊断的错误信息，并继续处理其他样本

### Requirement: Connection failures are isolated and diagnosable
系统 SHALL 为连接失败、超时、认证失败、限流和服务端错误分别记录可区分的错误类型。单个样本的失败 MUST NOT 默认中止同一评测运行中的其他样本。

#### Scenario: Agent is unreachable
- **WHEN** 平台无法建立连接或 DNS/网络连接失败
- **THEN** 系统将该样本标记为连接错误，记录请求标识和重试结果，并允许运行继续或按用户配置停止

#### Scenario: Agent exceeds timeout
- **WHEN** Agent 在配置的请求超时内未完成响应
- **THEN** 系统终止该请求，记录超时耗时，并将样本标记为超时而不是普通任务失败

### Requirement: Agent versions are identifiable
系统 SHALL 允许同一 Agent 保存可区分的版本标签或版本标识，并在每次 Evaluation Run 中记录实际使用的 Agent 版本。

#### Scenario: Run uses a fixed Agent version
- **WHEN** 用户启动评测并选择 Agent 版本
- **THEN** 运行结果关联该版本，即使 Agent 配置之后发生变化，历史运行仍显示原版本信息
