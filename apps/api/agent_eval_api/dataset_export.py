"""Stable JSONL and CSV exports for immutable dataset versions."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from typing import Any

from agent_eval_api.contracts import Dataset, DatasetCase, DatasetVersion

EXPORT_METADATA_FIELD = "__agent_eval_export_metadata"
EXPORT_RECORD_TYPE_FIELD = "__agent_eval_record_type"
EXPORT_METADATA_RECORD_TYPE = "metadata"
EXPORT_CASE_RECORD_TYPE = "case"
CASE_FIELDS = tuple(DatasetCase.model_fields)


def export_dataset_version_jsonl(dataset: Dataset, version: DatasetVersion) -> str:
    """Serialize a version as re-importable JSONL with a leading metadata record."""

    records: Iterable[dict[str, Any]] = (
        {EXPORT_METADATA_FIELD: export_metadata(dataset, version)},
        *(case.model_dump(mode="json") for case in version.cases),
    )
    return "\n".join(_json_dump(record) for record in records) + "\n"


def export_dataset_version_csv(dataset: Dataset, version: DatasetVersion) -> str:
    """Serialize a version as editable CSV while retaining nested fields as JSON cells."""

    buffer = io.StringIO(newline="")
    fieldnames = [EXPORT_RECORD_TYPE_FIELD, EXPORT_METADATA_FIELD, *CASE_FIELDS]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            EXPORT_RECORD_TYPE_FIELD: EXPORT_METADATA_RECORD_TYPE,
            EXPORT_METADATA_FIELD: _json_dump(export_metadata(dataset, version)),
        }
    )
    for case in version.cases:
        row = {
            EXPORT_RECORD_TYPE_FIELD: EXPORT_CASE_RECORD_TYPE,
            **_case_to_csv_row(case),
        }
        writer.writerow(row)
    return buffer.getvalue()


def export_metadata(dataset: Dataset, version: DatasetVersion) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "tags": dataset.tags,
        },
        "dataset_version": {
            "id": version.id,
            "version": version.version,
            "metadata": version.metadata,
            "created_at": version.created_at.isoformat(),
        },
    }


def _case_to_csv_row(case: DatasetCase) -> dict[str, str]:
    data = case.model_dump(mode="json")
    row: dict[str, str] = {}
    for field in CASE_FIELDS:
        value = data[field]
        if value is None:
            row[field] = ""
        elif field in {"id", "source_trace_id"} or isinstance(value, str):
            row[field] = value
        else:
            row[field] = _json_dump(value)
    return row


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
