from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from youtube_automation.commands.system.skills_sync import _migrate_config as migrate_config
from youtube_automation.commands.system.skills_sync import build_parser, main

TEST_MIGRATIONS = {
    "masterup": migrate_config.SkillConfigMigration("music", "master"),
    "suno": migrate_config.SkillConfigMigration("music", "prompt"),
}


@pytest.fixture
def channel_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(migrate_config, "SKILL_CONFIG_MIGRATIONS", TEST_MIGRATIONS)
    config_dir = tmp_path / "channel" / "config" / "skills"
    config_dir.mkdir(parents=True)
    return tmp_path / "channel"


def _write_config(channel_dir: Path, name: str, data: dict[str, object]) -> Path:
    path = channel_dir / "config" / "skills" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _read_config(channel_dir: Path, name: str) -> dict[str, object]:
    path = channel_dir / "config" / "skills" / f"{name}.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_migrate_config_parser_requires_channel_dir_and_supports_dry_run() -> None:
    args = build_parser().parse_args(["migrate-config", "--channel-dir", "/tmp/channel", "--dry-run"])

    assert args.channel_dir == Path("/tmp/channel")
    assert args.dry_run is True


def test_migrate_config_dry_run_reports_destination_without_changes(
    channel_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write_config(channel_dir, "suno", {"model": "v5"})
    original = source.read_bytes()

    assert main(["migrate-config", "--channel-dir", str(channel_dir), "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "suno.yaml -> music.yaml::prompt" in output
    assert "prompt:" in output
    assert source.read_bytes() == original
    assert not (channel_dir / "config" / "skills" / "music.yaml").exists()
    assert list((channel_dir / "config" / "skills").glob(".*.tmp")) == []


def test_migrate_config_apply_aggregates_sources_into_namespaced_sections(channel_dir: Path) -> None:
    suno = _write_config(channel_dir, "suno", {"model": "v5"})
    masterup = _write_config(channel_dir, "masterup", {"target_lufs": -14})

    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 0

    assert _read_config(channel_dir, "music") == {
        "master": {"target_lufs": -14},
        "prompt": {"model": "v5"},
    }
    assert not suno.exists()
    assert not masterup.exists()


def test_migrate_config_is_idempotent_after_apply(channel_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_config(channel_dir, "suno", {"model": "v5"})
    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 0
    migrated = (channel_dir / "config" / "skills" / "music.yaml").read_bytes()
    capsys.readouterr()

    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 0

    assert (channel_dir / "config" / "skills" / "music.yaml").read_bytes() == migrated
    assert "移行対象はありません" in capsys.readouterr().out


def test_migrate_config_warns_about_unmapped_orphan_without_modifying_it(
    channel_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    orphan = _write_config(channel_dir, "streaming-description", {"enabled": True})
    original = orphan.read_bytes()

    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 0

    assert "孤児 skill-config: streaming-description.yaml" in capsys.readouterr().out
    assert orphan.read_bytes() == original


def test_migrate_config_replace_failure_preserves_source_and_destination(
    channel_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write_config(channel_dir, "suno", {"model": "v5"})
    destination = _write_config(channel_dir, "music", {"existing": {"enabled": True}})
    source_before = source.read_bytes()
    destination_before = destination.read_bytes()

    def fail_replace(_source: str | os.PathLike[str], _destination: str | os.PathLike[str]) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(migrate_config.os, "replace", fail_replace)

    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 1

    assert "skill-config 移行に失敗" in capsys.readouterr().err
    assert source.read_bytes() == source_before
    assert destination.read_bytes() == destination_before


def test_migrate_config_rolls_back_already_replaced_destination_when_later_replace_fails(
    channel_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations = {
        "loop-video": migrate_config.SkillConfigMigration("thumbnail", "loop"),
        "suno": migrate_config.SkillConfigMigration("music", "prompt"),
    }
    monkeypatch.setattr(migrate_config, "SKILL_CONFIG_MIGRATIONS", migrations)
    loop_source = _write_config(channel_dir, "loop-video", {"engine": "veo"})
    suno_source = _write_config(channel_dir, "suno", {"model": "v5"})
    thumbnail = _write_config(channel_dir, "thumbnail", {"existing": True})
    music = _write_config(channel_dir, "music", {"existing": True})
    originals = {path: path.read_bytes() for path in (loop_source, suno_source, thumbnail, music)}
    real_replace = os.replace
    replace_count = 0

    def fail_second_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("injected second replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(migrate_config.os, "replace", fail_second_replace)

    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 1
    assert all(path.read_bytes() == payload for path, payload in originals.items())


def test_migrate_config_refuses_to_overwrite_different_existing_section(
    channel_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write_config(channel_dir, "suno", {"model": "v5"})
    destination = _write_config(channel_dir, "music", {"prompt": {"model": "v4"}})
    source_before = source.read_bytes()
    destination_before = destination.read_bytes()

    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 1

    assert "移行先の節が既存内容と衝突" in capsys.readouterr().err
    assert source.read_bytes() == source_before
    assert destination.read_bytes() == destination_before


def test_migrate_config_refuses_to_overwrite_different_existing_root(
    channel_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        migrate_config,
        "SKILL_CONFIG_MIGRATIONS",
        {"collection-ideate": migrate_config.SkillConfigMigration("wf-new", None)},
    )
    source = _write_config(channel_dir, "collection-ideate", {"freshness_days": 7})
    destination = _write_config(channel_dir, "wf-new", {"freshness_days": 3})
    source_before = source.read_bytes()
    destination_before = destination.read_bytes()

    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 1

    assert "移行先に既存内容があります" in capsys.readouterr().err
    assert source.read_bytes() == source_before
    assert destination.read_bytes() == destination_before


def test_production_cli_exposes_suno_to_music_prompt_migration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    channel_dir = tmp_path / "channel"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    source = _write_config(channel_dir, "suno", {"model": "v5"})
    assert main(["migrate-config", "--channel-dir", str(channel_dir), "--dry-run"]) == 0

    assert "suno.yaml -> music.yaml::prompt" in capsys.readouterr().out
    assert source.is_file()
    assert not (channel_dir / "config" / "skills" / "music.yaml").exists()


def test_production_cli_migrates_consolidated_skill_configs_without_orphans(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    channel_dir = tmp_path / "channel"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    sources = {
        "collection-ideate": {"freshness_days": 7},
        "loop-video": {"enabled": False},
        "masterup": {"audio": {"target_duration_min": 60}},
        "lyria": {"model": "lyria-3"},
        "benchmark": {"scan_recent": 150},
    }
    for name, data in sources.items():
        _write_config(channel_dir, name, data)

    assert main(["migrate-config", "--channel-dir", str(channel_dir)]) == 0

    assert _read_config(channel_dir, "wf-new") == sources["collection-ideate"]
    assert _read_config(channel_dir, "thumbnail")["loop"] == sources["loop-video"]
    assert _read_config(channel_dir, "music")["master"] == sources["masterup"]
    assert _read_config(channel_dir, "music")["generate"] == sources["lyria"]
    assert _read_config(channel_dir, "channel-research")["benchmark"] == sources["benchmark"]
    assert all(not (channel_dir / "config" / "skills" / f"{name}.yaml").exists() for name in sources)
    assert "孤児 skill-config" not in capsys.readouterr().out
