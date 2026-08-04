"""Candidate wheel から擬似下流へ全 asset を同期する E2E smoke test。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

_FILE_ASSETS = {
    Path(".claude/CLAUDE.md"): Path(".claude/CLAUDE.template.md"),
    Path("docs/workflow-cheatsheet.md"): Path("docs/workflow-cheatsheet.md"),
    Path("docs/features.md"): Path("docs/features.md"),
    Path("auth/client_secrets.template.json"): Path(
        "src/youtube_automation/infrastructure/resources/auth/client_secrets.template.json"
    ),
}


def _run(*args: str | Path, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _candidate_wheel(repo_root: Path, tmp_path: Path) -> Path:
    configured = os.environ.get("YTA_CANDIDATE_WHEEL")
    if configured:
        wheel = Path(configured)
        if not wheel.is_absolute():
            wheel = repo_root / wheel
        assert wheel.is_file(), f"YTA_CANDIDATE_WHEEL が見つかりません: {wheel}"
        return wheel

    wheel_dir = tmp_path / "wheel"
    result = _run("uv", "build", "--wheel", "--out-dir", wheel_dir, cwd=repo_root)
    assert result.returncode == 0, result.stderr
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, f"candidate wheel は1件を期待: {wheels}"
    return wheels[0]


def _tracked_skill_files(repo_root: Path) -> set[Path]:
    result = _run("git", "ls-files", "--", ".claude/skills", cwd=repo_root)
    assert result.returncode == 0, result.stderr
    prefix = Path(".claude/skills")
    dev_only = {"automation-release", "shadcn"}
    return {
        relative
        for line in result.stdout.splitlines()
        if line and (relative := Path(line).relative_to(prefix)).parts[0] not in dev_only
    }


def test_candidate_wheel_syncs_all_assets_into_clean_downstream(tmp_path: Path) -> None:
    repo_root = REPO_ROOT
    wheel = _candidate_wheel(repo_root, tmp_path)
    venv = tmp_path / "venv"

    created = _run("uv", "venv", venv, cwd=tmp_path)
    assert created.returncode == 0, created.stderr
    python = venv / "bin" / "python"
    installed = _run("uv", "pip", "install", "--python", python, wheel, cwd=tmp_path)
    assert installed.returncode == 0, installed.stderr

    downstream = tmp_path / "downstream"
    downstream.mkdir()
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    clean_env.pop("UV_PROJECT", None)
    clean_env["VIRTUAL_ENV"] = str(venv)

    package_location = _run(
        python,
        "-c",
        "import pathlib, youtube_automation; print(pathlib.Path(youtube_automation.__file__).resolve())",
        cwd=downstream,
        env=clean_env,
    )
    assert package_location.returncode == 0, package_location.stderr
    assert Path(package_location.stdout.strip()).is_relative_to(venv.resolve())

    compatibility_imports = _run(
        python,
        "-c",
        """
import importlib

legacy_modules = (
    "youtube_automation.infrastructure.errors",
    "youtube_automation.utils.skill_config",
    "youtube_automation.utils.collection_paths",
    "youtube_automation.utils.image_provider",
    "youtube_automation.utils.audio_visualizer_mask",
)
for module_name in legacy_modules:
    module = importlib.import_module(module_name)
    assert module.__name__ == module_name

canonical = importlib.import_module("youtube_automation.configuration.channel_target")
legacy_channel_target = importlib.import_module("youtube_automation.infrastructure.legacy_utils.channel_target")
compat_channel_target = importlib.import_module("youtube_automation.utils.channel_target")
assert canonical.resolve_existing_target_dir is legacy_channel_target.resolve_existing_target_dir
assert canonical.resolve_existing_target_dir is compat_channel_target.resolve_existing_target_dir
importlib.import_module("youtube_automation.infrastructure.legacy_utils.schemas")
importlib.import_module("youtube_automation.utils.schemas")

legacy = importlib.import_module("youtube_automation.infrastructure.legacy_utils.skill_config")
canonical_skills = importlib.import_module("youtube_automation.configuration.skills")
assert legacy.reset is canonical_skills.reset
assert legacy._cache is canonical_skills._cache
legacy.reset()
legacy._cache["wheel-identity-check"] = {}
canonical_skills.reset("wheel-identity-check")
assert "wheel-identity-check" not in legacy._cache
""",
        cwd=downstream,
        env=clean_env,
    )
    assert compatibility_imports.returncode == 0, compatibility_imports.stderr

    yt_skills = venv / "bin" / "yt-skills"
    synced = _run(yt_skills, "sync", cwd=downstream, env=clean_env)
    assert synced.returncode == 0, synced.stderr

    source_skill_files = _tracked_skill_files(repo_root)
    target_skills = downstream / ".claude" / "skills"
    target_skill_files = {
        path.relative_to(target_skills) for path in target_skills.rglob("*") if path.is_file() or path.is_symlink()
    }
    assert target_skill_files == source_skill_files
    for relative in source_skill_files:
        assert (target_skills / relative).read_bytes() == (repo_root / ".claude" / "skills" / relative).read_bytes()

    for target_relative, source_relative in _FILE_ASSETS.items():
        assert (downstream / target_relative).read_bytes() == (repo_root / source_relative).read_bytes()

    distributed_references = downstream / ".claude" / "skills" / "channel-new" / "references"
    bootstrap_guide = distributed_references / "gcp-bootstrap.md"
    assert bootstrap_guide.is_file()
    assert bootstrap_guide.read_text(encoding="utf-8")
    for script_name in ("gcp-bootstrap.sh", "gcp-terraform-apply.sh"):
        script = distributed_references / script_name
        assert script.is_file()
        references = re.findall(
            r"(?:`|\s)([A-Za-z0-9_.-]+\.md)(?:`|\s|[「」])",
            script.read_text(encoding="utf-8"),
        )
        assert references
        assert all((distributed_references / reference).is_file() for reference in references)

    settings = json.loads((downstream / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"]
    assert settings["permissions"]["deny"]
    assert "hooks" not in settings  # 非対話 sync は --accept-hooks 無しなら command hook を追加しない

    agents_skills = downstream / ".agents" / "skills"
    assert agents_skills.is_symlink()
    assert os.readlink(agents_skills) == "../.claude/skills"

    diffed = _run(yt_skills, "diff", cwd=downstream, env=clean_env)
    assert diffed.returncode == 0, diffed.stdout + diffed.stderr
    assert diffed.stdout.count("差分なし") == 5
    assert "hooks.PreToolUse" in diffed.stdout
