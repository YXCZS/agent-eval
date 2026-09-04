## Purpose

提供一个可直接操作的 Web 工作台，让用户无需编写评测脚本即可完成 Prompt Agent 配置、HTTP Agent 配置、测试集管理、评测运行、Trace 分析和版本比较。

## ADDED Requirements

### Requirement: User can navigate the evaluation workflow
系统 SHALL 提供 Agent、Datasets、Evaluators、Evaluation Runs 和 Reports/Traces 的可访问入口，并在相关页面显示对象状态、版本和最近运行结果。

#### Scenario: Create and run an evaluation from the UI
- **WHEN** 用户依次配置 Agent、选择 Dataset 和 Evaluators 并提交运行
- **THEN** 页面显示运行状态，运行完成后提供结果摘要和失败样本入口

### Requirement: UI supports Prompt Agent configuration
系统 SHALL 提供 Prompt Agent 配置页面，支持填写模型、系统 Prompt、用户 Prompt 模板、变量、采样参数和结构化输出 Schema，并提供单样本连接测试和渲染结果预览。

#### Scenario: Preview and test a Prompt Agent
- **WHEN** 用户填写 Prompt 模板和测试变量并执行连接测试
- **THEN** 页面显示渲染后的 Prompt、模型输出、Token/成本信息和可继续创建评测运行的结果

### Requirement: UI exposes import validation before confirmation
系统 SHALL 在文件导入页面提供字段映射、样本预览、错误行和确认导入操作。用户在确认前 MUST 能取消导入，不得因为预览而创建不可见的数据集版本。

#### Scenario: Correct an import mapping
- **WHEN** 用户将文件字段映射到 input、expected output 或 metadata 后预览
- **THEN** 预览内容和校验结果实时反映新的映射，用户确认后才创建 Dataset Case

### Requirement: UI exposes trace-to-score evidence
系统 SHALL 在报告中提供从聚合指标到样本、从样本到 Score、从 Score 到 Trace 节点的可导航路径。

#### Scenario: Navigate from a low score to the cause
- **WHEN** 用户点击某项低分指标并选择一个失败样本
- **THEN** 页面定位到该样本的评估解释和相关 Trace 节点，而不是只显示一个无法解释的总分

### Requirement: UI handles long-running and failed operations
系统 SHALL 显示评测运行的进度、排队数量、已完成数量、失败数量和取消操作。网络错误或权限错误 MUST 显示可理解的错误状态和重试或返回入口。

#### Scenario: Refresh an active run
- **WHEN** 用户离开运行页面后重新进入
- **THEN** 页面从服务端恢复并显示当前运行状态，而不依赖浏览器内存中的临时状态
