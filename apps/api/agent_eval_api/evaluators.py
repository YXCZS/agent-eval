"""Project-scoped registration for immutable evaluator versions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent_eval_api.auth import AuthContext, get_db, require_project_access
from agent_eval_api.contracts import (
    AgentType,
    EvaluatorType,
    EvaluatorVersion,
    EvaluatorVersionCreateRequest,
    ScoreDirection,
)
from agent_eval_api.db import EvaluatorVersionRecord, ProjectRecord, new_id

router = APIRouter(prefix="/projects/{project_id}/evaluators", tags=["evaluators"])


def get_project(db: Session, project_id: str) -> ProjectRecord:
    project = db.get(ProjectRecord, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


def get_evaluator(
    db: Session,
    project_id: str,
    evaluator_id: str,
) -> EvaluatorVersionRecord:
    evaluator = db.scalar(
        select(EvaluatorVersionRecord).where(
            EvaluatorVersionRecord.id == evaluator_id,
            EvaluatorVersionRecord.project_id == project_id,
        )
    )
    if evaluator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="evaluator not found")
    return evaluator


def evaluator_response(record: EvaluatorVersionRecord) -> EvaluatorVersion:
    return EvaluatorVersion(
        id=record.id,
        name=record.name,
        version=record.version,
        evaluator_type=EvaluatorType(record.evaluator_type),
        requires=record.requires,
        supported_agent_types=[
            AgentType(agent_type) for agent_type in record.supported_agent_types
        ],
        score_min=record.score_min,
        score_max=record.score_max,
        direction=ScoreDirection(record.direction),
        default_threshold=record.default_threshold,
        rubric=record.rubric,
        judge_model=record.judge_model,
        config=record.config,
        enabled=record.enabled,
    )


@router.post("", response_model=EvaluatorVersion, status_code=status.HTTP_201_CREATED)
def register_evaluator(
    project_id: str,
    payload: EvaluatorVersionCreateRequest,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> EvaluatorVersion:
    get_project(db, project_id)
    record = EvaluatorVersionRecord(
        id=new_id(),
        project_id=project_id,
        name=payload.name,
        version=payload.version,
        evaluator_type=payload.evaluator_type.value,
        requires=payload.requires,
        supported_agent_types=[agent_type.value for agent_type in payload.supported_agent_types],
        score_min=payload.score_min,
        score_max=payload.score_max,
        direction=payload.direction.value,
        default_threshold=payload.default_threshold,
        rubric=payload.rubric,
        judge_model=payload.judge_model,
        config=payload.config,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="evaluator name and version already exist",
        ) from None
    db.refresh(record)
    return evaluator_response(record)


@router.get("", response_model=list[EvaluatorVersion])
def list_evaluators(
    project_id: str,
    enabled: bool | None = None,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> list[EvaluatorVersion]:
    get_project(db, project_id)
    statement = (
        select(EvaluatorVersionRecord)
        .where(EvaluatorVersionRecord.project_id == project_id)
        .order_by(EvaluatorVersionRecord.name, EvaluatorVersionRecord.version)
    )
    if enabled is not None:
        statement = statement.where(EvaluatorVersionRecord.enabled.is_(enabled))
    return [evaluator_response(record) for record in db.scalars(statement)]


@router.get("/{evaluator_id}", response_model=EvaluatorVersion)
def read_evaluator(
    project_id: str,
    evaluator_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> EvaluatorVersion:
    return evaluator_response(get_evaluator(db, project_id, evaluator_id))


@router.patch("/{evaluator_id}/enabled", response_model=EvaluatorVersion)
def set_evaluator_enabled(
    project_id: str,
    evaluator_id: str,
    enabled: bool,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> EvaluatorVersion:
    record = get_evaluator(db, project_id, evaluator_id)
    record.enabled = enabled
    db.commit()
    db.refresh(record)
    return evaluator_response(record)
