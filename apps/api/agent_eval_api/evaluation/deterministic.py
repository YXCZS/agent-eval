"""Deterministic evaluators with explicit evidence and missing-result handling."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from agent_eval_api.contracts import ScoreDirection, ScoreStatus

from .base import (
    EvaluationContext,
    EvaluatorConfigurationError,
    EvaluatorOutcome,
)

EvaluatorFunction = Callable[[EvaluationContext], EvaluatorOutcome]


def _outcome(
    context: EvaluationContext,
    *,
    value: float,
    explanation: str,
    evidence: list[dict[str, Any]],
    threshold: float | None = None,
    raw_result: Any = None,
) -> EvaluatorOutcome:
    effective_threshold = threshold
    if effective_threshold is None:
        effective_threshold = context.evaluator.default_threshold
    if effective_threshold is None:
        effective_threshold = 1.0
    if context.evaluator.direction is ScoreDirection.LOWER_IS_BETTER:
        passed = value <= effective_threshold
    else:
        passed = value >= effective_threshold
    return EvaluatorOutcome(
        metric_name=context.evaluator.name,
        status=ScoreStatus.PASSED if passed else ScoreStatus.FAILED,
        value=value,
        passed=passed,
        explanation=explanation,
        evidence=evidence,
        raw_result=raw_result,
    )


def _missing(context: EvaluationContext, explanation: str) -> EvaluatorOutcome:
    return EvaluatorOutcome(
        metric_name=context.evaluator.name,
        status=ScoreStatus.MISSING,
        explanation=explanation,
    )


def _is_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return False
        return all(
            key in actual and _is_subset(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            _is_subset(left, right) for left, right in zip(expected, actual, strict=True)
        )
    return bool(expected == actual)


def _read_path(value: Any, path: str | None) -> Any:
    if not path:
        return value
    current = value
    for segment in path.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]
    return current


def task_success(context: EvaluationContext) -> EvaluatorOutcome:
    expected = context.case.expected_state
    if expected is None:
        return _missing(context, "expected_state is required")
    raw_path = context.evaluator.config.get("actual_state_path")
    path = str(raw_path) if raw_path is not None else None
    actual = _read_path(context.execution.output, path)
    passed = _is_subset(expected, actual)
    return _outcome(
        context,
        value=1.0 if passed else 0.0,
        explanation=(
            "actual state contains the expected state" if passed else "actual state differs"
        ),
        evidence=[{"expected_state": expected, "actual_state": actual, "path": path}],
    )


def exact_match(context: EvaluationContext) -> EvaluatorOutcome:
    expected = context.case.expected_output
    if expected is None:
        return _missing(context, "expected_output is required")
    actual = context.execution.output
    normalize_whitespace = bool(context.evaluator.config.get("normalize_whitespace", False))
    case_sensitive = bool(context.evaluator.config.get("case_sensitive", True))
    compared_expected = expected
    compared_actual = actual
    if isinstance(expected, str) and isinstance(actual, str):
        expected_text = expected
        actual_text = actual
        if normalize_whitespace:
            expected_text = " ".join(expected_text.split())
            actual_text = " ".join(actual_text.split())
        if not case_sensitive:
            expected_text = expected_text.casefold()
            actual_text = actual_text.casefold()
        compared_expected = expected_text
        compared_actual = actual_text
    matched = bool(compared_expected == compared_actual)
    return _outcome(
        context,
        value=1.0 if matched else 0.0,
        explanation="output exactly matches the reference" if matched else "output differs",
        evidence=[
            {
                "expected_output": expected,
                "actual_output": actual,
                "normalize_whitespace": normalize_whitespace,
                "case_sensitive": case_sensitive,
            }
        ],
    )


def tool_correctness(context: EvaluationContext) -> EvaluatorOutcome:
    expected_names = [call.name for call in context.case.expected_tools]
    actual_names = [call.name for call in context.execution.tool_calls]
    if not expected_names and not actual_names:
        score = 1.0
    else:
        overlap = sum((Counter(expected_names) & Counter(actual_names)).values())
        precision = overlap / len(actual_names) if actual_names else 0.0
        recall = overlap / len(expected_names) if expected_names else 0.0
        score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    ordered = bool(context.evaluator.config.get("ordered", False))
    order_matches = not ordered or expected_names == actual_names
    if not order_matches:
        score = 0.0
    return _outcome(
        context,
        value=score,
        explanation="tool selection matches" if score == 1.0 else "tool selection differs",
        evidence=[
            {
                "expected_tools": expected_names,
                "actual_tools": actual_names,
                "ordered": ordered,
                "order_matches": order_matches,
            }
        ],
    )


def argument_correctness(context: EvaluationContext) -> EvaluatorOutcome:
    expected_calls = context.case.expected_tools
    if not expected_calls:
        return _missing(context, "expected_tools is required")
    actual_calls = context.execution.tool_calls
    used: set[int] = set()
    checks: list[dict[str, Any]] = []
    correct = 0
    for expected in expected_calls:
        candidate_index = next(
            (
                index
                for index, actual in enumerate(actual_calls)
                if index not in used
                and actual.name == expected.name
                and (expected.order is None or actual.order == expected.order)
            ),
            None,
        )
        actual_arguments = None
        matched = False
        if candidate_index is not None:
            used.add(candidate_index)
            actual_arguments = actual_calls[candidate_index].arguments
            matched = _is_subset(expected.arguments, actual_arguments)
        correct += int(matched)
        checks.append(
            {
                "tool": expected.name,
                "expected_arguments": expected.arguments,
                "actual_arguments": actual_arguments,
                "matched": matched,
            }
        )
    score = correct / len(expected_calls)
    return _outcome(
        context,
        value=score,
        explanation=f"{correct}/{len(expected_calls)} expected tool arguments match",
        evidence=checks,
    )


def policy_compliance(context: EvaluationContext) -> EvaluatorOutcome:
    config = context.evaluator.config
    supported_rules = {
        "forbidden_tools",
        "required_tools",
        "max_tool_calls",
        "forbidden_output_patterns",
    }
    if not supported_rules.intersection(config):
        return _missing(context, "no deterministic policy rules are configured")
    actual_tools = [call.name for call in context.execution.tool_calls]
    violations: list[dict[str, Any]] = []
    for tool in config.get("forbidden_tools", []):
        if tool in actual_tools:
            violations.append({"rule": "forbidden_tool", "tool": tool})
    for tool in config.get("required_tools", []):
        if tool not in actual_tools:
            violations.append({"rule": "required_tool_missing", "tool": tool})
    max_tool_calls = config.get("max_tool_calls")
    if isinstance(max_tool_calls, int) and len(actual_tools) > max_tool_calls:
        violations.append(
            {"rule": "max_tool_calls", "limit": max_tool_calls, "actual": len(actual_tools)}
        )
    serialized_output = json.dumps(context.execution.output, ensure_ascii=False).casefold()
    for pattern in config.get("forbidden_output_patterns", []):
        if str(pattern).casefold() in serialized_output:
            violations.append({"rule": "forbidden_output_pattern", "pattern": pattern})
    return _outcome(
        context,
        value=0.0 if violations else 1.0,
        explanation="policy violations found" if violations else "all deterministic rules passed",
        evidence=violations or [{"rules_checked": sorted(supported_rules.intersection(config))}],
        raw_result={"violations": violations},
    )


def json_schema(context: EvaluationContext) -> EvaluatorOutcome:
    schema = context.case.output_schema
    if schema is None:
        return _missing(context, "output_schema is required")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise EvaluatorConfigurationError(f"invalid output_schema: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(context.execution.output),
        key=lambda error: list(error.absolute_path),
    )
    evidence = [
        {
            "message": error.message,
            "instance_path": list(error.absolute_path),
            "schema_path": list(error.absolute_schema_path),
        }
        for error in errors
    ]
    return _outcome(
        context,
        value=0.0 if errors else 1.0,
        explanation="output matches JSON Schema" if not errors else f"{len(errors)} schema errors",
        evidence=evidence or [{"valid": True}],
    )


def latency(context: EvaluationContext) -> EvaluatorOutcome:
    started_at = context.execution.started_at
    finished_at = context.execution.finished_at
    if started_at is None or finished_at is None:
        return _missing(context, "execution timestamps are required")
    latency_ms = max(0.0, (finished_at - started_at).total_seconds() * 1000)
    raw_limit = context.evaluator.config.get("max_ms")
    limit = float(raw_limit) if raw_limit is not None else context.evaluator.default_threshold
    if limit is None:
        raise EvaluatorConfigurationError("latency requires config.max_ms or default_threshold")
    return _outcome(
        context,
        value=latency_ms,
        threshold=limit,
        explanation=f"latency is {latency_ms:.3f} ms (limit {limit:.3f} ms)",
        evidence=[{"latency_ms": latency_ms, "max_ms": limit}],
    )


def cost(context: EvaluationContext) -> EvaluatorOutcome:
    raw_cost = context.execution.usage.get("cost")
    if raw_cost is None:
        return _missing(context, "usage.cost is required")
    try:
        value = float(raw_cost)
    except (TypeError, ValueError) as exc:
        raise EvaluatorConfigurationError("usage.cost must be numeric") from exc
    raw_limit = context.evaluator.config.get("max_cost")
    limit = float(raw_limit) if raw_limit is not None else context.evaluator.default_threshold
    if limit is None:
        raise EvaluatorConfigurationError("cost requires config.max_cost or default_threshold")
    return _outcome(
        context,
        value=value,
        threshold=limit,
        explanation=f"cost is {value:.6f} (limit {limit:.6f})",
        evidence=[{"cost": value, "max_cost": limit}],
    )


def token_usage(context: EvaluationContext) -> EvaluatorOutcome:
    field = str(context.evaluator.config.get("token_field", "total_tokens"))
    raw_value = context.execution.usage.get(field)
    if raw_value is None and field == "total_tokens":
        input_tokens = context.execution.usage.get("input_tokens")
        output_tokens = context.execution.usage.get("output_tokens")
        if input_tokens is not None and output_tokens is not None:
            raw_value = int(input_tokens) + int(output_tokens)
    if raw_value is None:
        return _missing(context, f"usage.{field} is required")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise EvaluatorConfigurationError(f"usage.{field} must be numeric") from exc
    raw_limit = context.evaluator.config.get("max_tokens")
    limit = float(raw_limit) if raw_limit is not None else context.evaluator.default_threshold
    if limit is None:
        raise EvaluatorConfigurationError("token usage requires max_tokens or default_threshold")
    return _outcome(
        context,
        value=value,
        threshold=limit,
        explanation=f"{field} is {value:.0f} (limit {limit:.0f})",
        evidence=[{"token_field": field, "tokens": value, "max_tokens": limit}],
    )


DETERMINISTIC_EVALUATORS: dict[str, EvaluatorFunction] = {
    "exact_match": exact_match,
    "task_success": task_success,
    "tool_correctness": tool_correctness,
    "argument_correctness": argument_correctness,
    "policy_compliance": policy_compliance,
    "json_schema": json_schema,
    "latency": latency,
    "token": token_usage,
    "token_usage": token_usage,
    "cost": cost,
}


def deterministic_evaluator_key(name: str) -> str:
    key = name.casefold().replace("-", "_").replace(" ", "_")
    for prefix in ("prompt_", "rag_", "tool_"):
        unprefixed = key.removeprefix(prefix)
        if unprefixed in DETERMINISTIC_EVALUATORS:
            return unprefixed
    return key


def evaluate_deterministic(context: EvaluationContext) -> list[EvaluatorOutcome]:
    configured_metric = context.evaluator.config.get("metric", context.evaluator.name)
    evaluator = DETERMINISTIC_EVALUATORS.get(deterministic_evaluator_key(str(configured_metric)))
    if evaluator is None:
        raise EvaluatorConfigurationError(
            f"unknown deterministic evaluator: {context.evaluator.name}"
        )
    return [evaluator(context)]
