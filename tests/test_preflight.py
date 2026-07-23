"""PreflightMixin の collection upload 前チェックの回帰テスト."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from youtube_automation.agents._preflight import PreflightMixin
from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader
from youtube_automation.configuration import load_config


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


def _write_minimal_channel(
    tmp_path: Path,
    *,
    youtube_language: str,
    supported_languages: list[str],
    audio: dict[str, float | int] | None = None,
) -> Path:
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
    if audio is not None:
        _write_json(channel_dir / "config" / "channel" / "audio.json", {"audio": audio})
    return channel_dir


def _write_collection(
    channel_dir: Path,
    *,
    scene_phrases: dict[str, str],
    description: str,
    tags: list[str] | None = None,
) -> Path:
    collection_dir = channel_dir / "collections" / "planning" / "20260622-tc-continuous"
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True, exist_ok=True)
    tags_section = (
        ""
        if tags is None
        else f"""\n## タグ（YouTube タグ欄）
```
{", ".join(tags)}
```
"""
    )
    (docs_dir / "descriptions.md").write_text(
        f"""## タイトル案
```
Continuous Focus Mix
```

## Complete Collection 概要欄
```
{description}
```
{tags_section}
""",
        encoding="utf-8",
    )
    _write_json(collection_dir / "workflow-state.json", {"scene_phrases": scene_phrases})
    return collection_dir


def _run_preflight(
    channel_dir: Path,
    collection_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_duration_outside_target: bool = False,
) -> None:
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    harness = _PreflightHarness(channel_dir / "collections")
    harness.allow_duration_outside_target = allow_duration_outside_target
    harness._preflight_check(collection_dir)


def test_heading_mismatch_reports_expected_missing_detected_and_fix_example(tmp_path: Path) -> None:
    collection_dir = tmp_path / "collections" / "planning" / "20260630-heading-typo"
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True)
    (docs_dir / "descriptions.md").write_text(
        """## タイトル
```
Continuous Focus Mix
```

## Complete Collection 概要欄
```
A continuous BGM mix without chapter markers.
```
""",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError) as excinfo:
        _PreflightHarness(tmp_path / "collections")._preflight_check(collection_dir)

    message = str(excinfo.value)
    assert "期待する見出し（完全一致）" in message
    assert ("不足/不一致の見出し:\n  - ## タイトル案\n  - ## タグ（YouTube タグ欄）") in message
    assert "検出した ## 見出し" in message
    assert "## タイトル" in message
    assert "修正例" in message
    assert "/video-description を再実行" in message


def test_empty_sections_keep_empty_section_error(tmp_path: Path) -> None:
    collection_dir = tmp_path / "collections" / "planning" / "20260630-empty-title"
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True)
    (docs_dir / "descriptions.md").write_text(
        """## タイトル案
```

```

