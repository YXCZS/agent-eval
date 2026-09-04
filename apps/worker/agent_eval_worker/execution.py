"""Idempotent execution of one queued evaluation case."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_eval_api.contracts import (
    EndpointConfig,
    ExecutionStatus,
    PromptConfig,
    RunStatus,
    Trace,
    TraceSpan,
    TraceSpanKind,
)
from agent_eval_api.db import (
    AgentRecord,
    AgentVersionRecord,
    CaseExecutionRecord,
    EvaluationRunRecord,
    TraceRecord,
    new_id,
)
from agent_eval_api.evaluation import aggregate_run_scores, evaluate_and_persist_scores
from agent_eval_api.run_state import transition_execution, transition_run
from agent_eval_api.runner import AgentAdapterError, PromptRunnerError, run_http_agent, run_prompt
from agent_eval_api.settings import Settings
from agent_eval_api.traces import persist_trace

_FINISHED_EXECUTION_STATUSES = {
    ExecutionStatus.COMPLETED.value,
    ExecutionStatus.FAILED.value,
    ExecutionStatus.CANCELLED.value,
}


def _execution_policy(run: EvaluationRunRecord) -> tuple[int, int | None]:
    snapshot = run.configuration_snapshot["agent_version"]
    if snapshot["agent_type"] == "prompt":
        prompt_config = PromptConfig.model_validate(snapshot["prompt_config"])
        return prompt_config.concurrency_limit, prompt_config.rate_limit_per_minute
    endpoint_config = EndpointConfig.model_validate(snapshot["endpoint_config"])
    return endpoint_config.concurrency_limit, endpoint_config.rate_limit_per_minute


def _agent_admission_delay(
    db: Session,
    run: EvaluationRunRecord,
    *,
    now: datetime,
    default_delay: float,
) -> float | None:
    """Atomically enforce cross-worker concurrency and start-rate limits per Agent."""

    agent_id = str(run.configuration_snapshot["agent_version"]["agent_id"])
    db.scalar(select(AgentRecord.id).where(AgentRecord.id == agent_id).with_for_update())
    concurrency_limit, rate_limit = _execution_policy(run)
    agent_executions = (
        select(CaseExecutionRecord)
        .join(EvaluationRunRecord, CaseExecutionRecord.run_id == EvaluationRunRecord.id)
        .join(
            AgentVersionRecord,
            EvaluationRunRecord.agent_version_id == AgentVersionRecord.id,
        )
        .where(AgentVersionRecord.agent_id == agent_id)
    )
    active = db.scalar(
        select(func.count()).select_from(agent_executions.where(
            CaseExecutionRecord.status == ExecutionStatus.RUNNING.value
        ).subquery())
    )
    if int(active or 0) >= concurrency_limit:
        return default_delay

    if rate_limit is None:
        return None
    cutoff = now - timedelta(minutes=1)
    raw_recent_starts = db.scalars(
        agent_executions.where(CaseExecutionRecord.started_at >= cutoff).with_only_columns(
            CaseExecutionRecord.started_at
        )
    ).all()
    recent_starts = [item for item in raw_recent_starts if item is not None]
    if len(recent_starts) < rate_limit:
        return None
    oldest = min(
        item.replace(tzinfo=UTC) if item.tzinfo is None else item for item in recent_starts
    )
    return max(default_delay, (oldest + timedelta(minutes=1) - now).total_seconds())


def _trace(
    *,
    trace_id: str,
    run: EvaluationRunRecord,
    execution: CaseExecutionRecord,
    status: ExecutionStatus,
    spans: list[TraceSpan],
    extensions: dict[str, Any],
) -> Trace:
    return Trace(
        trace_id=trace_id,
        run_id=run.id,
        case_id=execution.dataset_case.case_key,
        status=status,
        spans=spans,
        source="platform",
        extensions=extensions,
    )


def _agent_span(
    *,
    trace_id: str,
    span_id: str,
    execution: CaseExecutionRecord,
    status: ExecutionStatus,
    started_at: datetime,
    ended_at: datetime | None = None,
    output: Any = None,
    error: dict[str, str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> TraceSpan:
    case = execution.dataset_case
    return TraceSpan(
        span_id=span_id,
        trace_id=trace_id,
        kind=TraceSpanKind.AGENT,
        name="agent execution",
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        input={"input": case.input_json, "variables": case.variables, "messages": case.messages},
        output=output,
        error=error,
        attributes=attributes or {},
    )


async def _invoke(
    run: EvaluationRunRecord,
    execution: CaseExecutionRecord,
    trace_id: str,
    started_at: datetime,
) -> tuple[Any, list[dict[str, Any]], dict[str, Any], Trace, int]:
    case = execution.dataset_case
    agent_version = run.agent_version
    agent_span_id = new_id()
    if agent_version.agent_type == "prompt":
        prompt_config = PromptConfig.model_validate(agent_version.prompt_config)
        prompt_result = await run_prompt(
            prompt_config,
            case.variables,
            input_messages=case.messages or None,
        )
        ended_at = datetime.now(UTC)
        prompt_span_id = new_id()
        llm_span_id = new_id()
        spans = [
            _agent_span(
                trace_id=trace_id,
                span_id=agent_span_id,
                execution=execution,
                status=ExecutionStatus.COMPLETED,
                started_at=started_at,
                ended_at=ended_at,
                output=prompt_result.output,
                attributes={"agent.type": "prompt"},
            ),
            TraceSpan(
                span_id=prompt_span_id,
                trace_id=trace_id,
                parent_span_id=agent_span_id,
                kind=TraceSpanKind.PROMPT,
                name="prompt render",
                status=ExecutionStatus.COMPLETED,
                started_at=started_at,
                ended_at=ended_at,
                input={
                    "template": prompt_config.user_template,
                    "variables": prompt_result.variables_snapshot,
                },
                output=prompt_result.rendered_prompt,
            ),
            TraceSpan(
                span_id=llm_span_id,
                trace_id=trace_id,
                parent_span_id=prompt_span_id,
                kind=TraceSpanKind.LLM,
                name="chat.completions",
                status=ExecutionStatus.COMPLETED,
                started_at=started_at,
                ended_at=ended_at,
                output=prompt_result.output,
                attributes={
                    "gen_ai.request.model": prompt_config.model,
                    "gen_ai.usage.input_tokens": prompt_result.usage.input_tokens,
                    "gen_ai.usage.output_tokens": prompt_result.usage.output_tokens,
                    "gen_ai.usage.cost": prompt_result.usage.cost,
                    "agent_eval.structured_output_error": prompt_result.structured_output_error,
                },
            ),
        ]
        usage = {
            "input_tokens": prompt_result.usage.input_tokens,
            "output_tokens": prompt_result.usage.output_tokens,
            "total_tokens": prompt_result.usage.total_tokens,
            "cost": prompt_result.usage.cost,
        }
        return (
            prompt_result.output,
            [],
            usage,
            _trace(
                trace_id=trace_id,
                run=run,
                execution=execution,
                status=ExecutionStatus.COMPLETED,
                spans=spans,
                extensions={"agent_eval.raw_response": prompt_result.raw_response},
            ),
            prompt_result.attempts,
        )

    endpoint_config = EndpointConfig.model_validate(agent_version.endpoint_config)
    http_result = await run_http_agent(
        endpoint_config,
        case.input_json,
        variables=case.variables,
        messages=case.messages or None,
        run_id=run.id,
        case_id=case.case_key,
        trace_id=trace_id,
    )
    ended_at = datetime.now(UTC)
    tool_calls = [call.model_dump(mode="json") for call in http_result.tool_calls]
    spans = [
        _agent_span(
            trace_id=trace_id,
            span_id=agent_span_id,
            execution=execution,
            status=ExecutionStatus.COMPLETED,
            started_at=started_at,
            ended_at=ended_at,
            output=http_result.output,
            attributes={
                "agent.type": agent_version.agent_type,
                "agent.protocol": endpoint_config.protocol_version,
            },
        )
    ]
    spans.extend(
        TraceSpan(
            span_id=new_id(),
            trace_id=trace_id,
            parent_span_id=agent_span_id,
            kind=TraceSpanKind.TOOL,
            name=call.name,
            status=ExecutionStatus.COMPLETED,
            started_at=ended_at,
            ended_at=ended_at,
            input=call.arguments,
            attributes={"tool.name": call.name, "tool.order": call.order},
        )
        for call in http_result.tool_calls
    )
    return (
        http_result.output,
        tool_calls,
        http_result.usage,
        _trace(
            trace_id=trace_id,
            run=run,
            execution=execution,
            status=ExecutionStatus.COMPLETED,
            spans=spans,
            extensions={
                "agent_eval.raw_response": http_result.raw_response,
                "agent_eval.external_trace": http_result.trace,
            },
        ),
        http_result.attempts,
    )


def _finish_run(db: Session, run: EvaluationRunRecord) -> None:
    executions = db.scalars(
        select(CaseExecutionRecord.status)
        .where(CaseExecutionRecord.run_id == run.id)
        .with_for_update()
    ).all()
    completed = sum(item == ExecutionStatus.COMPLETED.value for item in executions)
    failed = sum(item == ExecutionStatus.FAILED.value for item in executions)
    run.completed_cases = completed
    run.failed_cases = failed
    if completed + failed != run.total_cases:
        return
    aggregate_run_scores(db, run)
    if failed == 0:
        transition_run(run, RunStatus.COMPLETED)
    elif completed == 0:
        transition_run(run, RunStatus.FAILED)
    else:
        transition_run(run, RunStatus.PARTIAL)


def execute_case(db: Session, settings: Settings, run_id: str, case_id: str) -> dict[str, str]:
    """Execute one CaseExecution once and persist either output or isolated failure."""

    run = db.scalar(
        select(EvaluationRunRecord)
        .where(EvaluationRunRecord.id == run_id)
        .with_for_update()
    )
    if run is None:
        return {"status": "not_found"}
    execution = db.scalar(
        select(CaseExecutionRecord)
        .where(
            CaseExecutionRecord.run_id == run_id,
            CaseExecutionRecord.case_id == case_id,
        )
        .with_for_update()
    )
    if execution is None:
        return {"status": "not_found"}
    if execution.status in _FINISHED_EXECUTION_STATUSES:
        return {"status": "already_finished"}
    if execution.status == ExecutionStatus.RUNNING.value:
        return {"status": "already_running"}

    if run.status == RunStatus.CANCELLED.value:
        transition_execution(execution, ExecutionStatus.CANCELLED)
        db.commit()
        return {"status": "cancelled"}
    if run.status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
        return {"status": "already_finished"}

    admission_delay = _agent_admission_delay(
        db,
        run,
        now=datetime.now(UTC),
        default_delay=settings.worker_admission_retry_seconds,
    )
    if admission_delay is not None:
        db.commit()
        return {"status": "deferred", "countdown": f"{admission_delay:.3f}"}

    transition_execution(execution, ExecutionStatus.RUNNING)
    execution.attempt += 1
    if run.status == RunStatus.QUEUED.value:
        transition_run(run, RunStatus.RUNNING)
    db.commit()

    trace_id = new_id()
    started_at = execution.started_at or datetime.now(UTC)
    output: Any = None
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    trace: Trace | None = None
    error_type: str | None = None
    message: str | None = None
    attempts = 1
    try:
        output, tool_calls, usage, trace, attempts = asyncio.run(
            _invoke(run, execution, trace_id, started_at)
        )
    except AgentAdapterError as exc:
        error_type = exc.error_type
        message = str(exc)
        attempts = exc.attempts
    except PromptRunnerError as exc:
        error_type = exc.error_type
        message = str(exc)
        attempts = exc.attempts
    except Exception as exc:  # pragma: no cover - defensive agent boundary
        error_type = "execution_error"
        message = str(exc)
        attempts = 1

    run = db.scalar(
        select(EvaluationRunRecord)
        .where(EvaluationRunRecord.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    execution = db.scalar(
        select(CaseExecutionRecord)
        .where(
            CaseExecutionRecord.run_id == run_id,
            CaseExecutionRecord.case_id == case_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None or execution is None:  # pragma: no cover - protected by foreign keys
        db.rollback()
        return {"status": "not_found"}
    if (
        run.status == RunStatus.CANCELLED.value
        or execution.status == ExecutionStatus.CANCELLED.value
    ):
        if execution.status == ExecutionStatus.RUNNING.value:
            transition_execution(execution, ExecutionStatus.CANCELLED)
        db.commit()
        return {"status": "cancelled"}

    execution.attempt = max(execution.attempt, attempts)
    if trace is not None:
        persist_trace(db, run.project_id, trace, settings, commit=False)
        execution.output = output
        execution.tool_calls = tool_calls
        execution.usage = usage
        execution.trace_id = trace_id
        transition_execution(execution, ExecutionStatus.COMPLETED)
        asyncio.run(evaluate_and_persist_scores(db, run, execution, trace, settings))
        _finish_run(db, run)
        db.commit()
        return {"status": "completed", "trace_id": trace_id}

    assert error_type is not None and message is not None
    ended_at = datetime.now(UTC)
    failed_trace = _trace(
        trace_id=trace_id,
        run=run,
        execution=execution,
        status=ExecutionStatus.FAILED,
        spans=[
            _agent_span(
                trace_id=trace_id,
                span_id=new_id(),
                execution=execution,
                status=ExecutionStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                error={"type": error_type, "message": message},
            )
        ],
        extensions={},
    )
    if db.get(TraceRecord, trace_id) is None:
        persist_trace(db, run.project_id, failed_trace, settings, commit=False)
    execution.error_type = error_type
    execution.error_message = message
    execution.trace_id = trace_id
    transition_execution(execution, ExecutionStatus.FAILED)
    asyncio.run(evaluate_and_persist_scores(db, run, execution, failed_trace, settings))
    _finish_run(db, run)
    db.commit()
    return {"status": "failed", "trace_id": trace_id}
