"""Pydantic contracts for the evaluation workbench.

The models intentionally keep domain payloads as JSON objects.  This lets the
platform support prompt, RAG, tool and custom agents without flattening their
different inputs into unrelated APIs.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None
JsonObject = dict[str, Any]


class ContractModel(BaseModel):
    """Reject accidental API drift while allowing explicit JSON payload fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentType(StrEnum):
    PROMPT = "prompt"
    RAG = "rag"
    TOOL = "tool"
    CUSTOM = "custom"


class EvaluatorType(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_JUDGE = "llm_judge"
    ADAPTER = "adapter"
    HUMAN = "human"


class AdapterKind(StrEnum):
    SAFETY_SCAN = "safety_scan"
    BENCHMARK = "benchmark"


class AdapterLifecycle(StrEnum):
    PLANNED = "planned"
    EXPERIMENTAL = "experimental"
    AVAILABLE = "available"


class AdapterExecutionMode(StrEnum):
    EXTERNAL_RUNNER = "external_runner"
    EXTERNAL_ENVIRONMENT = "external_environment"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScoreStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    MISSING = "missing"
    ERROR = "error"
    NOT_RUN = "not_run"


class AnnotationStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class ScoreDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class RegressionGateStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    INCOMPLETE = "incomplete"


class TraceSpanKind(StrEnum):
    AGENT = "agent"
    PROMPT = "prompt"
    LLM = "llm"
    TOOL = "tool"
    TOOL_RESULT = "tool_result"
    RETRIEVAL = "retrieval"
    GUARDRAIL = "guardrail"
    EVALUATOR = "evaluator"


class PromptConfig(ContractModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    endpoint: HttpUrl
    system_prompt: str = ""
    user_template: str = Field(min_length=1)
    variable_names: list[str] = Field(default_factory=list)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, gt=0)
    response_format: JsonObject | None = None
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=300.0)
    concurrency_limit: int = Field(default=4, gt=0, le=100)
    rate_limit_per_minute: int | None = Field(default=None, gt=0, le=60_000)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.2, ge=0.0, le=30.0)
    input_cost_per_1k: float | None = Field(default=None, ge=0.0)
    output_cost_per_1k: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def validate_variables(self) -> PromptConfig:
        names = set(self.variable_names)
        if len(names) != len(self.variable_names):
            raise ValueError("variable_names must not contain duplicates")
        if any(not name for name in self.variable_names):
            raise ValueError("variable_names must contain non-empty names")
        return self


class EndpointConfig(ContractModel):
    url: HttpUrl
    method: Literal["POST"] = "POST"
    auth_ref: str | None = Field(default=None, min_length=1, max_length=200)
    protocol_version: str = Field(default="v1", min_length=1, max_length=50)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    max_response_bytes: int = Field(default=1_048_576, gt=0)
    max_tool_calls: int = Field(default=32, ge=0)
    concurrency_limit: int = Field(default=4, gt=0, le=100)
    rate_limit_per_minute: int | None = Field(default=None, gt=0, le=60_000)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.2, ge=0.0, le=30.0)


