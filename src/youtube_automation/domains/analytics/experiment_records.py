"""Shared experiment and insight schema validation and JSONL readers."""

from __future__ import annotations

import json
import math
import re
import stat
from datetime import date
from importlib.resources import as_file, files
from pathlib import Path

from youtube_automation.core.errors import ValidationError

_SCHEMA_NAME = "experiment-entry.schema.json"
_INSIGHTS_SCHEMA_NAME = "insights-entry.schema.json"


def _reference_path(name: str) -> Path:
    resource = files("youtube_automation").joinpath("_skills", "analytics", "references", name)
    with as_file(resource) as packaged_path:
        if packaged_path.exists():
            return Path(packaged_path)
    source_path = Path(__file__).resolve().parents[4] / ".claude" / "skills" / "analytics" / "references" / name
    if source_path.exists():
        return source_path
    raise ValidationError(f"analytics schema が見つかりません: {name}")


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"schema を読めません: {path}") from error
    if not isinstance(payload, dict):
        raise ValidationError(f"schema が object ではありません: {path}")
    return payload


def load_schema() -> tuple[dict[str, object], dict[str, object]]:
    return _load_json_object(_reference_path(_SCHEMA_NAME)), _load_json_object(_reference_path(_INSIGHTS_SCHEMA_NAME))


def _resolved_property_schema(
    property_schema: dict[str, object], insights_schema: dict[str, object]
) -> dict[str, object]:
    reference = property_schema.get("$ref")
    if reference is None:
        return property_schema
    expected = f"{_INSIGHTS_SCHEMA_NAME}#/properties/lever"
    if reference != expected:
        raise ValidationError(f"未対応の schema $ref です: {reference!r}")
    properties = insights_schema.get("properties")
    if not isinstance(properties, dict) or not isinstance(properties.get("lever"), dict):
        raise ValidationError("insights schema に lever 契約がありません")
    return properties["lever"]


def _validate_string_property(name: str, value: object, schema: dict[str, object]) -> list[str]:
    if not isinstance(value, str):
        return [f"{name}: string にしてください"]
    errors: list[str] = []
    minimum_length = schema.get("minLength")
    if isinstance(minimum_length, int) and len(value) < minimum_length:
        errors.append(f"{name}: 非空文字列にしてください")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
        errors.append(f"{name}: pattern {pattern} に一致しません")
    return errors


def _validate_minimum(name: str, value: int | float, schema: dict[str, object]) -> list[str]:
    minimum = schema.get("minimum")
    if isinstance(minimum, (int, float)) and value < minimum:
        return [f"{name}: {minimum} 以上にしてください"]
    return []


def _validate_property(name: str, value: object, schema: dict[str, object]) -> list[str]:
    if "const" in schema and value != schema["const"]:
        return [f"{name}: {schema['const']!r} 固定です"]
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return [f"{name}: {enum!r} のいずれかにしてください"]
    value_type = schema.get("type")
    if value_type == "string":
        return _validate_string_property(name, value, schema)
    if value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{name}: bool ではない integer にしてください"]
        return _validate_minimum(name, value, schema)
    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return [f"{name}: finite number にしてください"]
        return _validate_minimum(name, value, schema)
    return []


def validate_entry(entry: object, schema: dict[str, object], insights_schema: dict[str, object]) -> list[str]:
    if not isinstance(entry, dict):
        return ["エントリは JSON object にしてください"]
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValidationError("experiment schema の properties / required が不正です")
    errors = [f"必須キー {key} がありません" for key in required if key not in entry]
    if schema.get("additionalProperties") is False:
        errors.extend(f"未知のキー {key} は許可されていません" for key in entry if key not in properties)
    for name, value in entry.items():
        property_schema = properties.get(name)
        if isinstance(property_schema, dict):
            errors.extend(_validate_property(name, value, _resolved_property_schema(property_schema, insights_schema)))
    errors.extend(_validate_entry_semantics(entry))
    return errors


def _validate_entry_semantics(entry: dict[str, object]) -> list[str]:
    """Check calendar validity and relationships between experiment state fields."""
    errors: list[str] = []
    for date_field in ("registered_date", "judged_date", "date"):
        date_value = entry.get(date_field)
        if isinstance(date_value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date_value):
            try:
                date.fromisoformat(date_value)
            except ValueError:
                errors.append(f"{date_field}: 実在する日付にしてください")
    if "registered_date" in entry:
        judged_fields = {"judged_date", "result_vpd", "verdict"}
        if entry.get("status") == "judged":
            errors.extend(f"status=judged には {key} が必要です" for key in judged_fields if key not in entry)
        elif entry.get("status") == "pending":
            errors.extend(f"status=pending には {key} を指定できません" for key in judged_fields if key in entry)
    return errors


def read_entries(path: Path) -> tuple[bytes, list[dict[str, object]]]:
    if not path.exists():
        return b"", []
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise ValidationError(f"experiments JSONL を確認できません: {path}") from error
    if not stat.S_ISREG(mode):
        raise ValidationError(f"experiments JSONL は regular file である必要があります: {path}")
    try:
        original = path.read_bytes()
        text = original.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ValidationError(f"experiments JSONL を読めません: {path}") from error
    schema, insights_schema = load_schema()
    entries = parse_json_lines(text, schema, insights_schema, error_context="experiments JSONL")
    return original, entries


def parse_json_lines(
    text: str,
    schema: dict[str, object],
    insights_schema: dict[str, object],
    *,
    error_context: str,
) -> list[dict[str, object]]:
    """Validate every nonblank JSONL record and reject aggregate schema/ID failures."""
    entries: list[dict[str, object]] = []
    seen_ids: dict[str, int] = {}
    failures: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError as error:
            failures.append(f"line {line_number}: JSON として不正です: {error.msg}")
            continue
        entry_errors = validate_entry(entry, schema, insights_schema)
        failures.extend(f"line {line_number}: schema 違反: {message}" for message in entry_errors)
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            if entry_id in seen_ids:
                failures.append(f"line {line_number}: id {entry_id!r} が line {seen_ids[entry_id]} と重複しています")
            else:
                seen_ids[entry_id] = line_number
        entries.append(entry)
    if failures:
        raise ValidationError(f"{error_context} の検証に失敗しました: " + "; ".join(failures))
    return entries


def validate_entries(path: Path) -> list[str]:
    try:
        read_entries(path)
    except ValidationError as error:
        return [str(error)]
    return []
