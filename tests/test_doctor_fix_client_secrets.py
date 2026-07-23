"""yt-doctor --fix-client-secrets の公開 CLI 契約テスト。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from youtube_automation.cli import doctor


@pytest.fixture(autouse=True)
def _project_override(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "target-project")


def _write_client_secret(path: Path, *, project_id: str, client_id: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "installed": {
            "client_id": client_id or f"{project_id}.apps.googleusercontent.com",
            "client_secret": "secret",
            "project_id": project_id,
            "redirect_uris": ["http://localhost"],
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_fix_moves_latest_matching_download_through_public_cli(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    downloads = home / "Downloads"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    older = downloads / "client_secret_older.json"
    selected = downloads / "client_secret_selected.json"
    mismatch = downloads / "client_secret_other.json"
    _write_client_secret(older, project_id="target-project")
    expected = _write_client_secret(
        selected,
        project_id="target-project",
        client_id="selected.apps.googleusercontent.com",
    )
    _write_client_secret(mismatch, project_id="other-project")
    os.utime(older, (1, 1))
    os.utime(selected, (2, 2))
    os.utime(mismatch, (3, 3))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    original_glob = Path.glob

    def enumerate_selected_before_older(path: Path, pattern: str):
        if path == downloads and pattern == "client_secret*.json":
            return iter((selected, mismatch, older))
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", enumerate_selected_before_older)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    destination = channel_dir / "auth" / "client_secrets.json"
    assert code == 0
    assert json.loads(destination.read_text(encoding="utf-8")) == expected
    assert not selected.exists()
    assert older.exists()
    assert mismatch.exists()
    assert f"{selected} を {destination} へ移動しました" in capsys.readouterr().out


def test_fix_without_downloads_candidate_exits_nonzero_with_download_guidance(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert "client_secret*.json が見つかりません" in output
    assert "Google Cloud Console" in output
    assert "Download JSON" in output
    assert not (channel_dir / "auth" / "client_secrets.json").exists()


def test_fix_rejects_invalid_and_mismatched_candidates_with_details(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    downloads = home / "Downloads"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    malformed = downloads / "client_secret_malformed.json"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("{not-json", encoding="utf-8")
    no_installed = downloads / "client_secret_web.json"
    no_installed.write_text(json.dumps({"web": {}}), encoding="utf-8")
    missing_key = downloads / "client_secret_missing.json"
    missing_key.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client",
                    "project_id": "target-project",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )
    mismatch = downloads / "client_secret_other.json"
    _write_client_secret(mismatch, project_id="other-project")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert f"{malformed}: JSON 読み込み失敗" in output
    assert f"{no_installed}: installed セクションがありません" in output
    assert f"{missing_key}: 必須キー不足: client_secret" in output
    assert f"{mismatch}: project_id が不一致 (other-project != target-project)" in output
    assert malformed.exists()
    assert no_installed.exists()
    assert missing_key.exists()
    assert mismatch.exists()
    assert not (channel_dir / "auth" / "client_secrets.json").exists()


def test_fix_reports_candidate_read_failure_and_preserves_source(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_unreadable.json"
    _write_client_secret(source, project_id="target-project")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    original_open = doctor.os.open

    def fail_candidate_read(path, flags, *args, **kwargs):
        if Path(path) == source:
            raise OSError("permission denied")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(doctor.os, "open", fail_candidate_read)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert f"{source}: ファイル読み込み失敗: permission denied" in output
    assert source.exists()
    assert not (channel_dir / "auth" / "client_secrets.json").exists()


def test_fix_rejects_non_object_json_with_details(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_array.json"
    source.parent.mkdir(parents=True)
    source.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert f"{source}: JSON object ではありません" in output
    assert source.exists()
    assert not (channel_dir / "auth" / "client_secrets.json").exists()


def test_fix_reports_mtime_failure_and_preserves_source(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_target.json"
    _write_client_secret(source, project_id="target-project")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    original_fstat = doctor.os.fstat

    def fail_candidate_stat(descriptor: int):
        metadata = original_fstat(descriptor)
        if metadata.st_ino == source.stat().st_ino:
            raise OSError("candidate disappeared")
        return metadata

    monkeypatch.setattr(doctor.os, "fstat", fail_candidate_stat)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert f"{source}: 更新時刻の取得に失敗: candidate disappeared" in output
    assert source.exists()
    assert not (channel_dir / "auth" / "client_secrets.json").exists()


def test_fix_rejects_symlink_and_non_file_source_candidates(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    downloads = home / "Downloads"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    link_target = tmp_path / "client_secret_target.json"
    expected = _write_client_secret(link_target, project_id="target-project")
    source_symlink = downloads / "client_secret_symlink.json"
    source_symlink.parent.mkdir(parents=True)
    source_symlink.symlink_to(link_target)
    source_directory = downloads / "client_secret_directory.json"
    source_directory.mkdir()
    source_fifo = downloads / "client_secret_fifo.json"
    os.mkfifo(source_fifo)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert f"{source_symlink}: 通常ファイルではありません" in output
    assert f"{source_directory}: 通常ファイルではありません" in output
    assert f"{source_fifo}: 通常ファイルではありません" in output
    assert source_symlink.is_symlink()
    assert source_symlink.readlink() == link_target
    assert json.loads(link_target.read_text(encoding="utf-8")) == expected
    assert source_directory.is_dir()
    assert source_fifo.exists()
    assert not (channel_dir / "auth" / "client_secrets.json").exists()


def test_fix_skips_existing_destination_without_overwriting(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    source = home / "Downloads" / "client_secret_new.json"
    _write_client_secret(source, project_id="target-project")
    destination = channel_dir / "auth" / "client_secrets.json"
    existing = _write_client_secret(destination, project_id="existing-project")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    assert code == 0
    assert json.loads(destination.read_text(encoding="utf-8")) == existing
    assert source.exists()
    assert f"{destination} は既に存在するためスキップしました" in capsys.readouterr().out


def test_fix_rejects_existing_non_file_destination(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_new.json"
    _write_client_secret(source, project_id="target-project")
    destination = channel_dir / "auth" / "client_secrets.json"
    destination.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    assert code != 0
    assert destination.is_dir()
    assert source.exists()
    assert f"{destination} は通常ファイルではないため移動できません" in capsys.readouterr().out


def test_fix_rejects_dangling_symlink_destination_without_overwriting(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_new.json"
    _write_client_secret(source, project_id="target-project")
    destination = channel_dir / "auth" / "client_secrets.json"
    destination.parent.mkdir(parents=True)
    link_target = destination.parent / "missing-client-secrets.json"
    destination.symlink_to(link_target)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    assert code != 0
    assert destination.is_symlink()
    assert destination.readlink() == link_target
    assert source.exists()
    assert f"{destination} は通常ファイルではないため移動できません" in capsys.readouterr().out


def test_fix_does_not_overwrite_destination_created_during_install(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_target.json"
    _write_client_secret(source, project_id="target-project")
    destination = channel_dir / "auth" / "client_secrets.json"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    original_open = doctor.os.open
    competing = {"installed": {"project_id": "competing-project"}}

    def create_destination_then_open(path, flags, *args, **kwargs):
        if Path(path) == destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(competing), encoding="utf-8")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(doctor.os, "open", create_destination_then_open)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    assert code != 0
    assert json.loads(destination.read_text(encoding="utf-8")) == competing
    assert source.exists()
    assert "既に存在するため移動できません" in capsys.readouterr().out


def test_fix_rejects_source_replaced_after_validation(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_target.json"
    _write_client_secret(source, project_id="target-project")
    replacement_target = tmp_path / "replacement.json"
    replacement = _write_client_secret(replacement_target, project_id="target-project")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    original_rename = doctor.os.rename

    def replace_source_then_rename(src, dst):
        source.unlink()
        source.symlink_to(replacement_target)
        return original_rename(src, dst)

    monkeypatch.setattr(doctor.os, "rename", replace_source_then_rename)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    assert code != 0
    assert source.is_symlink()
    assert json.loads(replacement_target.read_text(encoding="utf-8")) == replacement
    assert not (channel_dir / "auth" / "client_secrets.json").exists()
    assert "検査後に変更されたため移動できません" in capsys.readouterr().out


def test_fix_preserves_destination_replaced_during_install(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_target.json"
    _write_client_secret(source, project_id="target-project")
    destination = channel_dir / "auth" / "client_secrets.json"
    competing = {"installed": {"project_id": "competing-project"}}
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    def replace_destination(_descriptor: int):
        destination.unlink()
        destination.write_text(json.dumps(competing), encoding="utf-8")

    monkeypatch.setattr(doctor.os, "fsync", replace_destination)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert source.exists()
    assert json.loads(destination.read_text(encoding="utf-8")) == competing
    assert "作成した移動先が置き換えられたため移動できません" in output
    assert "destination rollback 失敗: 作成した移動先が置き換えられたため削除しません" in output


def test_fix_reports_staging_creation_failure_and_preserves_source(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_target.json"
    _write_client_secret(source, project_id="target-project")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(doctor.tempfile, "mkdtemp", lambda **_kwargs: (_ for _ in ()).throw(OSError("no space")))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    assert code != 0
    assert source.exists()
    assert not (channel_dir / "auth" / "client_secrets.json").exists()
    assert f"{source} の固定準備に失敗: no space" in capsys.readouterr().out


def test_fix_preserves_completed_move_when_empty_staging_cleanup_fails(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_target.json"
    expected = _write_client_secret(source, project_id="target-project")
    destination = channel_dir / "auth" / "client_secrets.json"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    original_rmdir = Path.rmdir

    def fail_staging_cleanup(path: Path):
        if path.name.startswith(".yt-doctor-client-secret-"):
            raise OSError("directory busy")
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", fail_staging_cleanup)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    assert code == 0
    assert not source.exists()
    assert json.loads(destination.read_text(encoding="utf-8")) == expected
    assert "staging cleanup 失敗: directory busy" in capsys.readouterr().out


def test_fix_move_failure_exits_nonzero_and_reports_error(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_target.json"
    _write_client_secret(source, project_id="target-project")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    original_open = doctor.os.open

    def fail_destination_open(path, flags, *args, **kwargs):
        if Path(path) == channel_dir / "auth" / "client_secrets.json":
            raise OSError("disk error")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(doctor.os, "open", fail_destination_open)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert "client_secrets.json への移動に失敗: disk error" in output
    assert source.exists()
    assert not (channel_dir / "auth" / "client_secrets.json").exists()


def test_fix_rolls_back_empty_destination_when_fstat_fails_after_creation(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_target.json"
    expected = _write_client_secret(source, project_id="target-project")
    destination = channel_dir / "auth" / "client_secrets.json"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    original_fstat = doctor.os.fstat

    def fail_destination_fstat(descriptor: int):
        metadata = original_fstat(descriptor)
        if destination.exists() and metadata.st_ino == destination.lstat().st_ino:
            raise OSError("destination fstat failed")
        return metadata

    monkeypatch.setattr(doctor.os, "fstat", fail_destination_fstat)

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    output = capsys.readouterr().out
    assert code != 0
    assert "client_secrets.json への移動に失敗: destination fstat failed" in output
    assert json.loads(source.read_text(encoding="utf-8")) == expected
    assert not destination.exists()


def test_fix_without_target_project_rejects_projectless_candidate(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    source = home / "Downloads" / "client_secret_without_project.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client",
                    "client_secret": "secret",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    code = doctor.main(["--fix-client-secrets", "--target", str(channel_dir)])

    assert code != 0
    assert "対象チャンネルの GCP project_id を特定できません" in capsys.readouterr().out
    assert source.exists()
    assert not (channel_dir / "auth" / "client_secrets.json").exists()
