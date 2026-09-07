"""Issue #1273: onboard から setup への skill rename 契約テスト。"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import doctor

_REPO_ROOT = REPO_ROOT
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
_SETUP_SKILL = _SKILLS_DIR / "setup" / "SKILL.md"
_SETUP_TOOL = _SKILLS_DIR / "setup" / "references" / "tool.md"
_SETUP_RUNBOOK = _SKILLS_DIR / "setup" / "references" / "check-runbook.md"
_SETUP_CHAIN_MANIFEST = _SKILLS_DIR / "setup" / "references" / "setup-chain-manifest.json"
_SETUP_CHAIN_STATE = _SKILLS_DIR / "setup" / "references" / "setup-chain-state.py"
_SETUP_MODE_GUARD = _SKILLS_DIR / "setup" / "references" / "setup-mode-guard.py"
_SETUP_CHANNEL_MODE = _SKILLS_DIR / "setup" / "references" / "channel-mode.md"
_SETUP_IMPORT_MODE = _SKILLS_DIR / "setup" / "references" / "import-mode.md"
_SETUP_REGENERATE_MODE = _SKILLS_DIR / "setup" / "references" / "regeneration-mode.md"
_SETUP_PUSH_MODE = _SKILLS_DIR / "setup" / "references" / "push-mode.md"
_FRESHNESS_RULES = _SKILLS_DIR / "wf-new" / "references" / "freshness-rules.md"
_CHANNEL_NEW_SKILL = _SKILLS_DIR / "channel-new" / "SKILL.md"
_ONBOARD_DIR = _SKILLS_DIR / "onboard"
_CURRENT_SETUP_DOCS = [
    _REPO_ROOT / "ONBOARDING.md",
    _REPO_ROOT / "infra" / "terraform" / "gcp" / "README.md",
]


def _setup_text() -> str:
    """SKILL.md 本体 + 段階的開示で切り出した references/ を合わせた全文。

    tool wizard と check id ごとの対応手順は references/ へ分離したため、
    「/setup の手順として書かれていること」を担保する契約は 3 ファイルを対象にする。
    SKILL.md 本体に残っていること自体が要件のものだけ `_SETUP_SKILL` を直接読む。
    """
    return (
        _SETUP_SKILL.read_text(encoding="utf-8")
        + "\n"
        + _SETUP_TOOL.read_text(encoding="utf-8")
        + "\n"
        + _SETUP_RUNBOOK.read_text(encoding="utf-8")
    )


def _runbook_section(check_id: str) -> str:
    """check-runbook.md から check_id 見出し 1 節だけを切り出す（次の h4 見出しの手前まで）。"""
    runbook = _SETUP_RUNBOOK.read_text(encoding="utf-8")
    heading = f"#### `{check_id}`"
    assert heading in runbook, f"check-runbook.md に {check_id} の節が無い"
    return runbook.split(heading, 1)[1].split("\n#### ", 1)[0]


def _load_setup_chain_state() -> ModuleType:
    spec = importlib.util.spec_from_file_location("setup_chain_state", _SETUP_CHAIN_STATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    end = text.find("\n---", 4)
    assert text.startswith("---\n")
    assert end != -1
    parsed = yaml.safe_load(text[4:end])
    assert isinstance(parsed, dict)
    return parsed


def test_onboard_skill_directory_is_removed() -> None:
    assert not os.path.lexists(_ONBOARD_DIR)


def test_setup_skill_frontmatter_matches_directory_name() -> None:
    frontmatter = _frontmatter(_SETUP_SKILL)
    assert frontmatter["name"] == "setup"


def test_setup_skill_declares_all_exclusive_modes_and_default_chain() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    description = _frontmatter(_SETUP_SKILL)["description"]

    assert "--tool" in description
    assert "--import" in description
    assert "--regenerate" in description
    assert "--push" in description
    assert "2 個以上なら、同じ flag の重複を含めて排他違反として停止" in text
    assert "1 個なら対応する reference を読み、その一段だけを実行する" in text
    assert "0 個なら chain manifest に従い `tool` → `channel` を状態判定付きで進める" in text
    assert "| `--tool` | `references/tool.md` |" in text
    assert "| `--channel` | `references/channel-mode.md` |" in text
    assert "| `--import` | `references/import-mode.md` |" in text
    assert "| `--regenerate` | `references/regeneration-mode.md` |" in text
    assert "| `--push` | `references/push-mode.md` |" in text


def test_setup_explicit_modes_never_enter_the_default_chain() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")

    assert "明示 mode はこの一括実行へ入らない" in text
    assert "もう一段を暗黙実行しない" in text
    assert "各 reference 内の不可逆操作・外部反映の承認 gate" in text


@pytest.mark.parametrize(
    "arguments",
    [
        ("--tool", "--channel"),
        ("--import", "--regenerate"),
        ("--push", "--push"),
        ("--channel", "--push"),
    ],
)
def test_setup_mode_guard_rejects_multiple_modes_without_artifact_mutation(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    artifact = tmp_path / "config" / "channel" / "meta.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"sentinel": true}\n', encoding="utf-8")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    result = subprocess.run(
        [sys.executable, str(_SETUP_MODE_GUARD), *arguments],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert result.returncode == 2
    assert '"reason": "exclusive_mode"' in result.stderr
    assert after == before


@pytest.mark.parametrize(
    ("arguments", "mode"),
    [
        ((), "default"),
        (("--tool",), "--tool"),
        (("--channel",), "--channel"),
        (("--import",), "--import"),
        (("--regenerate",), "--regenerate"),
        (("--push",), "--push"),
    ],
)
def test_setup_mode_guard_resolves_each_exclusive_mode(arguments: tuple[str, ...], mode: str) -> None:
    result = subprocess.run(
        [sys.executable, str(_SETUP_MODE_GUARD), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"status": "ok", "mode": mode}


def test_setup_chain_manifest_declares_default_chain_and_mode_only_steps() -> None:
    manifest = json.loads(_SETUP_CHAIN_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["chainId"] == "setup"
    assert [step["id"] for step in manifest["steps"]] == ["tool", "channel", "import", "regenerate", "push"]
    assert [step["id"] for step in manifest["steps"] if step["defaultChain"]] == ["tool", "channel"]
    tool, channel, imported, regenerated, pushed = manifest["steps"]
    assert tool["prerequisiteArtifacts"] == []
    assert channel["prerequisiteArtifacts"] == tool["outputArtifacts"]
    assert {
        "doctor:automation_package",
        "doctor:skills_synced",
        "doctor:gcp_project",
        "doctor:adc",
        "auth/client_secrets.json",
        "auth/token.json",
    }.issubset(tool["outputArtifacts"])
    assert {
        "config/channel/meta.json",
        "config/channel/analytics.json",
        "doctor:channel_config",
        "docs/channel/ttp-seed-confirmation.md",
        "docs/channel/competitor-branding-snapshot.json",
        "docs/channel/personas/persona-definition.json",
        "docs/channel/personas/persona-definition.html",
        "branding/icon.*",
        "branding/banner.*",
        "doctor:ttp_wf_new_readiness",
        "git:clean",
    }.issubset(channel["outputArtifacts"])
    assert all(step["approvalGate"]["skip"] is True for step in manifest["steps"])
    assert {step["idempotency"]["script"] for step in manifest["steps"]} == {"references/setup-chain-state.py"}
    assert imported["reference"] == "references/import-mode.md"
    assert regenerated["reference"] == "references/regeneration-mode.md"
    assert pushed["reference"] == "references/push-mode.md"


def test_setup_owns_import_regenerate_and_push_execution_contracts() -> None:
    setup = _SETUP_SKILL.read_text(encoding="utf-8")
    imported = _SETUP_IMPORT_MODE.read_text(encoding="utf-8")
    regenerated = _SETUP_REGENERATE_MODE.read_text(encoding="utf-8")
    pushed = _SETUP_PUSH_MODE.read_text(encoding="utf-8")

    assert "取り込み Step 1 前段" in imported and "取り込み Step 8" in imported
    assert "Step R1" in regenerated and "Step R8" in regenerated
    assert "yt-channel-settings push --apply" in pushed
    assert "ユーザー承認後だけ実反映" in pushed
    assert "市場・収集済みデータ分析は `/channel-research --market`" in setup
    assert "方向性検討は `/channel-strategy --direction`" in setup


def test_setup_chain_state_runs_unresolved_tool_and_skips_ready_tool(tmp_path: Path) -> None:
    state = _load_setup_chain_state()
    manifest = state.load_manifest(_SETUP_CHAIN_MANIFEST)
    unresolved = [
        doctor.CheckResult(id=check_id, status="fail" if check_id == "uv" else "ok", message=check_id)
        for check_id in state.TOOL_CHECK_IDS
    ]
    ready = [doctor.CheckResult(id=check_id, status="ok", message=check_id) for check_id in state.TOOL_CHECK_IDS]
    for artifact in manifest["steps"][0]["outputArtifacts"]:
        if not artifact.startswith("doctor:"):
            path = tmp_path / artifact
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ready\n", encoding="utf-8")

    run_code, run_result = state.evaluate(tmp_path, unresolved, manifest, "tool")
    skip_code, skip_result = state.evaluate(tmp_path, ready, manifest, "tool")

    assert (run_code, run_result["decision"], run_result["reason"]) == (
        state.EXIT_RUN,
        "run",
        "tool_checks_unresolved",
    )
    assert run_result["checks"] == [{"id": "uv", "status": "fail"}]
    assert (skip_code, skip_result["decision"], skip_result["reason"]) == (
        state.EXIT_SKIP,
        "skip",
        "tool_ready",
    )
    assert skip_result["checks"] == []


def test_setup_chain_state_preserves_stale_analytics_completion_exception(tmp_path: Path) -> None:
    state = _load_setup_chain_state()
    manifest = state.load_manifest(_SETUP_CHAIN_MANIFEST)
    checks = [doctor.CheckResult(id=check_id, status="ok", message=check_id) for check_id in state.TOOL_CHECK_IDS]
    checks.append(
        doctor.CheckResult(id="analytics_report", status="fail", message="stale report"),
    )
    for artifact in manifest["steps"][0]["outputArtifacts"]:
        if not artifact.startswith("doctor:"):
            path = tmp_path / artifact
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ready\n", encoding="utf-8")

    code, result = state.evaluate(tmp_path, checks, manifest, "tool")

    assert code == state.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["reason"] == "tool_ready_analytics_report_stale"
    assert result["checks"] == [{"id": "analytics_report", "status": "fail"}]


def test_setup_chain_state_is_idempotent_for_the_same_doctor_state(tmp_path: Path) -> None:
    state = _load_setup_chain_state()
    manifest = state.load_manifest(_SETUP_CHAIN_MANIFEST)
    checks = [
        doctor.CheckResult(id=check_id, status="warn" if check_id == "oauth_token" else "ok", message=check_id)
        for check_id in state.TOOL_CHECK_IDS
    ]

    first = state.evaluate(tmp_path, checks, manifest, "tool")
    second = state.evaluate(tmp_path, checks, manifest, "tool")

    assert first == second


def test_setup_skill_description_mentions_new_and_legacy_commands() -> None:
    description = _frontmatter(_SETUP_SKILL)["description"]
    assert "/setup" in description
    assert "/onboard" in description
    assert "--channel" in description
    assert "新規 YouTube チャンネル" in description


def test_setup_skill_uses_uv_run_for_automation_commands() -> None:
    text = _setup_text()
    assert "uv run yt-doctor --apply --json" in text
    assert "uv run yt-oauth" in text
    assert "uv run yt-channel-status" in text

    bare_command_patterns = [
        r"`yt-doctor --apply --json`",
        r"(?m)^yt-channel-status$",
        r"`yt-channel-status`",
        r"(?m)>\s+\d+\.\s+yt-channel-status\b",
    ]
    for pattern in bare_command_patterns:
        assert re.search(pattern, text) is None


def test_setup_skill_follows_skills_synced_next_action_contract() -> None:
    text = _setup_text()
    section = text.split("#### `skills_synced`", 1)[1].split("#### `numbered_duplicates`", 1)[0]
    assert '`apply.next_action.kind == "human"`' in section
    assert "利用者が実行を承認した場合だけ `--apply` が自動実行する" in section
    assert "apply.next_action.instructions" in section
    assert "uv run yt-skills sync --asset auth-template" in text
    assert "uv run yt-setup-dirs" in text
    assert "uv run yt-skills sync --asset skills --force --prune --yes" in text
    assert "通常の `--force` sync では削除されない" in text
    assert "`.agents/skills` が `.claude/skills` を指す symlink" in text
    assert "「prune を実行」/「中止」の 2 択" in section
    assert "承認されるまで `--apply` を実行しない" in section


def test_setup_skill_handles_reporting_job_next_action_and_rechecks() -> None:
    text = _setup_text()
    assert "#### `reporting_job`" in text
    assert "uv run yt-analytics --reporting-create-job" in text
    reporting_step = text.index("#### `reporting_job`")
    next_step = text.find("\n#### `", reporting_step + 1)
    section = text[reporting_step : next_step if next_step != -1 else None]
    assert "`--apply` が以下を自動実行" in section
    assert "`--apply` が再診断して次の check へ進む" in section


def test_setup_skill_branches_on_all_apply_stop_reasons() -> None:
    text = _setup_text()
    startup = text.split("## 起動時のチェック", 1)[1].split("## 認証コマンドと人間操作の責務", 1)[0]

    for stop_reason in ("completed", "human_required", "decision_required", "command_failed"):
        assert f"`{stop_reason}`:" in startup
    assert "`apply.check_id`" in startup
    assert "`apply.cmd` / `apply.stderr`" in startup
    assert "--project-id <project-id>" in startup
    assert "以後 `completed` まで全 flag を毎回付け" in startup
    assert "uv run yt-doctor --apply --json --project-id <project-id>" in startup


def test_setup_skill_keeps_a_single_approval_gate_without_gcp_plan_approval() -> None:
    """#4934 `single-gate-no-gcp-plan`: 承認は起動時の 1 gate のみで、GCP 変更 plan の再承認を持たない."""
    tool = _SETUP_TOOL.read_text(encoding="utf-8")
    startup = tool.split("## 起動時のチェック", 1)[1].split("## 認証コマンドと人間操作の責務", 1)[0]

    # 単一 gate は残り、警告文は 3 層再編後の文言になっている
    assert "AskUserQuestion により「表示した変更を実行」/「中止」の明示 2 択" in startup
    assert "「prune は列挙したファイルを削除し、Reporting job は YouTube 側に作成される」と警告する" in startup
    assert "承認されなければここで停止する" in startup

    # GCP 変更 plan の承認節と再承認ループは、節名を変えた形でも復活させない
    assert "GCP 変更 plan" not in tool
    assert "再承認" not in tool
    # decision_required は `gcp_project` の `--project-id` 1 問だけに縮める（project 作成の承認を持たない）
    decision = startup.split("`decision_required`:", 1)[1].split("`command_failed`:", 1)[0]
    assert "--project-id <project-id>" in decision
    assert "マシン層の project 選択" in decision
    for mutation in ("gcloud projects create", "billing projects link", "services enable"):
        assert mutation not in decision, f"decision_required に GCP 層の変更コマンド {mutation!r} が残っている"


