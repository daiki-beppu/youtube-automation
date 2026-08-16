"""信頼済みリポジトリ所有 JSON Schema の固定 registry。"""

from __future__ import annotations

import copy
import json
from enum import Enum
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Callable

import fastjsonschema

from youtube_automation.core.errors import DocumentValidationError

_DRAFT_7 = "http://json-schema.org/draft-07/schema#"


class RepositorySchema(str, Enum):
    """実行時にコンパイルを許可するリポジトリ所有 schema。"""

    ANALYSIS_REPORT = "analysis-report.schema.json"
    AUDIT_REPORT = "audit-report.schema.json"
    EXPERIMENT_ENTRY = "experiment-entry.schema.json"
    FEEDBACK_ENTRY = "feedback-entry.schema.json"
    INSIGHTS_ENTRY = "insights-entry.schema.json"
    WEEKLY_VOTE_LOG = "weekly_vote_log.schema.json"


_SKILL_RESOURCES = {
    RepositorySchema.ANALYSIS_REPORT: ("analytics", "references", "analysis-report.schema.json"),
    RepositorySchema.AUDIT_REPORT: ("audit", "references", "audit-report.schema.json"),
    RepositorySchema.EXPERIMENT_ENTRY: ("analytics", "references", "experiment-entry.schema.json"),
    RepositorySchema.FEEDBACK_ENTRY: ("skill-feedback", "references", "feedback-entry.schema.json"),
    RepositorySchema.INSIGHTS_ENTRY: ("analytics", "references", "insights-entry.schema.json"),
}
_SOURCE_SKILLS = Path(__file__).resolve().parents[4] / ".claude" / "skills"


def repository_schema_names() -> tuple[str, ...]:
    """固定 registry に登録された schema ファイル名を返す。"""
    return tuple(sorted(schema.value for schema in RepositorySchema))


def _read_skill_resource(schema: RepositorySchema) -> str:
    parts = _SKILL_RESOURCES[schema]
    resource = files("youtube_automation").joinpath("_skills", *parts)
    try:
        return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        return _SOURCE_SKILLS.joinpath(*parts).read_text(encoding="utf-8")


@cache
def _loaded_schema(schema: RepositorySchema) -> dict[str, object]:
    if schema is RepositorySchema.WEEKLY_VOTE_LOG:
        resource = files("youtube_automation.domains.collections.schemas").joinpath(schema.value)
        raw = resource.read_text(encoding="utf-8")
    else:
        raw = _read_skill_resource(schema)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"repository schema が JSON object ではありません: {schema.value}")
    if payload.get("$schema") != _DRAFT_7:
        raise ValueError(f"repository schema が Draft 7 ではありません: {schema.value}")
    return payload


def load_repository_schema(schema: RepositorySchema) -> dict[str, object]:
    """信頼済み schema のコピーを返す（compiler による書き換えを隔離する）。"""
    _require_schema(schema)
    return copy.deepcopy(_loaded_schema(schema))


def _trusted_reference(uri: str) -> dict[str, object]:
    if uri != RepositorySchema.INSIGHTS_ENTRY.value:
        raise ValueError(f"未登録の schema reference です: {uri}")
    return load_repository_schema(RepositorySchema.INSIGHTS_ENTRY)


@cache
def _compiled_validator(schema: RepositorySchema) -> Callable[[object], object]:
    definition = load_repository_schema(schema)
    return fastjsonschema.compile(
        definition,
        handlers={"": _trusted_reference},
        use_default=False,
        detailed_exceptions=True,
    )


def compile_repository_schemas() -> None:
    """registry の全 schema を process cache へコンパイルする。"""
    for schema in RepositorySchema:
        _compiled_validator(schema)


def validate_repository_document(schema: RepositorySchema, document: object) -> None:
    """文書を検証し、値を含まない JSON pointer 付き domain error へ変換する。"""
    _require_schema(schema)
    try:
        _compiled_validator(schema)(document)
    except fastjsonschema.JsonSchemaException as error:
        pointer = _json_pointer(error.path)
        raise DocumentValidationError(f"{schema.value}: schema keyword={error.rule} pointer={pointer}") from error


def _require_schema(schema: RepositorySchema) -> None:
    if not isinstance(schema, RepositorySchema):
        raise TypeError("schema は RepositorySchema から選択してください")


def _json_pointer(path: list[object]) -> str:
    parts = path[1:] if path and path[0] == "data" else path
    if not parts:
        return "/"
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "/" + "/".join(escaped)
