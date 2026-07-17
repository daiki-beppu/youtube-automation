"""data/insights.jsonl を insights-entry.schema.json に照らして検証する。

使い方:
    uv run python3 .claude/skills/analytics-analyze/references/validate_insights.py data/insights.jsonl

終了コード:
    0: 全行が schema 準拠（ファイル不在・空ファイルも「エントリ 0 件」として合格）
    1: schema 違反または id 重複がある
    2: 引数不正

schema（enum / 必須キー / pattern / additionalProperties）は同ディレクトリの
insights-entry.schema.json を単一ソースとして読み込む。検証条件をこのスクリプトへ
重複定義しないこと。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "insights-entry.schema.json"


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        schema = json.load(fh)
    if not isinstance(schema, dict):
        raise ValueError(f"schema が object ではありません: {_SCHEMA_PATH}")
    return schema


def _validate_value(name: str, value: object, prop_schema: dict) -> list[str]:
    errors: list[str] = []
    if "const" in prop_schema and value != prop_schema["const"]:
        errors.append(f"{name}: {prop_schema['const']!r} 固定です（実値: {value!r}）")
        return errors
    if "enum" in prop_schema and value not in prop_schema["enum"]:
        errors.append(f"{name}: {prop_schema['enum']} のいずれかにしてください（実値: {value!r}）")
        return errors
    if prop_schema.get("type") == "string":
        if not isinstance(value, str):
            errors.append(f"{name}: string にしてください（実値型: {type(value).__name__}）")
            return errors
        min_length = prop_schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{name}: {min_length} 文字以上の非空文字列にしてください")
        pattern = prop_schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{name}: pattern {pattern} に一致しません（実値: {value!r}）")
    return errors


def validate_entry(entry: object, schema: dict) -> list[str]:
    if not isinstance(entry, dict):
        return ["エントリは JSON object にしてください"]

    errors: list[str] = []
    properties: dict = schema.get("properties", {})

    for required_key in schema.get("required", []):
        if required_key not in entry:
            errors.append(f"必須キー {required_key} がありません")

    if schema.get("additionalProperties") is False:
        for key in entry:
            if key not in properties:
                errors.append(f"未知のキー {key} は許可されていません")

    for key, value in entry.items():
        prop_schema = properties.get(key)
        if isinstance(prop_schema, dict):
            errors.extend(_validate_value(key, value, prop_schema))

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <path/to/insights.jsonl>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.exists():
        print(f"OK: {path} は存在しません（エントリ 0 件として扱います）")
        return 0

    schema = _load_schema()
    failed = False
    seen_ids: dict[str, int] = {}
    entry_count = 0

    with path.open(encoding="utf-8") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            entry_count += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"line {lineno}: JSON として不正です: {exc}", file=sys.stderr)
                failed = True
                continue

            for message in validate_entry(entry, schema):
                print(f"line {lineno}: {message}", file=sys.stderr)
                failed = True

            entry_id = entry.get("id") if isinstance(entry, dict) else None
            if isinstance(entry_id, str) and entry_id:
                if entry_id in seen_ids:
                    print(
                        f"line {lineno}: id {entry_id!r} が line {seen_ids[entry_id]} と重複しています",
                        file=sys.stderr,
                    )
                    failed = True
                else:
                    seen_ids[entry_id] = lineno

    if failed:
        return 1
    print(f"OK: {path}（{entry_count} エントリ）は schema 準拠です")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
