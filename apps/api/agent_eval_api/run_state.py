"""State transition guards for persisted evaluation runs and case executions."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_eval_api.contracts import ExecutionStatus, RunStatus
from agent_eval_api.db import CaseExecutionRecord, EvaluationRunRecord

RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.PARTIAL,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.PARTIAL: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}

EXECUTION_TRANSITIONS: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.QUEUED: {ExecutionStatus.RUNNING, ExecutionStatus.CANCELLED},
    ExecutionStatus.RUNNING: {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.COMPLETED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.CANCELLED: set(),
}


def assert_run_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in RUN_TRANSITIONS[current]:
        raise ValueError(f"invalid evaluation run status transition: {current} -> {target}")


def assert_execution_transition(current: ExecutionStatus, target: ExecutionStatus) -> None:
    if target not in EXECUTION_TRANSITIONS[current]:
        raise ValueError(f"invalid case execution status transition: {current} -> {target}")


def transition_run(record: EvaluationRunRecord, target: RunStatus) -> None:
    """Apply a validated transition; the caller commits the database transaction."""

    assert_run_transition(RunStatus(record.status), target)
    now = datetime.now(UTC)
    record.status = target.value
    if target is RunStatus.RUNNING and record.started_at is None:
        record.started_at = now
    if target in {RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED}:
        record.finished_at = now


def transition_execution(record: CaseExecutionRecord, target: ExecutionStatus) -> None:
    """Apply a validated transition; the caller commits the database transaction."""

    assert_execution_transition(ExecutionStatus(record.status), target)
    now = datetime.now(UTC)
    record.status = target.value
    if target is ExecutionStatus.RUNNING and record.started_at is None:
        record.started_at = now
    if target in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}:
        record.finished_at = now
