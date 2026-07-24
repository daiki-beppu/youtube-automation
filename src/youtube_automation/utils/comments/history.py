"""返信済みコメントの履歴ファイル I/O（二重返信防止）."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from youtube_automation.infrastructure.errors import ConfigError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class ReplyHistory:
    """`comment_reply_history.json` を schema_version 付き JSON として永続化する."""

    def __init__(self, path: Path):
        self._path = path
        self._data: dict[str, Any] = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"schema_version": SCHEMA_VERSION, "replied": {}}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"comment_reply_history.json の JSON パース失敗: {self._path}: {e}") from e
        if not isinstance(data, dict):
            raise ConfigError(f"comment_reply_history.json のトップレベルは object でなければなりません: {self._path}")
        data.setdefault("schema_version", SCHEMA_VERSION)
        replied = data.setdefault("replied", {})
        if not isinstance(replied, dict):
            raise ConfigError(f"comment_reply_history.json の replied は object でなければなりません: {self._path}")
        return data

    def has_replied(self, comment_id: str) -> bool:
        return comment_id in self._data["replied"]

    def replied_video_ids(self) -> set[str]:
        """履歴に記録済みコメントの video_id 集合を返す（preflight の quota 節約用）.

        過去に返信実績がある video は既に到達可能だったとみなし、status preflight の
        対象から除外する。metadata に video_id を持たない古いレコードは無視する。
        """
        ids: set[str] = set()
        for metadata in self._data["replied"].values():
            if isinstance(metadata, dict):
                video_id = metadata.get("video_id")
                if video_id:
                    ids.add(video_id)
        return ids

    def mark_replied(self, comment_id: str, metadata: dict[str, Any]) -> None:
        self._data["replied"][comment_id] = metadata

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, ensure_ascii=False, indent=2) + "\n"
        # 途中断絶時の履歴破損を防ぐため tmp に書いてから rename で差し替える
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, self._path)
        logger.info("返信履歴を保存: %s (%d件)", self._path, len(self._data["replied"]))

    def replied_count(self) -> int:
        return len(self._data["replied"])
