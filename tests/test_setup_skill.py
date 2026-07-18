"""Issue #1273: onboard から setup への skill rename 契約テスト。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from youtube_automation.cli import doctor

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
_SETUP_SKILL = _SKILLS_DIR / "setup" / "SKILL.md"
_FRESHNESS_RULES = _SKILLS_DIR / "collection-ideate" / "references" / "freshness-rules.md"
_CHANNEL_NEW_SKILL = _SKILLS_DIR / "channel-new" / "SKILL.md"
_ONBOARD_DIR = _SKILLS_DIR / "onboard"
_CURRENT_SETUP_DOCS = [
    _REPO_ROOT / "ONBOARDING.md",
    _REPO_ROOT / "auth" / "SETUP.md",
    _REPO_ROOT / "infra" / "terraform" / "gcp" / "README.md",
]


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


def test_setup_skill_description_mentions_new_and_legacy_commands() -> None:
    description = _frontmatter(_SETUP_SKILL)["description"]
    assert "/setup" in description
    assert "/onboard" in description
    assert "/channel-new" in description
    assert "config・ペルソナ・branding" in description


def test_setup_skill_uses_uv_run_for_automation_commands() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert "uv run yt-doctor --apply --json" in text
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
    text = _SETUP_SKILL.read_text(encoding="utf-8")
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
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert "#### `reporting_job`" in text
    assert "uv run yt-analytics --reporting-create-job" in text
    reporting_step = text.index("#### `reporting_job`")
    next_step = text.find("\n#### `", reporting_step + 1)
    section = text[reporting_step : next_step if next_step != -1 else None]
    assert "`--apply` が以下を自動実行" in section
    assert "`--apply` が再診断して次の check へ進む" in section


def test_setup_skill_branches_on_all_apply_stop_reasons() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    startup = text.split("## 起動時のチェック", 1)[1].split("## AI が絶対に", 1)[0]

    for stop_reason in ("completed", "human_required", "decision_required", "command_failed"):
        assert f"`{stop_reason}`:" in startup
    assert "`apply.check_id`" in startup
    assert "`apply.cmd` / `apply.stderr`" in startup
    assert "--project-id <project-id>" in startup
    assert "--billing-account <billing-id>" in startup
    assert "以後 `completed` まで全 flag を毎回付け" in startup
    assert "uv run yt-doctor --apply --json --project-id <project-id> --billing-account <billing-id>" in startup


def test_setup_skill_requires_approval_before_apply_mutations() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    startup = text.split("## 起動時のチェック", 1)[1].split("## AI が絶対に", 1)[0]

    assert "uv run yt-doctor --json" in startup
    assert "AskUserQuestion" in startup
    assert "「表示した変更を実行」/「中止」の明示 2 択" in startup
    assert "GCP 変更は外部反映" in startup
    assert "prune は列挙したファイルを削除" in startup
    assert startup.index("uv run yt-doctor --json") < startup.index("uv run yt-doctor --apply --json")


def test_setup_skill_reapproves_project_scoped_plan_after_decisions() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    startup = text.split("## 起動時のチェック", 1)[1].split("## AI が絶対に", 1)[0]
    plan = startup.split("### GCP 変更 plan の承認", 1)[1]

    assert "`--project-id` / `--billing-account` を追加・変更するたび" in plan
    assert "正確な project ID" in plan
    assert "active account" in plan
    for mutation in ("Billing 紐付け", "API 有効化", "ADC quota project", "IAM 付与", "Reporting job 作成"):
        assert mutation in plan
    assert "「表示した GCP 変更を実行」/「中止」の 2 択" in plan
    assert "承認されるまで flag 付き `--apply` を実行しない" in plan
    assert "前回の承認を無効" in plan


def test_setup_skill_gates_numbered_duplicate_deletion() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    section = text.split("#### `numbered_duplicates`", 1)[1].split("### api カテゴリ", 1)[0]

    assert "実在パスを 1 件ずつ列挙" in section
    assert "「列挙した対象を削除」/「中止」の 2 択" in section
    assert "承認されるまで削除しない" in section


def test_setup_skill_keeps_pre_doctor_bootstrap_in_skill() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    startup = text.split("## 起動時のチェック", 1)[1].split("## AI が絶対に", 1)[0]

    assert "`pyproject.toml` が無ければ `uv init`" in startup
    assert "uv add git+https://github.com/daiki-beppu/youtube-automation.git" in startup
    assert "uv run yt-skills sync --asset skills --force" in startup
    assert startup.index("uv run yt-skills sync") < startup.index("uv run yt-doctor --apply --json")


def test_setup_skill_delegates_minimum_directory_generation_to_setup() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert "`/setup` は `uv run yt-setup-dirs`" in text
    assert "`/setup` では `config/channel/*.json` を生成しない" in text
    assert "OAuth クライアント JSON の配置先 `auth/`" in text


def test_setup_skill_enables_doctor_required_apis() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")

    for api_name in doctor.REQUIRED_APIS:
        assert api_name in text


def test_setup_skill_suggests_gcp_project_id_from_channel_name() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert "`config/channel/meta.json` の `channel.name`" in text
    assert "`yt-{channel-slug}`" in text
    assert "kebab-case" in text
    assert "6-30 文字" in text
    assert "`--name`): `{チャンネル名} YouTube`" in text
    assert "承認またはカスタム入力" in text


def test_setup_skill_requires_explicit_project_creation_approval() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    section = text.split("#### `gcp_project`", 1)[1].split("#### `billing_linked`", 1)[0]

    assert "決定した project ID と表示名を示し" in section
    assert "Google Cloud に外部 resource を作成" in section
    assert "AskUserQuestion" in section
    assert "「project を作成」/「中止」の明示 2 択" in section
    assert "作成が承認されるまで次のコマンドを実行しない" in section


def test_setup_project_and_billing_sections_route_through_plan_approval() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    project = text.split("#### `gcp_project`", 1)[1].split("#### `billing_linked`", 1)[0]
    billing = text.split("#### `billing_linked`", 1)[1].split("#### `apis_enabled`", 1)[0]

    for section in (project, billing):
        assert "必ず先に「GCP 変更 plan の承認」へ戻る" in section
        assert "AskUserQuestion で実行が承認された後だけ" in section
        assert "中止ならここで停止する" in section


def test_setup_skill_suggests_oauth_app_and_client_names() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert "`gcp_project` と同じルールでチャンネル名を解決" in text
    assert "`{チャンネル名} YouTube Automation`" in text
    assert "`{チャンネル名} Desktop Client`" in text
    assert "Google Auth Platform > Branding のアプリ名: <channel-name> YouTube Automation" in text
    assert "OAuth クライアント ID 名: <channel-name> Desktop Client" in text
    assert "OAuth 同意画面のアプリ名: <channel-name> YouTube Automation" not in text


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


def test_channel_new_setup_gate_does_not_require_doctor_all_green() -> None:
    text = _CHANNEL_NEW_SKILL.read_text(encoding="utf-8")
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
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert (
        "`data` | `/wf-new` の入力モード判定データ + 初期セットアップ事前検査"
        "（analytics_report / benchmark_data / ttp_wf_new_readiness / initial_setup_readiness）" in text
    )
    assert "#### `ttp_wf_new_readiness` — 承認済み TTP の `/channel-new` benchmark 反映状態" in text
    assert "/channel-new benchmark 反映未完了" in text
    assert "`config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default`" in text
    assert "`data/thumbnail_compare/benchmark/`" in text
    assert "uv run yt-doctor --apply --json" in text


def test_setup_stale_report_guidance_delegates_to_collection_ideate_contract() -> None:
    setup = _SETUP_SKILL.read_text(encoding="utf-8")
    freshness_rules = _FRESHNESS_RULES.read_text(encoding="utf-8")
    analytics_report_section = setup.split("#### `analytics_report`", 1)[1].split("\n#### `benchmark_data`", 1)[0]

    assert ".claude/skills/collection-ideate/references/freshness-rules.md" in analytics_report_section
    assert "後続の `/collection-ideate` が同じセッションで自動更新する" in analytics_report_section
    assert "`[HUMAN STEP]` として `/analytics-analyze` の実行を利用者へ依頼せず" in analytics_report_section
    assert "freshness.stale_action" not in setup
    assert "refresh / API 失敗時の停止・再開条件は上書きしない" in analytics_report_section

    assert "stale report の自動更新" in freshness_rules
    assert "同じセッションで自動実行" in freshness_rules
    assert "skill 呼び出し失敗または再検証失敗時" in freshness_rules

    assert "stale ではない → analytics mode" in analytics_report_section
    assert "`reports/analysis_*.md` が無く、`data/benchmark_*.json` がある → benchmark fallback mode" in (
        analytics_report_section
    )
    assert (
        "`reports/analysis_*.md` と `data/benchmark_*.json` がどちらも無い → minimal mode" in analytics_report_section
    )

    assert setup.count("`apply.stop_reason` が `completed`") == 1
    assert setup.count("`analytics_report` の stale fail だけ") == 1
    assert '`apply.stop_reason == "human_required"`' in analytics_report_section
    assert '`apply.check_id == "analytics_report"`' in analytics_report_section


def test_setup_skill_handles_upload_ready_channel_not_found() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    section = text.split("#### `upload_ready`", 1)[1].split("## 運用設定インタビュー", 1)[0]

    assert '`data.reason == "channel_not_found"`' in section
    assert "YouTube Studio" in section
    assert "https://studio.youtube.com" in section
    assert "チャンネルを作成" in section
    assert "uv run yt-doctor --apply --json" in section
    assert "[HUMAN STEP]" in section


def test_setup_skill_routes_remote_id_into_meta_via_existing_command() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    section = text.split("#### `upload_ready`", 1)[1].split("## 運用設定インタビュー", 1)[0]

    assert "`data.remote_channel_id`" in section
    assert "`channel.channel_id が未設定`" in section
    assert "uv run yt-channel-settings pull --channel-id-only --apply" in section
    assert "取得した ID を `config/channel/meta.json`" not in section


def test_setup_skill_does_not_auto_overwrite_mismatched_channel_id() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    section = text.split("#### `upload_ready`", 1)[1].split("## 運用設定インタビュー", 1)[0]

    assert '`data.reason == "channel_id_mismatch"`' in section
    assert "自動上書きしない" in section
    assert "uv run yt-channel-settings pull --channel-id-only` で dry-run" in section
    assert "uv run yt-channel-settings pull --channel-id-only --apply" in section
    assert "auth/token.json" in section
    assert "uv run yt-channel-status" in section


def test_setup_skill_keeps_api_errors_distinct_from_missing_channel() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    section = text.split("#### `upload_ready`", 1)[1].split("## 運用設定インタビュー", 1)[0]

    assert '`data.reason == "api_error"`' in section
    assert "チャンネル未作成として扱わない" in section
    assert "quota" in section
    assert "auth" in section
    assert "network" in section
    assert "uv run yt-doctor --apply --json" in section