class Agent(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    agent_type: AgentType
    description: str | None = None
    active: bool = True
    created_at: datetime
    updated_at: datetime


class AgentVersion(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    version: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=100)
    agent_type: AgentType
    prompt_config: PromptConfig | None = None
    endpoint_config: EndpointConfig | None = None
    enabled: bool = True
    created_at: datetime

    @model_validator(mode="after")
    def validate_execution_config(self) -> AgentVersion:
        if self.agent_type is AgentType.PROMPT:
            if self.prompt_config is None or self.endpoint_config is not None:
                raise ValueError("prompt agents require prompt_config only")
        elif self.endpoint_config is None or self.prompt_config is not None:
            raise ValueError("non-prompt agents require endpoint_config only")
        return self


class ExpectedToolCall(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    arguments: JsonObject = Field(default_factory=dict)
    order: int | None = Field(default=None, ge=0)


class ChatMessage(ContractModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: JsonValue
    name: str | None = Field(default=None, min_length=1, max_length=200)


class RetrievalContext(ContractModel):
    content: str = Field(min_length=1)
    document_id: str | None = Field(default=None, min_length=1, max_length=200)
    metadata: JsonObject = Field(default_factory=dict)


class DatasetCase(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    input: JsonValue
    variables: JsonObject = Field(default_factory=dict)
    expected_output: JsonValue = None
    output_schema: JsonObject | None = None
    criteria: list[str] = Field(default_factory=list)
    expected_tools: list[ExpectedToolCall] = Field(default_factory=list)
    expected_state: JsonObject | None = None
    retrieval_context: list[RetrievalContext] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)
    source_trace_id: str | None = Field(default=None, min_length=1, max_length=128)


class DatasetVersion(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    dataset_id: str = Field(min_length=1, max_length=128)
    version: int = Field(gt=0)
    cases: list[DatasetCase] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)
    created_at: datetime

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> DatasetVersion:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("dataset case ids must be unique within a version")
        return self


class Dataset(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    current_version_id: str | None = Field(default=None, min_length=1, max_length=128)
    created_at: datetime
    updated_at: datetime


class EvaluatorVersion(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    evaluator_type: EvaluatorType
    requires: list[str] = Field(default_factory=list)
    supported_agent_types: list[AgentType] = Field(min_length=1)
    score_min: float | None = None
    score_max: float | None = None
    direction: ScoreDirection
    default_threshold: float | None = None
    rubric: str | None = None
    judge_model: str | None = None
    config: JsonObject = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_score_range(self) -> EvaluatorVersion:
        if any(not field_name for field_name in self.requires) or len(self.requires) != len(
            set(self.requires)
        ):
            raise ValueError("requires must contain unique non-empty field names")
        if self.score_min is not None and self.score_max is not None:
            if self.score_min >= self.score_max:
                raise ValueError("score_min must be lower than score_max")
            if self.default_threshold is not None and not (
                self.score_min <= self.default_threshold <= self.score_max
            ):
                raise ValueError("default_threshold must be within score range")
        return self


class EvaluatorVersionCreateRequest(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    evaluator_type: EvaluatorType
    requires: list[str] = Field(default_factory=list)
    supported_agent_types: list[AgentType] = Field(min_length=1)
    score_min: float | None = None
    score_max: float | None = None
    direction: ScoreDirection
    default_threshold: float | None = None
    rubric: str | None = None
    judge_model: str | None = None
    config: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_score_range(self) -> EvaluatorVersionCreateRequest:
        EvaluatorVersion(
            id="validation-only",
            name=self.name,
            version=self.version,
            evaluator_type=self.evaluator_type,
            requires=self.requires,
            supported_agent_types=self.supported_agent_types,
            score_min=self.score_min,
            score_max=self.score_max,
            direction=self.direction,
            default_threshold=self.default_threshold,
            rubric=self.rubric,
            judge_model=self.judge_model,
            config=self.config,
        )
        return self


class AdapterCapability(ContractModel):
    """Declared boundary for integrations that need a separate runner or environment."""

    adapter_id: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    kind: AdapterKind
    lifecycle: AdapterLifecycle = AdapterLifecycle.PLANNED
    source_project: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=500)
    execution_mode: AdapterExecutionMode
    supported_agent_types: list[AgentType] = Field(min_length=1)
    required_case_fields: list[str] = Field(default_factory=list)
    required_trace_kinds: list[TraceSpanKind] = Field(default_factory=list)
    result_metrics: list[str] = Field(min_length=1)
    requires_external_environment: bool = False
    supports_ci: bool = True
    config_schema: JsonObject = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capability_lists(self) -> AdapterCapability:
        if len(self.supported_agent_types) != len(set(self.supported_agent_types)):
            raise ValueError("supported_agent_types must be unique")
        if any(not field_name for field_name in self.required_case_fields):
            raise ValueError("required_case_fields must contain non-empty names")
        if any(not metric for metric in self.result_metrics):
            raise ValueError("result_metrics must contain non-empty names")
        return self


class AdapterInvocation(ContractModel):
    """Canonical input passed to a future safety or benchmark runner."""

    adapter_id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=128)
    agent_version_id: str = Field(min_length=1, max_length=128)
    dataset_version_id: str = Field(min_length=1, max_length=128)
    cases: list[DatasetCase] = Field(min_length=1)
    config: JsonObject = Field(default_factory=dict)


class AdapterScoreResult(ContractModel):
    metric_name: str = Field(min_length=1, max_length=200)
    value: float | None = None
    passed: bool | None = None
    label: str | None = None
    explanation: str | None = None
    evidence: list[JsonObject] = Field(default_factory=list)
    raw_result: JsonValue | None = None


class AdapterExecutionResult(ContractModel):
    adapter_id: str = Field(min_length=1, max_length=100)
    adapter_version: str = Field(min_length=1, max_length=100)
    status: Literal["completed", "failed", "not_available"]
    scores: list[AdapterScoreResult] = Field(default_factory=list)
    raw_result: JsonValue | None = None
    error_type: str | None = None
    error_message: str | None = None


class EvaluationRun(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    agent_version_id: str = Field(min_length=1, max_length=128)
    dataset_version_id: str = Field(min_length=1, max_length=128)
    evaluator_version_ids: list[str] = Field(min_length=1)
    status: RunStatus = RunStatus.QUEUED
    total_cases: int = Field(default=0, ge=0)
    completed_cases: int = Field(default=0, ge=0)
    failed_cases: int = Field(default=0, ge=0)
    configuration_snapshot: JsonObject = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def validate_case_counts(self) -> EvaluationRun:
        if self.completed_cases + self.failed_cases > self.total_cases:
            raise ValueError("completed and failed cases cannot exceed total_cases")
        if len(self.evaluator_version_ids) != len(set(self.evaluator_version_ids)):
            raise ValueError("evaluator_version_ids must be unique")
        return self


class EvaluationRunCreateRequest(ContractModel):
    agent_version_id: str = Field(min_length=1, max_length=128)
    dataset_version_id: str = Field(min_length=1, max_length=128)
    evaluator_version_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_evaluators(self) -> EvaluationRunCreateRequest:
        if len(self.evaluator_version_ids) != len(set(self.evaluator_version_ids)):
            raise ValueError("evaluator_version_ids must be unique")
        return self


class CaseExecution(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=128)
    status: ExecutionStatus = ExecutionStatus.QUEUED
    attempt: int = Field(default=0, ge=0)
    output: JsonValue = None
    tool_calls: list[ExpectedToolCall] = Field(default_factory=list)
    usage: JsonObject = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    trace_id: str | None = Field(default=None, min_length=1, max_length=128)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EvaluationRunDetail(EvaluationRun):
    case_executions: list[CaseExecution] = Field(default_factory=list)


class TraceSpan(ContractModel):
    span_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    parent_span_id: str | None = Field(default=None, min_length=1, max_length=128)
    kind: TraceSpanKind
    name: str = Field(min_length=1, max_length=200)
    status: ExecutionStatus
    started_at: datetime
    ended_at: datetime | None = None
    input: JsonValue = None
    output: JsonValue = None
    error: JsonObject | None = None
    attributes: JsonObject = Field(default_factory=dict)
    extensions: JsonObject = Field(default_factory=dict)


class Trace(ContractModel):
    trace_id: str = Field(min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    case_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: ExecutionStatus
    spans: list[TraceSpan] = Field(default_factory=list)
    source: str = Field(default="platform", min_length=1, max_length=100)
    extensions: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span_trace_ids(self) -> Trace:
        if any(span.trace_id != self.trace_id for span in self.spans):
            raise ValueError("all trace spans must reference the containing trace")
        span_ids = [span.span_id for span in self.spans]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("trace span ids must be unique")
        parent_by_span = {span.span_id: span.parent_span_id for span in self.spans}
        for span in self.spans:
            parent_span_id = span.parent_span_id
            if parent_span_id is not None and parent_span_id not in parent_by_span:
                raise ValueError("trace span parent must exist in the containing trace")
            seen: set[str] = set()
            while parent_span_id is not None:
                if parent_span_id in seen:
                    raise ValueError("trace spans must not contain parent cycles")
                seen.add(parent_span_id)
                parent_span_id = parent_by_span[parent_span_id]
        return self


class TraceIngestRequest(ContractModel):
    """Accept either the platform schema or an external trace payload."""

    source: str = Field(default="external", min_length=1, max_length=100)
    trace: Trace | None = None
    payload: JsonObject | None = None

    @model_validator(mode="after")
    def validate_single_payload(self) -> TraceIngestRequest:
        if (self.trace is None) == (self.payload is None):
            raise ValueError("provide exactly one of trace or payload")
        return self


class TraceFieldSelection(ContractModel):
    span_id: str = Field(min_length=1, max_length=128)
    field: Literal["input", "output", "attributes", "extensions"]
    attribute_key: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_attribute_selection(self) -> TraceFieldSelection:
        if self.attribute_key is not None and self.field not in {"attributes", "extensions"}:
            raise ValueError("attribute_key requires attributes or extensions")
        return self


class TraceToDatasetCaseRequest(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    input: TraceFieldSelection | None = None
    expected_output: TraceFieldSelection | None = None
    expected_state: TraceFieldSelection | None = None
    tool_span_ids: list[str] | None = None
    metadata: JsonObject = Field(default_factory=dict)


class TraceSummary(ContractModel):
    trace_id: str = Field(min_length=1, max_length=128)
    run_id: str | None = None
    case_id: str | None = None
    status: ExecutionStatus
    source: str = Field(min_length=1, max_length=100)
    span_count: int = Field(ge=0)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime


class TraceTimelineSpan(ContractModel):
    span_id: str = Field(min_length=1, max_length=128)
    parent_span_id: str | None = None
    kind: TraceSpanKind
    name: str = Field(min_length=1, max_length=200)
    status: ExecutionStatus
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0.0)
    depth: int = Field(ge=0)


class TraceTimeline(ContractModel):
    trace_id: str = Field(min_length=1, max_length=128)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    spans: list[TraceTimelineSpan] = Field(default_factory=list)


class Score(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=128)
    metric_name: str = Field(min_length=1, max_length=200)
    evaluator_version_id: str = Field(min_length=1, max_length=128)
    trace_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: ScoreStatus
    value: float | None = None
    label: str | None = None
    passed: bool | None = None
    explanation: str | None = None
    evidence: list[JsonObject] = Field(default_factory=list)
    rubric: str | None = None
    judge_model: str | None = None
    threshold: float | None = None
    direction: ScoreDirection
    raw_result: JsonValue = None

    @model_validator(mode="after")
    def validate_result(self) -> Score:
        if self.status in {ScoreStatus.PASSED, ScoreStatus.FAILED}:
            if self.value is None and self.label is None:
                raise ValueError("passed or failed scores require value or label")
            if self.passed is None:
                raise ValueError("passed or failed scores require an explicit passed flag")
        if self.status in {ScoreStatus.MISSING, ScoreStatus.ERROR, ScoreStatus.NOT_RUN}:
            if self.passed is True:
                raise ValueError("missing, error and not_run scores cannot pass")
        return self


class AnnotationQueueCreateRequest(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    evaluator_version_id: str = Field(min_length=1, max_length=128)


class AnnotationQueue(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    evaluator_version_id: str = Field(min_length=1, max_length=128)
    created_at: datetime


class AnnotationQueueItemCreateRequest(ContractModel):
    run_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=128)


class AnnotationQueueItem(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    queue_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=128)
    trace_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: AnnotationStatus
    created_at: datetime
    completed_at: datetime | None = None


class HumanScoreRequest(ContractModel):
    value: float | None = None
    label: str | None = Field(default=None, min_length=1, max_length=100)
    passed: bool
    explanation: str | None = None
    evidence: list[JsonObject] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> HumanScoreRequest:
        if self.value is None and self.label is None:
            raise ValueError("human score requires value or label")
        return self


class HumanScoreAudit(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    score_id: str = Field(min_length=1, max_length=128)
    action: Literal["created", "updated"]
    reviewer: str = Field(min_length=1, max_length=200)
    previous_value: JsonObject | None = None
    new_value: JsonObject
    created_at: datetime


class AggregateMetric(ContractModel):
    metric_name: str = Field(min_length=1, max_length=200)
    evaluator_version_id: str = Field(min_length=1, max_length=128)
    valid_count: int = Field(default=0, ge=0)
    missing_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    passed_count: int = Field(default=0, ge=0)
    average: float | None = None
    pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    aggregation: Literal["mean", "pass_rate", "sum", "min", "max"]
    threshold: float | None = None
    direction: ScoreDirection

    @model_validator(mode="after")
    def validate_aggregate_counts(self) -> AggregateMetric:
        if self.passed_count > self.valid_count:
            raise ValueError("passed_count cannot exceed valid_count")
        if self.pass_rate is not None and self.valid_count == 0:
            raise ValueError("pass_rate requires at least one valid score")
        return self


class EvaluationReportSummary(ContractModel):
    run_id: str = Field(min_length=1, max_length=128)
    status: RunStatus
    agent_version_id: str = Field(min_length=1, max_length=128)
    dataset_version_id: str = Field(min_length=1, max_length=128)
    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    metrics: list[AggregateMetric] = Field(default_factory=list)
    created_at: datetime
    finished_at: datetime | None = None


class EvaluationReportCase(ContractModel):
    case_id: str = Field(min_length=1, max_length=128)
    metadata: JsonObject = Field(default_factory=dict)
    execution_status: ExecutionStatus
    error_type: str | None = None
    error_message: str | None = None
    output: JsonValue = None
    trace_id: str | None = Field(default=None, min_length=1, max_length=128)
    scores: list[Score] = Field(default_factory=list)


class EvaluationReport(ContractModel):
    run_id: str = Field(min_length=1, max_length=128)
    status: RunStatus
    total_cases: int = Field(ge=0)
    matched_cases: int = Field(ge=0)
    filters: JsonObject = Field(default_factory=dict)
    metrics: list[AggregateMetric] = Field(default_factory=list)
    cases: list[EvaluationReportCase] = Field(default_factory=list)
    generated_at: datetime


class ComparisonRequest(ContractModel):
    run_ids: list[str] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def validate_unique_runs(self) -> ComparisonRequest:
        if any(not run_id for run_id in self.run_ids):
            raise ValueError("run_ids must contain non-empty ids")
        if len(self.run_ids) != len(set(self.run_ids)):
            raise ValueError("run_ids must be unique")
        return self


class ComparisonRun(ContractModel):
    run_id: str = Field(min_length=1, max_length=128)
    agent_version_id: str = Field(min_length=1, max_length=128)
    agent_version: JsonObject = Field(default_factory=dict)
    dataset_version_id: str = Field(min_length=1, max_length=128)
    status: RunStatus
    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    created_at: datetime
    finished_at: datetime | None = None


class ComparisonMetricPoint(ContractModel):
    run_id: str = Field(min_length=1, max_length=128)
    average: float | None = None
    pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    valid_count: int = Field(default=0, ge=0)
    missing_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    passed_count: int = Field(default=0, ge=0)
    delta_average: float | None = None
    delta_pass_rate: float | None = None


class MetricComparison(ContractModel):
    metric_name: str = Field(min_length=1, max_length=200)
    evaluator_version_ids: list[str] = Field(default_factory=list)
    comparable: bool
    reason: str | None = None
    points: list[ComparisonMetricPoint] = Field(default_factory=list)


class GroupComparison(ContractModel):
    group_by: Literal["category", "difficulty", "tag"]
    group_value: str = Field(min_length=1, max_length=200)
    metric_name: str = Field(min_length=1, max_length=200)
    evaluator_version_ids: list[str] = Field(default_factory=list)
    comparable: bool
    reason: str | None = None
    points: list[ComparisonMetricPoint] = Field(default_factory=list)


class CaseComparisonRun(ContractModel):
    run_id: str = Field(min_length=1, max_length=128)
    execution_status: ExecutionStatus
    output: JsonValue = None
    trace_id: str | None = Field(default=None, min_length=1, max_length=128)
    error_type: str | None = None
    error_message: str | None = None
    failed: bool
    scores: list[Score] = Field(default_factory=list)


class CaseComparison(ContractModel):
    case_id: str = Field(min_length=1, max_length=128)
    metadata: JsonObject = Field(default_factory=dict)
    runs: list[CaseComparisonRun] = Field(default_factory=list)


class CaseComparisonChange(ContractModel):
    case_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    baseline_run_id: str = Field(min_length=1, max_length=128)
    failed_metrics: list[str] = Field(default_factory=list)


class EvaluationComparison(ContractModel):
    dataset_version_id: str = Field(min_length=1, max_length=128)
    baseline_run_id: str = Field(min_length=1, max_length=128)
    runs: list[ComparisonRun] = Field(min_length=2)
    metric_comparisons: list[MetricComparison] = Field(default_factory=list)
    group_comparisons: list[GroupComparison] = Field(default_factory=list)
    case_comparisons: list[CaseComparison] = Field(default_factory=list)
    new_failures: list[CaseComparisonChange] = Field(default_factory=list)
    recovered_cases: list[CaseComparisonChange] = Field(default_factory=list)
    generated_at: datetime


class RegressionGateRule(ContractModel):
    metric_name: str = Field(min_length=1, max_length=200)
    evaluator_version_id: str | None = Field(default=None, min_length=1, max_length=128)
    aggregation: Literal["average", "pass_rate"] = "pass_rate"
    minimum: float | None = None
    maximum: float | None = None
    require_all_passed: bool = False

    @model_validator(mode="after")
    def validate_condition(self) -> RegressionGateRule:
        if (
            self.minimum is None
            and self.maximum is None
            and not self.require_all_passed
        ):
            raise ValueError(
                "a regression gate rule requires minimum, maximum or require_all_passed"
            )
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum cannot exceed maximum")
        return self


class RegressionGateRequest(ContractModel):
    rules: list[RegressionGateRule] = Field(min_length=1, max_length=50)


class RegressionGateRuleResult(ContractModel):
    rule: RegressionGateRule
    status: RegressionGateStatus
    actual_value: float | None = None
    valid_count: int = Field(default=0, ge=0)
    missing_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    failed_case_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class RegressionGateResult(ContractModel):
    run_id: str = Field(min_length=1, max_length=128)
    run_status: RunStatus
    status: RegressionGateStatus
    rules: list[RegressionGateRuleResult] = Field(default_factory=list)
    generated_at: datetime


class HealthResponse(ContractModel):
    status: Literal["ok"]
    environment: Literal["development", "test", "production"]


class AccessCheckResponse(ContractModel):
    project_id: str = Field(min_length=1, max_length=128)
    principal_type: Literal["browser", "agent", "ci"]


class AgentCreateRequest(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    agent_type: AgentType
    description: str | None = None
    prompt_config: PromptConfig | None = None
    endpoint_config: EndpointConfig | None = None

    @model_validator(mode="after")
    def validate_execution_config(self) -> AgentCreateRequest:
        if self.agent_type is AgentType.PROMPT:
            if self.prompt_config is None or self.endpoint_config is not None:
                raise ValueError("prompt agents require prompt_config only")
        elif self.endpoint_config is None or self.prompt_config is not None:
            raise ValueError("non-prompt agents require endpoint_config only")
        return self


class AgentVersionCreateRequest(AgentCreateRequest):
    label: str = Field(default="", max_length=100)


class AgentResponse(ContractModel):
    id: str
    project_id: str
    name: str
    agent_type: AgentType
    description: str | None
    active: bool
    current_version_id: str | None
    created_at: datetime
    updated_at: datetime


class AgentVersionResponse(ContractModel):
    id: str
    agent_id: str
    version: int
    label: str
    agent_type: AgentType
    prompt_config: PromptConfig | None
    endpoint_config: EndpointConfig | None
    enabled: bool
    created_at: datetime


class AgentConnectionTestRequest(ContractModel):
    agent_type: AgentType
    prompt_config: PromptConfig | None = None
    endpoint_config: EndpointConfig | None = None
    input: JsonValue = "connection test"
    variables: JsonObject = Field(default_factory=dict)
    messages: list[ChatMessage] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_execution_config(self) -> AgentConnectionTestRequest:
        if self.agent_type is AgentType.PROMPT:
            if self.prompt_config is None or self.endpoint_config is not None:
                raise ValueError("prompt agents require prompt_config only")
        elif self.endpoint_config is None or self.prompt_config is not None:
            raise ValueError("non-prompt agents require endpoint_config only")
        return self


class AgentConnectionTestResponse(ContractModel):
    success: bool
    message: str
    error_type: str | None = None
    latency_ms: float = Field(ge=0.0)
    output: JsonValue | None = None
    rendered_prompt: str | None = None
    usage: JsonObject = Field(default_factory=dict)


class DatasetCreateRequest(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    cases: list[DatasetCase] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tags(self) -> DatasetCreateRequest:
        if any(not tag for tag in self.tags) or len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must be non-empty and unique")
        return self


class DatasetUpdateRequest(ContractModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    tags: list[str] | None = None

    @model_validator(mode="after")
    def validate_tags(self) -> DatasetUpdateRequest:
        if self.tags is not None and (
            any(not tag for tag in self.tags) or len(set(self.tags)) != len(self.tags)
        ):
            raise ValueError("tags must be non-empty and unique")
        return self


class DatasetVersionCreateRequest(ContractModel):
    cases: list[DatasetCase] = Field(default_factory=list)
    metadata: JsonObject | None = None


class DatasetCaseCreateRequest(DatasetCase):
    pass


class DatasetResponse(Dataset):
    pass


class DatasetImportRequest(ContractModel):
    format: Literal["csv", "json", "jsonl"]
    content_base64: str = Field(min_length=1)
    encoding: str = Field(default="utf-8", min_length=1, max_length=50)
    field_mapping: dict[str, str] = Field(default_factory=dict)


class DatasetImportCommitRequest(DatasetImportRequest):
    metadata: JsonObject | None = None
    allow_partial: bool = False


class DatasetImportIssueResponse(ContractModel):
    line: int = Field(ge=0)
    reason: str


class DatasetImportPreviewResponse(ContractModel):
    cases: list[DatasetCase] = Field(default_factory=list)
    issues: list[DatasetImportIssueResponse] = Field(default_factory=list)


class DatasetImportCommitResponse(ContractModel):
    dataset_version: DatasetVersion
    issues: list[DatasetImportIssueResponse] = Field(default_factory=list)