## Complete Collection 概要欄
```
A continuous BGM mix without chapter markers.
```
""",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError) as excinfo:
        _PreflightHarness(tmp_path / "collections")._preflight_check(collection_dir)

    message = str(excinfo.value)
    assert "タイトル案 / Complete Collection 概要欄 が空" in message
    assert "不足/不一致の見出し" not in message


def test_en_only_channel_without_timestamps_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en"])
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "continuous focus mix"},
        description="A continuous BGM mix without chapter markers.",
    )

    _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_three_part_title_template_passes_collection_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en"])
    content_path = channel_dir / "config" / "channel" / "content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    content["title"]["template"] = "{tagline} | Inspirational Pinoy Reggae Music {year} | {subtitle}"
    content_path.write_text(json.dumps(content), encoding="utf-8")
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "continuous focus mix"},
        description="A continuous BGM mix without chapter markers.",
    )
    descriptions_path = collection_dir / "20-documentation" / "descriptions.md"
    descriptions = descriptions_path.read_text(encoding="utf-8")
    descriptions_path.write_text(
        descriptions.replace(
            "Continuous Focus Mix",
            "YAKAP NG PAMILYA 💛 | Inspirational Pinoy Reggae Music 2026 | Awit ng Pagmamahal",
        ),
        encoding="utf-8",
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


def test_single_language_channel_without_scene_phrases_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """単一言語チャンネルは populate が no-op のため scene_phrases 無しでも preflight が通る (#1470)."""
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en"])
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={},
        description="A continuous BGM mix without chapter markers.",
    )

    _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_single_language_channel_missing_workflow_state_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """単一言語でも workflow-state.json の存在は preflight で必須 (#1470)."""
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en"])
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={},
        description="A continuous BGM mix without chapter markers.",
    )
    (collection_dir / "workflow-state.json").unlink()

    with pytest.raises(RuntimeError, match="workflow-state.json .*存在しません"):
        _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_single_language_channel_malformed_workflow_state_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """単一言語でも workflow-state.json 自体の破損は preflight で見逃さない (#1470)."""
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en"])
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={},
        description="A continuous BGM mix without chapter markers.",
    )
    (collection_dir / "workflow-state.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
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


def test_plan_preflight_rejects_overlong_localized_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en", "de"])
    _write_json(
        channel_dir / "config" / "localizations.json",
        {
            "supported_languages": ["en", "de"],
            "languages": {
                "en": {"title_template": "{scene_phrase}"},
                "de": {"title_template": "{scene_phrase} " + "x" * 100},
            },
        },
    )
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "focus", "de": "ruhiger Fokus"},
        description="A continuous BGM mix without chapter markers.",
    )

    with pytest.raises(RuntimeError, match=r"\[de\] 114 codepoints.*ruhiger Fokus"):
        _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_target_duration_config_allows_video_inside_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_dir = _write_minimal_channel(
        tmp_path,
        youtube_language="en",
        supported_languages=["en"],
        audio={"target_duration_min": 60, "target_duration_max": 120},
    )
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "continuous focus mix"},
        description="A continuous BGM mix without chapter markers.",
    )
    master_dir = collection_dir / "01-master"
    master_dir.mkdir(parents=True)
    (master_dir / "master.mp4").write_bytes(b"probe is mocked")
    monkeypatch.setattr("youtube_automation.agents._preflight.probe_duration", lambda _: 60 * 60)

    _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_target_duration_config_blocks_short_video_without_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_dir = _write_minimal_channel(
        tmp_path,
        youtube_language="en",
        supported_languages=["en"],
        audio={"target_duration_min": 60, "target_duration_max": 90},
    )
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "continuous focus mix"},
        description="A continuous BGM mix without chapter markers.",
    )
    master_dir = collection_dir / "01-master"
    master_dir.mkdir(parents=True)
    (master_dir / "master.mp4").write_bytes(b"probe is mocked")
    monkeypatch.setattr("youtube_automation.agents._preflight.probe_duration", lambda _: 50 * 60 + 29)

    with pytest.raises(RuntimeError, match=r"duration: 50m .*target 1h00m〜1h30m.*--allow-duration"):
        _run_preflight(channel_dir, collection_dir, monkeypatch)


def test_target_duration_override_allows_short_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_dir = _write_minimal_channel(
        tmp_path,
        youtube_language="en",
        supported_languages=["en"],
        audio={"target_duration_min": 60, "target_duration_max": 90},
    )
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={"en": "continuous focus mix"},
        description="A continuous BGM mix without chapter markers.",
    )
    master_dir = collection_dir / "01-master"
    master_dir.mkdir(parents=True)
    (master_dir / "master.mp4").write_bytes(b"probe is mocked")
    monkeypatch.setattr("youtube_automation.agents._preflight.probe_duration", lambda _: 50 * 60 + 29)

    _run_preflight(
        channel_dir,
        collection_dir,
        monkeypatch,
        allow_duration_outside_target=True,
    )


def test_unreachable_tags_min_count_reports_character_limit_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en"])
    content_path = channel_dir / "config" / "channel" / "content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    content["tags"]["min_count"] = 30
    _write_json(content_path, content)

    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={},
        description="A continuous BGM mix without chapter markers.",
        tags=["a" * 17] * 26 + ["b" * 27],
    )

    with pytest.raises(RuntimeError) as excinfo:
        _run_preflight(channel_dir, collection_dir, monkeypatch)

    message = str(excinfo.value)
    assert "tags.min_count=30 is unreachable under YouTube's 500-character tag limit" in message
    assert "Reduce tags.min_count or shorten base tags." in message


def test_upload_collection_reports_unreachable_tags_min_count_from_channel_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公開 upload agent は content.json を loader 経由で読み、到達不能設定を停止する。"""
    channel_dir = _write_minimal_channel(tmp_path, youtube_language="en", supported_languages=["en"])
    content_path = channel_dir / "config" / "channel" / "content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    content["tags"]["min_count"] = 30
    _write_json(content_path, content)
    collection_dir = _write_collection(
        channel_dir,
        scene_phrases={},
        description="A continuous BGM mix without chapter markers.",
        tags=["a" * 17] * 26 + ["b" * 27],
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    assert load_config().content.tags.min_count == 30
    uploader = YouTubeAutoUploader(str(channel_dir / "collections"))

    with pytest.raises(RuntimeError) as excinfo:
        uploader.upload_collection(str(collection_dir), apply_default_publish_at=False)

    message = str(excinfo.value)
    assert "tags.min_count=30 is unreachable under YouTube's 500-character tag limit" in message
    assert "Reduce tags.min_count or shorten base tags." in message