def test_setup_runbook_routes_gcp_layer_checks_to_upstream_terraform() -> None:
    """#4934 `runbook-routes-to-terraform`: GCP 層 4 節が変更コマンドを持たず上流 Terraform へ誘導する."""
    # GCP 層の変更コマンドを runbook 側に複製しない（terraform コマンドの実行手順も置かない）
    for check_id in ("gcp_project", "billing_linked", "apis_enabled", "iam_aiplatform_user"):
        section = _runbook_section(check_id)
        assert "infra/terraform/gcp/" in section, f"{check_id} の節に上流 Terraform への誘導が無い"
        for mutation in (
            "gcloud projects create",
            "gcloud services enable",
            "gcloud beta billing",
            "billing projects link",
            "add-iam-policy-binding",
            "terraform apply",
        ):
            assert mutation not in section, f"{check_id} の節に変更コマンド {mutation!r} が残っている"

    # gcp_project はマシン層の project 選択だけを行い、project 自体は上流の責務と明示する
    gcp_project = _runbook_section("gcp_project")
    assert "uv run yt-doctor --apply --json --project-id <project-id>" in gcp_project
    assert "project 自体の作成・変更は GCP 層の責務として上流 `infra/terraform/gcp/` が管理する" in gcp_project

    # 残る 3 節は同一の誘導文。1 箇所だけ書き換えたときの追従漏れをここで機械担保する
    routing = (
        "GCP 層は上流 `infra/terraform/gcp/` が管理する。fail なら `next_action.url` の README に従って"
        "上流で plan → apply を行い、完了後に `uv run yt-doctor --json` で再診断する。"
    )
    for check_id in ("billing_linked", "apis_enabled", "iam_aiplatform_user"):
        assert routing in _runbook_section(check_id), f"{check_id} の節が上流 Terraform への誘導文と一致しない"


