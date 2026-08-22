"""Candidate wheel から擬似下流へ全 asset を同期する E2E smoke test。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

_FILE_ASSETS = {
    Path(".gitignore"): Path("src/youtube_automation/infrastructure/resources/channel/gitignore.template"),
    Path(".github/workflows/youtube-automation.yml"): Path(
        "src/youtube_automation/infrastructure/resources/channel/youtube-automation.yml"
    ),
    Path(".github/workflows/codex-canary.yml"): Path(
        "src/youtube_automation/infrastructure/resources/channel/codex-canary.yml"
    ),
    Path(".claude/CLAUDE.md"): Path(".claude/CLAUDE.template.md"),
    Path("docs/workflow-cheatsheet.md"): Path("docs/workflow-cheatsheet.md"),
    Path("docs/features.md"): Path("docs/features.md"),
    Path("auth/client_secrets.template.json"): Path(
        "src/youtube_automation/infrastructure/resources/auth/client_secrets.template.json"
    ),
}
_CHANNEL_NEW_SHARED_ASSETS = frozenset(
    {
        "claude-md-template.md",
        "config-generation-rules.md",
        "config-template/analytics.json",
        "config-template/audio.json",
        "config-template/content.json",
        "config-template/meta.json",
        "config-template/skills/music.yaml",
        "config-template/skills/thumbnail.yaml",
        "config-template/youtube.json",
        "desire-vocabulary.md",
        "direction-mode.md",
        "directory-structure.md",
        "fetch_branding_snapshot.py",
        "generate_image.py",
        "schedule-template.json",
        "verification.md",
    }
)
_SETUP_SHARED_ASSETS = _CHANNEL_NEW_SHARED_ASSETS - {"direction-mode.md", "desire-vocabulary.md"}
_SETUP_MIGRATED_ASSETS = frozenset(
    {
        "import-mode.md",
        "localizations-template.json",
        "push-mode.md",
        "regeneration-mode.md",
        "save-push-troubleshooting.md",
    }
)


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


def _candidate_sdist(repo_root: Path, tmp_path: Path) -> Path:
    sdist_dir = tmp_path / "sdist"
    result = _run("uv", "build", "--sdist", "--out-dir", sdist_dir, cwd=repo_root)
    assert result.returncode == 0, result.stderr
    sdists = list(sdist_dir.glob("*.tar.gz"))
    assert len(sdists) == 1, f"candidate sdist は1件を期待: {sdists}"
    return sdists[0]


def _tracked_skill_files(repo_root: Path) -> set[Path]:
    inventory = SkillInventory(repo_root)
    skills_root = inventory.skills_root.relative_to(repo_root)
    result = _run("git", "ls-files", "--", skills_root, cwd=repo_root)
    assert result.returncode == 0, result.stderr
    dev_only = {"automation-release", "hallmark", "shadcn"}
    return {
        relative
        for line in result.stdout.splitlines()
        if line and (relative := Path(line).relative_to(skills_root)).parts[0] not in dev_only
    }


def _inventory_files(inventory: SkillInventory) -> set[Path]:
    return {
        path.relative_to(inventory.skills_root)
        for skill_dir in inventory.skill_directories()
        for path in skill_dir.rglob("*")
        if path.is_file() or path.is_symlink()
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

    cli_collection = downstream / "cli-collection"
    (cli_collection / "01-master").mkdir(parents=True)
    (cli_collection / "02-Individual-music").mkdir()
    yt_workflow_state = venv / "bin" / "yt-workflow-state"
    phase_updated = _run(
        yt_workflow_state,
        "--collection",
        cli_collection,
        "set-phase",
        "prepared",
        cwd=downstream,
        env=clean_env,
    )
    assert phase_updated.returncode == 0, phase_updated.stderr
    phase_read = _run(
        yt_workflow_state,
        "--collection",
        cli_collection,
        "get",
        "phase",
        cwd=downstream,
        env=clean_env,
    )
    assert phase_read.returncode == 0, phase_read.stderr
    assert phase_read.stdout == '"prepared"\n'
    workflow_status_help = _run(venv / "bin" / "yt-workflow-status", "--help", cwd=downstream, env=clean_env)
    assert workflow_status_help.returncode == 0, workflow_status_help.stderr
    review_help = _run(venv / "bin" / "yt-document-review", "--help", cwd=downstream, env=clean_env)
    assert review_help.returncode == 0, review_help.stderr
    plan_review_help = _run(venv / "bin" / "yt-collection-plan-select", "--help", cwd=downstream, env=clean_env)
    assert plan_review_help.returncode == 0, plan_review_help.stderr
    music_review_help = _run(venv / "bin" / "yt-music-prompt-select", "--help", cwd=downstream, env=clean_env)
    assert music_review_help.returncode == 0, music_review_help.stderr
    master_audio_review_help = _run(venv / "bin" / "yt-master-audio-review", "--help", cwd=downstream, env=clean_env)
    assert master_audio_review_help.returncode == 0, master_audio_review_help.stderr
    master_video_review_help = _run(venv / "bin" / "yt-master-video-review", "--help", cwd=downstream, env=clean_env)
    assert master_video_review_help.returncode == 0, master_video_review_help.stderr

    compatibility_imports = _run(
        python,
        "-c",
        """
