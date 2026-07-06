from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.cli import automation_update
from youtube_automation.cli.automation_update import EXIT_DIFF, EXIT_ERROR, EXIT_UP_TO_DATE, main
from youtube_automation.cli.automation_update_refs import Pin, _detect_pin

INLINE_TABLE_PYPROJECT = """\
[project]
name = "deepfocus365"
dependencies = ["youtube-channels-automation"]

[tool.uv.sources]
youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation", tag = "v5.5.0" }
"""

URL_PIN_PYPROJECT = """\
[project]
name = "deepfocus365"
dependencies = [
    "youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@v5.5.0",
]
"""

SSH_URL_PIN_PYPROJECT = """\
[project]
name = "deepfocus365"
dependencies = [
    "youtube-channels-automation @ git+ssh://git@github.com/daiki-beppu/youtube-automation.git@v5.5.0",
]
"""

BRANCH_FOLLOW_PYPROJECT = """\
[project]
name = "deepfocus365"
dependencies = ["youtube-channels-automation"]

[tool.uv.sources]
youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation", branch = "main" }
"""

SHA_PIN_PYPROJECT = """\
[project]
name = "deepfocus365"
dependencies = ["youtube-channels-automation"]

[tool.uv.sources]
youtube-channels-automation = {{ git = "https://github.com/daiki-beppu/youtube-automation", rev = "{sha}" }}
"""

SINGLE_QUOTE_SHA_PIN_PYPROJECT = """\
[project]
name = "deepfocus365"
dependencies = ["youtube-channels-automation"]

[tool.uv.sources]
youtube-channels-automation = {{ git = "https://github.com/daiki-beppu/youtube-automation", rev = '{sha}' }}
"""

_SHA_OLD = "a" * 40
_SHA_NEW = "b" * 40


def _write_repo(tmp_path: Path, pyproject_body: str) -> Path:
    repo = tmp_path / "channel"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(pyproject_body, encoding="utf-8")
    return repo


def _write_uv_lock(repo: Path, sha: str) -> None:
    (repo / "uv.lock").write_text(
        "[[package]]\n"
        'name = "youtube-channels-automation"\n'
        'version = "5.5.15"\n'
        f'source = {{ git = "https://github.com/daiki-beppu/youtube-automation?branch=main#{sha}" }}\n',
        encoding="utf-8",
    )


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """テストから GitHub API へ到達しないことを保証する."""

    def _fail(*args, **kwargs):
        raise AssertionError("テスト中に GitHub API へアクセスしてはならない")

    monkeypatch.setattr(automation_update, "_github_api_get", _fail)


@pytest.fixture
def recorded_commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """apply のサブプロセス実行を記録に置き換える."""
    commands: list[list[str]] = []

    def _record(cmd: list[str], cwd: Path) -> int:
        commands.append(cmd)
        return 0

    monkeypatch.setattr(automation_update, "_run_command", _record)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)
    return commands


# ---------------------------------------------------------------------------
# 実行場所判定 (要件 3)
# ---------------------------------------------------------------------------


