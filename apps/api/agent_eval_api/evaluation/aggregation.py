"""Stable per-metric aggregation with explicit missing and error accounting."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agent_eval_api.contracts import ScoreStatus
from agent_eval_api.db import (
    AggregateMetricRecord,
    EvaluationRunRecord,
    ScoreRecord,
    new_id,
)


def _aggregation(scores: list[ScoreRecord]) -> str:
    numeric = [score.value for score in scores if score.value is not None]
    if numeric and all(value in {0.0, 1.0} for value in numeric):
        return "pass_rate"
    return "mean"


def aggregate_run_scores(
    db: Session,
    run: EvaluationRunRecord,
) -> list[AggregateMetricRecord]:
    """Rebuild aggregates from Score rows; missing data is never treated as passing."""

    scores = db.scalars(
        select(ScoreRecord).where(ScoreRecord.run_id == run.id)
    ).all()
    grouped: dict[tuple[str, str], list[ScoreRecord]] = defaultdict(list)
    for score in scores:
        grouped[(score.metric_name, score.evaluator_version_id)].append(score)

    db.execute(delete(AggregateMetricRecord).where(AggregateMetricRecord.run_id == run.id))
    records: list[AggregateMetricRecord] = []
    for (metric_name, evaluator_version_id), metric_scores in sorted(grouped.items()):
        valid = [
            score
            for score in metric_scores
            if score.status in {ScoreStatus.PASSED.value, ScoreStatus.FAILED.value}
        ]
        missing_count = sum(
            score.status in {ScoreStatus.MISSING.value, ScoreStatus.NOT_RUN.value}
            for score in metric_scores
        )
        error_count = sum(score.status == ScoreStatus.ERROR.value for score in metric_scores)
        passed_count = sum(score.passed is True for score in valid)
        numeric = [score.value for score in valid if score.value is not None]
        record = AggregateMetricRecord(
            id=new_id(),
            run_id=run.id,
            metric_name=metric_name,
            evaluator_version_id=evaluator_version_id,
            valid_count=len(valid),
            missing_count=missing_count,
            error_count=error_count,
            passed_count=passed_count,
            average=sum(numeric) / len(numeric) if numeric else None,
            pass_rate=passed_count / len(valid) if valid else None,
            aggregation=_aggregation(valid),
            threshold=metric_scores[0].threshold,
            direction=metric_scores[0].direction,
        )
        db.add(record)
        records.append(record)
    db.flush()
    return records