import importlib
import sys
import tempfile
from pathlib import Path

import youtube_automation

from youtube_automation.domains.skills.inventory import SkillInventory

wheel_skills_root = Path(youtube_automation.__file__).resolve().parent / "_skills"
wheel_inventory = SkillInventory(wheel_skills_root)
assert wheel_inventory.skills_root == wheel_skills_root
assert "setup" in {path.name for path in wheel_inventory.skill_directories()}

schema_registry = importlib.import_module("youtube_automation.domains.documents.schema_registry")
schema_registry.compile_repository_schemas()
assert set(schema_registry.repository_schema_names()) == {
    "analysis-report.schema.json",
    "audit-report.schema.json",
    "channel-research-report.schema.json",
    "channel-strategy.schema.json",
    "collection-plan.schema.json",
    "experiment-entry.schema.json",
    "feedback-entry.schema.json",
    "insights-entry.schema.json",
    "music-prompt.schema.json",
    "video-description.schema.json",
    "weekly_vote_log.schema.json",
}
rendering = importlib.import_module("youtube_automation.domains.documents.rendering")
rendered = rendering.render_repository_document(
    schema_registry.RepositorySchema.WEEKLY_VOTE_LOG,
    {"schema_version": 1, "entries": []},
)
assert "Content-Security-Policy" in rendered
assert ".view-card, .view-table-section, .view-media" in rendered
workflow_status_rendering = importlib.import_module(
    "youtube_automation.domains.documents.workflow_status_rendering"
)
workflow_status_application = importlib.import_module("youtube_automation.application.workflow_status")
workflow_snapshot = workflow_status_application.WorkflowStatusSnapshot(
    generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    collections=(),
)
workflow_html = workflow_status_rendering.render_workflow_status(workflow_snapshot)
assert "コレクションはありません" in workflow_html
assert "#filter-planning:checked" in workflow_html
review_rendering = importlib.import_module("youtube_automation.domains.documents.review_rendering")
assert review_rendering.__name__.endswith("review_rendering")
plan_selection = importlib.import_module("youtube_automation.commands.documents.collection_plan_select")
assert plan_selection.__name__.endswith("collection_plan_select")
music_prompt_selection = importlib.import_module("youtube_automation.commands.documents.music_prompt_select")
assert music_prompt_selection.__name__.endswith("music_prompt_select")
master_audio_review = importlib.import_module("youtube_automation.commands.media.master_audio_review")
assert master_audio_review.__name__.endswith("master_audio_review")
master_video_review = importlib.import_module("youtube_automation.commands.media.master_video_review")
assert master_video_review.__name__.endswith("master_video_review")
document_migration = importlib.import_module("youtube_automation.application.documents.migration")
with tempfile.TemporaryDirectory() as directory:
    target = Path(directory) / "weekly.json"
    result = document_migration.write_operational_document(
        target,
        schema_registry.RepositorySchema.WEEKLY_VOTE_LOG,
        lambda: {"schema_version": 1, "entries": []},
        document_migration.MarkdownMigrationDecision.NOT_REQUIRED,
    )
    assert result is document_migration.DocumentWriteResult.CREATED
    assert target.is_file() and target.with_suffix(".html").is_file()

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