def test_check_rejects_upstream_repo(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, '[project]\nname = "youtube-channels-automation"\n')

    assert main(["check", "--target", str(repo)]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "upstream リポ" in err
    assert "下流チャンネルリポジトリ専用" in err


def test_check_rejects_normalized_upstream_name(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, '[project]\nname = "youtube_channels.automation"\n')

    assert main(["check", "--target", str(repo)]) == EXIT_ERROR
    assert "upstream リポ" in capsys.readouterr().err


def test_check_rejects_repo_without_dependency(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, '[project]\nname = "not-a-channel"\ndependencies = []\n')

    assert main(["check", "--target", str(repo)]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "依存として参照するチャンネルリポジトリではありません" in err
    assert "移動先候補の探し方" in err


def test_check_rejects_similar_dependency_name(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(
        tmp_path,
        '[project]\nname = "not-a-channel"\ndependencies = ["youtube-channels-automation-extra>=1"]\n',
    )

    assert main(["check", "--target", str(repo)]) == EXIT_ERROR
    assert "依存として参照するチャンネルリポジトリではありません" in capsys.readouterr().err


def test_check_rejects_registry_reference(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(
        tmp_path,
        '[project]\nname = "deepfocus365"\ndependencies = ["youtube-channels-automation>=5"]\n',
    )

    assert main(["check", "--target", str(repo)]) == EXIT_ERROR
    assert "registry 参照" in capsys.readouterr().err


def test_check_rejects_dependency_table_shape(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(
        tmp_path,
        '[project]\nname = "deepfocus365"\n\n[project.dependencies]\nyoutube-channels-automation = ">=5"\n',
    )

    assert main(["check", "--target", str(repo)]) == EXIT_ERROR

    assert "依存として参照するチャンネルリポジトリではありません" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# pin 形式判定 (要件 1: tag pin / inline table 両対応)
# ---------------------------------------------------------------------------


def test_detect_pin_inline_table_tag() -> None:
    import tomllib

    pin = _detect_pin(tomllib.loads(INLINE_TABLE_PYPROJECT))
    assert pin == Pin("inline-table", "tag", "v5.5.0")


def test_detect_pin_url_tag() -> None:
    import tomllib

    pin = _detect_pin(tomllib.loads(URL_PIN_PYPROJECT))
    assert pin == Pin("url", "tag", "v5.5.0")


def test_detect_pin_branch_follow() -> None:
    import tomllib

    pin = _detect_pin(tomllib.loads(BRANCH_FOLLOW_PYPROJECT))
    assert pin == Pin("inline-table", "branch", "main")


def test_detect_pin_url_without_ref_is_branch_follow() -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = '
        '["youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation.git"]\n'
    )
    assert _detect_pin(pyproject) == Pin("url", "branch", "main")


def test_detect_pin_url_main_ref_is_branch_follow() -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = '
        '["youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@main"]\n'
    )
    assert _detect_pin(pyproject) == Pin("url", "branch", "main")


def test_detect_pin_url_unknown_ref_is_rejected() -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = '
        '["youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@develop"]\n'
    )

    with pytest.raises(automation_update.ConfigError, match="main / 40 桁 sha / vX.Y.Z tag"):
        _detect_pin(pyproject)


def test_detect_pin_inline_branch_other_than_main_is_rejected() -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = ["youtube-channels-automation"]\n'
        "[tool.uv.sources]\n"
        'youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation", '
        'branch = "develop" }\n'
    )

    with pytest.raises(automation_update.ConfigError, match="main / 40 桁 sha / vX.Y.Z tag"):
        _detect_pin(pyproject)


def test_detect_pin_inline_table_rejects_multiple_ref_keys() -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = ["youtube-channels-automation"]\n'
        "[tool.uv.sources]\n"
        'youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation", '
        f'tag = "v5.5.0", rev = "{_SHA_OLD}" }}\n'
    )

    with pytest.raises(automation_update.ConfigError, match="同時指定できません"):
        _detect_pin(pyproject)


def test_detect_pin_rejects_unofficial_inline_git_url() -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = ["youtube-channels-automation"]\n'
        "[tool.uv.sources]\n"
        'youtube-channels-automation = { git = "https://github.com/evil/repo", tag = "v1" }\n'
    )

    with pytest.raises(automation_update.ConfigError, match="official upstream"):
        _detect_pin(pyproject)


@pytest.mark.parametrize(
    "git_url",
    [
        "https://github.com/daiki-beppu/youtube-automation/../../openai/openai-python",
        "https://github.com/daiki-beppu/youtube-automation/tree/main",
        "https://github.com/daiki-beppu/youtube-automation.git/extra",
        "https://evil.example/daiki-beppu/youtube-automation",
    ],
)
def test_detect_pin_rejects_git_url_with_extra_path_or_host(git_url: str) -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = ["youtube-channels-automation"]\n'
        "[tool.uv.sources]\n"
        f'youtube-channels-automation = {{ git = "{git_url}", tag = "v1" }}\n'
    )

    with pytest.raises(automation_update.ConfigError, match="official upstream"):
        _detect_pin(pyproject)


