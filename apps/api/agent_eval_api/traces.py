"""Canonical trace persistence and project-scoped retrieval."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from agent_eval_api.auth import AuthContext, get_db, require_project_access
from agent_eval_api.contracts import (
    ExecutionStatus,
    Trace,
    TraceIngestRequest,
    TraceSpan,
    TraceSpanKind,
    TraceSummary,
    TraceTimeline,
    TraceTimelineSpan,
)
from agent_eval_api.db import EvaluationRunRecord, TraceRecord, TraceSpanRecord
from agent_eval_api.settings import Settings, get_settings
from agent_eval_api.trace_normalization import normalize_trace_payload
from agent_eval_api.trace_privacy import sanitize_trace

router = APIRouter(prefix="/projects/{project_id}/traces", tags=["traces"])


def get_project_trace(db: Session, project_id: str, trace_id: str) -> TraceRecord:
    trace = db.scalar(
        select(TraceRecord)
        .where(TraceRecord.id == trace_id, TraceRecord.project_id == project_id)
        .options(selectinload(TraceRecord.spans))
    )
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")
    return trace


def trace_response(trace: TraceRecord) -> Trace:
    return Trace(
        trace_id=trace.id,
        run_id=trace.run_id,
        case_id=trace.case_id,
        status=ExecutionStatus(trace.status),
        spans=[
            TraceSpan(
                span_id=span.span_id,
                trace_id=trace.id,
                parent_span_id=span.parent_span_id,
                kind=TraceSpanKind(span.kind),
                name=span.name,
                status=ExecutionStatus(span.status),
                started_at=span.started_at,
                ended_at=span.ended_at,
                input=span.input,
                output=span.output,
                error=span.error,
                attributes=span.attributes,
                extensions=span.extensions,
            )
            for span in sorted(trace.spans, key=lambda item: (item.started_at, item.span_id))
        ],
        source=trace.source,
        extensions=trace.extensions,
    )


def trace_summary(trace: TraceRecord) -> TraceSummary:
    spans = sorted(trace.spans, key=lambda item: (item.started_at, item.span_id))
    started_at = spans[0].started_at if spans else None
    ended_at = max(
        (span.ended_at or span.started_at for span in spans),
        default=None,
    )
    return TraceSummary(
        trace_id=trace.id,
        run_id=trace.run_id,
        case_id=trace.case_id,
        status=ExecutionStatus(trace.status),
        source=trace.source,
        span_count=len(spans),
        started_at=started_at,
        ended_at=ended_at,
        created_at=trace.created_at,
    )


def trace_timeline(trace: TraceRecord) -> TraceTimeline:
    ordered_spans = sorted(trace.spans, key=lambda item: (item.started_at, item.span_id))
    parent_by_span = {span.span_id: span.parent_span_id for span in ordered_spans}

    def depth(span_id: str) -> int:
        result = 0
        parent_span_id = parent_by_span[span_id]
        while parent_span_id is not None:
            result += 1
            parent_span_id = parent_by_span[parent_span_id]
        return result

    return TraceTimeline(
        trace_id=trace.id,
        started_at=ordered_spans[0].started_at if ordered_spans else None,
        ended_at=max(
            (span.ended_at or span.started_at for span in ordered_spans),
            default=None,
        ),
        spans=[
            TraceTimelineSpan(
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                kind=TraceSpanKind(span.kind),
                name=span.name,
                status=ExecutionStatus(span.status),
                started_at=span.started_at,
                ended_at=span.ended_at,
                duration_ms=(
                    (span.ended_at - span.started_at).total_seconds() * 1000
                    if span.ended_at is not None
                    else None
                ),
                depth=depth(span.span_id),
            )
            for span in ordered_spans
        ],
    )


def persist_trace(
    db: Session,
    project_id: str,
    trace: Trace,
    settings: Settings,
    *,
    commit: bool = True,
) -> TraceRecord:
    trace = sanitize_trace(trace, settings)
    if db.get(TraceRecord, trace.trace_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="trace already exists")
    if trace.run_id is not None:
        run = db.scalar(
            select(EvaluationRunRecord).where(
                EvaluationRunRecord.id == trace.run_id,
                EvaluationRunRecord.project_id == project_id,
            )
        )
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="evaluation run not found"
            )

    record = TraceRecord(
        id=trace.trace_id,
        project_id=project_id,
        run_id=trace.run_id,
        case_id=trace.case_id,
        status=trace.status.value,
        source=trace.source,
        extensions=trace.extensions,
    )
    record.spans = [
        TraceSpanRecord(
            trace_id=record.id,
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            kind=span.kind.value,
            name=span.name,
            status=span.status.value,
            started_at=span.started_at,
            ended_at=span.ended_at,
            input=span.input,
            output=span.output,
            error=span.error,
            attributes=span.attributes,
            extensions=span.extensions,
        )
        for span in trace.spans
    ]
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
    else:
        db.flush()
    return record


@router.post("", response_model=Trace, status_code=status.HTTP_201_CREATED)
def create_trace(
    project_id: str,
    payload: Trace,
    db: Session = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> Trace:
    return trace_response(persist_trace(db, project_id, payload, settings))


@router.post("/ingest", response_model=Trace, status_code=status.HTTP_201_CREATED)
def ingest_trace(
    project_id: str,
    payload: TraceIngestRequest,
    db: Session = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> Trace:
    trace = payload.trace or normalize_trace_payload(payload.payload or {}, source=payload.source)
    return trace_response(persist_trace(db, project_id, trace, settings))


@router.get("", response_model=list[TraceSummary])
def list_traces(
    project_id: str,
    run_id: str | None = None,
    case_id: str | None = None,
    trace_status: ExecutionStatus | None = Query(  # noqa: B008
        default=None,
        alias="status",
    ),
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> list[TraceSummary]:
    statement = (
        select(TraceRecord)
        .where(TraceRecord.project_id == project_id)
        .options(selectinload(TraceRecord.spans))
        .order_by(TraceRecord.created_at.desc(), TraceRecord.id.desc())
        .limit(limit)
    )
    if run_id is not None:
        statement = statement.where(TraceRecord.run_id == run_id)
    if case_id is not None:
        statement = statement.where(TraceRecord.case_id == case_id)
    if trace_status is not None:
        statement = statement.where(TraceRecord.status == trace_status.value)
    return [trace_summary(trace) for trace in db.scalars(statement)]


@router.get("/{trace_id}/timeline", response_model=TraceTimeline)
def read_trace_timeline(
    project_id: str,
    trace_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> TraceTimeline:
    return trace_timeline(get_project_trace(db, project_id, trace_id))


@router.get("/{trace_id}", response_model=Trace)
def read_trace(
    project_id: str,
    trace_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> Trace:
    return trace_response(get_project_trace(db, project_id, trace_id))
