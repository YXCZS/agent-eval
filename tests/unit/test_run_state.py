import pytest

from agent_eval_api.contracts import ExecutionStatus, RunStatus
from agent_eval_api.db import CaseExecutionRecord, EvaluationRunRecord
from agent_eval_api.run_state import (
    assert_execution_transition,
    assert_run_transition,
    transition_execution,
    transition_run,
)


def test_run_state_machine_allows_only_forward_non_terminal_transitions() -> None:
    assert_run_transition(RunStatus.QUEUED, RunStatus.RUNNING)
    assert_run_transition(RunStatus.RUNNING, RunStatus.PARTIAL)

    with pytest.raises(ValueError, match="queued -> completed"):
        assert_run_transition(RunStatus.QUEUED, RunStatus.COMPLETED)
    with pytest.raises(ValueError, match="completed -> running"):
        assert_run_transition(RunStatus.COMPLETED, RunStatus.RUNNING)


def test_case_execution_state_machine_prevents_terminal_or_skipped_transitions() -> None:
    assert_execution_transition(ExecutionStatus.RUNNING, ExecutionStatus.FAILED)

    with pytest.raises(ValueError, match="queued -> completed"):
        assert_execution_transition(ExecutionStatus.QUEUED, ExecutionStatus.COMPLETED)
    with pytest.raises(ValueError, match="failed -> running"):
        assert_execution_transition(ExecutionStatus.FAILED, ExecutionStatus.RUNNING)


def test_transitions_update_database_fact_status_and_timestamps() -> None:
    run = EvaluationRunRecord(status="queued")
    execution = CaseExecutionRecord(status="queued")

    transition_run(run, RunStatus.RUNNING)
    transition_execution(execution, ExecutionStatus.RUNNING)
    assert run.status == "running"
    assert run.started_at is not None
    assert execution.status == "running"
    assert execution.started_at is not None

    transition_run(run, RunStatus.PARTIAL)
    transition_execution(execution, ExecutionStatus.FAILED)
    assert run.finished_at is not None
    assert execution.finished_at is not None