@pytest.mark.parametrize(
    "git_url",
    [
        "https://github.com/daiki-beppu/youtube-automation",
        "https://github.com/daiki-beppu/youtube-automation.git",
        "ssh://git@github.com/daiki-beppu/youtube-automation.git",
        "git@github.com:daiki-beppu/youtube-automation.git",
    ],
)
def test_detect_pin_accepts_canonical_official_git_urls(git_url: str) -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = ["youtube-channels-automation"]\n'
        "[tool.uv.sources]\n"
        f'youtube-channels-automation = {{ git = "{git_url}", tag = "v1.2.3" }}\n'
    )

    assert _detect_pin(pyproject).value == "v1.2.3"


def test_detect_pin_rejects_unofficial_direct_git_url() -> None:
    import tomllib

    pyproject = tomllib.loads(
        '[project]\nname = "x"\ndependencies = ["youtube-channels-automation @ git+https://evil.example/repo@v1"]\n'
    )

    with pytest.raises(automation_update.ConfigError, match="official upstream"):
        _detect_pin(pyproject)


# ---------------------------------------------------------------------------
# check: 差分判定 (要件 1)
# ---------------------------------------------------------------------------


def test_check_inline_tag_pin_up_to_date(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["check", "--target", str(repo), "--tag", "v5.5.0"]) == EXIT_UP_TO_DATE
    assert "✓ 既に最新です" in capsys.readouterr().out


def test_check_inline_tag_pin_diff(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["check", "--target", str(repo), "--tag", "v5.6.0"]) == EXIT_DIFF
    out = capsys.readouterr().out
    assert "tag pin (v5.5.0" in out
    assert "差分あり: v5.5.0 → v5.6.0" in out


def test_check_url_tag_pin_diff(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, URL_PIN_PYPROJECT)

    assert main(["check", "--target", str(repo), "--tag", "v5.6.0"]) == EXIT_DIFF
    assert "URL 直接参照" in capsys.readouterr().out


def test_check_fetches_latest_release_when_tag_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(automation_update, "_fetch_latest_release_tag", lambda: "v9.9.9")

    assert main(["check", "--target", str(repo)]) == EXIT_DIFF
    assert "v9.9.9" in capsys.readouterr().out


def test_check_rejects_invalid_explicit_tag(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["check", "--target", str(repo), "--tag", "not-a-version"]) == EXIT_ERROR

    assert "vX.Y.Z" in capsys.readouterr().err


def test_check_rejects_invalid_latest_release_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(automation_update, "_fetch_latest_release_tag", lambda: "not-a-version")

    assert main(["check", "--target", str(repo)]) == EXIT_ERROR

    assert "vX.Y.Z" in capsys.readouterr().err


def test_check_uses_cwd_when_target_omitted(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.chdir(repo)

    assert main(["check", "--tag", "v5.6.0"]) == EXIT_DIFF
    assert f"実行場所: {repo}" in capsys.readouterr().out


def test_check_branch_follow_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, BRANCH_FOLLOW_PYPROJECT)
    _write_uv_lock(repo, _SHA_OLD)
    monkeypatch.setattr(automation_update, "_fetch_branch_head_sha", lambda branch: _SHA_OLD)

    assert main(["check", "--target", str(repo)]) == EXIT_UP_TO_DATE
    assert "uv.lock が upstream HEAD と一致" in capsys.readouterr().out


def test_check_branch_follow_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, BRANCH_FOLLOW_PYPROJECT)
    _write_uv_lock(repo, _SHA_OLD)
    monkeypatch.setattr(automation_update, "_fetch_branch_head_sha", lambda branch: _SHA_NEW)

    assert main(["check", "--target", str(repo)]) == EXIT_DIFF

    out = capsys.readouterr().out
    assert _SHA_OLD in out
    assert _SHA_NEW in out


def test_check_branch_follow_without_lock_is_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, BRANCH_FOLLOW_PYPROJECT)
    monkeypatch.setattr(automation_update, "_fetch_branch_head_sha", lambda branch: _SHA_NEW)

    assert main(["check", "--target", str(repo)]) == EXIT_DIFF

    out = capsys.readouterr().out
    assert _SHA_NEW in out
    assert "uv.lock に解決済み sha がありません" in out


def test_check_sha_pin_requires_human_decision(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, SHA_PIN_PYPROJECT.format(sha=_SHA_OLD))

    assert main(["check", "--target", str(repo)]) == EXIT_DIFF
    out = capsys.readouterr().out
    assert "sha pin" in out
    assert "--rev" in out


