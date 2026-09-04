from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from youtube_automation.commands.system import automation_update
from youtube_automation.commands.system.automation_update import EXIT_DIFF, EXIT_ERROR, EXIT_UP_TO_DATE, main
from youtube_automation.commands.system.automation_update_refs import Pin, _detect_pin

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
    config_dir = repo / "config" / "channel"
    config_dir.mkdir(parents=True)
    (config_dir / "meta.json").write_text(
        json.dumps(
            {
                "channel": {
                    "name": "Test Channel",
                    "short": "test",
                    "youtube_handle": "@test",
                    "url": "https://youtube.com/@test",
                }
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "bgm", "style": "ambient", "context": "study"},
                "tags": {"base": ["bgm"], "themes": {}},
                "descriptions": {
                    "opening": "Relaxing {style}.",
                    "perfect_for": ["Study"],
                    "hashtags": ["#bgm"],
                },
                "title": {"template": "{theme} bgm"},
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "youtube.json").write_text(
        json.dumps(
            {
                "youtube": {
                    "category_id": "10",
                    "privacy_status": "public",
                    "language": "ja",
                }
            }
        ),
        encoding="utf-8",
    )
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
    monkeypatch.setattr(automation_update, "_check_channel_config", lambda root: "config/channel/ ロード成功")
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)
    return commands


def _subcommand_help(command: str, capsys: pytest.CaptureFixture) -> str:
    with pytest.raises(SystemExit) as exc_info:
        main([command, "--help"])

    assert exc_info.value.code == 0
    return " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("command", ["check", "apply"])
def test_subcommand_help_explains_target_resolution(command: str, capsys: pytest.CaptureFixture) -> None:
    help_text = _subcommand_help(command, capsys)

    assert "下流チャンネルリポジトリのルート" in help_text
    assert "省略時は CWD から親方向へ自動解決" in help_text


def test_check_help_explains_tag_pin_comparison(capsys: pytest.CaptureFixture) -> None:
    help_text = _subcommand_help("check", capsys)

    assert "tag pin 専用" in help_text
    assert "vX.Y.Z 形式" in help_text
    assert "省略時は upstream の最新 stable release" in help_text


def test_apply_help_explains_pin_specific_revision_inputs(capsys: pytest.CaptureFixture) -> None:
    help_text = _subcommand_help("apply", capsys)

    assert "tag pin 専用" in help_text
    assert "vX.Y.Z 形式" in help_text
    assert "省略時は upstream の最新 stable release" in help_text
    assert "sha pin 専用" in help_text
    assert "40 桁の hex SHA" in help_text
    assert "sha pin では必須" in help_text


def test_apply_help_explains_safety_flag_scope(capsys: pytest.CaptureFixture) -> None:
    help_text = _subcommand_help("apply", capsys)

    assert "local fix の破棄を承認済み" in help_text
    assert "local fix guard だけを bypass" in help_text
    assert "配布済み skill 名を 1 件以上指定" in help_text
    assert "skills asset の指定スキルと claude-md asset" in help_text
    assert "local fix guard は既定で維持" in help_text
    assert "全 asset 同期時" in help_text
    assert "--sync-only では使用しない" in help_text
    assert "省略時は新規 hook だけ追加しない" in help_text
    assert "作業ツリーの clean guard だけを bypass" in help_text
    assert "それ単独では local fix guard は維持" in help_text


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


def test_fetch_latest_release_tag_ignores_newer_extension_release(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _releases(path: str) -> object:
        calls.append(path)
        return [
            {"tag_name": "ext-v0.2.5", "published_at": "2026-07-10T11:05:00Z"},
            {"tag_name": "v5.5.17", "published_at": "2026-07-10T10:50:00Z"},
            {"tag_name": "v5.5.16", "published_at": "2026-07-09T10:50:00Z"},
        ]

    monkeypatch.setattr(automation_update, "_github_api_get", _releases)

    assert automation_update._fetch_latest_release_tag() == "v5.5.17"
    assert calls == ["repos/daiki-beppu/youtube-automation/releases?per_page=100&page=1"]


def test_fetch_latest_release_tag_uses_publish_time_not_response_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        automation_update,
        "_github_api_get",
        lambda path: [
            {"tag_name": "v5.5.16", "published_at": "2026-07-09T10:50:00Z"},
            {"tag_name": "v5.5.17", "published_at": "2026-07-10T10:50:00Z"},
        ],
    )

    assert automation_update._fetch_latest_release_tag() == "v5.5.17"