removed_modules = (
    "youtube_automation.infrastructure.legacy_utils.profile",
    "youtube_automation.infrastructure.legacy_utils.worktree",
    "youtube_automation.utils.profile",
    "youtube_automation.utils.worktree",
)
for module_name in removed_modules:
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        assert exc.name == module_name
    else:
        raise AssertionError(f"removed duplicate module remains importable: {module_name}")

errors = importlib.import_module("youtube_automation.infrastructure.errors")
canonical_errors = importlib.import_module("youtube_automation.core.errors")
assert errors.ConfigError is canonical_errors.ConfigError
try:
    raise errors.ConfigError("wheel-facade-behavior")
except errors.ConfigError as exc:
    assert str(exc) == "wheel-facade-behavior"

paths = importlib.import_module("youtube_automation.utils.collection_paths")
canonical_paths = importlib.import_module("youtube_automation.infrastructure.media.collection_paths")
assert paths.CollectionPaths is canonical_paths.CollectionPaths
assert paths.CollectionPaths("example").collection_name == "example"

image_provider = importlib.import_module("youtube_automation.utils.image_provider")
canonical_image_provider = importlib.import_module("youtube_automation.infrastructure.media.image_provider")
assert image_provider.PromptSchema is canonical_image_provider.PromptSchema
assert image_provider.PromptSchema(primary_request="wheel").primary_request == "wheel"
for submodule in ("config", "composition", "prompt_schema", "gemini", "openai"):
    canonical_name = f"youtube_automation.infrastructure.media.image_provider.{submodule}"
    canonical_submodule = sys.modules[canonical_name]
    assert getattr(image_provider, submodule) is canonical_submodule
    assert sys.modules[f"youtube_automation.utils.image_provider.{submodule}"] is canonical_submodule
for submodule in ("config", "composition", "prompt_schema", "gemini", "openai"):
    facade_submodule = importlib.import_module(f"youtube_automation.utils.image_provider.{submodule}")
    canonical_submodule = importlib.import_module(
        f"youtube_automation.infrastructure.media.image_provider.{submodule}"
    )
    assert facade_submodule is canonical_submodule

composition = importlib.import_module("youtube_automation.utils.image_provider.composition")
canonical_composition = importlib.import_module(
    "youtube_automation.infrastructure.media.image_provider.composition"
)
original_log_image_cost = composition.log_image_cost
assert original_log_image_cost.__globals__ is composition.__dict__
replacement_log_image_cost = object()
composition.log_image_cost = replacement_log_image_cost
assert canonical_composition.log_image_cost is replacement_log_image_cost

