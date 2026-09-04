"""Creation and inspection of reproducible, project-scoped evaluation runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_eval_api.auth import AuthContext, get_db, require_project_access
from agent_eval_api.contracts import (
    CaseExecution,
    EvaluationRun,
    EvaluationRunCreateRequest,
    EvaluationRunDetail,
    ExecutionStatus,
    ExpectedToolCall,
    RunStatus,
)
from agent_eval_api.db import (
    AgentRecord,
    AgentVersionRecord,
    CaseExecutionRecord,
    DatasetCaseRecord,
    DatasetRecord,
    DatasetVersionRecord,
    EvaluationRunRecord,
    EvaluatorVersionRecord,
    ProjectRecord,
    new_id,
)

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["evaluation-runs"])

_RUNTIME_REQUIREMENTS = {
    "output",
    "execution_output",
    "tool_calls",
    "usage",
    "latency",
    "cost",
    "trace",
    "trace.spans",
}
_OPTIONAL_CASE_REQUIREMENTS = {
    "expected_output",
    "output_schema",
    "criteria",
    "expected_tools",
    "expected_state",
    "retrieval_context",
    "messages",
}


def enqueue_case_jobs(run_id: str, case_ids: Sequence[str]) -> None:
    """Send one independent work item for every case after the run is committed."""

    from agent_eval_worker.tasks import execute_case_task

    for case_id in case_ids:
        execute_case_task.delay(run_id, case_id)


def get_project(db: Session, project_id: str) -> ProjectRecord:
    project = db.get(ProjectRecord, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


def get_project_agent_version(
    db: Session, project_id: str, agent_version_id: str
) -> tuple[AgentRecord, AgentVersionRecord]:
    row = db.execute(
        select(AgentRecord, AgentVersionRecord)
        .join(AgentVersionRecord, AgentVersionRecord.agent_id == AgentRecord.id)
        .where(
            AgentRecord.project_id == project_id,
            AgentVersionRecord.id == agent_version_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent version not found")
    return row[0], row[1]


def get_project_dataset_version(
    db: Session, project_id: str, dataset_version_id: str
) -> DatasetVersionRecord:
    version = db.scalar(
        select(DatasetVersionRecord)
        .join(DatasetRecord, DatasetVersionRecord.dataset_id == DatasetRecord.id)
        .where(
            DatasetRecord.project_id == project_id,
            DatasetVersionRecord.id == dataset_version_id,
        )
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="dataset version not found"
        )
    return version


def get_project_evaluators(
    db: Session, project_id: str, evaluator_ids: list[str]
) -> list[EvaluatorVersionRecord]:
    records = db.scalars(
        select(EvaluatorVersionRecord).where(
            EvaluatorVersionRecord.project_id == project_id,
            EvaluatorVersionRecord.id.in_(evaluator_ids),
        )
    ).all()
    by_id = {record.id: record for record in records}
    missing = [evaluator_id for evaluator_id in evaluator_ids if evaluator_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "evaluator not found", "evaluator_version_ids": missing},
        )
    return [by_id[evaluator_id] for evaluator_id in evaluator_ids]


def case_has_requirement(case: DatasetCaseRecord, requirement: str) -> bool:
    if requirement in _RUNTIME_REQUIREMENTS:
        return True
    if requirement == "input":
        return case.input_json is not None
    if requirement in _OPTIONAL_CASE_REQUIREMENTS:
        return bool(getattr(case, requirement))
    if requirement == "variables" or requirement == "metadata":
        return True
    if requirement.startswith("metadata."):
        key = requirement.removeprefix("metadata.")
        return bool(key) and key in case.metadata_json
    return False


def validate_evaluator_requirements(
    evaluators: Sequence[EvaluatorVersionRecord], cases: Sequence[DatasetCaseRecord]
) -> None:
    missing: list[dict[str, Any]] = []
    for evaluator in evaluators:
        for case in cases:
            unavailable = [
                requirement
                for requirement in evaluator.requires
                if not case_has_requirement(case, requirement)
            ]
            if unavailable:
                missing.append(
                    {
                        "evaluator_version_id": evaluator.id,
                        "case_id": case.case_key,
                        "fields": unavailable,
                    }
                )
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "evaluator requirements are missing from dataset cases",
                "missing": missing,
            },
        )


def agent_snapshot(agent: AgentRecord, version: AgentVersionRecord) -> dict[str, Any]:
    return {
        "agent_id": agent.id,
        "name": agent.name,
        "agent_type": version.agent_type,
        "version_id": version.id,
        "version": version.version,
        "label": version.label,
        "prompt_config": version.prompt_config,
        "endpoint_config": version.endpoint_config,
    }


def evaluator_snapshot(evaluator: EvaluatorVersionRecord) -> dict[str, Any]:
    return {
        "id": evaluator.id,
        "name": evaluator.name,
        "version": evaluator.version,
        "evaluator_type": evaluator.evaluator_type,
        "requires": evaluator.requires,
        "supported_agent_types": evaluator.supported_agent_types,
        "score_min": evaluator.score_min,
        "score_max": evaluator.score_max,
        "direction": evaluator.direction,
        "default_threshold": evaluator.default_threshold,
        "rubric": evaluator.rubric,
        "judge_model": evaluator.judge_model,
        "config": evaluator.config,
    }


def run_response(record: EvaluationRunRecord) -> EvaluationRun:
    evaluator_ids = [item["id"] for item in record.configuration_snapshot["evaluators"]]
    return EvaluationRun(
        id=record.id,
        agent_version_id=record.agent_version_id,
        dataset_version_id=record.dataset_version_id,
        evaluator_version_ids=evaluator_ids,
        status=RunStatus(record.status),
        total_cases=record.total_cases,
        completed_cases=record.completed_cases,
        failed_cases=record.failed_cases,
        configuration_snapshot=record.configuration_snapshot,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def execution_response(record: CaseExecutionRecord) -> CaseExecution:
    return CaseExecution(
        id=record.id,
        run_id=record.run_id,
        case_id=record.dataset_case.case_key,
        status=ExecutionStatus(record.status),
        attempt=record.attempt,
        output=record.output,
        tool_calls=[ExpectedToolCall.model_validate(item) for item in record.tool_calls],
        usage=record.usage,
        error_type=record.error_type,
        error_message=record.error_message,
        trace_id=record.trace_id,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


@router.post("", response_model=EvaluationRun, status_code=status.HTTP_201_CREATED)
def create_run(
    project_id: str,
    payload: EvaluationRunCreateRequest,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> EvaluationRun:
    get_project(db, project_id)
    agent, agent_version = get_project_agent_version(db, project_id, payload.agent_version_id)
    if not agent.active or not agent_version.enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="agent version must be enabled before starting a run",
        )
    dataset_version = get_project_dataset_version(db, project_id, payload.dataset_version_id)
    evaluators = get_project_evaluators(db, project_id, payload.evaluator_version_ids)
    disabled = [evaluator.id for evaluator in evaluators if not evaluator.enabled]
    if disabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "evaluators must be enabled", "evaluator_version_ids": disabled},
        )
    incompatible = [
        evaluator.id
        for evaluator in evaluators
        if agent_version.agent_type not in evaluator.supported_agent_types
    ]
    if incompatible:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "evaluator does not support the selected agent type",
                "agent_type": agent_version.agent_type,
                "evaluator_version_ids": incompatible,
            },
        )

    cases = db.scalars(
        select(DatasetCaseRecord)
        .where(DatasetCaseRecord.dataset_version_id == dataset_version.id)
        .order_by(DatasetCaseRecord.case_key)
    ).all()
    validate_evaluator_requirements(evaluators, cases)

    run = EvaluationRunRecord(
        id=new_id(),
        project_id=project_id,
        agent_version_id=agent_version.id,
        dataset_version_id=dataset_version.id,
        status=RunStatus.QUEUED.value,
        total_cases=len(cases),
        configuration_snapshot={
            "agent_version": agent_snapshot(agent, agent_version),
            "dataset_version": {
                "id": dataset_version.id,
                "dataset_id": dataset_version.dataset_id,
                "version": dataset_version.version,
                "metadata": dataset_version.metadata_json,
                "case_count": len(cases),
            },
            "evaluators": [evaluator_snapshot(evaluator) for evaluator in evaluators],
        },
    )
    db.add(run)
    db.add_all(
        [
            CaseExecutionRecord(
                id=new_id(),
                run_id=run.id,
                case_id=case.id,
                status=ExecutionStatus.QUEUED.value,
            )
            for case in cases
        ]
    )
    if not cases:
        from agent_eval_api.run_state import transition_run

        transition_run(run, RunStatus.RUNNING)
        transition_run(run, RunStatus.COMPLETED)
    db.commit()
    db.refresh(run)
    enqueue_case_jobs(run.id, [case.id for case in cases])
    return run_response(run)


@router.get("", response_model=list[EvaluationRun])
def list_runs(
    project_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> list[EvaluationRun]:
    get_project(db, project_id)
    records = db.scalars(
        select(EvaluationRunRecord)
        .where(EvaluationRunRecord.project_id == project_id)
        .order_by(EvaluationRunRecord.created_at.desc())
    ).all()
    return [run_response(record) for record in records]


def get_run(db: Session, project_id: str, run_id: str) -> EvaluationRunRecord:
    run = db.scalar(
        select(EvaluationRunRecord).where(
            EvaluationRunRecord.project_id == project_id,
            EvaluationRunRecord.id == run_id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="evaluation run not found"
        )
    return run


def run_detail_response(db: Session, run: EvaluationRunRecord) -> EvaluationRunDetail:
    executions = db.scalars(
        select(CaseExecutionRecord)
        .join(DatasetCaseRecord, CaseExecutionRecord.case_id == DatasetCaseRecord.id)
        .where(CaseExecutionRecord.run_id == run.id)
        .order_by(DatasetCaseRecord.case_key)
    ).all()
    return EvaluationRunDetail(
        **run_response(run).model_dump(),
        case_executions=[execution_response(execution) for execution in executions],
    )


@router.get("/{run_id}", response_model=EvaluationRunDetail)
def read_run(
    project_id: str,
    run_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> EvaluationRunDetail:
    run = get_run(db, project_id, run_id)
    return run_detail_response(db, run)


@router.post("/{run_id}/cancel", response_model=EvaluationRunDetail)
def cancel_run(
    project_id: str,
    run_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> EvaluationRunDetail:
    """Cancel queued work and make running workers discard late results."""

    run = db.scalar(
        select(EvaluationRunRecord)
        .where(
            EvaluationRunRecord.project_id == project_id,
            EvaluationRunRecord.id == run_id,
        )
        .with_for_update()
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="evaluation run not found"
        )
    current = RunStatus(run.status)
    if current is RunStatus.CANCELLED:
        return run_detail_response(db, run)
    if current not in {RunStatus.QUEUED, RunStatus.RUNNING}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot cancel a {current.value} evaluation run",
        )

    executions = db.scalars(
        select(CaseExecutionRecord)
        .where(
            CaseExecutionRecord.run_id == run.id,
            CaseExecutionRecord.status.in_(
                [ExecutionStatus.QUEUED.value, ExecutionStatus.RUNNING.value]
            ),
        )
        .with_for_update()
    ).all()
    from agent_eval_api.run_state import transition_execution, transition_run

    for execution in executions:
        transition_execution(execution, ExecutionStatus.CANCELLED)
    transition_run(run, RunStatus.CANCELLED)
    db.commit()
    db.refresh(run)
    return run_detail_response(db, run)
