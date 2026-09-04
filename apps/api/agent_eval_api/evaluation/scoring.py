"""Evaluate one finished case and atomically persist normalized sample Scores."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_eval_api.contracts import (
    AgentType,
    CaseExecution,
    DatasetCase,
    EvaluatorType,
    EvaluatorVersion,
    ExecutionStatus,
    Score,
    ScoreDirection,
    ScoreStatus,
    Trace,
    TraceSpanKind,
)
from agent_eval_api.db import (
    CaseExecutionRecord,
    EvaluationRunRecord,
    EvaluatorVersionRecord,
    ScoreRecord,
    TraceSpanRecord,
    new_id,
)
from agent_eval_api.settings import Settings
from agent_eval_api.trace_privacy import PrivacyStats, sanitize_value

from .adapters import AdapterRunner, ThirdPartyAdapterError, evaluate_adapter
from .base import EvaluationContext, EvaluatorConfigurationError, EvaluatorOutcome
from .deterministic import deterministic_evaluator_key, evaluate_deterministic
from .judge import JudgeProviderConfig, JudgeProviderError, evaluate_llm_judge
from .prompt_metrics import (
    EmbeddingProviderConfig,
    EmbeddingProviderError,
    evaluate_prompt_deterministic,
)


def _case(record: CaseExecutionRecord) -> DatasetCase:
    case = record.dataset_case
    return DatasetCase.model_validate(
        {
            "id": case.case_key,
            "input": case.input_json,
            "variables": case.variables,
            "expected_output": case.expected_output,
            "output_schema": case.output_schema,
            "criteria": case.criteria,
            "expected_tools": case.expected_tools,
            "expected_state": case.expected_state,
            "retrieval_context": case.retrieval_context,
            "messages": case.messages,
            "metadata": case.metadata_json,
            "source_trace_id": case.source_trace_id,
        }
    )


def _execution(record: CaseExecutionRecord) -> CaseExecution:
    return CaseExecution.model_validate(
        {
            "id": record.id,
            "run_id": record.run_id,
            "case_id": record.dataset_case.case_key,
            "status": ExecutionStatus(record.status),
            "attempt": record.attempt,
            "output": record.output,
            "tool_calls": record.tool_calls,
            "usage": record.usage,
            "error_type": record.error_type,
            "error_message": record.error_message,
            "trace_id": record.trace_id,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
        }
    )


def _evaluator(record: EvaluatorVersionRecord) -> EvaluatorVersion:
    return EvaluatorVersion(
        id=record.id,
        name=record.name,
        version=record.version,
        evaluator_type=EvaluatorType(record.evaluator_type),
        requires=record.requires,
        supported_agent_types=[AgentType(item) for item in record.supported_agent_types],
        score_min=record.score_min,
        score_max=record.score_max,
        direction=ScoreDirection(record.direction),
        default_threshold=record.default_threshold,
        rubric=record.rubric,
        judge_model=record.judge_model,
        config=record.config,
        enabled=record.enabled,
    )


def _secret(value: Any) -> str | None:
    return value.get_secret_value() if value is not None else None


def _judge_provider(evaluator: EvaluatorVersion, settings: Settings) -> JudgeProviderConfig:
    endpoint = evaluator.config.get("endpoint") or settings.llm_base_url
    model = evaluator.judge_model or evaluator.config.get("model")
    if not endpoint or not model:
        raise EvaluatorConfigurationError(
            "LLM judge requires evaluator endpoint/model or runtime LLM settings"
        )
    return JudgeProviderConfig(
        endpoint=str(endpoint),
        model=str(model),
        api_key=_secret(settings.llm_api_key),
        timeout_seconds=float(evaluator.config.get("timeout_seconds", 60.0)),
        max_retries=int(evaluator.config.get("max_retries", 2)),
        retry_backoff_seconds=float(evaluator.config.get("retry_backoff_seconds", 0.2)),
    )


def _embedding_provider(
    evaluator: EvaluatorVersion, settings: Settings
) -> EmbeddingProviderConfig:
    endpoint = evaluator.config.get("endpoint") or settings.embedding_base_url
    model = evaluator.config.get("model")
    if not endpoint or not model:
        raise EvaluatorConfigurationError(
            "semantic similarity requires evaluator endpoint/model or runtime embedding settings"
        )
    return EmbeddingProviderConfig(
        endpoint=str(endpoint),
        model=str(model),
        api_key=_secret(settings.embedding_api_key or settings.llm_api_key),
        timeout_seconds=float(evaluator.config.get("timeout_seconds", 60.0)),
        max_retries=int(evaluator.config.get("max_retries", 2)),
        retry_backoff_seconds=float(evaluator.config.get("retry_backoff_seconds", 0.2)),
    )


def _error_outcome(evaluator: EvaluatorVersion, exc: Exception) -> EvaluatorOutcome:
    error_type = getattr(exc, "error_type", "evaluation_error")
    return EvaluatorOutcome(
        metric_name=evaluator.name,
        status=ScoreStatus.ERROR,
        passed=None,
        explanation=str(exc),
        raw_result={"error_type": str(error_type), "message": str(exc)},
    )


async def _evaluate(
    context: EvaluationContext,
    settings: Settings,
    adapter_runners: Mapping[str, AdapterRunner] | None,
) -> list[EvaluatorOutcome]:
    evaluator = context.evaluator
    try:
        if context.execution.status is not ExecutionStatus.COMPLETED:
            return [
                EvaluatorOutcome(
                    metric_name=evaluator.name,
                    status=ScoreStatus.NOT_RUN,
                    explanation="agent execution did not complete",
                )
            ]
        if evaluator.evaluator_type is EvaluatorType.DETERMINISTIC:
            configured_metric = evaluator.config.get("metric", evaluator.name)
            key = deterministic_evaluator_key(str(configured_metric))
            if key == "semantic_similarity":
                return await evaluate_prompt_deterministic(
                    context,
                    embedding_provider=_embedding_provider(evaluator, settings),
                )
            return evaluate_deterministic(context)
        if evaluator.evaluator_type is EvaluatorType.LLM_JUDGE:
            return await evaluate_llm_judge(context, _judge_provider(evaluator, settings))
        if evaluator.evaluator_type is EvaluatorType.ADAPTER:
            adapter = str(evaluator.config.get("adapter", "")).casefold()
            runner = adapter_runners.get(adapter) if adapter_runners is not None else None
            return await evaluate_adapter(context, runner)
        return [
            EvaluatorOutcome(
                metric_name=evaluator.name,
                status=ScoreStatus.NOT_RUN,
                explanation="human evaluator requires manual review",
            )
        ]
    except (
        EmbeddingProviderError,
        EvaluatorConfigurationError,
        JudgeProviderError,
        ThirdPartyAdapterError,
    ) as exc:
        return [_error_outcome(evaluator, exc)]
    except Exception as exc:  # pragma: no cover - defensive evaluator boundary
        return [_error_outcome(evaluator, exc)]


def _safe(value: Any, settings: Settings) -> Any:
    return sanitize_value(value, settings, PrivacyStats())


def _safe_text(value: str | None, settings: Settings) -> str | None:
    if value is None:
        return None
    sanitized = _safe(value, settings)
    return sanitized if isinstance(sanitized, str) else json.dumps(sanitized, ensure_ascii=False)


def _score(
    run: EvaluationRunRecord,
    execution: CaseExecutionRecord,
    evaluator: EvaluatorVersion,
    outcome: EvaluatorOutcome,
    settings: Settings,
) -> Score:
    evidence = [_safe(item, settings) for item in outcome.evidence]
    return Score(
        id=new_id(),
        run_id=run.id,
        case_id=execution.dataset_case.case_key,
        evaluator_version_id=evaluator.id,
        trace_id=execution.trace_id,
        metric_name=outcome.metric_name,
        status=outcome.status,
        value=outcome.value,
        label=_safe_text(outcome.label, settings),
        passed=outcome.passed,
        explanation=_safe_text(outcome.explanation, settings),
        evidence=evidence,
        rubric=_safe_text(evaluator.rubric, settings),
        judge_model=evaluator.judge_model,
        threshold=evaluator.default_threshold,
        direction=evaluator.direction,
        raw_result=_safe(outcome.raw_result, settings),
    )


def _record(score: Score) -> ScoreRecord:
    return ScoreRecord(
        id=score.id,
        run_id=score.run_id,
        case_id=score.case_id,
        evaluator_version_id=score.evaluator_version_id,
        trace_id=score.trace_id,
        metric_name=score.metric_name,
        status=score.status.value,
        value=score.value,
        label=score.label,
        passed=score.passed,
        explanation=score.explanation,
        evidence=score.evidence,
        rubric=score.rubric,
        judge_model=score.judge_model,
        threshold=score.threshold,
        direction=score.direction.value,
        raw_result=score.raw_result,
    )


async def evaluate_and_persist_scores(
    db: Session,
    run: EvaluationRunRecord,
    execution: CaseExecutionRecord,
    trace: Trace,
    settings: Settings,
    *,
    adapter_runners: Mapping[str, AdapterRunner] | None = None,
) -> list[ScoreRecord]:
    """Evaluate all frozen evaluator versions once and stage Score rows for commit."""

    evaluator_ids = [item["id"] for item in run.configuration_snapshot["evaluators"]]
    records = db.scalars(
        select(EvaluatorVersionRecord).where(EvaluatorVersionRecord.id.in_(evaluator_ids))
    ).all()
    by_id = {record.id: record for record in records}
    persisted: list[ScoreRecord] = []
    parent_span_id = next(
        (span.span_id for span in trace.spans if span.parent_span_id is None),
        None,
    )
    for evaluator_id in evaluator_ids:
        record = by_id.get(evaluator_id)
        if record is None:
            continue  # Frozen versions are protected by foreign keys in normal operation.
        evaluator = _evaluator(record)
        context = EvaluationContext(
            case=_case(execution),
            execution=_execution(execution),
            evaluator=evaluator,
            trace=trace,
        )
        started_at = datetime.now(UTC)
        outcomes = await _evaluate(context, settings, adapter_runners)
        ended_at = datetime.now(UTC)
        for outcome in outcomes:
            score = _score(run, execution, evaluator, outcome, settings)
            row = _record(score)
            db.add(row)
            persisted.append(row)
            db.add(
                TraceSpanRecord(
                    trace_id=trace.trace_id,
                    span_id=new_id(),
                    parent_span_id=parent_span_id,
                    kind=TraceSpanKind.EVALUATOR.value,
                    name=outcome.metric_name,
                    status=(
                        ExecutionStatus.FAILED.value
                        if outcome.status is ScoreStatus.ERROR
                        else ExecutionStatus.COMPLETED.value
                    ),
                    started_at=started_at,
                    ended_at=ended_at,
                    input={"evaluator_version_id": evaluator.id},
                    output={
                        "score_id": score.id,
                        "status": score.status.value,
                        "value": score.value,
                        "passed": score.passed,
                    },
                    error=(
                        {"type": "evaluation_error", "message": score.explanation}
                        if score.status is ScoreStatus.ERROR
                        else None
                    ),
                    attributes={
                        "evaluator.version": evaluator.version,
                        "evaluator.type": evaluator.evaluator_type.value,
                    },
                    extensions={},
                )
            )
    db.flush()
    return persisted