def test_fetch_latest_release_tag_fails_when_only_extension_releases_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        automation_update,
        "_github_api_get",
        lambda path: [{"tag_name": "ext-v0.2.5", "published_at": "2026-07-10T11:05:00Z"}],
    )

    with pytest.raises(automation_update.ConfigError, match="本体の stable release tag"):
        automation_update._fetch_latest_release_tag()


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
    assert ["uv", "run", "yt-skills", "list"] in recorded_commands


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
    assert ["uv", "run", "yt-skills", "list"] in recorded_commands


def test_apply_url_tag_pin_rewrites(tmp_path: Path, no_network, recorded_commands: list[list[str]]) -> None:
    repo = _write_repo(tmp_path, URL_PIN_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "youtube-automation@v5.6.0" in text
    assert "@v5.5.0" not in text


def test_apply_url_tag_pin_ignores_optional_dependency_before_active_project_dependency(
    tmp_path: Path, no_network, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(
        tmp_path,
        """\
[project.optional-dependencies]
dev = [
    "youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@v5.4.0",
]

[project]
name = "deepfocus365"
dependencies = [
    # "youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@v5.3.0",
    "youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@v5.5.0",
]
""",
    )

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "youtube-automation@v5.4.0" in text
    assert "youtube-automation@v5.3.0" in text
    assert "youtube-automation@v5.6.0" in text
    assert "youtube-automation@v5.5.0" not in text


def test_apply_url_tag_pin_rejects_ambiguous_active_dependency_without_changes(
    tmp_path: Path,
    no_network,
    recorded_commands: list[list[str]],
    capsys: pytest.CaptureFixture,
) -> None:
    dependency = "youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@v5.5.0"
    repo = _write_repo(
        tmp_path,
        f'[project]\nname = "deepfocus365"\ndependencies = [\n    "{dependency}",\n    "{dependency}",\n]\n',
    )
    pyproject = repo / "pyproject.toml"
    before = pyproject.read_bytes()
    pin = _detect_pin(automation_update._load_pyproject(pyproject))

    with pytest.raises(automation_update.ConfigError, match="一意に特定できない"):
        automation_update._rewrite_pin(before.decode("utf-8"), pin, "v5.6.0")

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1

    assert "一意に特定できない" in capsys.readouterr().err
    assert pyproject.read_bytes() == before
    assert recorded_commands == []


def test_apply_ssh_url_tag_pin_rewrites_only_ref(
    tmp_path: Path, no_network, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, SSH_URL_PIN_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "git+ssh://git@github.com/daiki-beppu/youtube-automation.git@v5.6.0" in text
    assert "git+ssh://git@v5.6.0" not in text
    assert "@v5.5.0" not in text


def test_apply_inline_table_tag_pin_ignores_commented_source_before_active_entry(
    tmp_path: Path, no_network, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(
        tmp_path,
        """\
[project]
name = "deepfocus365"
dependencies = ["youtube-channels-automation"]

[tool.uv.sources]
# youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation", tag = "v5.4.0" }
youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation", tag = "v5.5.0" }
""",
    )

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0

    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'tag = "v5.4.0"' in text
    assert 'tag = "v5.6.0"' in text
    assert 'tag = "v5.5.0"' not in text


def test_apply_same_tag_is_idempotent(
    tmp_path: Path, no_network, recorded_commands: list[list[str]], capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.5.0"]) == 0
    assert 'tag = "v5.5.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "書き換えなし" in capsys.readouterr().out
    assert len(recorded_commands) == 3  # lock / sync / smoke check は実行される


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


def test_git_status_porcelain_ignores_untracked_files(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "untracked.txt").write_text("local\n", encoding="utf-8")

    assert automation_update._git_status_porcelain(repo) == ""

    subprocess.run(["git", "add", "pyproject.toml"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
        cwd=repo,
        check=True,
    )
    (repo / "pyproject.toml").write_text(INLINE_TABLE_PYPROJECT + "\n# changed\n", encoding="utf-8")

    assert "pyproject.toml" in automation_update._git_status_porcelain(repo)


def _init_apply_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "add", "pyproject.toml"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)


@pytest.mark.parametrize("branch_pin", [False, True])
@pytest.mark.parametrize("allow_dirty", [False, True])
def test_apply_commit_commits_only_new_status_paths(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, branch_pin: bool, allow_dirty: bool
) -> None:
    repo = _write_repo(tmp_path, BRANCH_FOLLOW_PYPROJECT if branch_pin else INLINE_TABLE_PYPROJECT)
    _init_apply_git_repo(repo)
    (repo / "existing-untracked.txt").write_text("keep me local\n", encoding="utf-8")

    if allow_dirty:
        (repo / "preexisting-staged.txt").write_text("user work", encoding="utf-8")
        subprocess.run(["git", "add", "preexisting-staged.txt"], cwd=repo, check=True)

    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)
    monkeypatch.setattr(automation_update, "_check_channel_config", lambda root: "config/channel/ ロード成功")

    def _run(cmd: list[str], cwd: Path) -> int:
        if cmd[:4] == ["uv", "run", "yt-skills", "sync"]:
            generated = cwd / ".claude" / "skills" / "generated.md"
            generated.parent.mkdir(parents=True)
            generated.write_text("generated\n", encoding="utf-8")
        if cmd[:2] == ["uv", "lock"] and branch_pin:
            _write_uv_lock(cwd, _SHA_NEW)
        return 0

    monkeypatch.setattr(automation_update, "_run_command", _run)

    args = ["apply", "--target", str(repo), "--commit"]
    args += [] if branch_pin else ["--tag", "v5.6.0"]
    args += ["--allow-dirty"] if allow_dirty else []
    assert main(args) == 0
    expected_ref = _SHA_NEW[:12] if branch_pin else "v5.6.0"
    assert (
        subprocess.run(
            ["git", "log", "-1", "--pretty=%s"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        == f"chore: youtube-automation {expected_ref} への追従"
    )
    committed = subprocess.run(
        ["git", "show", "--pretty=", "--name-only", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    assert committed == [".claude/skills/generated.md", "uv.lock" if branch_pin else "pyproject.toml"]
    remaining = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert "?? existing-untracked.txt\n" in remaining
    assert ".claude/skills/generated.md" not in remaining

    if allow_dirty:
        assert "A  preexisting-staged.txt\n" in remaining


def test_apply_commit_failure_keeps_updated_worktree(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    _init_apply_git_repo(repo)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)
    monkeypatch.setattr(automation_update, "_check_channel_config", lambda root: "config/channel/ ロード成功")
    monkeypatch.setattr(automation_update, "_run_command", lambda cmd, cwd: 0)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--commit"]) == 1
    assert 'tag = "v5.6.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


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


def test_apply_allows_protected_local_skill_without_force_sync(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    commands: list[list[str]] = []
    monkeypatch.setattr(automation_update, "_run_command", lambda cmd, cwd: commands.append(cmd) or 0)
    monkeypatch.setattr(automation_update, "_check_channel_config", lambda root: "config/channel/ ロード成功")
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")

    def _diff_protected_local(*args, **kwargs):
        return automation_update.subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=(
                "target にのみ存在 (未知のローカル entry として prune から保護されます):\n"
                "  - youtube-production-manager\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(automation_update.subprocess, "run", _diff_protected_local)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0
    assert commands


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


def test_skills_diff_protected_local_skill_is_not_local_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _diff_protected_local(*args, **kwargs):
        return automation_update.subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=(
                "target にのみ存在 (未知のローカル entry として prune から保護されます):\n"
                "  - youtube-production-manager\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(automation_update.subprocess, "run", _diff_protected_local)

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


def test_apply_failed_step_can_rerun_with_allow_dirty_from_rewritten_pin(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    commands: list[list[str]] = []
    git_status_calls = 0
    fail_next_lock = True

    def _status(root: Path) -> str:
        nonlocal git_status_calls
        git_status_calls += 1
        return ""

    def _run(cmd: list[str], cwd: Path) -> int:
        nonlocal fail_next_lock
        commands.append(cmd)
        if fail_next_lock and cmd[:2] == ["uv", "lock"]:
            fail_next_lock = False
            return 1
        return 0

    monkeypatch.setattr(automation_update, "_run_command", _run)
    monkeypatch.setattr(automation_update, "_check_channel_config", lambda root: "config/channel/ ロード成功")
    monkeypatch.setattr(automation_update, "_git_status_porcelain", _status)
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1
    assert 'tag = "v5.6.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")

    commands.clear()
    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--allow-dirty"]) == 0

    assert git_status_calls == 1
    assert commands == [
        ["uv", "lock", "--upgrade-package", "youtube-channels-automation"],
        ["uv", "run", "yt-skills", "sync", "--force"],
        ["uv", "run", "yt-skills", "list"],
    ]


def test_apply_force_sync_passes_force_flag(tmp_path: Path, no_network, recorded_commands: list[list[str]]) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--force-sync"]) == 0
    assert ["uv", "run", "yt-skills", "sync", "--force"] in recorded_commands


def test_apply_accept_hooks_propagates_explicit_approval(
    tmp_path: Path, no_network, recorded_commands: list[list[str]]
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--accept-hooks"]) == 0
    assert ["uv", "run", "yt-skills", "sync", "--force", "--accept-hooks"] in recorded_commands


def test_apply_accept_hooks_reports_that_changed_hooks_start_next_session(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text('{"permissions": {}}', encoding="utf-8")

    def _run_and_add_hook(cmd: list[str], cwd: Path) -> int:
        if cmd[:4] == ["uv", "run", "yt-skills", "sync"]:
            settings_path.write_text(
                json.dumps(
                    {
                        "permissions": {},
                        "hooks": {
                            "SessionStart": [
                                {"hooks": [{"type": "command", "command": "uv run yt-session-start-context"}]}
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
        return 0

    monkeypatch.setattr(automation_update, "_run_command", _run_and_add_hook)
    monkeypatch.setattr(automation_update, "_check_channel_config", lambda root: "config/channel/ ロード成功")
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--accept-hooks"]) == 0

    assert "hook の変更は次回の Claude Code セッションから有効になります" in capsys.readouterr().out


def test_apply_accept_hooks_omits_next_session_notice_when_hooks_are_unchanged(
    tmp_path: Path,
    no_network,
    recorded_commands: list[list[str]],
    capsys: pytest.CaptureFixture,
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--accept-hooks"]) == 0

    assert "次回の Claude Code セッション" not in capsys.readouterr().out


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

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--sync-only", "music", "thumbnail"]) == 0
    assert [
        "uv",
        "run",
        "yt-skills",
        "sync",
        "--asset",
        "skills",
        "--only",
        "music",
        "thumbnail",
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

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0", "--sync-only", "music"]) == 1

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


def test_apply_channel_config_check_uses_target_even_when_channel_dir_differs(
    tmp_path: Path, no_network, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    other_base = tmp_path / "other"
    other_base.mkdir()
    other_repo = _write_repo(other_base, INLINE_TABLE_PYPROJECT)
    (other_repo / "config" / "channel" / "meta.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(other_repo))
    monkeypatch.setattr(automation_update, "_run_command", lambda cmd, cwd: 0)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)

    def _doctor(cmd: list[str], **kwargs):
        assert cmd == [
            "uv",
            "run",
            "yt-doctor",
            "--check",
            "channel_config",
            "--json",
            "--target",
            str(repo),
        ]
        assert kwargs["cwd"] == repo
        payload = {"checks": [{"id": "channel_config", "status": "ok", "message": "config/channel/ ロード成功"}]}
        return automation_update.subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(automation_update.subprocess, "run", _doctor)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 0


def test_channel_config_check_validates_every_channel_in_multi_channel_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "workspace"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(INLINE_TABLE_PYPROJECT, encoding="utf-8")
    channel_roots = [repo / "channels" / slug for slug in ("ambient", "jazz")]
    for channel_root in channel_roots:
        (channel_root / "config" / "channel").mkdir(parents=True)
    observed_targets: list[Path] = []

    def _doctor(cmd: list[str], **kwargs):
        target = Path(cmd[-1])
        observed_targets.append(target)
        assert kwargs["cwd"] == target
        payload = {"checks": [{"id": "channel_config", "status": "ok", "message": "config/channel/ ロード成功"}]}
        return automation_update.subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(automation_update.subprocess, "run", _doctor)

    result = automation_update._check_channel_config(repo)

    assert observed_targets == channel_roots
    assert result == "2 チャンネルの config/channel/ ロード成功"


def test_channel_config_check_fails_when_workspace_has_no_channel_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "workspace"
    repo.mkdir()

    def _doctor(cmd: list[str], **kwargs):
        assert cmd == [
            "uv",
            "run",
            "yt-doctor",
            "--check",
            "channel_config",
            "--json",
            "--target",
            str(repo),
        ]
        assert kwargs["cwd"] == repo
        payload = {
            "checks": [
                {
                    "id": "channel_config",
                    "status": "fail",
                    "message": "config/channel/ ディレクトリが存在しない",
                }
            ]
        }
        return automation_update.subprocess.CompletedProcess(cmd, 1, json.dumps(payload), "")

    monkeypatch.setattr(automation_update.subprocess, "run", _doctor)

    with pytest.raises(automation_update._StepFailed, match="config/channel/ ディレクトリが存在しない"):
        automation_update._check_channel_config(repo)


def test_apply_returns_nonzero_when_target_channel_config_is_invalid(
    tmp_path: Path,
    no_network,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    (repo / "config" / "channel" / "meta.json").write_text("{broken", encoding="utf-8")
    commands: list[list[str]] = []
    monkeypatch.setattr(automation_update, "_run_command", lambda cmd, cwd: commands.append(cmd) or 0)
    monkeypatch.setattr(automation_update, "_git_status_porcelain", lambda root: "")
    monkeypatch.setattr(automation_update, "_skills_diff_has_changes", lambda root: False)

    def _doctor(cmd: list[str], **kwargs):
        assert cmd == [
            "uv",
            "run",
            "yt-doctor",
            "--check",
            "channel_config",
            "--json",
            "--target",
            str(repo),
        ]
        payload = {
            "checks": [
                {
                    "id": "channel_config",
                    "status": "fail",
                    "message": "config/channel/ ロード失敗: broken JSON",
                }
            ]
        }
        return automation_update.subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(automation_update.subprocess, "run", _doctor)

    assert main(["apply", "--target", str(repo), "--tag", "v5.6.0"]) == 1

    captured = capsys.readouterr()
    assert "'smoke check: channel config' で失敗しました" in captured.err
    assert "config/channel/ ロード失敗" in captured.err
    assert "追従が完了しました" not in captured.out
    assert commands[-1] == ["uv", "run", "yt-skills", "list"]


def test_channel_config_check_ignores_nonzero_exit_when_channel_config_is_ok(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    payload = {
        "checks": [
            {"id": "channel_config", "status": "ok", "message": "config/channel/ ロード成功"},
            {"id": "upload_ready", "status": "fail", "message": "OAuth token が失効しています"},
        ]
    }
    completed = automation_update.subprocess.CompletedProcess([], 1, json.dumps(payload), "")
    monkeypatch.setattr(automation_update.subprocess, "run", lambda *args, **kwargs: completed)

    result = automation_update._check_channel_config(repo)

    assert result.startswith("config/channel/ ロード成功")
    assert "warning" in result
    assert "exit code 1" in result


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        (
            automation_update.subprocess.CompletedProcess([], 2, "", "doctor failed"),
            "exit code 2",
        ),
        (
            automation_update.subprocess.CompletedProcess([], 0, "not-json", ""),
            "出力を解析できません",
        ),
        (
            automation_update.subprocess.CompletedProcess([], 0, "{}", ""),
            "checks 配列がありません",
        ),
        (
            automation_update.subprocess.CompletedProcess([], 0, '{"checks": []}', ""),
            "channel_config check がありません",
        ),
    ],
)
def test_apply_channel_config_check_reports_invalid_doctor_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completed: automation_update.subprocess.CompletedProcess,
    expected: str,
) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    monkeypatch.setattr(automation_update.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(automation_update._StepFailed, match=expected):
        automation_update._check_channel_config(repo)


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


@pytest.mark.parametrize("staged", [False, True])
def test_commit_apply_changes_includes_both_rename_paths(tmp_path: Path, staged: bool) -> None:
    repo = _write_repo(tmp_path, INLINE_TABLE_PYPROJECT)
    _init_apply_git_repo(repo)
    old = repo / "old.md"
    old.write_text("skill contents\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "skill"], cwd=repo, check=True)
    before = automation_update._git_status_paths(repo)
    old.rename(repo / "new.md")
    if staged:
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    assert automation_update._git_status_paths(repo) == {"old.md", "new.md"}
    automation_update._commit_apply_changes(repo, before, "v5.8.0")
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=repo) == b""
    tree = subprocess.check_output(["git", "ls-tree", "--name-only", "HEAD"], cwd=repo).splitlines()
    assert b"new.md" in tree
    assert b"old.md" not in tree