def test_setup_skill_gates_numbered_duplicate_deletion() -> None:
    text = _setup_text()
    section = text.split("#### `numbered_duplicates`", 1)[1].split("### api カテゴリ", 1)[0]

    assert "実在パスを 1 件ずつ列挙" in section
    assert "「列挙した対象を削除」/「中止」の 2 択" in section
    assert "承認されるまで削除しない" in section


def test_setup_skill_keeps_pre_doctor_bootstrap_in_skill() -> None:
    text = _SETUP_TOOL.read_text(encoding="utf-8")
    startup = text.split("## 起動時のチェック", 1)[1].split("## 認証コマンドと人間操作の責務", 1)[0]

    assert "`pyproject.toml` が無ければ `uv init`" in startup
    assert "uv add git+https://github.com/daiki-beppu/youtube-automation.git" in startup
    assert "uv run yt-skills sync --asset skills --force" in startup
    assert startup.index("uv run yt-skills sync") < startup.index("uv run yt-doctor --apply --json")


def test_setup_skill_keeps_command_execution_out_of_human_role() -> None:
    text = _setup_text()
    responsibility = text.split("## 認証コマンドと人間操作の責務", 1)[1].split("## [HUMAN STEP]", 1)[0]

    assert "すべてのコマンドの起動・実行・再診断は AI または setup スクリプトが担当" in text
    assert "利用者へ実行を依頼してはならない" in responsibility
    assert "PTY 付きの対話 session" in responsibility
    assert "人間は開いたブラウザでログイン・アカウント選択・OAuth 同意だけ" in responsibility
    assert "あなたのターミナル" not in text
    for command in (
        "gcloud auth login",
        "gcloud auth application-default login",
        "uv run yt-oauth",
    ):
        assert command in responsibility


