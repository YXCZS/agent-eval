"""Prompt-specific deterministic metrics, including embedding cosine similarity."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Any

import httpx

from agent_eval_api.contracts import ScoreDirection, ScoreStatus

from .base import EvaluationContext, EvaluatorConfigurationError, EvaluatorOutcome
from .deterministic import deterministic_evaluator_key, evaluate_deterministic


class EmbeddingProviderError(RuntimeError):
    def __init__(self, error_type: str, message: str, *, attempts: int = 1) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.attempts = attempts


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    endpoint: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 60.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.2


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _extract_embeddings(body: Any) -> list[list[float]]:
    try:
        rows = sorted(body["data"], key=lambda item: item["index"])
        embeddings = [[float(value) for value in item["embedding"]] for item in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise EmbeddingProviderError(
            "protocol_error", "embedding response has an invalid schema"
        ) from exc
    if len(embeddings) != 2 or not embeddings[0] or len(embeddings[0]) != len(embeddings[1]):
        raise EmbeddingProviderError(
            "protocol_error", "embedding response must contain two equal-length vectors"
        )
    return embeddings


async def _request_embeddings(
    provider: EmbeddingProviderConfig,
    texts: list[str],
    *,
    client: httpx.AsyncClient | None,
) -> tuple[list[list[float]], int]:
    headers = {"Content-Type": "application/json"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=provider.timeout_seconds)
    attempt = 0
    try:
        while True:
            try:
                response = await http_client.post(
                    provider.endpoint,
                    headers=headers,
                    json={"model": provider.model, "input": texts},
                )
                if response.status_code == 429:
                    raise EmbeddingProviderError(
                        "rate_limit", "embedding provider rate limited the request"
                    )
                if response.status_code >= 500:
                    raise EmbeddingProviderError(
                        "service_error",
                        f"embedding provider returned HTTP {response.status_code}",
                    )
                response.raise_for_status()
                return _extract_embeddings(response.json()), attempt + 1
            except EmbeddingProviderError as exc:
                if exc.error_type == "protocol_error" or attempt >= provider.max_retries:
                    raise EmbeddingProviderError(
                        exc.error_type, str(exc), attempts=attempt + 1
                    ) from exc
            except httpx.TimeoutException as exc:
                if attempt >= provider.max_retries:
                    raise EmbeddingProviderError(
                        "timeout", "embedding request timed out", attempts=attempt + 1
                    ) from exc
            except httpx.HTTPStatusError as exc:
                raise EmbeddingProviderError(
                    "provider_error",
                    f"embedding request failed: HTTP {exc.response.status_code}",
                    attempts=attempt + 1,
                ) from exc
            except httpx.HTTPError as exc:
                if attempt >= provider.max_retries:
                    raise EmbeddingProviderError(
                        "connection_error",
                        "embedding request could not be completed",
                        attempts=attempt + 1,
                    ) from exc
            except ValueError as exc:
                raise EmbeddingProviderError(
                    "protocol_error",
                    "embedding response is not valid JSON",
                    attempts=attempt + 1,
                ) from exc
            await asyncio.sleep(provider.retry_backoff_seconds * (2**attempt))
            attempt += 1
    finally:
        if owns_client:
            await http_client.aclose()


def _cosine(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise EmbeddingProviderError("protocol_error", "embedding vector norm must be non-zero")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


async def semantic_similarity(
    context: EvaluationContext,
    provider: EmbeddingProviderConfig,
    *,
    client: httpx.AsyncClient | None = None,
) -> EvaluatorOutcome:
    expected = context.case.expected_output
    if expected is None:
        return EvaluatorOutcome(
            metric_name=context.evaluator.name,
            status=ScoreStatus.MISSING,
            explanation="expected_output is required",
        )
    vectors, attempts = await _request_embeddings(
        provider,
        [_text(expected), _text(context.execution.output)],
        client=client,
    )
    similarity = _cosine(vectors[0], vectors[1])
    threshold = context.evaluator.default_threshold
    if threshold is None:
        raise EvaluatorConfigurationError("semantic similarity requires default_threshold")
    if context.evaluator.direction is ScoreDirection.LOWER_IS_BETTER:
        passed = similarity <= threshold
    else:
        passed = similarity >= threshold
    return EvaluatorOutcome(
        metric_name=context.evaluator.name,
        status=ScoreStatus.PASSED if passed else ScoreStatus.FAILED,
        value=similarity,
        passed=passed,
        explanation=f"embedding cosine similarity is {similarity:.6f}",
        evidence=[
            {
                "similarity": similarity,
                "threshold": threshold,
                "embedding_model": provider.model,
                "dimensions": len(vectors[0]),
            }
        ],
        raw_result={
            "provider": "openai-compatible",
            "model": provider.model,
            "attempts": attempts,
            "dimensions": len(vectors[0]),
        },
    )


async def evaluate_prompt_deterministic(
    context: EvaluationContext,
    *,
    embedding_provider: EmbeddingProviderConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[EvaluatorOutcome]:
    configured_metric = context.evaluator.config.get("metric", context.evaluator.name)
    key = deterministic_evaluator_key(str(configured_metric))
    if key == "semantic_similarity":
        if embedding_provider is None:
            raise EvaluatorConfigurationError(
                "semantic similarity requires an embedding provider"
            )
        return [await semantic_similarity(context, embedding_provider, client=client)]
    if key not in {"exact_match", "json_schema", "latency", "token", "token_usage", "cost"}:
        raise EvaluatorConfigurationError(
            f"unknown Prompt deterministic evaluator: {context.evaluator.name}"
        )
    return evaluate_deterministic(context)