# ---------------------------------------------------------------------------
# apply: pin 書き換えとステップ実行 (要件 2)
# ---------------------------------------------------------------------------


def test_apply_inline_tag_pin_rewrites_and_runs_steps(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'tag = "v5.6.0"' in text
    assert 'tag = "v5.5.0"' not in text
    assert recorded_commands == [
        ["uv", "lock", "--upgrade-package", "youtube-channels-automation"],
        ["uv", "run", "yt-skills", "sync", "--force"],
        ["uv", "run", "yt-skills", "list"],
        ["uv", "run", "yt-config-migrate", "verify", "--target", str(repo)],
    ]
    assert "✓ 追従が完了しました" in capsys.readouterr().out


def test_apply_fetches_latest_release_when_tag_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(automation_update, "_fetch_latest_release_tag", lambda: "v9.9.9")

    assert main(["apply", "--target", str(repo)]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'tag = "v9.9.9"' in text
    assert ["uv", "run", "yt-config-migrate", "verify", "--target", str(repo)] in recorded_commands


def test_apply_rejects_invalid_explicit_tag_without_side_effects(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    before = (repo / "pyproject.toml").read_text(encoding="utf-8")

    assert main(["apply", "--target", str(repo), "--tag", "not-a-version"]) == EXIT_ERROR

    assert "vX.Y.Z" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == before
    assert recorded_commands == []


def test_apply_rejects_invalid_latest_release_tag_without_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recorded_commands: list[list[str]],
    capsys: pytest.CaptureFixture,
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    before = (repo / "pyproject.toml").read_text(encoding="utf-8")
    monkeypatch.setattr(automation_update, "_fetch_latest_release_tag", lambda: "not-a-version")

    assert main(["apply", "--target", str(repo)]) == EXIT_ERROR

    assert "vX.Y.Z" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == before
    assert recorded_commands == []


def test_apply_uses_cwd_when_target_omitted(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.chdir(repo)

    assert main(["apply", "--tag", "v5.6.0"]) == 0

    assert 'tag = "v5.6.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert ["uv", "run", "yt-config-migrate", "verify", "--target", str(repo)] in recorded_commands


def test_apply_url_tag_pin_rewrites(tmp_path: Path, no_network, recorded_commands: list[list[str]]) -> None:
    repo = _write_repo(tmp_path, URL_PIN_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "youtube-automation@v5.6.0" in text
    assert "@v5.5.0" not in text


def test_apply_ssh_url_tag_pin_rewrites_only_ref(
    tmp_path: Path, no_network, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, SSH_URL_PIN_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "git+ssh://git@github.com/daiki-beppu/youtube-automation.git@v5.6.0" in text
    assert "git+ssh://git@v5.6.0" not in text
    assert "@v5.5.0" not in text


def test_apply_same_tag_is_idempotent(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.5.0"]) == 0
    assert 'tag = "v5.5.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "書き換えなし" in capsys.readouterr().out
    assert len(recorded_commands) == 4  # lock / sync / smoke x2 は実行される


def test_apply_branch_follow_skips_rewrite(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, BRANCH_FOLLOW_PYPROJECT)
    before = (repo / "pyproject.toml").read_text(encoding="utf-8")

    assert main(["apply", "--target", str(repo)]) == 0
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == before
    assert "pin 書き換えは不要" in capsys.readouterr().out


def test_apply_tag_pin_rejects_rev_option(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--rev", _SHA_NEW]) == EXIT_ERROR

    assert "--rev は sha pin" in capsys.readouterr().err
    assert 'tag = "v5.5.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert recorded_commands == []


def test_apply_branch_follow_rejects_tag_option(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, BRANCH_FOLLOW_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == EXIT_ERROR

    assert "--tag は tag pin" in capsys.readouterr().err
    assert recorded_commands == []


def test_apply_sha_pin_rejects_tag_option(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, SHA_PIN_PYPROJECT.format(sha=_SHA_OLD))

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == EXIT_ERROR

    assert "--tag は tag pin" in capsys.readouterr().err
    assert _SHA_OLD in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert recorded_commands == []


def test_apply_stops_at_failed_step(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    commands: list[list[str]] = []

    def _fail_on_lock(cmd: list[str], cwd: Path) -> int:
        commands.append(cmd)
        return 1 if cmd[:2] == ["uv", "lock"] else 0

    monkeypatch.setattr(automation_update, "_run_command", _fail_on_lock)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1

    err = capsys.readouterr().err
    assert "'uv lock' で失敗しました" in err
    assert "--allow-dirty" in err
    # 失敗ステップ以降 (sync / smoke check) は実行されない
    assert commands == [["uv", "lock", "--upgrade-package", "youtube-channels-automation"]]
    assert 'tag = "v5.6.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_apply_dirty_worktree_fails_before_any_command(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    commands: list[list[str]] = []
    monkeypatch.setattr(automation_update, "_run_command", lambda cmd, cwd: commands.append(cmd) or 0)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: " M pyproject.toml")

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1

    assert "'git 作業ツリー確認' で失敗しました" in capsys.readouterr().err
    assert commands == []
    # pin も書き換えられていない
    assert 'tag = "v5.5.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_apply_local_fix_diff_requires_explicit_sync_decision(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    commands: list[list[str]] = []
    monkeypatch.setattr(automation_update, "_run_command", lambda cmd, cwd: commands.append(cmd) or 0)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: True)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1

    err = capsys.readouterr().err
    assert "yt-skills diff" in err
    assert "--force-sync" in err
    assert commands == []
    assert 'tag = "v5.5.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_skills_diff_missing_target_is_not_local_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _diff_missing(*args, **kwargs):
        return automation_update.subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout=".claude/skills/suno/SKILL.md: target が存在しません\n",
            stderr="",
        )

    monkeypatch.setattr(automation_update.subprocess, "run", _diff_missing)

    assert automation_update._skills_diff_has_changes(tmp_path) is False


def test_skills_diff_content_change_is_local_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _diff_changed(*args, **kwargs):
        return automation_update.subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout=".claude/skills/suno/SKILL.md: 内容が異なる\n",
            stderr="",
        )

    monkeypatch.setattr(automation_update.subprocess, "run", _diff_changed)

    assert automation_update._skills_diff_has_changes(tmp_path) is True


def test_apply_allow_dirty_skips_worktree_check(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(
        automation_update,
        "_git_status_porcelain",
        lambda root: (_ for _ in ()).throw(AssertionError("--allow-dirty では呼ばれない")),
    )

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--allow-dirty"]) == 0


def test_apply_force_sync_passes_force_flag(tmp_path: Path, no_network, recorded_commands: list[list[str]]) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--force-sync"]) == 0
    assert ["uv", "run", "yt-skills", "sync", "--force"] in recorded_commands


def test_apply_force_sync_bypasses_local_fix_diff_guard(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: True)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--force-sync"]) == 0

    assert ["uv", "run", "yt-skills", "sync", "--force"] in recorded_commands


def test_apply_sync_only_is_allowlist_and_forces_selected_assets(
    tmp_path: Path, no_network, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--sync-only", "lyria", "suno"]) == 0
    assert [
        "uv",
        "run",
        "yt-skills",
        "sync",
        "--asset",
        "skills",
        "--only",
        "lyria",
        "suno",
        "--force",
    ] in recorded_commands
    assert ["uv", "run", "yt-skills", "sync", "--asset", "claude-md", "--force"] in recorded_commands


def test_apply_sync_only_rejects_local_fix_diff_before_side_effects(
    tmp_path: Path,
    no_network,
    monkeypatch: pytest.MonkeyPatch,
    recorded_commands: list[list[str]],
    capsys: pytest.CaptureFixture,
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: True)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--sync-only", "suno"]) == 1

    err = capsys.readouterr().err
    assert "yt-skills diff" in err
    assert "--force-sync" in err
    assert recorded_commands == []
    assert 'tag = "v5.5.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_apply_sync_only_rejects_unknown_skill_before_side_effects(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    before = (repo / "pyproject.toml").read_text(encoding="utf-8")

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--sync-only", "typo-skill"]) == EXIT_ERROR

    assert "同梱版に存在しない skill" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == before
    assert recorded_commands == []


def test_apply_config_migrate_verify_uses_target_even_when_channel_dir_differs(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    other_base = tmp_path / "other"
    other_base.mkdir()
    other_repo = _write_repo(other_base, INLINE_TABLE_PYPROJECT)
    monkeypatch.setenv("CHANNEL_DIR", str(other_repo))

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0

    assert ["uv", "run", "yt-config-migrate", "verify", "--target", str(repo)] in recorded_commands
    assert ["uv", "run", "yt-config-migrate", "verify", "--target", str(other_repo)] not in recorded_commands


def test_apply_unknown_skills_diff_failure_stops_before_side_effects(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    commands: list[list[str]] = []
    monkeypatch.setattr(automation_update, "_run_command", lambda cmd, cwd: commands.append(cmd) or 0)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")

    def _diff_unknown_failure(cmd: list[str], **kwargs):
        assert cmd == ["uv", "run", "yt-skills", "diff"]
        return automation_update.subprocess.CompletedProcess(args=cmd, returncode=9, stdout="", stderr="boom\n")

    monkeypatch.setattr(automation_update.subprocess, "run", _diff_unknown_failure)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1

    err = capsys.readouterr().err
    assert "'yt-skills diff による local fix 確認' で失敗しました" in err
    assert "exit code 9" in err
    assert commands == []
    assert 'tag = "v5.5.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_apply_sha_pin_requires_rev(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, SHA_PIN_PYPROJECT.format(sha=_SHA_OLD))

    assert main(["apply", "--target", str(repo)]) == EXIT_ERROR
    assert "--rev" in capsys.readouterr().err


def test_apply_sha_pin_with_rev_rewrites(tmp_path: Path, no_network, recorded_commands: list[list[str]]) -> None:
    repo = _write_repo(tmp_path, SHA_PIN_PYPROJECT.format(sha=_SHA_OLD))

    assert main(["apply", "--target", str(repo), "--rev", _SHA_NEW]) == 0
    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert _SHA_NEW in text
    assert _SHA_OLD not in text


def test_apply_sha_pin_rejects_invalid_rev_without_rewrite(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, SHA_PIN_PYPROJECT.format(sha=_SHA_OLD))

    assert main(["apply", "--target", str(repo), "--rev", "not-a-sha"]) == EXIT_ERROR

    assert "40 桁の hex sha" in capsys.readouterr().err
    assert _SHA_OLD in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert recorded_commands == []


def test_apply_single_quoted_sha_pin_preserves_quote_style(
    tmp_path: Path, no_network, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, SINGLE_QUOTE_SHA_PIN_PYPROJECT.format(sha=_SHA_OLD))

    assert main(["apply", "--target", str(repo), "--rev", _SHA_NEW]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert f"rev = '{_SHA_NEW}'" in text
    assert _SHA_OLD not in text


def test_apply_rejects_upstream_repo(tmp_path: Path, no_network, capsys: pytest.CaptureFixture) -> None:
    repo = _write_repo(tmp_path, '[project]\nname = "youtube-channels-automation"\n')

    assert main(["apply", "--target", str(repo)]) == EXIT_ERROR
    assert "upstream リポ" in capsys.readouterr().err


def test_apply_rejects_registry_reference_without_side_effects(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(
        tmp_path,
        '[project]\nname = "deepfocus365"\ndependencies = ["youtube-channels-automation>=5"]\n',
    )
    before = (repo / "pyproject.toml").read_text(encoding="utf-8")

    assert main(["apply", "--target", str(repo)]) == EXIT_ERROR

    assert "registry 参照" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == before
    assert recorded_commands == []


def test_apply_external_command_start_failure_is_step_failure(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)

    def _fail_to_start(*args, **kwargs):
        raise FileNotFoundError("missing executable")

    monkeypatch.setattr(automation_update.subprocess, "run", _fail_to_start)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1
    err = capsys.readouterr().err
    assert "'uv lock' で失敗しました" in err
    assert "missing executable" in err


def test_apply_pyproject_write_failure_is_step_failure(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)

    original_write_text = Path.write_text

    def _write_text(self: Path, *args, **kwargs):
        if self == repo / "pyproject.toml":
            raise OSError("disk full")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _write_text)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1

    err = capsys.readouterr().err
    assert "'pyproject.toml の pin 書き換え' で失敗しました" in err
    assert "disk full" in err
