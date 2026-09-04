"""Relational persistence model.

Frequently filtered identifiers are relational columns.  Agent-specific and
provider-specific payloads remain JSON so the schema can evolve without
flattening every new agent framework into a migration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JsonType = JSON().with_variant(JSONB, "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    api_keys: Mapped[list[ApiKeyRecord]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    agents: Mapped[list[AgentRecord]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    datasets: Mapped[list[DatasetRecord]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    evaluators: Mapped[list[EvaluatorVersionRecord]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    traces: Mapped[list[TraceRecord]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ApiKeyRecord(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("project_id", "key_hash", name="uq_api_keys_project_hash"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[ProjectRecord] = relationship(back_populates="api_keys")


class AgentRecord(Base):
    __tablename__ = "agents"
    __table_args__ = (Index("ix_agents_project_type", "project_id", "agent_type"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[ProjectRecord] = relationship(back_populates="agents")
    versions: Mapped[list[AgentVersionRecord]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class AgentVersionRecord(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        Index("ix_agent_versions_agent_enabled", "agent_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_config: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    endpoint_config: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    agent: Mapped[AgentRecord] = relationship(back_populates="versions")
    runs: Mapped[list[EvaluationRunRecord]] = relationship(back_populates="agent_version")


class DatasetRecord(Base):
    __tablename__ = "datasets"
    __table_args__ = (Index("ix_datasets_project_name", "project_id", "name"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_versions.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[ProjectRecord] = relationship(back_populates="datasets")
    versions: Mapped[list[DatasetVersionRecord]] = relationship(
        back_populates="dataset",
        foreign_keys="DatasetVersionRecord.dataset_id",
        cascade="all, delete-orphan",
    )
    current_version: Mapped[DatasetVersionRecord | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class DatasetVersionRecord(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_dataset_versions_dataset_version"),
        Index("ix_dataset_versions_dataset_created", "dataset_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JsonType, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    dataset: Mapped[DatasetRecord] = relationship(
        back_populates="versions", foreign_keys=[dataset_id]
    )
    cases: Mapped[list[DatasetCaseRecord]] = relationship(
        back_populates="dataset_version", cascade="all, delete-orphan"
    )
    runs: Mapped[list[EvaluationRunRecord]] = relationship(back_populates="dataset_version")


class DatasetCaseRecord(Base):
    __tablename__ = "dataset_cases"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "case_key", name="uq_dataset_cases_version_key"),
        Index("ix_dataset_cases_version", "dataset_version_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    case_key: Mapped[str] = mapped_column(String(128), nullable=False)
    input_json: Mapped[Any] = mapped_column("input", JsonType, nullable=False)
    variables: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    expected_output: Mapped[Any | None] = mapped_column(JsonType)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    criteria: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    expected_tools: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonType, default=list, nullable=False
    )
    expected_state: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    retrieval_context: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonType, default=list, nullable=False
    )
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JsonType, default=dict, nullable=False
    )
    source_trace_id: Mapped[str | None] = mapped_column(String(128))

    dataset_version: Mapped[DatasetVersionRecord] = relationship(back_populates="cases")
    executions: Mapped[list[CaseExecutionRecord]] = relationship(back_populates="dataset_case")


class EvaluatorVersionRecord(Base):
    __tablename__ = "evaluator_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            "version",
            name="uq_evaluator_versions_project_name_version",
        ),
        Index("ix_evaluator_versions_project_enabled", "project_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    evaluator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requires: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    supported_agent_types: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    score_min: Mapped[float | None] = mapped_column(Float)
    score_max: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    default_threshold: Mapped[float | None] = mapped_column(Float)
    rubric: Mapped[str | None] = mapped_column(Text)
    judge_model: Mapped[str | None] = mapped_column(String(200))
    config: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    project: Mapped[ProjectRecord] = relationship(back_populates="evaluators")


class EvaluationRunRecord(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_evaluation_runs_project_created", "project_id", "created_at"),
        Index("ix_evaluation_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_version_id: Mapped[str] = mapped_column(ForeignKey("agent_versions.id"), nullable=False)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JsonType, default=dict, nullable=False
    )
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent_version: Mapped[AgentVersionRecord] = relationship(back_populates="runs")
    dataset_version: Mapped[DatasetVersionRecord] = relationship(back_populates="runs")
    executions: Mapped[list[CaseExecutionRecord]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    traces: Mapped[list[TraceRecord]] = relationship(back_populates="run")
    scores: Mapped[list[ScoreRecord]] = relationship(back_populates="run")


class CaseExecutionRecord(Base):
    __tablename__ = "case_executions"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_case_executions_run_case"),
        Index("ix_case_executions_run_status", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(ForeignKey("dataset_cases.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output: Mapped[Any | None] = mapped_column(JsonType)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("traces.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[EvaluationRunRecord] = relationship(back_populates="executions")
    dataset_case: Mapped[DatasetCaseRecord] = relationship(back_populates="executions")
    trace: Mapped[TraceRecord | None] = relationship(foreign_keys=[trace_id])


class TraceRecord(Base):
    __tablename__ = "traces"
    __table_args__ = (
        Index("ix_traces_project_created", "project_id", "created_at"),
        Index("ix_traces_run_case", "run_id", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="SET NULL")
    )
    case_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="platform")
    extensions: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    project: Mapped[ProjectRecord] = relationship(back_populates="traces")
    run: Mapped[EvaluationRunRecord | None] = relationship(back_populates="traces")
    spans: Mapped[list[TraceSpanRecord]] = relationship(
        back_populates="trace", cascade="all, delete-orphan"
    )


class TraceSpanRecord(Base):
    __tablename__ = "trace_spans"
    __table_args__ = (
        UniqueConstraint("trace_id", "span_id", name="uq_trace_spans_trace_span"),
        Index("ix_trace_spans_trace_parent", "trace_id", "parent_span_id"),
        Index("ix_trace_spans_trace_started", "trace_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    trace_id: Mapped[str] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    span_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input: Mapped[Any | None] = mapped_column(JsonType)
    output: Mapped[Any | None] = mapped_column(JsonType)
    error: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    attributes: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    extensions: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)

    trace: Mapped[TraceRecord] = relationship(back_populates="spans")


class ScoreRecord(Base):
    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "case_id", "metric_name", "evaluator_version_id", name="uq_scores_case_metric"
        ),
        Index("ix_scores_run_metric", "run_id", "metric_name"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    evaluator_version_id: Mapped[str] = mapped_column(
        ForeignKey("evaluator_versions.id"), nullable=False
    )
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("traces.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    label: Mapped[str | None] = mapped_column(String(100))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    explanation: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    rubric: Mapped[str | None] = mapped_column(Text)
    judge_model: Mapped[str | None] = mapped_column(String(200))
    threshold: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_result: Mapped[Any | None] = mapped_column(JsonType)

    run: Mapped[EvaluationRunRecord] = relationship(back_populates="scores")


class AnnotationQueueRecord(Base):
    __tablename__ = "annotation_queues"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_annotation_queues_project_name"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    evaluator_version_id: Mapped[str] = mapped_column(
        ForeignKey("evaluator_versions.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    items: Mapped[list[AnnotationQueueItemRecord]] = relationship(
        back_populates="queue", cascade="all, delete-orphan"
    )


class AnnotationQueueItemRecord(Base):
    __tablename__ = "annotation_queue_items"
    __table_args__ = (
        UniqueConstraint("queue_id", "run_id", "case_id", name="uq_annotation_item_case"),
        Index("ix_annotation_items_queue_status", "queue_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    queue_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_queues.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("traces.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    queue: Mapped[AnnotationQueueRecord] = relationship(back_populates="items")


class HumanScoreAuditRecord(Base):
    __tablename__ = "human_score_audits"
    __table_args__ = (Index("ix_human_score_audits_score_created", "score_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    score_id: Mapped[str] = mapped_column(
        ForeignKey("scores.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    new_value: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AggregateMetricRecord(Base):
    __tablename__ = "aggregate_metrics"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "metric_name",
            "evaluator_version_id",
            name="uq_aggregate_metrics_run_metric_evaluator",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    evaluator_version_id: Mapped[str] = mapped_column(
        ForeignKey("evaluator_versions.id"), nullable=False
    )
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average: Mapped[float | None] = mapped_column(Float)
    pass_rate: Mapped[float | None] = mapped_column(Float)
    aggregation: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)


@event.listens_for(AgentVersionRecord, "before_update")
@event.listens_for(DatasetVersionRecord, "before_update")
@event.listens_for(EvaluatorVersionRecord, "before_update")
def reject_version_mutation(_: Any, __: Any, target: Any) -> None:
    """Version rows are snapshots; create a new row instead of mutating history."""

    state = inspect(target)
    changed = {
        attribute.key
        for attribute in state.mapper.column_attrs
        if state.attrs[attribute.key].history.has_changes()
    }
    if isinstance(target, (AgentVersionRecord, EvaluatorVersionRecord)) and changed <= {"enabled"}:
        return
    raise ValueError("versioned records are immutable")
