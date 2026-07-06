"""yt-config-migrate CLI のユニットテスト (tmp_path ベース)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.cli.config_migrate import (
    LOCALIZATIONS_FILENAME,
    SECTION_MAP,
    _resolve_target_dir,
    main,
)
from youtube_automation.utils.exceptions import ConfigError


@pytest.fixture(autouse=True)
def _auto_reset(monkeypatch):
    """CHANNEL_DIR を毎テスト前後にクリア + 新 loader シングルトンをリセット."""
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    from youtube_automation.utils.config import reset as reset_config

    reset_config()
    yield
    reset_config()


# ----------------------- Helpers -----------------------


def _minimal_legacy() -> dict:
    return {
        "channel": {
            "name": "Test Channel",
            "short": "TC",
            "youtube_handle": "@testchannel",
            "url": "https://youtube.com/@testchannel",
        },
        "genre": {"primary": "chiptune", "style": "8-bit", "context": "RPG"},
        "tags": {
            "base": ["chiptune"],
            "themes": {"battle": ["battle music"], "village": ["village music"]},
        },
        "descriptions": {
            "opening": "{style} {primary} for {context}",
            "perfect_for": ["gaming"],
            "hashtags": ["#chiptune"],
        },
        "title": {"template": "{theme} - {activity}"},
        "youtube": {"category_id": "10", "privacy_status": "public", "language": "en"},
    }


def _write_legacy(tmp_path: Path, data: dict) -> Path:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    path = cfg_dir / "channel_config.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------- migrate dry-run -----------------------


def test_migrate_dry_run_minimal(tmp_path, capsys):
    _write_legacy(tmp_path, _minimal_legacy())
    rc = main(["migrate", "--target", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "meta.json" in out
    assert "content.json" in out
    assert "youtube.json" in out
    channel_dir = tmp_path / "config" / "channel"
    assert not channel_dir.exists() or not any(channel_dir.glob("*.json"))


def test_migrate_apply_minimal(tmp_path):
    _write_legacy(tmp_path, _minimal_legacy())
    rc = main(["migrate", "--apply", "--target", str(tmp_path)])
    assert rc == 0
    channel_dir = tmp_path / "config" / "channel"
    meta = _read_json(channel_dir / "meta.json")
    content = _read_json(channel_dir / "content.json")
    youtube = _read_json(channel_dir / "youtube.json")
    assert meta["channel"]["name"] == "Test Channel"
    assert content["genre"]["primary"] == "chiptune"
    assert content["tags"]["base"] == ["chiptune"]
    assert youtube["youtube"]["category_id"] == "10"
    # 空セクションは生成されない
    assert not (channel_dir / "analytics.json").exists()
    assert not (channel_dir / "playlists.json").exists()
    assert not (channel_dir / "workflow.json").exists()
    assert not (channel_dir / "audio.json").exists()
    # backup default
    assert (tmp_path / "config" / "channel_config.json.bak").is_file()


def test_migrate_apply_full(tmp_path):
    legacy = _minimal_legacy()
    legacy["youtube_channel"] = {"description": "desc", "keywords": [], "country": "JP"}
    legacy["content_model"] = {"type": "release", "languages": ["en"]}
    legacy["music_engine"] = "suno"
    legacy["analytics"] = {"collection_filter_keywords": ["collection"]}
    legacy["benchmark"] = {"channels": []}
    legacy["playlists"] = {"main": "PL123"}
    legacy["workflow"] = {}
    legacy["audio"] = {"target_duration_min": 30}
    legacy["comments"] = {"enabled": False, "rules": [], "templates": {}}
    _write_legacy(tmp_path, legacy)
    rc = main(["migrate", "--apply", "--target", str(tmp_path)])
    assert rc == 0
    channel_dir = tmp_path / "config" / "channel"
    for name in SECTION_MAP:
        assert (channel_dir / name).is_file(), f"missing {name}"
    workflow = _read_json(channel_dir / "workflow.json")
    assert workflow == {"workflow": {}}
    audio = _read_json(channel_dir / "audio.json")
    assert audio["audio"]["target_duration_min"] == 30
    youtube = _read_json(channel_dir / "youtube.json")
    assert youtube["music_engine"] == "suno"
    assert youtube["content_model"]["type"] == "release"
    meta = _read_json(channel_dir / "meta.json")
    assert meta["youtube_channel"]["country"] == "JP"


def test_migrate_bobble_style(tmp_path):
    legacy = _minimal_legacy()
    legacy["audio"] = {"target_duration_min": 30}
    legacy["music_engine"] = "lyria"
    _write_legacy(tmp_path, legacy)
    rc = main(["migrate", "--apply", "--target", str(tmp_path)])
    assert rc == 0
    channel_dir = tmp_path / "config" / "channel"
    audio = _read_json(channel_dir / "audio.json")
    assert audio["audio"]["target_duration_min"] == 30
    youtube = _read_json(channel_dir / "youtube.json")
    assert youtube["music_engine"] == "lyria"


def test_migrate_rjn_localization_merge_fresh(tmp_path):
    legacy = _minimal_legacy()
    legacy["localization"] = {
        "default_language": "en",
        "supported_languages": ["en", "ja"],
    }
    _write_legacy(tmp_path, legacy)
    rc = main(["migrate", "--apply", "--target", str(tmp_path)])
    assert rc == 0
    loc = _read_json(tmp_path / "config" / LOCALIZATIONS_FILENAME)
    assert loc["default_language"] == "en"
    assert loc["supported_languages"] == ["en", "ja"]


def test_migrate_rjn_localization_merge_match(tmp_path, capsys):
    legacy = _minimal_legacy()
    legacy["localization"] = {
        "default_language": "en",
        "supported_languages": ["en"],
    }
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / LOCALIZATIONS_FILENAME).write_text(
        json.dumps({"default_language": "en", "supported_languages": ["en"]}),
        encoding="utf-8",
    )
    _write_legacy(tmp_path, legacy)
    rc = main(["migrate", "--apply", "--target", str(tmp_path)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "一致" in err or "マージ不要" in err


def test_migrate_rjn_localization_merge_mismatch(tmp_path, capsys):
    legacy = _minimal_legacy()
    legacy["localization"] = {
        "default_language": "en",
        "supported_languages": ["en", "ja"],
    }
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / LOCALIZATIONS_FILENAME).write_text(
        json.dumps({"default_language": "ja", "supported_languages": ["ja"]}),
        encoding="utf-8",
    )
    _write_legacy(tmp_path, legacy)
    rc = main(["migrate", "--apply", "--target", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "一致しません" in err


def test_migrate_unmapped_key_warning(tmp_path, capsys):
    legacy = _minimal_legacy()
    legacy["suno"] = {"workspace_name": "ws"}
    _write_legacy(tmp_path, legacy)
    rc = main(["migrate", "--target", str(tmp_path)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "suno" in err
    assert "未マップ" in err


def test_migrate_unmapped_key_strict(tmp_path):
    legacy = _minimal_legacy()
    legacy["suno"] = {"workspace_name": "ws"}
    _write_legacy(tmp_path, legacy)
    rc = main(["migrate", "--strict", "--apply", "--target", str(tmp_path)])
    assert rc == 1
    channel_dir = tmp_path / "config" / "channel"
    assert not channel_dir.exists() or not any(channel_dir.glob("*.json"))


def test_migrate_backup_default(tmp_path):
    _write_legacy(tmp_path, _minimal_legacy())
    rc = main(["migrate", "--apply", "--target", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "config" / "channel_config.json").is_file()
    assert (tmp_path / "config" / "channel_config.json.bak").is_file()


def test_migrate_no_backup_delete_source(tmp_path):
    _write_legacy(tmp_path, _minimal_legacy())
    rc = main(
        [
            "migrate",
            "--apply",
            "--no-backup",
            "--delete-source",
            "--target",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert not (tmp_path / "config" / "channel_config.json").is_file()
    assert not (tmp_path / "config" / "channel_config.json.bak").is_file()
    assert (tmp_path / "config" / "channel" / "meta.json").is_file()


def test_migrate_refuses_existing_channel_dir(tmp_path, capsys):
    _write_legacy(tmp_path, _minimal_legacy())
    channel_dir = tmp_path / "config" / "channel"
    channel_dir.mkdir(parents=True)
    (channel_dir / "meta.json").write_text("{}", encoding="utf-8")
    rc = main(["migrate", "--apply", "--target", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "既に JSON ファイルが存在" in err


# ----------------------- verify -----------------------


def test_verify_success(tmp_path, capsys):
    _write_legacy(tmp_path, _minimal_legacy())
    assert main(["migrate", "--apply", "--delete-source", "--target", str(tmp_path)]) == 0
    capsys.readouterr()  # clear
    rc = main(["verify", "--target", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, f"verify failed. stdout={out}"
    assert "OK" in out
    assert "Test Channel" in out


def _write_localizations(tmp_path: Path, title_template: str) -> None:
    loc = {
        "supported_languages": ["en"],
        "default_language": "en",
        "languages": {"en": {"title_template": title_template, "description_opening": "Relaxing music."}},
    }
    (tmp_path / "config" / LOCALIZATIONS_FILENAME).write_text(
        json.dumps(loc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_verify_rejects_disallowed_title_template_placeholder(tmp_path, capsys):
    """Issue #1471: channel-import 生成の不正 title_template をアップロード前に検出する。"""
    _write_legacy(tmp_path, _minimal_legacy())
    assert main(["migrate", "--apply", "--delete-source", "--target", str(tmp_path)]) == 0
    _write_localizations(tmp_path, "{axis_label} - {scene_phrase}")
    capsys.readouterr()  # clear
    rc = main(["verify", "--target", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "axis_label" in err  # 不正プレースホルダ名
    assert "scene_phrase" in err  # 許可キー一覧の提示


def test_verify_accepts_allowed_title_template_placeholders(tmp_path, capsys):
    _write_legacy(tmp_path, _minimal_legacy())
    assert main(["migrate", "--apply", "--delete-source", "--target", str(tmp_path)]) == 0
    _write_localizations(tmp_path, "{scene_phrase} | Jazz BGM ({activities})")
    capsys.readouterr()  # clear
    rc = main(["verify", "--target", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, f"verify failed. output={out}"
    assert "OK" in out


# ----------------------- diff -----------------------


def test_diff_detects_unmapped(tmp_path, capsys):
    legacy = _minimal_legacy()
    legacy["suno"] = {"workspace_name": "ws"}
    _write_legacy(tmp_path, legacy)
    rc = main(["diff", "--target", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "(unmapped)" in out
    assert "suno" in out


def test_diff_no_unmapped(tmp_path, capsys):
    _write_legacy(tmp_path, _minimal_legacy())
    rc = main(["diff", "--target", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "(unmapped)" not in out
    assert "meta.json" in out


# ----------------------- _resolve_target_dir -----------------------


def test_resolve_target_dir_explicit(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "channel_config.json").write_text("{}", encoding="utf-8")
    result = _resolve_target_dir(str(tmp_path))
    assert result.samefile(tmp_path)


def test_resolve_target_dir_env(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "channel_config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    result = _resolve_target_dir(None)
    assert result.samefile(tmp_path)


def test_resolve_target_dir_ancestor(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "channel_config.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    result = _resolve_target_dir(None)
    assert result.samefile(tmp_path)


def test_resolve_target_dir_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError):
        _resolve_target_dir(None)


def test_resolve_target_dir_new_structure_cwd(tmp_path, monkeypatch):
    """post-migrate 状態 (config/channel/ のみ) で CWD 解決が成功すること."""
    (tmp_path / "config" / "channel").mkdir(parents=True)
    (tmp_path / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = _resolve_target_dir(None)
    assert result.samefile(tmp_path)


def test_resolve_target_dir_new_structure_ancestor(tmp_path, monkeypatch):
    """新構造のチャンネルディレクトリの子孫から起動しても祖先を辿って解決できること."""
    (tmp_path / "config" / "channel").mkdir(parents=True)
    (tmp_path / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "collections" / "live"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    result = _resolve_target_dir(None)
    assert result.samefile(tmp_path)


def test_resolve_target_dir_error_message_mentions_both_markers(tmp_path, monkeypatch):
    """エラーメッセージが新マーカーと旧マーカーの両方を案内すること."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as exc_info:
        _resolve_target_dir(None)
    msg = str(exc_info.value)
    assert "config/channel/" in msg
    assert "config/channel_config.json" in msg
