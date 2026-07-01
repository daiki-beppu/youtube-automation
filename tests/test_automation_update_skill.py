from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "automation-update" / "SKILL.md"


def _step_1_1_script() -> str:
    text = _SKILL_MD.read_text(encoding="utf-8")
    step_start = text.index("### Step 1-1.")
    code_start = text.index("```bash", step_start) + len("```bash")
    code_end = text.index("```", code_start)
    return text[code_start:code_end].strip() + "\n"


def _run_step_1_1(cwd: Path, home: Path, *, path: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home)}
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        ["bash", "-c", _step_1_1_script()],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )


def _write_pyproject(repo_dir: Path, body: str) -> None:
    repo_dir.mkdir(parents=True)
    (repo_dir / "pyproject.toml").write_text(body, encoding="utf-8")


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_tool_path(tmp_path: Path) -> str:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uv", "#!/usr/bin/env bash\necho 'uv 0.0.0-test'\n")
    _write_executable(
        fake_bin / "git",
        '#!/usr/bin/env bash\nif [ "$1" = status ]; then exit 0; fi\nexit 0\n',
    )
    _write_executable(
        fake_bin / "gh",
        "#!/usr/bin/env bash\n"
        'if [ "$1" = auth ] && [ "$2" = status ]; then\n'
        "  echo 'github.com OK'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )
    return f"{fake_bin}{os.pathsep}{os.environ['PATH']}"


def test_automation_update_step_guides_with_escaped_channel_candidate(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    channel_repo = home / "02-yt" / "channel;touch PWNED"
    _write_pyproject(
        channel_repo,
        '[project]\nname = "deepfocus365"\ndependencies = ["youtube-channels-automation>=5"]\n',
    )

    result = _run_step_1_1(outside, home)

    assert result.returncode == 1
    assert "現在地:" in result.stdout
    assert "移動先候補:" in result.stdout
    assert result.stdout.count("cd -- ") == 1
    assert f"cd -- {channel_repo}" not in result.stdout
    assert "channel\\;touch\\ PWNED" in result.stdout
    assert not (outside / "PWNED").exists()


def test_automation_update_step_guides_from_upstream_repo(tmp_path: Path) -> None:
    home = tmp_path / "home"
    upstream_repo = tmp_path / "upstream"
    _write_pyproject(upstream_repo, '[project]\nname = "youtube-channels-automation"\n')

    result = _run_step_1_1(upstream_repo, home)

    assert result.returncode == 0
    assert "このスキルは下流リポ専用です" in result.stdout
    assert "現在地:" in result.stdout
    assert "理由:" in result.stdout
    assert "移動先候補:" in result.stdout
    assert "[project].dependencies" in result.stdout
    assert "[project].name が youtube-channels-automation の upstream 本体は除外" in result.stdout


def test_automation_update_step_fallback_excludes_upstream_projects(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_pyproject(home / "02-yt" / "upstream", '[project]\nname = "youtube-channels-automation"\n')

    result = _run_step_1_1(outside, home)

    assert result.returncode == 1
    assert "自動検出できませんでした" in result.stdout
    assert "xargs grep -l" not in result.stdout
    assert "find " in result.stdout
    assert "-type f" in result.stdout
    assert "[project].dependencies" in result.stdout
    assert "[project].name が youtube-channels-automation の upstream 本体は除外" in result.stdout


def test_automation_update_step_rejects_unrelated_pyproject(tmp_path: Path) -> None:
    home = tmp_path / "home"
    unrelated_repo = tmp_path / "unrelated"
    _write_pyproject(unrelated_repo, '[project]\nname = "not-a-channel"\ndependencies = []\n')

    result = _run_step_1_1(unrelated_repo, home)

    assert result.returncode == 1
    assert "youtube-channels-automation を依存として参照するチャンネルリポジトリではありません" in result.stdout
    assert "自動検出できませんでした" in result.stdout


def test_automation_update_step_rejects_similar_dependency_name(tmp_path: Path) -> None:
    home = tmp_path / "home"
    similar_repo = tmp_path / "similar"
    _write_pyproject(
        similar_repo,
        '[project]\nname = "not-a-channel"\ndependencies = ["youtube-channels-automation-extra>=1"]\n',
    )

    result = _run_step_1_1(similar_repo, home)

    assert result.returncode == 1
    assert "uv 0.0.0-test" not in result.stdout
    assert "自動検出できませんでした" in result.stdout


def test_automation_update_step_rejects_comment_or_description_match(tmp_path: Path) -> None:
    home = tmp_path / "home"
    described_repo = tmp_path / "described"
    _write_pyproject(
        described_repo,
        (
            "[project]\n"
            'name = "not-a-channel"\n'
            'description = "mentions youtube-channels-automation only"\n'
            "dependencies = []\n"
        ),
    )

    result = _run_step_1_1(described_repo, home)

    assert result.returncode == 1
    assert "uv 0.0.0-test" not in result.stdout
    assert "自動検出できませんでした" in result.stdout


def test_automation_update_step_allows_exact_channel_dependency(tmp_path: Path) -> None:
    home = tmp_path / "home"
    channel_repo = tmp_path / "channel"
    _write_pyproject(
        channel_repo,
        (
            "[project]\n"
            'name = "deepfocus365"\n'
            'dependencies = ["youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation.git"]\n'
        ),
    )

    result = _run_step_1_1(channel_repo, home, path=_fake_tool_path(tmp_path))

    assert result.returncode == 0
    assert "/automation-update は下流チャンネルリポジトリで実行してください" not in result.stdout
    assert "uv 0.0.0-test" in result.stdout
    assert "github.com OK" in result.stdout


def test_automation_update_step_ignores_non_regular_pyproject_candidates(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    fifo_dir = home / "02-yt" / "fifo-repo"
    fifo_dir.mkdir(parents=True)
    os.mkfifo(fifo_dir / "pyproject.toml")

    result = _run_step_1_1(outside, home)

    assert result.returncode == 1
    assert "自動検出できませんでした" in result.stdout
    assert "cd -- " not in result.stdout
