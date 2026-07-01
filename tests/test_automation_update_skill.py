from __future__ import annotations

import os
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


def _run_step_1_1(cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _step_1_1_script()],
        cwd=cwd,
        env={**os.environ, "HOME": str(home)},
        text=True,
        capture_output=True,
        check=False,
    )


def _write_pyproject(repo_dir: Path, body: str) -> None:
    repo_dir.mkdir(parents=True)
    (repo_dir / "pyproject.toml").write_text(body, encoding="utf-8")


def test_automation_update_guides_user_when_outside_channel_repo() -> None:
    text = _SKILL_MD.read_text(encoding="utf-8")

    assert "対象外フォルダで起動された場合" in text
    assert "現在地が不適切な理由" in text
    assert "移動先候補のチャンネルフォルダ" in text
    assert "print_channel_repo_guidance" in text
    assert "現在地: $(pwd)" in text
    assert "youtube-channels-automation を依存として参照するチャンネルリポジトリではありません" in text
    assert "cd -- %q" in text
    assert "xargs grep -l 'youtube-channels-automation'" not in text
    assert "チャンネルリポジトリ側へ cd してから /automation-update を再実行してください" in text


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
    assert "cd -- " in result.stdout
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
    assert 'name\\s*=\\s*"youtube-channels-automation"' in result.stdout


def test_automation_update_step_fallback_excludes_upstream_projects(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_pyproject(home / "02-yt" / "upstream", '[project]\nname = "youtube-channels-automation"\n')

    result = _run_step_1_1(outside, home)

    assert result.returncode == 1
    assert "自動検出できませんでした" in result.stdout
    assert "xargs grep -l" not in result.stdout
    assert "grep -q 'youtube-channels-automation'" in result.stdout
    assert "! grep -qE" in result.stdout
    assert 'name\\s*=\\s*"youtube-channels-automation"' in result.stdout


def test_automation_update_step_rejects_unrelated_pyproject(tmp_path: Path) -> None:
    home = tmp_path / "home"
    unrelated_repo = tmp_path / "unrelated"
    _write_pyproject(unrelated_repo, '[project]\nname = "not-a-channel"\ndependencies = []\n')

    result = _run_step_1_1(unrelated_repo, home)

    assert result.returncode == 1
    assert "youtube-channels-automation を依存として参照するチャンネルリポジトリではありません" in result.stdout
    assert "自動検出できませんでした" in result.stdout
