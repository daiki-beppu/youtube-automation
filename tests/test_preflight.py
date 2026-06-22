"""PreflightMixin の collection upload 前チェックの回帰テスト."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from youtube_automation.agents._preflight import PreflightMixin


class _PreflightHarness(PreflightMixin):
    def __init__(self, collections_root: Path) -> None:
        self.collections_root = collections_root

    @staticmethod
    def _extract_md_section(text: str, header: str) -> str | None:
        pattern = rf"^## {re.escape(header)}\n```(?:\w+)?\n(.*?)\n```"
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        return match.group(1) if match else None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_minimal_channel(tmp_path: Path, *, youtube_language: str, supported_languages: list[str]) -> Path:
    channel_dir = tmp_path / "channel"
    _write_json(
        channel_dir / "config" / "channel" / "meta.json",
        {
            "channel": {
                "name": "Test Channel",
                "short": "TC",
                "youtube_handle": "@testchannel",
                "url": "https://youtube.com/@testchannel",
            }
        },
    )
    _write_json(
        channel_dir / "config" / "channel" / "content.json",
        {
            "genre": {"primary": "ambient", "style": "quiet", "context": "work"},
            "tags": {
                "base": ["ambient music", "focus music"],
                "themes": {"continuous": ["continuous music"]},
            },
            "descriptions": {
                "opening": "{style} {primary} for {context}",
                "perfect_for": ["Work", "Focus"],
                "hashtags": ["#AmbientMusic"],
            },
            "title": {"template": "{theme} - {activity}"},
        },
    )
    _write_json(
        channel_dir / "config" / "channel" / "youtube.json",
        {
            "youtube": {
                "category_id": "10",
                "privacy_status": "public",
                "language": youtube_language,
            }
        },
    )
    _write_json(
        channel_dir / "config" / "localizations.json",
        {"supported_languages": supported_languages, "languages": {}},
    )
    return channel_dir


def _write_collection(channel_dir: Path, *, scene_phrases: dict[str, str], description: str) -> Path:
    collection_dir = channel_dir / "collections" / "planning" / "20260622-tc-continuous"
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "descriptions.md").write_text(
        f"""## タイトル案
```
Continuous Focus Mix
```

## Complete Collection 概要欄
```
{description}
```
""",
        encoding="utf-8",
    )
    _write_json(collection_dir / "workflow-state.json", {"scene_phrases": scene_phrases})
    return collection_dir


def _run_preflight(channel_dir: Path, collection_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    _PreflightHarness(channel_dir / "collections")._preflight_check(collection_dir)


def test_en_only_channel_without_timestamps_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en"])
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "continuous focus mix"},
        description="A continuous BGM mix without chapter markers.",
    )

    _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_scene_phrases_require_only_supported_languages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="ja", supported_languages=["ja"])
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"ja": "連続作業用ミックス"},
        description="A continuous BGM mix without chapter markers.",
    )

    _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_missing_supported_scene_phrase_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en", "ja", "de"])
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "continuous focus mix"},
        description="00:00 Opening\n10:00 Middle\n20:00 Ending",
    )

    with pytest.raises(RuntimeError, match="workflow-state.json.scene_phrases"):
        _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_low_cpm_localization_warning_still_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en", "ko"])
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "continuous focus mix", "ko": "continuous focus mix"},
        description="A continuous BGM mix without chapter markers.",
    )

    _run_preflight(channel_dir, collection_dir, monkeypatch)

    assert "low CPM localization languages included: ko" in caplog.text
