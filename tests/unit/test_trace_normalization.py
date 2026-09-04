from agent_eval_api.contracts import ExecutionStatus, TraceSpanKind
from agent_eval_api.trace_normalization import normalize_trace_payload


def test_openinference_fields_are_normalized_and_extensions_are_preserved() -> None:
    trace = normalize_trace_payload(
        {
            "trace_id": "external-trace-1",
            "status": "OK",
            "vendor.trace": {"session": "s-1"},
            "spans": [
                {
                    "span_id": "llm-span",
                    "name": "chat.completions",
                    "startTimeUnixNano": "1720000000000000000",
                    "endTimeUnixNano": "1720000001000000000",
                    "status": {"code": "OK"},
                    "vendor.span": "keep-me",
                    "attributes": {
                        "openinference.span.kind": "LLM",
                        "input.value": '{"question":"Where is order 42?"}',
                        "output.value": "shipped",
                        "gen_ai.request.model": "gpt-test",
                        "vendor.attribute": {"attempt": 1},
                    },
                }
            ],
        },
        source="openinference",
    )

    span = trace.spans[0]
    assert trace.trace_id == "external-trace-1"
    assert trace.source == "openinference"
    assert trace.extensions["vendor.trace"] == {"session": "s-1"}
    assert span.kind is TraceSpanKind.LLM
    assert span.status is ExecutionStatus.COMPLETED
    assert span.input == {"question": "Where is order 42?"}
    assert span.attributes["gen_ai.request.model"] == "gpt-test"
    assert span.attributes["vendor.attribute"] == {"attempt": 1}
    assert span.extensions["vendor.span"] == "keep-me"


def test_otlp_resource_spans_are_flattened_with_resource_attributes() -> None:
    trace = normalize_trace_payload(
        {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "order-agent"}}
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "otlp-trace-1",
                                    "spanId": "tool-span",
                                    "name": "search_order",
                                    "startTimeUnixNano": "1720000000000000000",
                                    "attributes": [
                                        {
                                            "key": "gen_ai.operation.name",
                                            "value": {"stringValue": "execute_tool"},
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        },
        source="otlp",
    )

    assert trace.trace_id == "otlp-trace-1"
    assert trace.spans[0].kind is TraceSpanKind.TOOL
    assert trace.spans[0].attributes["service.name"] == "order-agent"