def test_setup_skill_drives_youtube_oauth_in_background() -> None:
    text = _setup_text()
    oauth = text.split("#### `oauth_token`", 1)[1].split("#### `reporting_job`", 1)[0]

    assert "uv run yt-oauth" in oauth
    assert "background session" in oauth
    assert "stdout" in oauth
    assert "同意 URL" in oauth
    assert "ブラウザ認証だけ" in oauth
    assert "exit 0" in oauth
    assert "uv run yt-doctor --apply --json <apply_flags>" in oauth


def test_setup_skill_delegates_minimum_directory_generation_to_setup() -> None:
    text = _setup_text()
    assert "`/setup` は `uv run yt-setup-dirs`" in text
    assert "`/setup --tool` では `config/channel/*.json` を生成しない" in text
    assert "OAuth クライアント JSON の配置先 `auth/`" in text


def test_skills_use_uv_run_for_doctor_json() -> None:
    offenders: list[str] = []
    for skill_md in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        lines = skill_md.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if "yt-doctor --json" in line and "uv run yt-doctor --json" not in line:
                relative_path = skill_md.relative_to(_REPO_ROOT)
                offenders.append(f"{relative_path}:{line_number}: {line.strip()}")

    assert offenders == []


def test_legacy_onboard_reference_is_limited_to_setup_description() -> None:
    offenders: list[str] = []
    for skill_md in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        if "/onboard" in text and skill_md != _SETUP_SKILL:
            offenders.append(str(skill_md.relative_to(_REPO_ROOT)))
    assert offenders == []


