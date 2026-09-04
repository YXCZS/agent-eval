## Purpose

将单个 Prompt、RAG 或 Tool Agent 样本的评估证据汇总为可解释的指标和报告，使用户能够知道得分、失败位置、失败原因以及质量变化。

## ADDED Requirements

### Requirement: System stores sample-level scores and evidence
系统 SHALL 保存每个 Dataset Case 的各项 Score，并关联对应的 Trace、Evaluator、运行配置和评估证据。用户 MUST 能区分执行失败、评估失败、评估未运行和评估未通过。

#### Scenario: View a failed sample
- **WHEN** 用户打开一个未通过 Task Success 的样本
- **THEN** 系统同时显示实际输出、期望信息、Trace、失败的评估器、分数和解释

### Requirement: System aggregates scores by metric
系统 SHALL 按指标计算样本数量、通过率或平均分，并明确忽略、失败和缺失样本的处理方式。聚合结果 MUST 保留数据集版本、运行标识和评估器版本。

#### Scenario: Aggregate a run with missing scores
- **WHEN** 部分样本因输入字段缺失而没有某项 Score
- **THEN** 系统显示有效样本数和缺失数量，不将缺失样本静默当作满分

### Requirement: Reports include operational metrics
系统 SHALL 在运行报告中提供至少任务成功率、工具正确性、参数正确性、回答质量、策略合规率、延迟和成本等可用指标，并允许按类别、难度、标签和错误类型筛选。

#### Scenario: Filter failures by category
- **WHEN** 用户选择某个业务类别和错误类型
- **THEN** 系统只展示符合条件的样本及对应指标变化，并更新有效样本数量

### Requirement: Reports expose Prompt Agent quality metrics
系统 SHALL 在 Prompt Agent 报告中支持展示回答正确性、回答相关性、指令遵循、结构化输出有效性、延迟、Token 和成本，并允许用户查看渲染后的 Prompt 与对应 Score 证据。

#### Scenario: Inspect a Prompt Agent failure
- **WHEN** Prompt Agent 的 JSON Schema 或 Instruction Following 评估未通过
- **THEN** 报告显示变量、渲染后的 Prompt、实际输出、评估解释和对应 LLM Trace 节点

### Requirement: Reports are exportable
系统 SHALL 允许用户导出运行摘要和样本级结果。导出数据 MUST 包含指标定义、分值方向、阈值、评估器版本和生成时间等解释结果所需的元数据。

#### Scenario: Export an evaluation report
- **WHEN** 用户导出某次已完成运行的 JSON 或 CSV 报告
- **THEN** 系统生成包含聚合指标和样本级 Score 的文件，并可根据权限决定是否包含原始 Trace 内容
