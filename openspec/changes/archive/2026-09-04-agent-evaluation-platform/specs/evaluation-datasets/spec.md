## Purpose

提供面向 Prompt Agent、单轮、多轮、Tool Agent 和 RAG Agent 的统一测试集管理能力，使测试样本可以持续积累、校验、复用、导出并用于可重复实验。

## ADDED Requirements

### Requirement: User can create Dataset Cases from multiple sources
系统 SHALL 支持用户通过手动录入、CSV/JSON/JSONL 导入、API/SDK 写入和已保存 Trace 转换创建 Dataset Case。不同来源创建的样本 MUST 使用同一套数据集模型。

#### Scenario: Create a case manually
- **WHEN** 用户填写输入并提交一个测试用例
- **THEN** 系统创建包含唯一标识的 Dataset Case，并允许继续编辑或加入评测运行

#### Scenario: Create cases from a Trace
- **WHEN** 用户选择一个已保存 Trace 并确认需要保留的字段
- **THEN** 系统创建新的或追加到已有 Dataset 的 Dataset Case，并保留来源 Trace 的关联信息

### Requirement: Dataset Case supports structured evaluation expectations
系统 SHALL 支持至少以下字段：输入、Prompt 变量、可选参考输出、可选结构化输出 Schema、可选自然语言规则、可选期望工具调用、可选期望最终状态、可选 RAG 上下文、多轮消息和元数据。输入、变量、上下文和元数据 MUST 支持结构化对象，而不是仅支持纯文本。

#### Scenario: Store a Tool Agent case
- **WHEN** 用户提交输入、期望工具名称及工具参数
- **THEN** 系统保存这些结构化期望，并可在后续工具正确性评估中提供给评估器

#### Scenario: Store a reference-free case
- **WHEN** 用户只提交输入和行为规则而不提供参考答案
- **THEN** 系统允许保存该样本，并标明依赖无参考答案评估或人工评审

#### Scenario: Store a Prompt Agent case
- **WHEN** 用户提交 Prompt 变量、可选多轮消息、参考输出、输出 Schema 或自然语言规则
- **THEN** 系统保存这些字段，并可在 Prompt Runner 和对应评估器中使用，而不要求 `expected_tools` 或 `retrieval_context`

### Requirement: File import provides mapping, preview, and validation
系统 SHALL 支持用户将文件列或 JSON 字段映射到 Dataset Case 字段，并在导入前展示样本预览。系统 MUST 检查必填字段、结构化字段格式、重复标识和不支持的字段，并报告逐行错误。

#### Scenario: Import a valid JSONL dataset
- **WHEN** 用户上传每行一个对象且包含合法输入的 JSONL 文件，完成字段映射并确认导入
- **THEN** 系统创建对应数量的 Dataset Case，并显示成功数量、数据集版本和可追溯的导入记录

#### Scenario: Import contains invalid rows
- **WHEN** 上传文件包含缺少输入或结构化字段无法解析的行
- **THEN** 系统在预览中指出行号和错误原因，用户可以取消导入或仅导入通过校验的行

### Requirement: Datasets are versioned and reproducible
系统 SHALL 为数据集及其每次变更生成可识别版本。已用于 Evaluation Run 的版本 MUST 保持不可变；编辑已使用版本时系统 SHALL 创建新版本而不是修改历史样本。

#### Scenario: Edit a dataset used by a previous run
- **WHEN** 用户修改已有样本或新增样本
- **THEN** 系统创建新的数据集版本，历史运行仍引用原版本及原始样本内容

### Requirement: Dataset can be exported
系统 SHALL 允许用户导出当前或指定版本的数据集，导出结果 MUST 包含样本标识、输入、期望字段和元数据，并保留嵌套结构。

#### Scenario: Export a structured dataset
- **WHEN** 用户选择 JSONL 导出并指定数据集版本
- **THEN** 系统下载与该版本一致的 JSONL 文件，且再次导入后样本语义不变
