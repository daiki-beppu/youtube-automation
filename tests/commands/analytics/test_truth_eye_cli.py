from __future__ import annotations

import json
import subprocess

import pytest
import yaml

from youtube_automation.commands.analytics.truth_eye import main
from youtube_automation.domains.analytics.truth_eye import VIEWPOINTS


def _draft() -> str:
    rows = ["| 観点 ID | 伸びた側 | 伸びなかった側 |", "|---|---|---|"]
    rows.extend(f"| {item.id} | winner | loser |" for item in VIEWPOINTS)
    return "\n".join(rows) + "\n## 抽象化\nprinciple\n## 再生数差への寄与順位\n1. V01\n2. V02\n3. V03\n"


def _write_pair(path):
    path.write_text(
        json.dumps(
            {
                "channel": "reference",
                "winner": {
                    "video_id": "win",
                    "title": "W",
                    "views": 10,
                    "published_at": "2026-01-01",
                    "duration": "PT1M",
                },
                "loser": {
                    "video_id": "lose",
                    "title": "L",
                    "views": 1,
                    "published_at": "2026-01-01",
                    "duration": "PT1M",
                },
            }
        ),
        encoding="utf-8",
    )


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _init_git_repo(repo):
    _git(repo, "init")
    _git(repo, "config", "user.name", "Truth Eye Test")
    _git(repo, "config", "user.email", "truth-eye@example.com")
    tracked = repo / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "--", "tracked.txt")
    _git(repo, "commit", "-m", "initial")


def test_seal_failure_prints_missing_items_as_json(tmp_path, capsys):
    pair = tmp_path / "pair.json"
    _write_pair(pair)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft().replace("| V07 | winner | loser |\n", ""), encoding="utf-8")

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert output == {"ok": False, "missing": ["V07"]}
    assert draft.exists()


def test_seal_commits_only_generated_record_and_sealed_file(tmp_path, capsys):
    _init_git_repo(tmp_path)
    pair = tmp_path / "pair.json"
    _write_pair(pair)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["committed"] is True
    assert output["commit"] == _git(tmp_path, "rev-parse", "--short", "HEAD")
    assert _git(tmp_path, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        f"docs/benchmarks/training/{output['record'].rsplit('/', 1)[1]}",
        f"docs/benchmarks/training/{output['sealed'].rsplit('/', 1)[1]}",
    ]
    stem = output["record"].rsplit("/", 1)[1].removesuffix(".md")
    assert _git(tmp_path, "log", "-1", "--pretty=%s") == f"docs(truth-eye): 訓練記録を封印する {stem}"
    assert set(_git(tmp_path, "status", "--short").splitlines()) == {"?? pair.json"}


@pytest.mark.parametrize("staged", [False, True])
def test_seal_skips_commit_when_other_tracked_file_is_dirty(tmp_path, capsys, staged):
    _init_git_repo(tmp_path)
    before = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    if staged:
        _git(tmp_path, "add", "--", "tracked.txt")
    pair = tmp_path / "pair.json"
    _write_pair(pair)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["committed"] is False
    assert output["changed_files"] == ["tracked.txt"]
    assert "未コミット変更" in output["reason"]
    assert _git(tmp_path, "rev-parse", "HEAD") == before


def test_seal_reports_both_sides_of_a_renamed_tracked_file(tmp_path, capsys):
    _init_git_repo(tmp_path)
    before = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "mv", "tracked.txt", "renamed.txt")
    pair = tmp_path / "pair.json"
    _write_pair(pair)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["committed"] is False
    assert output["changed_files"] == ["renamed.txt", "tracked.txt"]
    assert _git(tmp_path, "rev-parse", "HEAD") == before


def test_seal_reports_non_ascii_dirty_path_verbatim(tmp_path, capsys):
    _init_git_repo(tmp_path)
    tracked = tmp_path / "日本語 ノート.md"
    tracked.write_text("clean\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "日本語 ノート.md")
    _git(tmp_path, "commit", "-m", "add note")
    tracked.write_text("dirty\n", encoding="utf-8")
    pair = tmp_path / "pair.json"
    _write_pair(pair)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["committed"] is False
    assert output["changed_files"] == ["日本語 ノート.md"]


def test_seal_succeeds_outside_git_repository(tmp_path, capsys):
    pair = tmp_path / "pair.json"
    _write_pair(pair)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ok"] is True
    assert output["committed"] is False
    assert "Git リポジトリ" in output["reason"]


def test_seal_succeeds_when_git_identity_is_missing(tmp_path, capsys):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "")
    _git(tmp_path, "config", "user.email", "")
    pair = tmp_path / "pair.json"
    _write_pair(pair)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["committed"] is False
    assert "identity" in output["reason"]
    assert _git(tmp_path, "status", "--short").splitlines() == ["?? docs/", "?? pair.json"]


def test_seal_succeeds_when_git_execution_raises_os_error(tmp_path, capsys, monkeypatch):
    pair = tmp_path / "pair.json"
    _write_pair(pair)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")
    monkeypatch.setattr(
        "youtube_automation.infrastructure.vcs.training_commit.run_git",
        lambda *_args: (_ for _ in ()).throw(PermissionError("git is not executable")),
    )

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ok"] is True
    assert output["committed"] is False
    assert "Git の実行に失敗" in output["reason"]


def test_verify_cli_returns_nonzero_and_hashes_after_tamper(tmp_path, capsys):
    sealed = tmp_path / "record.sealed.md"
    sealed.write_text("changed", encoding="utf-8")
    record = tmp_path / "record.md"
    record.write_text("---\nsealed:\n  path: record.sealed.md\n  sha256: deadbeef\n---\n", encoding="utf-8")

    exit_code = main(["verify", str(record)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert output["ok"] is False
    assert output["expected"] == "deadbeef"
    assert len(output["actual"]) == 64


def test_status_cli_returns_training_summary(tmp_path, capsys):
    training = tmp_path / "docs/benchmarks/training"
    training.mkdir(parents=True)
    metadata = {
        "schema_version": 1,
        "menu": "thumbnail",
        "channel": "reference",
        "pair": {},
        "sealed": {},
        "next_try": None,
    }
    (training / "20260901-thumbnail-reference-win.md").write_text(
        f"---\n{yaml.safe_dump(metadata, sort_keys=False)}---\n\n"
        "## Phase 0\n\nprepared\n\n## Phase 1\n\n\n## Phase 2\n\n\n## Phase 3\n\n\n"
        "## Phase 4\n\n\n## Phase 5\n",
        encoding="utf-8",
    )

    exit_code = main(["status", "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["incomplete_count"] == 1
    assert output["incomplete"][0]["resume_phase"] == 1