mask = importlib.import_module("youtube_automation.utils.audio_visualizer_mask")
canonical_mask = importlib.import_module("youtube_automation.infrastructure.media.audio_visualizer_mask")
assert mask.parse_size is canonical_mask.parse_size
assert mask.parse_size("12x34") == (12, 34)

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
compat_skills = importlib.import_module("youtube_automation.utils.skill_config")
assert compat_skills.reset is canonical_skills.reset
assert compat_skills._cache is canonical_skills._cache
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
    target_inventory = SkillInventory(downstream)
    target_skills = target_inventory.skills_root
    assert target_skills == downstream / ".claude" / "skills"
    target_skill_files = _inventory_files(target_inventory)
    assert target_skill_files == source_skill_files
    for relative in source_skill_files:
        target = target_skills / relative
        source = SkillInventory(repo_root).skills_root / relative
        assert target.read_bytes() == source.read_bytes()

    workflow_state_scripts = (
        target_skills / "publish" / "references" / "generate_batch.py",
        target_skills / "publish" / "references" / "clean-scan.py",
        target_skills / "publish" / "references" / "publish-chain-state.py",
        target_skills / "wf-new" / "references" / "wf-auto-state.py",
        target_skills / "wf-next" / "references" / "master_audio_transition.py",
    )
    for script in workflow_state_scripts:
        help_result = _run(python, script, "--help", cwd=downstream, env=clean_env)
        assert help_result.returncode == 0, help_result.stderr

    for target_relative, source_relative in _FILE_ASSETS.items():
        assert (downstream / target_relative).read_bytes() == (repo_root / source_relative).read_bytes()

    distributed_references = downstream / ".claude" / "skills" / "setup" / "references"
    channel_mode = distributed_references / "channel-mode.md"
    assert channel_mode.is_file()
    setup_manifest = distributed_references / "setup-chain-manifest.json"
    setup_state = distributed_references / "setup-chain-state.py"
    assert setup_manifest.is_file()
    assert setup_state.is_file()
    assert os.access(setup_state, os.X_OK)
    state_help = _run(python, setup_state, "--help", cwd=downstream, env=clean_env)
    assert state_help.returncode == 0, state_help.stderr
    assert "--step {tool,channel}" in state_help.stdout
    opening_assets = {
        "new-channel-bootstrap.md",
        "ttp-seed-and-duration.md",
        "persona-branding-readiness.md",
        "derive_ttp_duration.py",
        "initial_save_guard.sh",
    }
    for asset in opening_assets | {"setup-mode-guard.py"}:
        assert (distributed_references / asset).is_file()
        assert not (downstream / ".claude" / "skills" / "channel-new" / "references" / asset).exists()
    for asset in _SETUP_MIGRATED_ASSETS:
        assert (distributed_references / asset).is_file()
        assert not (downstream / ".claude" / "skills" / "channel-new" / "references" / asset).exists()
    for markdown in (channel_mode, *(distributed_references / name for name in opening_assets if name.endswith(".md"))):
        local_links = [
            link
            for link in re.findall(r"\[[^]]+\]\(([^)]+)\)", markdown.read_text(encoding="utf-8"))
            if not link.startswith(("http://", "https://", "#"))
        ]
        assert local_links
        assert all((markdown.parent / link).is_file() for link in local_links)

    assert not (downstream / ".claude" / "skills" / "channel-new").exists()
    strategy_references = downstream / ".claude" / "skills" / "channel-strategy" / "references"
    assert (strategy_references / "direction.md").is_file()
    assert (strategy_references / "desire-vocabulary.md").is_file()
    for shared_asset in _SETUP_SHARED_ASSETS:
        assert (distributed_references / shared_asset).is_file()

    channel_research = downstream / ".claude" / "skills" / "channel-research"
    collector = channel_research / "references" / "benchmark_collector.py"
    assert collector.is_file()
    assert not collector.is_symlink()
    assert (
        collector.read_bytes()
        == (REPO_ROOT / "src/youtube_automation/commands/analytics/benchmark_collector.py").read_bytes()
    )
    assert not (downstream / ".claude" / "skills" / "benchmark").exists()
    assert (channel_research / "references" / "market.md").is_file()
    assert (channel_research / "references" / "market_research_contract.py").is_file()
    assert (channel_research / "references" / "report-contract.md").is_file()
    assert (channel_research / "references" / "thumbnail.md").is_file()
    assert not (downstream / ".claude" / "skills" / "market-research").exists()
    assert not (downstream / ".claude" / "skills" / "thumbnail-research").exists()

    channel_strategy = downstream / ".claude" / "skills" / "channel-strategy"
    assert (channel_strategy / "SKILL.md").is_file()
    assert (channel_strategy / "references" / "persona.md").is_file()
    assert (channel_strategy / "references" / "scene.md").is_file()
    assert (channel_strategy / "references" / "constraints.md").is_file()
    assert (channel_strategy / "references" / "persona_flow.py").is_file()
    assert (channel_strategy / "references" / "channel-strategy-chain-manifest.json").is_file()
    assert (channel_strategy / "references" / "channel-strategy-chain-state.py").is_file()
    assert not (downstream / ".claude" / "skills" / "audience-persona-design").exists()
    assert not (downstream / ".claude" / "skills" / "viewing-scene").exists()
    assert not (downstream / ".claude" / "skills" / "creative-constraints").exists()

    bootstrap_guide = distributed_references / "gcp-bootstrap.md"
    assert bootstrap_guide.is_file()
    guide_text = bootstrap_guide.read_text(encoding="utf-8")
    local_links = [
        link
        for link in re.findall(r"\[[^]]+\]\(([^)]+)\)", guide_text)
        if not link.startswith(("http://", "https://", "#"))
    ]
    assert local_links
    assert all((distributed_references / link).is_file() for link in local_links)
    for relative in (
        "gcp-bootstrap.sh",
        "gcp-terraform-apply.sh",
        "terraform-gcp/terraform.tfvars.example",
        "terraform-gcp/variables.tf",
    ):
        assert (distributed_references / relative).is_file()
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
    assert diffed.stdout.count("差分なし") == len(_FILE_ASSETS) + 1  # file assets + skills
    assert "hooks.PreToolUse" in diffed.stdout