def test_current_setup_docs_do_not_route_to_legacy_onboard() -> None:
    offenders: list[str] = []
    for doc in _CURRENT_SETUP_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert "/setup" in text
        if "/onboard" in text:
            offenders.append(str(doc.relative_to(_REPO_ROOT)))

    assert offenders == []


def test_setup_channel_gate_does_not_require_doctor_all_green() -> None:
    text = _SETUP_CHANNEL_MODE.read_text(encoding="utf-8")
    assert "summary.next_check_id" not in text
    assert (
        "`channel_config`: `config/channel/ ディレクトリが存在しない "
        "(新規チャンネル、setup 用ディレクトリのみでは未生成)`"
    ) in text
    assert "`upload_ready`: `config/channel/meta.json が存在しない`" in text
    assert "`upload_ready`: `channel.channel_id が未設定`" in text
    assert "`upload_ready` が `auth/token.json が存在しない`" in text
    assert "`upload 必須 scope 不足`" in text

    required_check_ids = {
        "ffmpeg",
        "ffprobe",
        "uv",
        "uv_project",
        "automation_package",
        "skills_synced",
        "gcloud",
        "gcloud_account",
        "gcp_project",
        "billing_linked",
        "apis_enabled",
        "adc",
        "adc_quota_project",
        "iam_aiplatform_user",
        "env_file",
        "client_secrets",
        "oauth_token",
    }
    for check_id in required_check_ids:
        assert f"`{check_id}`" in text


