"""Machine-readable regression gates over persisted evaluation scores."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_eval_api.auth import AuthContext, get_db, require_project_access
from agent_eval_api.contracts import (
    RegressionGateRequest,
    RegressionGateResult,
    RegressionGateRule,
    RegressionGateRuleResult,
    RegressionGateStatus,
    RunStatus,
    ScoreStatus,
)
from agent_eval_api.db import EvaluationRunRecord, ScoreRecord

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["regression-gates"])

_VALID_SCORE_STATUSES = {ScoreStatus.PASSED.value, ScoreStatus.FAILED.value}


def _incomplete_results(
    rules: list[RegressionGateRule], reason: str
) -> list[RegressionGateRuleResult]:
    return [
        RegressionGateRuleResult(
            rule=rule,
            status=RegressionGateStatus.INDETERMINATE,
            reason=reason,
        )
        for rule in rules
    ]


def _result_for_rule(
    rule: RegressionGateRule,
    scores: Sequence[ScoreRecord],
    total_cases: int,
) -> RegressionGateRuleResult:
    matching = [score for score in scores if score.metric_name == rule.metric_name]
    evaluator_ids = {score.evaluator_version_id for score in matching}
    if rule.evaluator_version_id is not None:
        matching = [
            score for score in matching if score.evaluator_version_id == rule.evaluator_version_id
        ]
    elif len(evaluator_ids) > 1:
        return RegressionGateRuleResult(
            rule=rule,
            status=RegressionGateStatus.INDETERMINATE,
            reason="metric has multiple evaluator versions; specify evaluator_version_id",
        )

    invalid = [score for score in matching if score.status not in _VALID_SCORE_STATUSES]
    valid = [score for score in matching if score.status in _VALID_SCORE_STATUSES]
    missing_count = max(0, total_cases - len(matching)) + sum(
        score.status in {ScoreStatus.MISSING.value, ScoreStatus.NOT_RUN.value}
        for score in matching
    )
    error_count = sum(score.status == ScoreStatus.ERROR.value for score in matching)
    failed_case_ids = sorted(
        score.case_id for score in valid if score.passed is not True
    )
    if invalid or len(matching) != total_cases or not valid:
        return RegressionGateRuleResult(
            rule=rule,
            status=RegressionGateStatus.INDETERMINATE,
            valid_count=len(valid),
            missing_count=missing_count,
            error_count=error_count,
            failed_case_ids=failed_case_ids,
            reason="metric has missing, not-run or error scores",
        )

    numeric = [score.value for score in valid]
    if any(value is None for value in numeric):
        return RegressionGateRuleResult(
            rule=rule,
            status=RegressionGateStatus.INDETERMINATE,
            valid_count=len(valid),
            missing_count=missing_count,
            error_count=error_count,
            failed_case_ids=failed_case_ids,
            reason="metric has non-numeric scores",
        )
    numeric_values = [float(value) for value in numeric if value is not None]
    actual_value = (
        sum(numeric_values) / len(numeric_values)
        if rule.aggregation == "average"
        else sum(score.passed is True for score in valid) / len(valid)
    )
    violates_threshold = (rule.minimum is not None and actual_value < rule.minimum) or (
        rule.maximum is not None and actual_value > rule.maximum
    )
    violates_hard_gate = rule.require_all_passed and bool(failed_case_ids)
    return RegressionGateRuleResult(
        rule=rule,
        status=(
            RegressionGateStatus.FAILED
            if violates_threshold or violates_hard_gate
            else RegressionGateStatus.PASSED
        ),
        actual_value=actual_value,
        valid_count=len(valid),
        missing_count=missing_count,
        error_count=error_count,
        failed_case_ids=failed_case_ids,
        reason=(
            "one or more sample scores did not pass the hard gate"
            if violates_hard_gate
            else "metric value is outside the configured threshold"
            if violates_threshold
            else None
        ),
    )


@router.post("/{run_id}/regression-gate", response_model=RegressionGateResult)
def evaluate_regression_gate(
    project_id: str,
    run_id: str,
    payload: RegressionGateRequest,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> RegressionGateResult:
    run = db.scalar(
        select(EvaluationRunRecord).where(
            EvaluationRunRecord.id == run_id,
            EvaluationRunRecord.project_id == project_id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="evaluation run not found",
        )
    run_status = RunStatus(run.status)
    if run_status in {RunStatus.QUEUED, RunStatus.RUNNING}:
        return RegressionGateResult(
            run_id=run.id,
            run_status=run_status,
            status=RegressionGateStatus.INCOMPLETE,
            rules=_incomplete_results(payload.rules, "evaluation run is still in progress"),
            generated_at=datetime.now(UTC),
        )
    if run_status is not RunStatus.COMPLETED:
        return RegressionGateResult(
            run_id=run.id,
            run_status=run_status,
            status=RegressionGateStatus.INDETERMINATE,
            rules=_incomplete_results(
                payload.rules,
                "evaluation run did not complete successfully",
            ),
            generated_at=datetime.now(UTC),
        )

    scores = db.scalars(select(ScoreRecord).where(ScoreRecord.run_id == run.id)).all()
    rule_results = [
        _result_for_rule(rule, scores, run.total_cases) for rule in payload.rules
    ]
    if any(result.status is RegressionGateStatus.FAILED for result in rule_results):
        gate_status = RegressionGateStatus.FAILED
    elif any(result.status is RegressionGateStatus.INDETERMINATE for result in rule_results):
        gate_status = RegressionGateStatus.INDETERMINATE
    else:
        gate_status = RegressionGateStatus.PASSED
    return RegressionGateResult(
        run_id=run.id,
        run_status=run_status,
        status=gate_status,
        rules=rule_results,
        generated_at=datetime.now(UTC),
    )
