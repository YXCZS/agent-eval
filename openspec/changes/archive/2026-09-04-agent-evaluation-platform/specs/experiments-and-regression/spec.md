## Purpose

提供可复现的 Agent、Prompt 版本实验、结果对比和持续回归门禁，让评测结果能够支持版本发布决策而不是只作为一次性报告。

## ADDED Requirements

### Requirement: Evaluation Run records reproducibility metadata
系统 SHALL 记录运行使用的 Agent 版本、Prompt 配置版本、Dataset 版本、Evaluator 版本、模型和 Judge 配置、提示词或规则版本、采样参数、运行时间和随机种子（如适用）。

#### Scenario: Reopen a historical run
- **WHEN** 用户查看已完成的历史运行
- **THEN** 系统显示足以解释该运行结果的版本和配置元数据，并不依赖当前默认配置

### Requirement: User can compare Prompt versions
系统 SHALL 允许用户在同一 Dataset Version 上比较两个或多个 Prompt 配置版本，并展示各项指标差值、样本级输出差异、新增失败和恢复成功案例。

#### Scenario: Compare two Prompt versions
- **WHEN** 用户选择 Prompt v1 和 Prompt v2 在同一测试集上的运行
- **THEN** 系统展示回答质量、结构化输出、延迟和成本的变化，并可进入具体样本 Trace

### Requirement: User can compare Agent versions
系统 SHALL 允许用户选择同一 Dataset 版本上的两个或多个运行进行对比，并展示总体指标、分组指标、样本级变化和新增/消失的失败案例。

#### Scenario: Compare two Agent versions
- **WHEN** 用户选择 Agent v1 和 Agent v2 在同一测试集上的运行
- **THEN** 系统显示每项指标的差值、通过率变化和仅在某个版本失败的样本

### Requirement: User can configure regression gates
系统 SHALL 允许用户为指标设置最低或最高阈值，并将策略违规等关键指标配置为必须满足的硬门槛。门禁结果 MUST 为通过、未通过或无法判定，并显示触发门禁的样本和指标。

#### Scenario: Run passes regression gates
- **WHEN** 所有必需指标满足阈值且没有禁止的策略违规
- **THEN** 系统将运行标记为门禁通过，并提供可用于 CI 的机器可读结果

#### Scenario: Run fails regression gates
- **WHEN** 任务成功率低于阈值或发生禁止的策略违规
- **THEN** 系统将运行标记为门禁未通过，并指出具体指标、阈值和失败样本

### Requirement: Regression result is stable under missing data
系统 SHALL 在运行未完成、样本缺失或评估器错误时将门禁标记为无法判定或未完成，不得将缺失结果默认为通过。

#### Scenario: Evaluate an incomplete run
- **WHEN** 用户在仍有排队样本或评估器错误的运行上请求门禁结果
- **THEN** 系统返回未完成或无法判定状态，并说明缺失原因