def test_setup_skill_handles_ttp_wf_new_readiness_next_check() -> None:
    text = _setup_text()
    assert (
        "（analytics_report / benchmark_data / ttp_wf_new_readiness / wf_new_readiness / "
        "initial_setup_readiness）" in text
    )
    assert "#### `ttp_wf_new_readiness` — 承認済み TTP の `/setup --regenerate` benchmark 反映状態" in text
    assert "/setup --regenerate benchmark 反映未完了" in text
    assert "`config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default`" in text
    assert "`data/thumbnail_compare/benchmark/`" in text
    assert "uv run yt-doctor --apply --json" in text


def test_setup_skill_handles_wf_new_readiness_next_check() -> None:
    text = _setup_text()
    section = text.split("#### `wf_new_readiness`", 1)[1].split("\n#### `initial_setup_readiness`", 1)[0]

    assert "`ttp_mode: true` × `minimal mode`" in section
    assert '`next_action.kind == "human"`' in section
    assert section.index("benchmark.channels") < section.index("/channel-research --benchmark")
    assert section.index("/channel-research --benchmark") < section.index("yt-doctor --json")
    assert "persona 文書の有無も停止条件に加えない" in section
    assert "`benchmark_data` / `analytics_report` / `ttp_wf_new_readiness` の意味を変更せず" in section


