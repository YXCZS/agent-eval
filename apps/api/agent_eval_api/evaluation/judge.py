"""OpenAI-compatible LLM judge with validated, reproducible structured decisions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from agent_eval_api.contracts import ScoreDirection, ScoreStatus

from .base import EvaluationContext, EvaluatorConfigurationError, EvaluatorOutcome


class JudgeDecision(BaseModel):
    score: float
    explanation: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    label: str | None = None


class JudgeProviderError(RuntimeError):
    def __init__(self, error_type: str, message: str, *, attempts: int = 1) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.attempts = attempts


@dataclass(frozen=True)
class JudgeProviderConfig:
    endpoint: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 60.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.2


DEFAULT_RUBRICS = {
    "answer_quality": (
        "Score how correct, relevant, clear, and useful the actual answer is for the input and "
        "reference answer. Do not reward unsupported claims."
    ),
    "instruction_following": (
        "Score whether the answer follows all explicit instructions and criteria in the test case."
    ),
    "completeness": (
        "Score whether the answer covers every material part needed to satisfy the request."
    ),
    "natural_language_rules": (
        "Score whether the output complies with every natural-language rule in criteria."
    ),
}


def _metric_key(name: str) -> str:
    key = name.casefold().replace("-", "_").replace(" ", "_")
    aliases = {"rule_compliance": "natural_language_rules", "answer_correctness": "answer_quality"}
    return aliases.get(key, key)


def _judge_payload(context: EvaluationContext, rubric: str) -> dict[str, Any]:
    return {
        "metric": context.evaluator.name,
        "rubric": rubric,
        "input": context.case.input,
        "messages": [message.model_dump(mode="json") for message in context.case.messages],
        "expected_output": context.case.expected_output,
        "criteria": context.case.criteria,
        "actual_output": context.execution.output,
        "tool_calls": [call.model_dump(mode="json") for call in context.execution.tool_calls],
    }


def _extract_decision(body: Any) -> JudgeDecision:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise JudgeProviderError(
            "protocol_error", "judge response is missing message content"
        ) from exc
    if isinstance(content, str):
        stripped = content.strip()
        if stripped.startswith("```json") and stripped.endswith("```"):
            stripped = stripped[7:-3].strip()
        try:
            content = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise JudgeProviderError("protocol_error", "judge content is not valid JSON") from exc
    try:
        return JudgeDecision.model_validate(content)
    except ValidationError as exc:
        raise JudgeProviderError("protocol_error", "judge decision has an invalid schema") from exc


async def _request_decision(
    provider: JudgeProviderConfig,
    payload: dict[str, Any],
    *,
    client: httpx.AsyncClient | None,
) -> tuple[JudgeDecision, dict[str, Any], int]:
    headers = {"Content-Type": "application/json"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    request_body = {
        "model": provider.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict evaluation judge. Return only JSON with numeric score, "
                    "non-empty explanation, evidence string array, and optional label."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=provider.timeout_seconds)
    attempt = 0
    try:
        while True:
            try:
                response = await http_client.post(
                    provider.endpoint,
                    headers=headers,
                    json=request_body,
                )
                if response.status_code == 429:
                    raise JudgeProviderError(
                        "rate_limit", "judge provider rate limited the request"
                    )
                if response.status_code >= 500:
                    raise JudgeProviderError(
                        "service_error", f"judge provider returned HTTP {response.status_code}"
                    )
                response.raise_for_status()
                body = response.json()
                return _extract_decision(body), body, attempt + 1
            except JudgeProviderError as exc:
                if exc.error_type == "protocol_error" or attempt >= provider.max_retries:
                    raise JudgeProviderError(
                        exc.error_type, str(exc), attempts=attempt + 1
                    ) from exc
            except httpx.TimeoutException as exc:
                if attempt >= provider.max_retries:
                    raise JudgeProviderError(
                        "timeout", "judge request timed out", attempts=attempt + 1
                    ) from exc
            except httpx.HTTPStatusError as exc:
                raise JudgeProviderError(
                    "provider_error",
                    f"judge request failed: HTTP {exc.response.status_code}",
                    attempts=attempt + 1,
                ) from exc
            except httpx.HTTPError as exc:
                if attempt >= provider.max_retries:
                    raise JudgeProviderError(
                        "connection_error",
                        "judge request could not be completed",
                        attempts=attempt + 1,
                    ) from exc
            except ValueError as exc:
                raise JudgeProviderError(
                    "protocol_error",
                    "judge response is not valid JSON",
                    attempts=attempt + 1,
                ) from exc
            await asyncio.sleep(provider.retry_backoff_seconds * (2**attempt))
            attempt += 1
    finally:
        if owns_client:
            await http_client.aclose()


def _validate_score(context: EvaluationContext, score: float) -> None:
    minimum = context.evaluator.score_min
    maximum = context.evaluator.score_max
    if minimum is not None and score < minimum:
        raise JudgeProviderError("protocol_error", "judge score is below evaluator score_min")
    if maximum is not None and score > maximum:
        raise JudgeProviderError("protocol_error", "judge score is above evaluator score_max")


async def evaluate_llm_judge(
    context: EvaluationContext,
    provider: JudgeProviderConfig,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[EvaluatorOutcome]:
    key = _metric_key(context.evaluator.name)
    default_rubric = DEFAULT_RUBRICS.get(key)
    if default_rubric is None:
        raise EvaluatorConfigurationError(f"unknown LLM judge evaluator: {context.evaluator.name}")
    rubric = context.evaluator.rubric or default_rubric
    if key in {"instruction_following", "natural_language_rules"} and not (
        context.case.criteria or context.evaluator.rubric
    ):
        return [
            EvaluatorOutcome(
                metric_name=context.evaluator.name,
                status=ScoreStatus.MISSING,
                explanation="criteria or an evaluator rubric is required",
            )
        ]
    payload = _judge_payload(context, rubric)
    decision, raw_response, attempts = await _request_decision(
        provider, payload, client=client
    )
    _validate_score(context, decision.score)
    threshold = context.evaluator.default_threshold
    if threshold is None:
        raise EvaluatorConfigurationError("LLM judge requires default_threshold")
    if context.evaluator.direction is ScoreDirection.LOWER_IS_BETTER:
        passed = decision.score <= threshold
    else:
        passed = decision.score >= threshold
    return [
        EvaluatorOutcome(
            metric_name=context.evaluator.name,
            status=ScoreStatus.PASSED if passed else ScoreStatus.FAILED,
            value=decision.score,
            label=decision.label,
            passed=passed,
            explanation=decision.explanation,
            evidence=[{"statement": item} for item in decision.evidence],
            raw_result={
                "provider": "openai-compatible",
                "model": provider.model,
                "rubric": rubric,
                "attempts": attempts,
                "response": raw_response,
            },
        )
    ]
