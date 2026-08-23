"""PreflightChecker の collection upload 前チェックの回帰テスト."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.video_description import write_video_description_pair
from youtube_automation.configuration import load_config
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.uploads.youtube import PreflightChecker, YouTubeAutoUploader


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
    title: str = "Continuous Focus Mix",
) -> Path:
    collection_dir = channel_dir / "collections" / "planning" / "20260622-tc-continuous"
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True, exist_ok=True)
    write_video_description_pair(
        docs_dir,
        title=title,
        description=description,
        tags=[] if tags is None else tags,
    )
    _write_json(collection_dir / "workflow-state.json", {"scene_phrases": scene_phrases})
    master_dir = collection_dir / "01-master"
    master_dir.mkdir(parents=True)
    (master_dir / "master.mp4").write_bytes(b"probe is mocked")
    (collection_dir / "02-Individual-music").mkdir()
    (collection_dir / "10-assets").mkdir()
    return collection_dir


def _run_preflight(
    channel_dir: Path,
    collection_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_duration_outside_target: bool = False,
    duration_seconds: float = 3600,
    metadata_generator_factory=None,
) -> None:
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    checker_kwargs = {
        "duration_probe": lambda _: duration_seconds,
        "allow_duration_outside_target": allow_duration_outside_target,
    }
    if metadata_generator_factory is not None:
        checker_kwargs["metadata_generator_factory"] = metadata_generator_factory
    checker = PreflightChecker(channel_dir / "collections", **checker_kwargs)
    checker.check(collection_dir)


def test_legacy_markdown_is_not_parsed_by_preflight(tmp_path: Path) -> None:
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

    with pytest.raises(ValidationError) as excinfo:
        PreflightChecker(tmp_path / "collections").check(collection_dir)

    assert "descriptions.json が存在しません" in str(excinfo.value)


def test_invalid_json_pair_fails_closed(tmp_path: Path) -> None:
    collection_dir = tmp_path / "collections" / "planning" / "20260630-empty-title"
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True)
    source = write_video_description_pair(docs_dir)
    document = json.loads(source.read_text(encoding="utf-8"))
    document["title"] = ""
    source.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValidationError) as excinfo:
        PreflightChecker(tmp_path / "collections").check(collection_dir)

    assert "pointer=/title" in str(excinfo.value)


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
        title="YAKAP NG PAMILYA 💛 | Inspirational Pinoy Reggae Music 2026 | Awit ng Pagmamahal",
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

    with pytest.raises(ValidationError, match="workflow-state.json .*存在しません"):
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

    with pytest.raises(ValidationError, match="workflow-state.json.scene_phrases"):
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
    with pytest.raises(
        ValidationError,
        match=r"duration: 50m .*target 1h00m〜1h30m.*--allow-duration-outside-target",
    ):
        _run_preflight(channel_dir, collection_dir, monkeypatch, duration_seconds=50 * 60 + 29)


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
    _run_preflight(
        channel_dir,
        collection_dir,
        monkeypatch,
        allow_duration_outside_target=True,
        duration_seconds=50 * 60 + 29,
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

    with pytest.raises(ValidationError) as excinfo:
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
    checker = PreflightChecker(channel_dir / "collections", duration_probe=lambda _: 3600)
    uploader = YouTubeAutoUploader(str(channel_dir / "collections"), preflight_checker=checker)
    monkeypatch.setattr(uploader, "_verify_authenticated_upload_channel", lambda: None)

    with pytest.raises(ValidationError) as excinfo:
        uploader.upload_collection(str(collection_dir), apply_default_publish_at=False)

    message = str(excinfo.value)
    assert "tags.min_count=30 is unreachable under YouTube's 500-character tag limit" in message
    assert "Reduce tags.min_count or shorten base tags." in message
