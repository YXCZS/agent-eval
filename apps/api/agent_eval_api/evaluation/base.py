"""Framework-neutral evaluator contract used by built-in and adapter evaluators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_eval_api.contracts import (
    CaseExecution,
    DatasetCase,
    EvaluatorVersion,
    ScoreStatus,
    Trace,
)


@dataclass(frozen=True)
class EvaluationContext:
    case: DatasetCase
    execution: CaseExecution
    evaluator: EvaluatorVersion
    trace: Trace | None = None


@dataclass(frozen=True)
class EvaluatorOutcome:
    metric_name: str
    status: ScoreStatus
    value: float | None = None
    label: str | None = None
    passed: bool | None = None
    explanation: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    raw_result: Any = None


class Evaluator(Protocol):
    """A pluggable evaluator produces one or more normalized, unpersisted outcomes."""

    def evaluate(self, context: EvaluationContext) -> list[EvaluatorOutcome]: ...


class EvaluatorConfigurationError(ValueError):
    """Raised when an evaluator name or deterministic rule configuration is invalid."""
