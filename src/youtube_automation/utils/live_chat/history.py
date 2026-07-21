"""ライブチャット処理履歴の永続化."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from youtube_automation.utils.exceptions import ConfigError

SCHEMA_VERSION = 1
HistoryScalar = str | int | float | bool | None
HistoryRecord = dict[str, HistoryScalar]


class HistoryData(TypedDict):
    schema_version: int
    processed: dict[str, HistoryRecord]


class LiveChatHistory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data = self._load()

    def _load(self) -> HistoryData:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "processed": {}}
        try:
            raw: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigError(f"ライブチャット履歴を読めません: {self.path}: {error}") from error
        if not isinstance(raw, dict) or not isinstance(raw.get("processed"), dict):
            raise ConfigError(f"ライブチャット履歴の形式が不正です: {self.path}")
        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ConfigError(f"未対応のライブチャット履歴 schema_version={version!r}")
        processed: dict[str, HistoryRecord] = {}
        for message_id, value in raw["processed"].items():
            if not isinstance(message_id, str) or not isinstance(value, dict):
                raise ConfigError(f"ライブチャット履歴の形式が不正です: {self.path}")
            if any(
                not isinstance(key, str) or (field is not None and not isinstance(field, (str, int, float, bool)))
                for key, field in value.items()
            ):
                raise ConfigError(f"ライブチャット履歴の形式が不正です: {self.path}")
            processed[message_id] = dict(value)
        return {"schema_version": SCHEMA_VERSION, "processed": processed}

    def has_processed(self, message_id: str) -> bool:
        return message_id in self._data["processed"]

    def mark(self, message_id: str, **metadata: HistoryScalar) -> None:
        metadata.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        self._data["processed"][message_id] = metadata
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def replied_records(self) -> list[HistoryRecord]:
        records = [value for value in self._data["processed"].values() if value.get("outcome") == "replied"]
        return sorted(records, key=lambda value: value.get("recorded_at", ""))