def test_setup_stale_report_guidance_delegates_to_wf_new_ideation_contract() -> None:
    setup = _setup_text()
    freshness_rules = _FRESHNESS_RULES.read_text(encoding="utf-8")
    analytics_report_section = setup.split("#### `analytics_report`", 1)[1].split("\n#### `benchmark_data`", 1)[0]

    assert ".claude/skills/wf-new/references/freshness-rules.md" in analytics_report_section
    assert "後続の `/wf-new` 企画工程が同じセッションで自動更新する" in analytics_report_section
    assert "`[HUMAN STEP]` として `/analytics --analyze` の実行を利用者へ依頼せず" in analytics_report_section
    assert "freshness.stale_action" not in setup
    assert "refresh / API 失敗時の停止・再開条件は上書きしない" in analytics_report_section

    assert "stale report の自動更新" in freshness_rules
    assert "同じセッションで自動実行" in freshness_rules
    assert "skill 呼び出し失敗または再検証失敗時" in freshness_rules

    assert "stale ではない → analytics mode" in analytics_report_section
    assert "検証済み `reports/analysis_*.json` が無く、`data/benchmark_*.json` がある → benchmark fallback mode" in (
        analytics_report_section
    )
    assert (
        "検証済み `reports/analysis_*.json` と `data/benchmark_*.json` がどちらも無い → minimal mode"
        in analytics_report_section
    )

    assert setup.count("`apply.stop_reason` が `completed`") == 1
    assert setup.count("`analytics_report` の stale fail だけ") == 1
    assert '`apply.stop_reason == "human_required"`' in analytics_report_section
    assert '`apply.check_id == "analytics_report"`' in analytics_report_section


def test_setup_skill_handles_upload_ready_channel_not_found() -> None:
    text = _setup_text()
    section = text.split("#### `upload_ready`", 1)[1].split("## 運用設定インタビュー", 1)[0]

    assert '`data.reason == "channel_not_found"`' in section
    assert "YouTube Studio" in section
    assert "https://studio.youtube.com" in section
    assert "チャンネルを作成" in section
    assert "uv run yt-doctor --apply --json" in section
    assert "[HUMAN STEP]" in section


def test_setup_skill_routes_remote_id_into_meta_via_existing_command() -> None:
    text = _setup_text()
    section = text.split("#### `upload_ready`", 1)[1].split("## 運用設定インタビュー", 1)[0]

    assert "`data.remote_channel_id`" in section
    assert "`channel.channel_id が未設定`" in section
    assert "uv run yt-channel-settings pull --channel-id-only --apply" in section
    assert "取得した ID を `config/channel/meta.json`" not in section


def test_setup_skill_does_not_auto_overwrite_mismatched_channel_id() -> None:
    text = _setup_text()
    section = text.split("#### `upload_ready`", 1)[1].split("## 運用設定インタビュー", 1)[0]

    assert '`data.reason == "channel_id_mismatch"`' in section
    assert "自動上書きしない" in section
    assert "uv run yt-channel-settings pull --channel-id-only` で dry-run" in section
    assert "uv run yt-channel-settings pull --channel-id-only --apply" in section
    assert "auth/token.json" in section
    assert "uv run yt-oauth" in section


def test_setup_skill_keeps_api_errors_distinct_from_missing_channel() -> None:
    text = _setup_text()
    section = text.split("#### `upload_ready`", 1)[1].split("## 運用設定インタビュー", 1)[0]

    assert '`data.reason == "api_error"`' in section
    assert "チャンネル未作成として扱わない" in section
    assert "quota" in section
    assert "auth" in section
    assert "network" in section
    assert "uv run yt-doctor --apply --json" in section