def test_candidate_sdist_contains_setup_channel_owner_once(tmp_path: Path) -> None:
    sdist = _candidate_sdist(REPO_ROOT, tmp_path)
    opening_assets = {
        "new-channel-bootstrap.md",
        "ttp-seed-and-duration.md",
        "persona-branding-readiness.md",
        "derive_ttp_duration.py",
        "initial_save_guard.sh",
    }
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        names = {Path(member.name) for member in members}

    for asset in opening_assets:
        setup_matches = [path for path in names if str(path).endswith(f"/.claude/skills/setup/references/{asset}")]
        channel_new_matches = [
            path for path in names if str(path).endswith(f"/.claude/skills/channel-new/references/{asset}")
        ]
        assert len(setup_matches) == 1
        assert channel_new_matches == []
    assert any(str(path).endswith("/.claude/skills/setup/references/channel-mode.md") for path in names)
    assert any(str(path).endswith("/.claude/skills/setup/references/setup-mode-guard.py") for path in names)
    manifest_members = [
        member
        for member in members
        if member.name.endswith("/.claude/skills/setup/references/setup-chain-manifest.json")
    ]
    state_members = [
        member for member in members if member.name.endswith("/.claude/skills/setup/references/setup-chain-state.py")
    ]
    assert len(manifest_members) == 1
    assert len(state_members) == 1
    assert state_members[0].mode & 0o111
    for relative in _SETUP_SHARED_ASSETS:
        matches = [member for member in members if member.name.endswith(f"/.claude/skills/setup/references/{relative}")]
        assert len(matches) == 1
    for relative in _SETUP_MIGRATED_ASSETS:
        setup_matches = [
            member for member in members if member.name.endswith(f"/.claude/skills/setup/references/{relative}")
        ]
        channel_new_matches = [
            member for member in members if member.name.endswith(f"/.claude/skills/channel-new/references/{relative}")
        ]
        assert len(setup_matches) == 1
        assert channel_new_matches == []

    expected_links = {
        "generate_image.py": "../../../../src/youtube_automation/commands/media/generate_image.py",
    }
    for relative, linkname in expected_links.items():
        member = next(
            member for member in members if member.name.endswith(f"/.claude/skills/setup/references/{relative}")
        )
        assert member.issym()
        assert member.linkname == linkname

    collector_members = [
        member
        for member in members
        if member.name.endswith("/.claude/skills/channel-research/references/benchmark_collector.py")
    ]
    assert len(collector_members) == 1
    assert collector_members[0].issym()
    assert collector_members[0].linkname == (
        "../../../../src/youtube_automation/commands/analytics/benchmark_collector.py"
    )
    comment_collector = next(
        member
        for member in members
        if member.name.endswith("/.claude/skills/channel-research/references/fetch_benchmark_comments.py")
    )
    assert comment_collector.issym()
    assert comment_collector.linkname == (
        "../../../../src/youtube_automation/commands/analytics/fetch_benchmark_comments.py"
    )
    assert not any("/.claude/skills/benchmark/" in member.name for member in members)
