#!/usr/bin/env python3
"""単一変数実験を検証済み JSONL へ append-only 登録する。"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import date
from importlib.resources import as_file, files
from pathlib import Path
from statistics import median

from youtube_automation.commands.analytics import vpd_rank
from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import AutomationError, ValidationError
from youtube_automation.infrastructure.analytics.theme_performance import classify_videos_by_theme

_SCHEMA_NAME = "experiment-entry.schema.json"
_INSIGHTS_SCHEMA_NAME = "insights-entry.schema.json"
DEFAULT_CHANGE_TEMPLATE = "{lever}: unspecified -> unspecified"
DEFAULT_HYPOTHESIS_SOURCE = "unspecified"


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


def _validate_property(name: str, value: object, schema: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        return [f"{name}: {schema['const']!r} 固定です"]
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return [f"{name}: {enum!r} のいずれかにしてください"]
    value_type = schema.get("type")
    if value_type == "string":
        if not isinstance(value, str):
            return [f"{name}: string にしてください"]
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"{name}: 非空文字列にしてください")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            errors.append(f"{name}: pattern {pattern} に一致しません")
    elif value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{name}: bool ではない integer にしてください"]
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{name}: {minimum} 以上にしてください")
    elif value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return [f"{name}: finite number にしてください"]
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{name}: {minimum} 以上にしてください")
    return errors


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
    registered_date = entry.get("registered_date")
    if isinstance(registered_date, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", registered_date):
        try:
            date.fromisoformat(registered_date)
        except ValueError:
            errors.append("registered_date: 実在する日付にしてください")
    return errors


def _read_entries(path: Path) -> tuple[bytes, list[dict[str, object]]]:
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
        raise ValidationError("experiments JSONL の検証に失敗しました: " + "; ".join(failures))
    return original, entries


def validate_entries(path: Path) -> list[str]:
    try:
        _read_entries(path)
    except ValidationError as error:
        return [str(error)]
    return []


def _required_text(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError(f"{name} は空でない文字列で指定してください")
    return normalized


def _lever_values() -> tuple[str, ...]:
    schema, insights_schema = load_schema()
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not isinstance(properties.get("lever"), dict):
        raise ValidationError("experiment schema に lever 契約がありません")
    lever_schema = _resolved_property_schema(properties["lever"], insights_schema)
    enum = lever_schema.get("enum")
    if not isinstance(enum, list) or not all(isinstance(value, str) for value in enum):
        raise ValidationError("insights schema の lever enum が不正です")
    return tuple(enum)


def _validate_lever(value: str) -> str:
    lever = _required_text("lever", value)
    if "," in lever:
        raise ValidationError("lever はカンマ区切りにせず 1 つだけ指定してください")
    if lever not in _lever_values():
        raise ValidationError(f"lever は {_lever_values()} のいずれかにしてください")
    return lever


def _nonnegative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("0 以上の integer を指定してください") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("0 以上の integer を指定してください")
    return parsed


def _record_id(registered: date, lever: str, target: str) -> str:
    target_slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", target.lower())).strip("-")
    if not target_slug:
        raise ValidationError("target から experiment id を生成できません")
    return f"{registered:%Y%m%d}-{lever}-{target_slug}"


def _validate_ranking(ranking: object) -> tuple[list[dict[str, object]], int]:
    if not isinstance(ranking, dict) or not isinstance(ranking.get("ranking"), list):
        raise ValidationError("yt-vpd-rank の ranking が不正です")
    items = ranking["ranking"]
    n = ranking.get("n")
    min_age_days = ranking.get("min_age_days")
    if isinstance(n, bool) or not isinstance(n, int) or n != len(items):
        raise ValidationError("yt-vpd-rank の n が ranking 件数と一致しません")
    if isinstance(min_age_days, bool) or not isinstance(min_age_days, int) or min_age_days < 0:
        raise ValidationError("yt-vpd-rank の min_age_days が不正です")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("video_id"), str):
            raise ValidationError("yt-vpd-rank の video entry が不正です")
        value = item.get("vpd")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValidationError(f"yt-vpd-rank の vpd が不正です: {item.get('video_id')}")
    return items, min_age_days


def _baseline(ranking: object, baseline_scope: str, theme_keywords: dict[str, list[str]]) -> tuple[float, str]:
    items, min_age_days = _validate_ranking(ranking)
    scope = _required_text("baseline_scope", baseline_scope)
    selected = items
    basis_scope = "all"
    if scope != "all":
        if scope not in theme_keywords:
            raise ValidationError(f"baseline_scope theme が設定されていません: {scope}")
        metadata = {str(item["video_id"]): {"title": item.get("title", "")} for item in items}
        groups = classify_videos_by_theme(metadata, theme_keywords)
        selected_ids = set(groups.get(scope, []))
        selected = [item for item in items if item["video_id"] in selected_ids]
        basis_scope = f"theme:{scope}"
    if not selected:
        raise ValidationError(f"baseline_scope の eligible video がありません: {scope}")
    baseline_vpd = float(median(float(item["vpd"]) for item in selected))
    basis = (
        f"source=yt-vpd-rank; scope={basis_scope}; n={len(selected)}; median={baseline_vpd}; "
        f"min_age_days={min_age_days}"
    )
    return baseline_vpd, basis


def _judge_after_days(config: dict[str, object]) -> int:
    experiment = config.get("experiment")
    if not isinstance(experiment, dict) or "judge_after_days" not in experiment:
        raise ValidationError("analytics.experiment.judge_after_days が未設定です")
    value = experiment["judge_after_days"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError("analytics.experiment.judge_after_days は 1 以上の integer にしてください")
    return value


def _atomic_append(path: Path, original: bytes, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    separator = b"" if not original or original.endswith(b"\n") else b"\n"
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(original)
            stream.write(separator)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def register_experiment(
    *,
    lever: str,
    target: str,
    change: str,
    hypothesis_source: str,
    baseline_scope: str,
    experiments_path: Path,
    today: date,
    ranking_loader: Callable[[], dict[str, object]],
    skill_config: dict[str, object],
    theme_keywords: dict[str, list[str]],
) -> dict[str, object]:
    resolved_lever = _validate_lever(lever)
    resolved_target = _required_text("target", target)
    resolved_change = _required_text("change", change)
    resolved_hypothesis = _required_text("hypothesis_source", hypothesis_source)
    resolved_scope = _required_text("baseline_scope", baseline_scope)
    if resolved_scope != "all" and resolved_scope not in theme_keywords:
        raise ValidationError(f"baseline_scope theme が設定されていません: {resolved_scope}")
    judge_days = _judge_after_days(skill_config)
    original, existing = _read_entries(experiments_path)
    record_id = _record_id(today, resolved_lever, resolved_target)
    if any(entry.get("target") == resolved_target and entry.get("status") == "pending" for entry in existing):
        raise ValidationError(f"target に pending experiment が既にあります: {resolved_target}")
    if any(entry.get("id") == record_id for entry in existing):
        raise ValidationError(f"experiment id が既存行と重複しています: {record_id}")
    ranking = ranking_loader()
    baseline_vpd, baseline_basis = _baseline(ranking, resolved_scope, theme_keywords)
    record: dict[str, object] = {
        "schema_version": 1,
        "id": record_id,
        "registered_date": today.isoformat(),
        "lever": resolved_lever,
        "change": resolved_change,
        "hypothesis_source": resolved_hypothesis,
        "target": resolved_target,
        "baseline_vpd": baseline_vpd,
        "baseline_basis": baseline_basis,
        "judge_after_days": judge_days,
        "status": "pending",
    }
    schema, insights_schema = load_schema()
    errors = validate_entry(record, schema, insights_schema)
    if errors:
        raise ValidationError("生成した experiment が schema 違反です: " + "; ".join(errors))
    _atomic_append(experiments_path, original, record)
    return record


def _today() -> date:
    return date.today()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="単一変数 experiment の登録")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register = subparsers.add_parser("register", help="pending experiment を append-only 登録")
    register.add_argument(
        "--lever",
        action="append",
        choices=_lever_values(),
        required=True,
        help="変更する単一レバー",
    )
    register.add_argument("--target", required=True, help="対象 collection slug または video_id")
    register.add_argument(
        "--change",
        help=f"変更内容（旧状態 -> 新状態）。省略時: {DEFAULT_CHANGE_TEMPLATE!r} の lever 展開値",
    )
    register.add_argument(
        "--hypothesis-source",
        default=DEFAULT_HYPOTHESIS_SOURCE,
        help=f"根拠 win pattern / insight id。省略時: {DEFAULT_HYPOTHESIS_SOURCE!r}",
    )
    register.add_argument("--baseline-scope", default="all", help="all または config の theme 名")
    register.add_argument(
        "--min-age-days",
        type=_nonnegative_integer,
        default=7,
        help="baseline 対象の最低公開日齢",
    )
    args = parser.parse_args(argv)
    if len(args.lever) != 1:
        parser.error("--lever は 1 回だけ指定してください")
    try:
        config = load_config()
        record = register_experiment(
            lever=args.lever[0],
            target=args.target,
            change=args.change if args.change is not None else DEFAULT_CHANGE_TEMPLATE.format(lever=args.lever[0]),
            hypothesis_source=args.hypothesis_source,
            baseline_scope=args.baseline_scope,
            experiments_path=channel_dir() / "data" / "experiments.jsonl",
            today=_today(),
            ranking_loader=lambda: vpd_rank._load_ranking(
                min_age_days=args.min_age_days,
                top_count=None,
            ),
            skill_config=load_skill_config("analytics"),
            theme_keywords=config.content.tags.themes,
        )
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    except AutomationError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
