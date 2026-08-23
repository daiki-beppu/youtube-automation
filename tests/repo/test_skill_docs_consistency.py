import json
import logging
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.configuration import skills as skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

ROOT = REPO_ROOT
SKILL_INVENTORY = SkillInventory(ROOT)


def test_all_skills_use_machine_readable_chain_block() -> None:
    skill_paths = [path / "SKILL.md" for path in SKILL_INVENTORY.skill_directories()]
    chain_block = re.compile(
        r"\A---\n.*?\n---\n\n## 前後工程\n\n"
        r"- `前工程`: (?P<upstream>[^\n]+)\n"
        r"- `後工程`: (?P<downstream>[^\n]+)\n",
        re.DOTALL,
    )
    chain_reference = r"`/[a-z0-9-]+(?: --[a-z0-9-]+)?`"
    chain_value = re.compile(
        rf"^(?:`なし`|`\*`（共通基盤としてほぼ全スキル）|"
        rf"{chain_reference}(?:, {chain_reference})*)$"
    )
    known_skills = {path.parent.name for path in skill_paths}

    assert skill_paths
    for path in skill_paths:
        text = path.read_text(encoding="utf-8")
        match = chain_block.match(text)
        assert match is not None, f"{path}: frontmatter 直後の前後工程ブロックが不正"
        for direction in ("upstream", "downstream"):
            value = match.group(direction)
            assert chain_value.fullmatch(value), f"{path}: {direction} の書式が不正: {value}"
            for reference in re.findall(r"`/([a-z0-9-]+)(?: --[a-z0-9-]+)?`", value):
                assert reference in known_skills, f"{path}: 存在しない skill 参照 /{reference}"


def test_skill_chain_legacy_summary_formats_are_absent() -> None:
    legacy_summary = re.compile(
        r"^\*\*(?:前|後)工程|^(?:前|後)工程は|^次工程は|^→ |"
        r"^- `/[^\n]+` → (?:前|後)工程|"
        r"^description:.*(?:前|後|次)工程[ :：]/",
        re.MULTILINE,
    )

    for skill_dir in SKILL_INVENTORY.skill_directories():
        path = skill_dir / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        assert legacy_summary.search(text) is None, f"{path}: 旧形式の前後工程一覧が残存"


def test_active_migration_docs_do_not_reference_removed_cli_paths() -> None:
    paths = (
        ROOT / "docs/development.md",
        ROOT / "docs/skill-design/skill-authoring-guidelines.md",
        ROOT / "extensions/distrokid-helper/lib/types.ts",
        ROOT / "extensions/distrokid-helper/lib/api.ts",
        ROOT / "extensions/distrokid-helper/tests/api.test.ts",
    )
    forbidden = re.compile(
        r"src/youtube_automation/(?:cli/automation_update_refs|cli/skills_sync|scripts/distrokid_release|"
        r"scripts/generate_loop_video|scripts/captions_upload|scripts/distrokid_prepare|scripts/collection_serve)"
    )
    for path in paths:
        assert forbidden.search(path.read_text(encoding="utf-8")) is None, path


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _markdown_section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^#{{2,4}}\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"section not found: {heading}"
    return match.group("body")


def _read_wf_new() -> str:
    return "\n".join(
        _read(path)
        for path in (
            ".claude/skills/wf-new/SKILL.md",
            ".claude/skills/wf-new/references/phase2.md",
        )
    )


def _assert_appears_before(text: str, earlier: str, later: str) -> None:
    earlier_idx = text.find(earlier)
    later_idx = text.find(later)
    assert earlier_idx >= 0, f"{earlier!r} not found"
    assert later_idx >= 0, f"{later!r} not found"
    assert earlier_idx < later_idx


def _skill_frontmatter(skill: str) -> dict:
    parsed = SKILL_INVENTORY.frontmatter(skill)
    assert isinstance(parsed, dict)
    return parsed


def _isolated_git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        cwd=repo,
        env=_isolated_git_env(),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_workflow_schema_references_existing_skill_schema() -> None:
    schema_path = ".claude/skills/wf-new/references/schema.md"
    assert (ROOT / schema_path).exists()

    for path in (".claude/skills/wf-next/SKILL.md", ".claude/skills/wf-status/SKILL.md"):
        text = _read(path)
        assert ".claude/references/workflow/schema.md" not in text
        assert schema_path in text


def test_wf_auto_is_the_integrated_entrypoint_without_copying_child_workflows() -> None:
    wf_auto = _read(".claude/skills/wf-new/references/auto.md")
    wf_new = _read_wf_new()
    wf_next = _read(".claude/skills/wf-next/SKILL.md")
    wf_status = _read(".claude/skills/wf-status/SKILL.md")
    schema = _read(".claude/skills/wf-new/references/schema.md")

    for child in ("wf-new", "music --generate", "music --master", "wf-next", "publish"):
        assert f"`/{child}`" in wf_auto
    assert "no_active_collection" in wf_auto
    assert "同じ run 内" in wf_auto
    assert "無人実行" in wf_auto
    assert "allow_external_publish" in wf_auto
    assert "references/wf-auto-state.py" in wf_auto
    assert "/wf-new --auto" in wf_new
    assert "/wf-new --auto" in wf_next
    assert "/wf-new --auto" in wf_status
    assert "/wf-new --auto" in schema


def test_wf_auto_is_the_only_integrated_workflow_entrypoint() -> None:
    canonical = _read(".claude/skills/wf-new/references/auto.md")
    features = _read("docs/features.md")
    cheatsheet = _read("docs/workflow-cheatsheet.md")

    assert "正規入口" in canonical
    assert not (ROOT / ".claude/skills/automation-run").exists()
    assert "正規入口" in features and "| /automation-run |" not in features
    assert "/wf-new --auto" in cheatsheet


def test_theme_compare_docs_and_error_use_content_tags_themes() -> None:
    for path in (
        ".claude/skills/analytics/references/analyze.md",
        "src/youtube_automation/commands/analytics/theme_compare.py",
    ):
        text = _read(path)
        assert "channel_config.tags.themes" not in text
        assert "config/channel/content.json::tags.themes" in text

    assert "load_config().content.tags.themes" in _read(".claude/skills/analytics/references/analyze.md")


def test_analytics_analyze_documents_playlist_effect_section() -> None:
    analytics_analyze = _read(".claude/skills/analytics/references/analyze.md")
    analytics_collect = _read(".claude/skills/analytics/references/collect.md")

    assert "分析項目」の全項目" in analytics_analyze
    assert "**プレイリスト効果分析**" in analytics_analyze
    assert "`playlist_analytics.playlists`" in analytics_analyze
    assert "`view_share_percent`" in analytics_analyze
    assert "`average_view_duration`" in analytics_analyze
    assert "`config/channel/playlists.json`" in analytics_analyze
    assert "原因であるとは断定しない" in analytics_analyze
    assert "上位 200 件内のシェア" in analytics_analyze
    assert "チャンネル全体に対するシェアとして扱わない" in analytics_analyze
    assert "視聴数上位 200 件のプレイリスト別 views・平均視聴時間・上位 200 件内の視聴シェア" in analytics_collect


def test_localizations_docs_use_root_localizations_file() -> None:
    for path in (
        ".claude/skills/wf-new/references/scene_phrases.md",
        "src/youtube_automation/commands/media/populate_scene_phrases.py",
    ):
        text = _read(path)
        assert "config/channel/localizations.json::supported_languages" not in text
        assert "config/localizations.json::supported_languages" in text


def test_wf_new_theme_scenes_fallback_uses_agent_generated_en_phrase() -> None:
    wf_new = _read_wf_new()

    assert "theme_scenes[<theme>] が未定義の場合" in wf_new
    assert '--en "<Agent-generated English scene phrase>"' in wf_new
    assert "--translations-file /tmp/scene-phrases.json" in wf_new


def test_upload_settings_contract_is_nested_in_schedule_config() -> None:
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    regeneration_mode = _read(".claude/skills/setup/references/regeneration-mode.md")
    channel_init = _read("src/youtube_automation/commands/channel/channel_init_templates.py")
    channel_init_test = _read("tests/commands/channel/test_channel_init.py")
    schedule_template = _read(".claude/skills/setup/references/schedule-template.json")

    for text in (setup_channel, regeneration_mode, channel_init, channel_init_test):
        assert "config/upload_settings.json" not in text

    assert "`config/schedule_config.json`（`upload_settings` を含む）" in setup_channel
    assert "投稿頻度と `upload_settings`" in regeneration_mode
    assert '"upload_settings": {' in schedule_template


def test_setup_directory_generation_contract_is_separate_from_channel_config() -> None:
    setup = _read(".claude/skills/setup/SKILL.md")
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    setup_dirs = _read("src/youtube_automation/commands/system/setup_dirs.py")
    channel_init = _read("src/youtube_automation/commands/channel/channel_init.py")
    setup_directory_contract = _read("src/youtube_automation/infrastructure/legacy_utils/setup_directory_contract.py")
    pyproject = _read("pyproject.toml")

    assert "uv run yt-setup-dirs" in setup
    assert "`--tool` では `config/channel/*.json` を生成しない" in setup
    assert "`/setup` が作成済みのディレクトリはそのまま再利用する" in setup_channel
    assert "setup_directory_contract" in setup_dirs
    assert "setup_directory_contract" in channel_init
    assert "SETUP_DIRECTORIES" in setup_directory_contract
    assert 'yt-setup-dirs = "youtube_automation.entrypoints:yt_setup_dirs"' in pyproject


def test_setup_channel_ttp_confirmation_contract_is_documented() -> None:
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    branding_snapshot_script = _read(".claude/skills/setup/references/fetch_branding_snapshot.py")

    for forbidden in ("--benchmark-channel", "uv run yt-discover-competitors", "uv run yt-benchmark-comments"):
        assert forbidden not in setup_channel
    for contract in (
        "TTP seed fetch と承認済み対象反映",
        "承認前に `benchmark.channels` へ書き込まない",
        "追加調査は後続スキルへ委譲",
        "docs/channel/ttp-seed-confirmation.md",
        "docs/channel/competitor-branding-snapshot.json",
        ".claude/skills/setup/references/fetch_branding_snapshot.py",
        "承認済み TTP 対象が 0 件の場合は Step 7 以降へ進まない",
        "relationship（何を転写するか）",
        "ttp_wf_new_readiness",
        "ユーザー承認済み例外",
    ):
        assert contract in setup_channel
    assert 'CHANNELS_PART = "snippet,brandingSettings,localizations"' in branding_snapshot_script
    assert '"untrusted_data": True' in branding_snapshot_script


def test_setup_channel_ttp_hearing_routes_direction_to_strategy_mode() -> None:
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    seed_details = _read(".claude/skills/setup/references/ttp-seed-and-duration.md")
    strategy = _read(".claude/skills/channel-strategy/SKILL.md")
    mode_routing = SKILL_INVENTORY.section("channel-strategy", "## モード判定")
    strategy_description = _skill_frontmatter("channel-strategy")["description"]
    direction_mode = _read(".claude/skills/channel-strategy/references/direction.md")
    ttp_principles = setup_channel.split("## TTP 原則", 1)[1].split("## 外部データの扱い", 1)[0]
    step1 = setup_channel.split("### Step 1: TTP ヒアリング", 1)[1].split(
        "### Step 2: 現在のディレクトリを repo 初期化",
        1,
    )[0]
    step4 = setup_channel.split("### Step 4: フルパッケージ config / 初期運用ファイル生成", 1)[1].split(
        "### Step 5: TTP seed fetch と承認済み対象反映",
        1,
    )[0]
    step7 = setup_channel.split("### Step 7: 本格ペルソナ作成チェーン", 1)[1].split(
        "### Step 8: branding 初回反映",
        1,
    )[0]

    assert "「どんなチャンネルにしたいか」より先に" not in ttp_principles
    assert "新規開設では方向性・差別化・ポジショニングを聞かず" in ttp_principles

    step1_questions = [line for line in step1.splitlines() if line.startswith("- **")]
    assert step1_questions == [
        "- **TTP したいチャンネル**: URL / handle / channel ID を 1 件以上",
        "- **branding 方針**: TTP 対象の description / keywords / localizations をどの程度転写するか",
    ]
    all_elements_default = "タイトル構造 / サムネ構図 / 投稿頻度 / 尺 / ジャンル / branding の全要素を TTP 準拠とする"
    assert f"既定値 `{all_elements_default}` を記録する" in step1
    assert f'--relationship "{all_elements_default}"' in setup_channel
    assert seed_details.count(f"`{all_elements_default}`") == 2
    assert "固定の既定値は実データ確認済みを意味しない" in seed_details
    for forbidden in ("方向性を聞く", "差別化を聞く", "ポジショニングを聞く"):
        assert forbidden not in step1
    for config_prompt in (
        "**仮チャンネル名と SHORT**",
        "**初期ジャンル情報**",
        "**動画尺**",
        "**音楽エンジン**",
        "**DistroKid 配信有無**",
        "**DistroKid 初期 profile**",
    ):
        assert config_prompt not in step1
        assert config_prompt in step4
    assert "検討が必要なら `/setup --channel` 完了後の方向性検討モードに委譲" in step1
    assert "Step 1 の TTP ヒアリングとは別に、config 生成に必要な初期値だけをここで確認する" in step4

    assert "`--direction`" in mode_routing
    for trigger in ("方向性決めたい", "ポジショニング", "差別化", "ブレスト"):
        assert trigger in strategy_description

    assert "references/direction.md" in strategy
    for heading in (
        "## Step D1: 分析レポートの読み込みとサマリー",
        "## Step D2: ポジショニング議論",
        "## Step D3: 決定事項の整理",
        "## Step D4: 方向性ドキュメント保存",
        "## Step D5: 次フェーズへの案内",
    ):
        assert heading in direction_mode
    assert "決定事項を検証済み `docs/channel/channel-direction.json` + `.html` pair に保存" in direction_mode
    assert "`mkdir -p docs/channel`" in direction_mode
    assert "config を再生成・再反映する場合は `/setup --regenerate`" in direction_mode
    assert "制作に進む場合は `/wf-new`" in direction_mode

    assert "/channel-research --voice` → `/channel-strategy --persona` → `/channel-strategy --scene" in step7
    assert "必須" in step7
    assert "docs/channel/personas/persona-definition.json" in step7
    assert "docs/channel/personas/persona-definition.html" in step7
    assert "Step 8 へ進まない" in step7
    assert "channel-new-persona.md" not in setup_channel

    audience_persona = _read(".claude/skills/channel-strategy/references/persona.md")
    assert "新規開設時" in audience_persona
    assert "競合チャンネルのコメント" in audience_persona
    assert "公開前" in audience_persona
    assert "channel-new-persona.md" not in audience_persona

    voice = _read(".claude/skills/channel-research/references/voice.md")
    assert "新規開設モードでは Step 7 の必須前工程" in voice
    assert "その互換入口である `/channel-strategy --direction` の新規開設モード" not in voice
    assert ".claude/skills/setup/references/persona-branding-readiness.md" in voice
    assert "公開後の再分析では" in voice
    assert "標準フローでは実行せず" not in voice

    assert "`/channel-direction`" not in strategy


def test_branding_missing_report_requires_existing_file_check_before_generation() -> None:
    skill_docs = {
        "setup-channel": _read(".claude/skills/setup/references/channel-mode.md"),
        "automation": _read(".claude/skills/automation/references/update.md"),
    }

    for text in skill_docs.values():
        assert "`branding/icon.png` / `branding/banner.png` の「未生成」" in text
        assert "新規生成の前に必ず `branding/` 配下の既存ファイルを確認" in text
        assert "同名 stem の別拡張子" in text
        assert "`icon.jpg` / `banner.webp`" in text
        assert "別サフィックス" in text
        assert "`banner-v2.jpg` / `banner-v3.png`" in text
        assert "複数候補がある場合はどれが最終版か人間に確認" in text
        assert "リネーム/変換" in text


def test_channel_strategy_frontmatter_includes_direction_dispatch_keywords() -> None:
    frontmatter = _skill_frontmatter("channel-strategy")
    assert frontmatter["name"] == "channel-strategy"
    description = frontmatter["description"]
    for keyword in ("方向性決めたい", "ポジショニング", "差別化", "ブレスト"):
        assert keyword in description
    for keyword in ("チャンネル取り込み", "channel-import", "設定反映", "branding push"):
        assert keyword not in description


def test_setup_channel_ttp_completion_condition_is_an_early_hard_gate() -> None:
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    completion_heading = "## 完了条件（--channel）"

    assert setup_channel.splitlines().index(completion_heading) < 60
    completion = setup_channel.split(completion_heading, 1)[1].split("## TTP 原則", 1)[0]
    assert "docs/channel/personas/persona-definition.json" in completion
    assert "docs/channel/personas/persona-definition.html" in completion
    assert "候補ごとの source、seed fetch 要約、承認 / 不採用判断" in completion
    assert "`snippet` / `brandingSettings` / `localizations` snapshot" in completion
    assert "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default" in completion
    assert "data/video_analysis/<slug>/*.json::suno_preset.genre_line" in completion


def test_channel_strategy_docs_distinguish_required_initial_persona_from_optional_reanalysis() -> None:
    features = _read("docs/features.md")
    onboarding = _read("ONBOARDING.md")

    assert (
        "`/setup` → `/channel-research --voice` → `/channel-strategy`"
        "（`--persona` → `--scene` → `--constraints`）→ `/wf-new`"
    ) in features
    assert "`/channel-research --voice` は公開後の再分析では任意" in features
    assert "公開前のペルソナチェーンは既存の競合 / TTP / viewer-voice 成果物を入力に完走" in features
    assert "公開後の `/channel-strategy --scene` は従来どおり Analytics report を要求する" in features
    assert "/channel-research --voice  → 公開後のコメント再分析" in onboarding
    assert "公開前チェーンは競合 / TTP / viewer-voice 成果物を入力" in onboarding
    assert "自チャンネル Analytics report や任意の本格 benchmark 収集を要求しない" in onboarding
    assert "公開後の見直しでは従来どおりそれらを入力にする" in onboarding


def test_setup_channel_prelaunch_persona_chain_propagates_context_without_analytics() -> None:
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    audience_persona = _read(".claude/skills/channel-strategy/references/persona.md")
    viewing_scene = _read(".claude/skills/channel-strategy/references/scene.md")

    step7 = setup_channel.split("### Step 7: 本格ペルソナ作成チェーン", 1)[1].split(
        "### Step 8: branding 初回反映",
        1,
    )[0]
    assert "実行コンテキスト: 新規開設（公開前）" in step7
    assert ("`/channel-strategy --persona` から同じ実行コンテキストを引き継いで `/channel-strategy --scene`") in step7
    for path in (
        "docs/plans/viewer-voice-analysis.json",
        "docs/channel/ttp-seed-confirmation.md",
        "docs/channel/competitor-branding-snapshot.json",
    ):
        assert path in step7
    assert "任意の `/channel-research --benchmark`" in step7
    assert "`reports/analysis_*.md` は要求しない" in step7

    entry_contract = _markdown_section(audience_persona, "## Overview").split("入口で実行コンテキスト", 1)[1]
    assert "新規開設（公開前）" in entry_contract
    assert "公開後" in entry_contract
    assert "任意の `/channel-research --benchmark` 成果物" in entry_contract
    for path in (
        "docs/plans/viewer-voice-analysis.json",
        "docs/channel/ttp-seed-confirmation.md",
        "docs/channel/competitor-branding-snapshot.json",
    ):
        assert path in entry_contract
    phase5 = _markdown_section(audience_persona, "### Phase 5: viewing-scene 検証")
    assert "新規開設（公開前）" in phase5
    assert "公開後" in phase5
    assert "実行コンテキストを明示して渡し" in phase5
    audience_guidance = _markdown_section(audience_persona, "## 障害時ガイダンス")
    assert "公開前入力不在" in audience_guidance
    assert "公開後入力不在" in audience_guidance
    assert "新規開設（公開前）で競合 / TTP / viewer-voice 成果物が不足" in audience_guidance
    assert "公開後に `data/` のベンチマーク/Analytics スナップショットが無い" in audience_guidance

    audience_agent1 = audience_persona.split("**Agent 1: ベンチマークタグ分析**", 1)[1].split(
        "**Agent 2: コミュニティ調査**",
        1,
    )[0]
    audience_prelaunch = audience_agent1.split("**新規開設（公開前）**:", 1)[1].split("**公開後**:", 1)[0]
    audience_postlaunch = audience_agent1.split("**公開後**:", 1)[1]
    assert "記録済みの範囲だけ入力" in audience_prelaunch
    assert "推測で補わず「動画タグ頻度は未検証」" in audience_prelaunch
    assert "全ベンチマーク動画のタグを集計（頻度順）" not in audience_prelaunch
    assert "全ベンチマーク動画のタグを集計（頻度順）" in audience_postlaunch

    viewing_overview = _markdown_section(viewing_scene, "## Overview")
    assert "新規開設（公開前）" in viewing_overview
    assert "公開後" in viewing_overview
    assert "実行コンテキストが明示されない場合もこちら" in viewing_overview
    guard = _markdown_section(viewing_scene, "### 停止する fail")
    assert "新規開設（公開前）" in guard
    assert "公開後に検証済み `reports/analysis_*.json` + `.html` pair が無い" in guard
    assert "`reports/analysis_*.json` が無い" not in guard.replace(
        "公開後に検証済み `reports/analysis_*.json` + `.html` pair が無い",
        "",
    )
    for path in (
        "docs/plans/viewer-voice-analysis.json",
        "docs/channel/ttp-seed-confirmation.md",
        "docs/channel/competitor-branding-snapshot.json",
    ):
        assert path in guard


def test_viewing_scene_keeps_post_publish_inputs_and_analysis_phases() -> None:
    viewing_scene = _read(".claude/skills/channel-strategy/references/scene.md")
    flow = viewing_scene.split("## 実行フロー", 1)[1].split("## 障害時ガイダンス", 1)[0]

    assert "**公開後**:" in flow
    assert "`reports/` の最新分析レポートを読み込む" in flow
    assert "`data/benchmark_YYYYMMDD.json`" in flow
    assert "任意の `data/benchmark_YYYYMMDD.json` が無くても停止しない" in flow
    viewing_agent1 = flow.split("**Agent 1: 自チャンネルシーン別パフォーマンス**", 1)[1].split(
        "**Agent 2: ベンチマーク活動タグ分析**",
        1,
    )[0]
    viewing_prelaunch = viewing_agent1.split("**新規開設（公開前）**:", 1)[1].split("**公開後**:", 1)[0]
    viewing_postlaunch = viewing_agent1.split("**公開後**:", 1)[1]
    assert "定性シーン仮説" in viewing_prelaunch
    assert "推測で補わず「公開前のため未検証」" in viewing_prelaunch
    for quantitative_step in (
        "シーン × 再生数 × 平均視聴時間のマッピング表",
        "シーン別パフォーマンスランキング",
        "動画尺とパフォーマンスの相関分析",
    ):
        assert quantitative_step not in viewing_prelaunch
        assert quantitative_step in viewing_postlaunch

    viewing_agent2 = flow.split("**Agent 2: ベンチマーク活動タグ分析**", 1)[1].split(
        "**Agent 3: 検索需要調査**",
        1,
    )[0]
    benchmark_prelaunch = viewing_agent2.split("**新規開設（公開前）**:", 1)[1].split("**公開後**:", 1)[0]
    benchmark_postlaunch = viewing_agent2.split("**公開後**:", 1)[1]
    assert "推測で補わず「公開前のため未検証」" in benchmark_prelaunch
    assert "活動タグ別の平均再生数を比較" not in benchmark_prelaunch
    assert "活動タグ別の平均再生数を比較" in benchmark_postlaunch
    for heading in (
        "**Agent 1: 自チャンネルシーン別パフォーマンス**",
        "**Agent 2: ベンチマーク活動タグ分析**",
        "**Agent 3: 検索需要調査**",
        "### Phase 2: 第一ペルソナ × シーン検証",
        "### Phase 3: 意思決定 + レポート保存",
    ):
        assert heading in flow


def test_setup_import_mode_contract_is_separate_from_ttp_completion() -> None:
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    setup = _read(".claude/skills/setup/SKILL.md")
    import_mode = _read(".claude/skills/setup/references/import-mode.md")
    config_rules = _read(".claude/skills/setup/references/config-generation-rules.md")

    assert "完了条件（--channel）" in setup_channel
    assert "docs/channel/personas/persona-definition.json" in setup_channel
    assert "docs/channel/personas/persona-definition.html" in setup_channel
    assert "既存チャンネル取り込みモードにはこの TTP 完了条件を適用しない" in setup_channel
    assert "取り込み Step 8: 次ステップ案内" in setup_channel
    assert "references/import-mode.md" in setup
    assert "`music_engine` に入れる値は `suno` / `lyria` のどちらか" in import_mode
    assert "both` は config 契約外" in import_mode
    assert "audio.target_duration_min" in import_mode
    assert "audio.target_duration_max" in import_mode
    assert "meta / content / youtube / analytics / audio" in import_mode
    assert "references/config-template/audio.json" in import_mode
    assert "責務別 5 ファイル" in import_mode
    assert (ROOT / ".claude/skills/setup/references/config-template/audio.json").is_file()
    assert (
        "`config/channel/meta.json::channel.channel_id` が未設定の場合は、認証済みチャンネル ID を必ず取得"
        in import_mode
    )
    assert "`channel_id` の `config/channel/meta.json::channel.channel_id` 保存" in import_mode
    for text in (setup, import_mode):
        assert "channel_id` 取得またはユーザー承認済み" not in text
        assert "ユーザー承認済みの未完了項目明記" not in text
    assert (
        "benchmark.channels`、`ttp-seed-confirmation.md`、branding snapshot、"
        "`ttp_wf_new_readiness` は取り込みモードの必須完了条件ではない"
    ) in import_mode
    assert "config-template" + ".json" not in config_rules
    assert "config-template/*.json" in config_rules


def test_setup_import_step_8_presents_reachable_wf_new_guidance() -> None:
    import_mode = _read(".claude/skills/setup/references/import-mode.md")
    step_8 = import_mode.split("## 取り込み Step 8:", 1)[1]

    assert "uv run yt-doctor --json" in step_8
    assert "`checks` から `id: wf_new_readiness`" in step_8
    ok_guidance = step_8.split("### `status: ok`", 1)[1].split("### `status: warn`", 1)[0]
    assert "`message`" in ok_guidance
    assert "確定した入力モード" in ok_guidance
    assert "今すぐ `/wf-new`" in ok_guidance
    assert "品質を上げる任意項目" in ok_guidance
    for optional_item in ("ブランディング素材", "ペルソナ定義", "追加ベンチマーク"):
        assert optional_item in ok_guidance


def test_setup_import_step_8_preserves_warn_recovery_without_blocking_import() -> None:
    import_mode = _read(".claude/skills/setup/references/import-mode.md")
    step_8 = import_mode.split("## 取り込み Step 8:", 1)[1]
    warn_guidance = step_8.split("### `status: warn`", 1)[1].split("### 共通の完了契約", 1)[0]
    completion = step_8.split("### 共通の完了契約", 1)[1]

    assert "`next_action.instructions`" in warn_guidance
    assert "順序を保ったまま" in warn_guidance
    assert "`/wf-new` 到達に必須" in warn_guidance
    assert "品質を上げる任意項目" in warn_guidance
    assert "`warn` でも取り込みモード自体は完了" in completion
    assert "`wf_new_readiness` を `ok` にすることは取り込みモードの完了条件に加えない" in completion
    assert "`wf_new_readiness` の判定結果に基づく必須／任意の次ステップ案内" in import_mode
    assert "ttp_mode" not in import_mode


def test_setup_localizations_priority_matches_generation_rules() -> None:
    regeneration_mode = _read(".claude/skills/setup/references/regeneration-mode.md")
    rules = _read(".claude/skills/setup/references/config-generation-rules.md")

    step_r5 = regeneration_mode.split("## Step R5:", 1)[1].split("## Step R6:", 1)[0]
    assert '既定 `["ja", "en"]`' in step_r5
    assert "TTP かつ競合が多言語なら" in step_r5
    assert "TTP かつ競合が非多言語なら `en` のみ" in step_r5
    assert "非 TTP なら単一言語・ローカライズなし" in step_r5

    assert "TTP 路線かつ競合が多言語化している" in rules
    assert "TTP 路線かつ競合が多言語化していない" in rules
    assert "非 TTP 路線" in rules
    assert "独自の言語追加・削除をしない" in rules


def test_channel_new_requires_initial_save_before_followup_update() -> None:
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    automation_update = _read(".claude/skills/automation/references/update.md")

    assert "初回保存と automation --update 前の整理" in setup_channel
    assert "git status --porcelain" in setup_channel
    assert "後続の `/automation --update` は dirty worktree で停止する" in setup_channel
    assert "git add -A" in setup_channel
    assert "`git add -A` 後の guard を唯一の安全境界にする" in setup_channel
    assert "bash .claude/skills/setup/references/initial_save_guard.sh || exit 1" in setup_channel
    assert 'git commit -m "chore: 初回チャンネル設定を保存"' in setup_channel
    assert "secret-like file staged; unstaged before commit" in setup_channel
    assert "staged secret を自動で外して停止" in setup_channel
    assert "未コミット変更が残っています。/automation --update の前に以下を完了してください" in setup_channel
    assert "保存未完了として終了した場合は、以下の成功案内は出さない" in setup_channel
    assert "初回保存も完了しているため" in setup_channel

    assert "`git status --porcelain` が **非空** の場合" in automation_update
    assert "/setup --import 直後の初回保存が未完了なら" in automation_update


def test_channel_new_pre_wf_new_checks_include_analytics_reporting_and_live_streaming() -> None:
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    step9 = setup_channel.split("### Step 9: wf-new 接続前チェック", 1)[1].split(
        "### Step 10: 初回保存と automation --update 前の整理",
        1,
    )[0]
    success_message = setup_channel.split(
        "保存未完了として終了した場合は、以下の成功案内は出さない",
        1,
    )[1]

    assert "Analytics / Reporting レポート取得設定が未確認" in step9
    assert "YouTube Analytics / Reporting API" in step9
    assert "Reporting API job 作成状態" in step9
    assert "`/analytics --collect`" in step9
    assert "`/setup`" in step9
    assert "初回制作は止めず" in step9

    assert "ライブ配信を使う可能性がある" in step9
    assert "YouTube Studio で Live streaming を早めに有効化" in step9
    assert "初回配信可能になるまで最大 24 時間" in step9
    assert "`/streaming`" in step9

    assert "公開後の分析は /analytics --collect" in success_message
    assert "Live streaming 有効化" in success_message
    assert "/streaming の準備確認" in success_message


def test_wf_new_fail_fast_contract_points_to_setup_import_and_collection_local_suno_style() -> None:
    channel_new = _read(".claude/skills/channel-strategy/SKILL.md")
    doctor = _read("src/youtube_automation/commands/system/doctor.py")

    hard_gates = SKILL_INVENTORY.section("wf-new", "## Hard Gates")

    assert "config/channel/` が存在し、`load_config()` でロードできること" in hard_gates
    assert "存在しない場合は `/setup --channel`" in hard_gates
    assert "`load_config()` が失敗する場合は `/setup --import`" in hard_gates
    assert "Suno collection Style boundary" in hard_gates
    assert "`20-documentation/suno-patterns.yaml`" in hard_gates
    assert "共有 `config/skills/music.yaml::prompt` を書き換えない" in hard_gates
    assert "`suno_preset` は推奨入力" in hard_gates

    assert "取り込みモード" not in channel_new
    assert "def check_channel_config" in doctor
    assert 'id="channel_config"' in doctor
    assert "def check_ttp_wf_new_readiness" in doctor
    assert 'CheckDefinition(\n        "ttp_wf_new_readiness"' in doctor


def test_analytics_collect_documents_reporting_api_preflight() -> None:
    analytics_collect = _read(".claude/skills/analytics/references/collect.md")

    assert "`/analytics --collect reporting`" in analytics_collect
    assert "uv run yt-analytics --reporting-dry-run" in analytics_collect
    assert "uv run yt-analytics --reporting-create-job" in analytics_collect
    assert "uv run yt-analytics --include-reporting" in analytics_collect
    assert "最大 48 時間" in analytics_collect
    assert "youtubereporting.googleapis.com" in analytics_collect


def test_analytics_collect_documents_full_depth_collection_path() -> None:
    analytics_collect = _read(".claude/skills/analytics/references/collect.md")

    assert "`/analytics --collect full`" in analytics_collect
    assert "uv run yt-analytics --depth full" in analytics_collect
    assert "references/validate-depth.sh" in analytics_collect
    assert "retention" in analytics_collect
    assert "by_country" in analytics_collect


def test_analytics_analyze_requires_numeric_retention_evidence_for_full_data() -> None:
    analytics_analyze = _read(".claude/skills/analytics/references/analyze.md")
    validator = _read(".claude/skills/analytics/references/analysis-json-validator.md")

    assert "視聴維持率分析" in analytics_analyze
    assert "references/analysis-json-validator.md" in analytics_analyze
    assert "retention_analysis" in validator
    assert "data_points > 0" in validator
    assert "空でない `retention_curve`" in validator


@pytest.mark.parametrize(
    "skill_path",
    [".claude/skills/analytics/SKILL.md"],
)
def test_revised_analytics_skills_stop_when_channel_config_is_invalid(skill_path: str) -> None:
    prerequisite = SKILL_INVENTORY.section(Path(skill_path).parent.name, "## 共通前提")

    assert "`load_config()` でロード可能" in prerequisite
    assert "停止" in prerequisite


@pytest.mark.parametrize(
    "secret_path",
    [".env", "auth/client_secrets.json", "auth/token.json", "auth/token_streaming.json"],
)
def test_setup_channel_initial_save_guard_blocks_staged_secrets(tmp_path: Path, secret_path: str) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    secret_file = repo / secret_path
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text("SECRET=value\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "add", "-f", secret_path)

    guard = ROOT / ".claude/skills/setup/references/initial_save_guard.sh"
    result = subprocess.run(
        [
            "bash",
            "-lc",
            f'bash {shlex.quote(str(guard))} || exit 1\ngit commit -m "chore: 初回チャンネル設定を保存"',
        ],
        cwd=repo,
        env=_isolated_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode != 0
    assert "secret-like file staged; unstaged before commit" in result.stderr
    assert secret_path in result.stderr
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert secret_path not in _git(repo, "diff", "--cached", "--name-only").stdout.splitlines()


def test_setup_channel_initial_save_plain_add_then_guard_blocks_oauth_secret(tmp_path: Path) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    auth_dir = repo / "auth"
    auth_dir.mkdir()
    (auth_dir / "token_streaming.json").write_text("{}\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")

    _git(repo, "add", "-A")
    staged = set(_git(repo, "diff", "--cached", "--name-only").stdout.splitlines())
    assert "config/channel.json" in staged
    assert "auth/token_streaming.json" in staged

    guard = ROOT / ".claude/skills/setup/references/initial_save_guard.sh"
    result = subprocess.run(
        ["bash", str(guard)],
        cwd=repo,
        env=_isolated_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode != 0
    assert "auth/token_streaming.json" in result.stderr
    staged_after_guard = set(_git(repo, "diff", "--cached", "--name-only").stdout.splitlines())
    assert "config/channel.json" in staged_after_guard
    assert "auth/token_streaming.json" not in staged_after_guard


def test_setup_channel_initial_save_guard_allows_non_secret_staged_files(tmp_path: Path) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "-A")

    guard = ROOT / ".claude/skills/setup/references/initial_save_guard.sh"
    result = subprocess.run(
        ["bash", str(guard)],
        cwd=repo,
        env=_isolated_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""


def test_setup_channel_initial_save_success_path_commits_and_cleans_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / ".gitignore").write_text(
        ".env\nauth/client_secrets.json\nauth/token*.json\n",
        encoding="utf-8",
    )
    (repo / ".env").write_text("SECRET=value\n", encoding="utf-8")
    auth_dir = repo / "auth"
    auth_dir.mkdir()
    (auth_dir / "client_secrets.json").write_text("{}\n", encoding="utf-8")
    (auth_dir / "token_streaming.json").write_text("{}\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")

    guard = ROOT / ".claude/skills/setup/references/initial_save_guard.sh"
    _git(repo, "add", "-A")
    guard_result = subprocess.run(
        ["bash", str(guard)],
        cwd=repo,
        env=_isolated_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert guard_result.returncode == 0

    _git(repo, "commit", "-m", "chore: 初回チャンネル設定を保存")
    assert _git(repo, "status", "--porcelain").stdout == ""
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_channel_strategy_followup_skill_routing_uses_new_contract() -> None:
    discover = _read(".claude/skills/channel-research/references/discover.md")
    research = _read(".claude/skills/channel-research/references/market.md")
    viewer_voice = _read(".claude/skills/channel-research/references/voice.md")
    setup = _read(".claude/skills/setup/SKILL.md")
    channel_strategy = _read(".claude/skills/channel-strategy/SKILL.md")
    channel_regeneration_mode = _read(".claude/skills/setup/references/regeneration-mode.md")
    channel_direction_mode = _read(".claude/skills/channel-strategy/references/direction.md")
    onboarding = _read("ONBOARDING.md")
    features = _read("docs/features.md")

    assert "/channel-strategy --direction Step 5 の前段" not in discover
    assert "このスキルの前工程は `/setup --channel` Step 6" in discover
    assert "標準フローでは本スキルを実行せず" in discover
    assert "ユーザー承認と relationship メモを必ず残す" in discover
    assert "genre_keywords" not in discover
    assert "target_scene" not in discover
    assert "config/channel/content.json::genre.{primary,style,context}" in discover

    assert "`market-comparison`" in research
    assert "`collected-analysis`" in research
    assert "data/benchmark_*.json" in research
    assert "data/comments_*.json" in research
    assert "docs/channel-research.json" in research
    assert "/channel-research --voice` → 前提" in research

    assert "チャンネル立ち上げ・方向性見直し時に必ず使用" not in viewer_voice
    assert "`/setup --channel` の新規開設モードでは Step 7 の必須前工程として実行する" in viewer_voice
    assert "公開後の再分析では" in viewer_voice
    assert "任意後続スキル" not in viewer_voice
    assert (
        "`docs/plans/viewer-voice-analysis.json` + `.html` は後続 `/channel-strategy --persona` の必須入力"
        in viewer_voice
    )

    for path_text in (setup, channel_strategy, channel_regeneration_mode, channel_direction_mode, onboarding):
        assert "TTP benchmark" not in path_text
        assert "TTP ベンチマーク収集" not in path_text

    for stage in ("TTP hearing", "seed confirmation", "config", "persona", "branding"):
        assert stage in setup
    assert "TTP 対象確認 / seed fetch / 承認済み benchmark.channels 反映" in channel_regeneration_mode
    assert "`/channel-direction`" not in channel_strategy
    assert "docs/channel/ttp-seed-confirmation.md" in channel_direction_mode
    assert "docs/channel/competitor-branding-snapshot.json" in channel_direction_mode
    assert "config/channel/analytics.json::benchmark.channels" in channel_direction_mode
    assert "入力がすべて欠けている場合" in channel_direction_mode
    assert "根拠なしに方向性検討を進めない" in channel_direction_mode
    assert "`/setup --channel` が保存した" in channel_direction_mode
    assert "untrusted data" in channel_direction_mode
    assert "動画尺 / 投稿頻度 / コメント語彙は収集済みデータがある場合だけ使う" in channel_direction_mode

    followup_direction_files = [
        ".claude/skills/audit/references/alignment.md",
        ".claude/skills/wf-new/references/ideate.md",
        ".claude/skills/music/references/generate.md",
        ".claude/skills/analytics/references/flop.md",
        ".claude/skills/audit/references/video.md",
    ]
    for path in followup_direction_files:
        content = _read(path)
        assert "/channel-strategy --direction" in content
        assert "方向性検討モード" in content
        assert "`/channel-direction`" not in content

    assert "ビジョン共有 + 競合発掘" not in onboarding
    assert "yt-discover-competitors` で 5-10 件" not in onboarding
    assert "ベンチマークデータ + コメント収集まで実行" not in onboarding
    assert "docs/channel/ttp-seed-confirmation.md" in onboarding
    assert "docs/channel/competitor-branding-snapshot.json" in onboarding
    assert "/channel-strategy --direction → 方向性ブレスト" in onboarding
    assert "| /channel-direction |" not in features
    assert "untrusted data" in onboarding

    assert "新規チャンネル開設 → 競合発掘 → 方向性決定 → セットアップ" not in features
    assert (
        "`/setup` → `/channel-research --voice` → `/channel-strategy`"
        "（`--persona` → `--scene` → `--constraints`）→ `/wf-new`"
    ) in features


def test_skill_frontmatter_descriptions_disambiguate_sibling_routes() -> None:
    benchmark_desc = _skill_frontmatter("channel-research")["description"]
    channel_strategy_desc = _skill_frontmatter("channel-strategy")["description"]
    video_desc = _skill_frontmatter("video")["description"]
    publish_desc = _skill_frontmatter("publish")["description"]

    assert "「競合分析」" in benchmark_desc
    assert "「競合データ収集」" in benchmark_desc
    assert "--benchmark" in benchmark_desc
    assert "「市場調査」" in benchmark_desc
    assert "「競合分析」" not in channel_strategy_desc
    assert "方向性" in channel_strategy_desc
    assert "channel-research の voice mode、市場比較は market mode" in channel_strategy_desc

    assert "YouTube へのアップロードは公開系 skill の責務" in video_desc
    assert "動画生成は /video" in publish_desc


def test_thumbnail_search_order_is_documented() -> None:
    expected_order = "`10-assets/thumbnail.jpg` → `10-assets/thumbnail.png`"
    for path in (
        ".claude/skills/publish/references/upload.md",
        ".claude/skills/publish/references/posting-checklist.md",
    ):
        text = _read(path)
        assert expected_order in text
        assert "→ `10-assets/main.jpg` → `10-assets/main.png`" not in text
        assert "textless 動画背景" in text


def test_upload_schedule_plan_must_precede_publish_guidance() -> None:
    video_upload = _read(".claude/skills/publish/references/upload.md")
    wf_next = _read(".claude/skills/wf-next/SKILL.md")
    posting_checklist = _read(".claude/skills/publish/references/posting-checklist.md")
    scheduled_publish = _read(".claude/skills/publish/references/scheduled-publish.md")

    for text in (video_upload, wf_next, posting_checklist, scheduled_publish):
        assert "uv run yt-upload-collection --plan" in text
        assert "📅 公開設定: 非公開でアップロード（即時公開は行いません）" in text
        assert "📅 公開設定: 限定公開 (unlisted)" in text
        assert "📅 公開設定: 非公開 (private)" in text
        assert "📅 公開予定" in text

    assert "書き込み API と upload を実行しない read-only plan" in video_upload
    for text in (posting_checklist, scheduled_publish):
        assert "アップロード API は叩かない" in text
        assert "YouTube read API を呼ぶ場合がある" in text
        assert "実 API は叩かない" not in text
        assert "API 非消費" not in text

    collection_flow = video_upload[
        video_upload.index("### collection アップロードフロー") : video_upload.index("### release アップロードフロー")
    ]
    _assert_appears_before(collection_flow, "uv run yt-upload-collection --plan", "Complete Collection アップロード")

    release_flow = video_upload[
        video_upload.index("### release アップロードフロー") : video_upload.index("### コマンドリファレンス")
    ]
    assert "uv run yt-upload-auto" in release_flow
    assert "uv run yt-upload-collection --plan" in release_flow
    assert "この分岐では実行しない" in release_flow
    assert "collection 用 plan 結果を流用しない" in release_flow

    _assert_appears_before(
        posting_checklist,
        "uv run yt-upload-collection --plan",
        "uv run yt-upload-collection [-c NAME]",
    )

    wf_next_gate = wf_next[wf_next.index("skip_upload_approval = false") :]
    _assert_appears_before(wf_next_gate, "uv run yt-upload-collection --plan", "AskUserQuestion")
    _assert_appears_before(wf_next_gate, "uv run yt-upload-collection --plan", "/publish --upload")


def test_first_post_playlist_initialization_contract_is_documented() -> None:
    playlist = _read(".claude/skills/publish/references/playlist.md")
    video_upload = _read(".claude/skills/publish/references/upload.md")
    wf_next = _read(".claude/skills/wf-next/SKILL.md")
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    checklist = _read(".claude/skills/publish/references/posting-checklist.md")

    description = _skill_frontmatter("publish")["description"]
    for trigger in ("初投稿", "初回投稿", "初回公開前にプレイリスト初期化"):
        assert trigger in description

    for command in (
        "uv run yt-playlist-status",
        "uv run yt-playlist-manager --init --dry-run",
        "uv run yt-playlist-manager --init",
    ):
        assert command in video_upload
        assert command in wf_next
        assert command in checklist

    assert "/publish --playlist" in setup_channel
    assert "`yt-playlist-status` → `yt-playlist-manager --init --dry-run` → `--init`" in setup_channel

    for text in (playlist, video_upload, wf_next, setup_channel, checklist):
        assert "playlist_id" in text
        assert "自動 assign" in text

    assert "`collection` 型では `collection_uploader` 内部の `assign_video()`" in video_upload
    assert "プレイリストへの動画追加は後続のアップロード経路が担う" in video_upload
    assert "`skip_upload_approval` とは別の playlist 作成ゲート" in wf_next
    assert "`skip_upload_approval = true` でも" in wf_next
    assert "確認を省略しない" in wf_next
    assert "ユーザーが playlist 初期化を却下した場合" in wf_next
    assert "`/publish --upload` を実行せず停止" in wf_next
    assert "`config/channel/playlists.json` が無い" in wf_next
    assert "全 playlist に `playlist_id` がある場合はスキップ" in wf_next
    assert "初投稿プレイリスト初期化ゲート" in wf_next
    assert "`upload.video_id = null`" in wf_next
    assert "初回動画の追加は `/publish --upload` 内部の自動 assign に任せる" in checklist


def test_wf_next_example_uses_skip_approval_keys() -> None:
    """#1744: wf_next の example は承認省略キーを使用する."""
    example = _read("examples/channel_config.example/workflow.json")
    example_config = json.loads(example)
    wf_next_example = example_config["workflow"]["wf_next"]

    # example は新キーのみ（既定値どおり true = 承認省略）で、旧キーを含まない
    assert '"skip_audio_approval": true' in example
    assert '"skip_upload_approval": true' in example
    assert "approval_gates" not in wf_next_example


def test_publish_skip_approvals_are_documented_consistently() -> None:
    publish = _read(".claude/skills/publish/SKILL.md")
    setup = _read(".claude/skills/setup/SKILL.md")
    readme = _read("README.md")
    example = json.loads(_read("examples/channel_config.example/workflow.json"))
    config = example["workflow"]["post-publish"]

    assert "approval_gates" not in config
    assert config["skip_approvals"] == {
        "community-post": True,
        "pinned-comment": True,
    }
    for text in (publish, setup, readme):
        assert "skip_approvals" in text
    assert "resolved skip が `false`" in publish
    assert "逆向き alias" in publish
    assert "同一 step" in publish


def test_chain_manifest_approval_gate_uses_true_equals_skip() -> None:
    schema = _read("docs/skill-design/chain-manifest-schema.md")
    publish = _read(".claude/skills/publish/SKILL.md")
    analytics_run = _read(".claude/skills/analytics/SKILL.md")

    assert '"required": ["skip"]' in schema
    assert '"required": ["enabled"]' in schema
    assert '"oneOf"' in schema
    assert "skip = not enabled" in schema
    assert "semantic validation" in schema
    for skill in (publish, analytics_run):
        assert "approvalGate.skip" in skill
        assert "skip = not enabled" in skill
        assert "同時指定" in skill


def test_common_docs_list_optional_channel_config_files() -> None:
    required = ("shorts.json", "comments.json", "pinned-comment.json", "distrokid.json")

    for path in ("README.md", "AGENTS.md", "CLAUDE.md", "ONBOARDING.md"):
        text = _read(path)
        for name in required:
            assert name in text, f"{path} missing {name}"


def test_distrokid_skill_uses_helper_name() -> None:
    skill_path = ROOT / ".claude" / "skills" / "distrokid-helper" / "SKILL.md"
    assert skill_path.exists()

    frontmatter = _skill_frontmatter("distrokid-helper")
    assert frontmatter["name"] == "distrokid-helper"
    assert (skill_path.parent / "references" / "distrokid_prepare.py").is_file()
    assert (skill_path.parent / "references" / "spec-example.json").is_file()

    features = _read("docs/features.md")
    assert "/distrokid-helper" in features
    assert "サーバー起動まで実行" in features
    assert "distrokid-prep" not in features


def test_distrokid_skill_and_example_document_single_and_multi_disc_naming() -> None:
    skill = _read(".claude/skills/distrokid-helper/SKILL.md")
    example = json.loads(_read(".claude/skills/distrokid-helper/references/spec-example.json"))

    assert "**単一 disc（35 曲以下）**" in skill
    assert "`dark-techno`" in skill
    assert "**複数 disc（35 曲超）**" in skill
    assert "`disc{N}-<theme-kebab-case>-vol{N}`" in skill
    assert example["single_disc"]["discs"][0]["slug"] == "dark-techno"
    assert example["single_disc"]["discs"][0]["album_title"] == "Dark Techno"
    assert example["multi_disc"]["discs"][0]["album_title"] == "Coding Focus Vol.1"
    assert example["multi_disc"]["discs"][1]["slug"] == "disc2-coding-focus-vol2"


def test_distrokid_helper_docs_describe_dynamic_selector_fetch_contract() -> None:
    skill = _read(".claude/skills/distrokid-helper/SKILL.md")
    readme = _read("extensions/distrokid-helper/README.md")

    for text in (skill, readme):
        assert "ローカル配信元" in text
        assert "selector" in text
        assert "動的検出" in text
        assert "候補履歴は保存しない" in text or "候補履歴は保存せず" in text
        assert "自動取得" in text
        assert "selector を開く" in text
        assert "更新完了後" in text or "候補更新後" in text
        assert "データ取得" not in text

    assert "popup のサーバー URL" not in skill
    assert "サーバー URL に `http://localhost:7874` を設定" not in skill


def test_distrokid_helper_records_confirmed_submission_through_workflow_state_owner() -> None:
    skill = _read(".claude/skills/distrokid-helper/SKILL.md")

    command = "uv run yt-workflow-state --collection <collection> record-distrokid-submission"
    assert skill.count(command) == 1
    assert "ユーザーが転記・アップロード完了を確認した後" in skill
    assert "human_tasks.distrokid_submission.completed_at" in skill


def test_suno_helper_docs_use_the_visible_server_source_picker_contract() -> None:
    skill = _read(".claude/skills/music/references/generate.md")
    readme = _read("extensions/suno-helper/README.md")

    for text in (skill, readme):
        assert '[data-suno-control="server-source-trigger"]' in text
        assert 'role="option"' in text
        assert '[data-suno-control="server-url"]' not in text


def test_community_draft_documents_typed_batch_generator_contract() -> None:
    text = _read(".claude/skills/publish/references/community.md")

    assert "load_config().community_draft.posts" in text
    assert re.search(r"単一ソースは\s+`references/generate_batch\.py`\s+とし", text)
    assert "planning.final_title" in text
    assert "planning.publish_target_at" in text
    assert "`CHANNEL_DIR` 配下" in text
    assert "community-posts.json" in text
    assert "timezone 付き `scheduled_at`" in text
    assert "channel root 相対 `image_path`" in text
    assert "`visibility: public`" in text


def test_community_draft_does_not_require_upstream_adr() -> None:
    text = _read(".claude/skills/publish/references/community.md")

    assert "docs/adr/0019-community-helper-extension.md" not in text


def test_skill_config_defaults_have_read_gate_in_skill_docs() -> None:
    skill_dirs = [path for path in SKILL_INVENTORY.skill_directories() if (path / "config.default.yaml").is_file()]
    assert skill_dirs

    for skill_dir in skill_dirs:
        skill = skill_dir.name
        rel_skill_md = f".claude/skills/{skill}/SKILL.md"
        text = _read(rel_skill_md)

        assert "## 設定読み込みゲート" in text, f"{skill} missing config read gate"
        assert f".claude/skills/{skill}/config.default.yaml" in text
        assert f"config/skills/{skill}.yaml" in text
        registered = skill_config.SKILL_CONFIG_KEYS | skill_config.SKILL_ONLY_CONFIG_KEYS
        loader_keys = [
            key
            for key in registered
            if skill_config.skill_config_default_relative_path(key.partition(".")[0]).parts[0] == skill
        ]
        expected_loader_keys = ["postmortem"] if skill == "flop-analysis" else loader_keys
        for loader_key in expected_loader_keys:
            assert f'load_skill_config("{loader_key}")' in text
        assert "存在する場合" in text
        assert "勝手に作成しない" in text

        if skill == "community-post":
            assert "default と任意 override を確認する" in text
            assert "gate で Read" in text
        else:
            assert "deep-merge" in text
            assert "チャンネル上書き" in text

        gate_pos = text.index("## 設定読み込みゲート")
        operational_markers = [
            marker
            for marker in (
                "## Instructions",
                "## 実行フロー",
                "## Workflow",
                "## Scripts",
                "## Quick Reference",
                "## Inputs",
                "## 前提",
                "## 制約・前提",
                "### モード判定",
                "### スタイルバリアント",
                "### Step 1",
                "### 前提条件チェック",
                "### 対象コレクション",
            )
            if marker in text
        ]
        if operational_markers:
            assert gate_pos < min(text.index(marker) for marker in operational_markers), (
                f"{skill} config read gate must appear before operational steps"
            )


def test_music_master_generate_master_examples_only_use_cli_help_options() -> None:
    skill = _read(".claude/skills/music/references/master.md")
    result = subprocess.run(
        [sys.executable, "-m", "youtube_automation.commands.media.generate_master", "--help"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    help_options = set(re.findall(r"--[a-z][a-z0-9-]*", result.stdout))
    documented_commands = re.findall(r"uv run yt-generate-master[^\n`]*", skill)
    documented_options = {
        option for command in documented_commands for option in re.findall(r"--[a-z][a-z0-9-]*", command)
    }

    assert documented_commands
    assert documented_options <= help_options
    assert {"--bitrate", "--crossfade-duration"}.isdisjoint(set(re.findall(r"--[a-z][a-z0-9-]*", skill)))


def test_analytics_report_uses_common_structured_document_renderer() -> None:
    skill = _read(".claude/skills/analytics/references/report.md")
    default_config = yaml.safe_load(_read(".claude/skills/analytics/config.default.yaml")) or {}

    colors = default_config.get("theme", {}).get("colors")
    assert colors == {
        "background": "#0f1419",
        "card_background": "#1a2332",
        "accent": "#c8a96e",
        "text": "#e8e6e3",
        "chart_palette": ["#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7", "#dfe6e9"],
        "success": "#00b894",
        "warning": "#fdcb6e",
        "danger": "#e17055",
    }

    assert "yt-document-render" in skill
    assert "analysis-report.schema.json" in skill
    assert "Chart.js" in skill
    assert "Chart.js/CDN" in skill
    assert "個別 CSS" in skill
    for color in (
        "#0f1419",
        "#1a2332",
        "#c8a96e",
        "#e8e6e3",
        "#4ecdc4",
        "#45b7d1",
        "#96ceb4",
        "#ffeaa7",
        "#dfe6e9",
        "#00b894",
        "#fdcb6e",
        "#e17055",
    ):
        assert color not in skill


def test_collection_lifecycle_uses_mp3_as_public_audio_contract() -> None:
    text = _read(".claude/skills/wf-new/references/collection-lifecycle.md")

    assert "01-master/           # マスター音声・動画（*.mp3, *.mp4）" in text
    assert "02-Individual-music/ # 個別音声ファイル（*.mp3）" in text
    assert "WAV は中間成果物" in text


def test_collection_localization_docs_use_root_localizations_contract() -> None:
    for path in (
        ".claude/skills/publish/references/upload.md",
        ".claude/skills/setup/references/channel-mode.md",
        ".claude/skills/setup/references/regeneration-mode.md",
        ".claude/skills/setup/references/config-generation-rules.md",
    ):
        text = _read(path)
        assert "localization.supported_languages" not in text
        assert "config/localizations.json" in text

    rules = _read(".claude/skills/setup/references/config-generation-rules.md")
    required_sections = rules.split("以下は **すべて `config/channel/*.json` に含める**:", 1)[1].split(
        "## ルート設定ファイル",
        1,
    )[0]
    assert "`localizations`" not in required_sections
    assert "`config/localizations.json`" in rules


def test_setup_client_secrets_step_uses_download_and_automatic_move() -> None:
    # check id ごとの手順は段階的開示で references/check-runbook.md へ分離済み
    setup = _read(".claude/skills/setup/references/check-runbook.md")
    step = setup.split("#### `client_secrets`", 1)[1].split("#### `oauth_token`", 1)[0]

    for expected in (
        "Client secrets",
        "Add secret",
        "Download JSON",
        "done",
        "uv run yt-doctor --fix-client-secrets",
        "uv run yt-doctor --apply --json",
        "client_secrets` が `ok`",
    ):
        assert expected in step
    assert "client_secrets.template.json" not in step
    assert "転記" not in step


def test_public_setup_guide_owns_installation_and_oauth_completion() -> None:
    oauth_setup = _read("docs/oauth-setup.md")
    recommended = oauth_setup.split("## 推奨ルート", 1)[1].split("## 上級者向け", 1)[0]

    for expected in (
        "uv init",
        "uv add git+https://github.com/daiki-beppu/youtube-automation.git",
        "uv run yt-skills sync --asset skills --force",
        "/setup --tool",
        "[HUMAN STEP]",
        "Download JSON",
        "done",
        "uv run yt-doctor --fix-client-secrets",
        "uv run yt-doctor --apply --json",
        "apply.stop_reason` が `completed",
    ):
        assert expected in recommended
    assert "client_secrets.template.json" not in recommended
    assert "転記" not in recommended

    onboarding = _read("ONBOARDING.md")
    onboarding_setup = onboarding.split("## 2. ツール導入と API セットアップ", 1)[1].split(
        "### 2.4 初期設定後の GCP 課金確認", 1
    )[0]
    assert "[`docs/oauth-setup.md`](docs/oauth-setup.md) を正本" in onboarding_setup
    assert "```bash" not in onboarding_setup
    assert "Download JSON" not in onboarding_setup


def test_oauth_module_and_setup_guide_distinguish_automatic_and_manual_routes() -> None:
    oauth_handler = _read("src/youtube_automation/infrastructure/auth/youtube.py")
    module_docstring = oauth_handler.split('"""', 2)[1]
    for expected in ("Download JSON", "yt-doctor --fix-client-secrets"):
        assert expected in module_docstring
    assert "secret を発行して auth/client_secrets.json に配置" not in module_docstring

    oauth_setup = _read("docs/oauth-setup.md")
    route_zero = oauth_setup.split("## 推奨ルート", 1)[1].split("## 上級者向け", 1)[0]
    for expected in ("Download JSON", "done", "yt-doctor --fix-client-secrets", "yt-doctor --apply --json"):
        assert expected in route_zero
    assert "client_secrets.json` 配置は PKCE / GUI 制約で AI 実行不可" not in route_zero

    manual_routes = oauth_setup.split("### ルート A", 1)[1].split("## Google Auth Platform 手動設定", 1)[0]
    assert "ルート A / B では `client_secrets.json` の手動配置を行う" in manual_routes


def test_channel_new_regeneration_documents_ttp_wf_new_readiness_gate() -> None:
    regeneration_mode = _read(".claude/skills/setup/references/regeneration-mode.md")
    rules = _read(".claude/skills/setup/references/config-generation-rules.md")

    for text in (regeneration_mode, rules):
        assert "uv run yt-doctor --json" in text
        assert "ttp_wf_new_readiness" in text
        assert "/setup --regenerate benchmark 反映未完了" in text
        assert "data/benchmark_*.json" in text
        assert "docs/benchmarks/*.md" in text
        assert "data/thumbnail_compare/benchmark/" in text
        assert "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default" in text
        assert "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.channel_branding" in text


def test_thumbnail_compare_documents_planning_thumbnail_runtime_contract() -> None:
    compare = _read(".claude/skills/thumbnail/references/compare.md")
    prerequisites = _markdown_section(compare, "## 前提")
    phase_one = _markdown_section(compare, "### Phase 1: サムネイル収集（スクリプト実行）")
    troubleshooting = _markdown_section(compare, "## 障害時ガイダンス")
    related_files = _markdown_section(compare, "## 関連ファイル")

    for section in (prerequisites, phase_one, related_files):
        assert "collections/live/*/10-assets/thumbnail.jpg" in section
        assert "collections/planning/*/10-assets/thumbnail.jpg" in section

    for excluded in ("thumbnail-v*.jpg", "planning-preview.png", "main.png/jpg"):
        assert excluded in phase_one

    assert "<channel_slug>_planning_<collection>.jpg" in phase_one
    assert "既存出力" in phase_one
    assert "上書きしない" in phase_one
    assert "個別 timeout" in troubleshooting
    assert "成功分" in troubleshooting


def test_thumbnail_background_generation_is_noninteractive_and_observed_to_completion() -> None:
    completion = SKILL_INVENTORY.section("thumbnail", "## 所要時間と完了報告")

    for expected in (
        "-y < /dev/null",
        "fire-and-forget",
        "exit code",
        "30 秒以下",
        "成果物 0 枚",
        "status: failure",
    ):
        assert expected in completion

    assert completion.index("承認済み") < completion.index("-y < /dev/null")
    assert completion.index("exit 0") < completion.index("status: success")


def test_setup_owns_setting_push_mode_and_strategy_keeps_direction_mode() -> None:
    description = _skill_frontmatter("channel-strategy")["description"]
    setup_description = _skill_frontmatter("setup")["description"]

    for trigger in (
        "設定反映",
        "チャンネル設定更新",
        "branding push",
        "ローカライゼーション同期",
        "meta.json を YouTube に反映",
    ):
        assert trigger in setup_description
        assert trigger not in description

    mode_routing = SKILL_INVENTORY.section("channel-strategy", "## モード判定")
    assert "`--direction`" in mode_routing

    mode = _read(".claude/skills/setup/references/push-mode.md")
    for command in (
        "uv run yt-channel-settings diff",
        "uv run yt-channel-settings push",
        "uv run yt-channel-settings push --apply",
        "uv run yt-channel-settings pull",
        "uv run yt-channel-settings pull --apply",
    ):
        assert command in mode

    for contract in (
        "brandingSettings",
        "別々の `channels().update()`",
        "branding_settings cannot be used with other parts",
        "localizations",
        "`Required` 400",
        "--no-localizations",
        "youtube.force-ssl",
    ):
        assert contract in mode


def test_channel_new_regeneration_snapshot_collects_all_benchmark_channels() -> None:
    regeneration_mode = _read(".claude/skills/setup/references/regeneration-mode.md")
    step = regeneration_mode.split("### Step R2.1:", 1)[1].split("### Step R2.2:", 1)[0]

    assert "benchmark.channels[0]" + "` が指定" not in step
    assert "承認済み TTP 対象" in step
    assert "全件取得" in step
    assert "1 回のコマンド" in step
    assert '--channel-id "<benchmark.channels[0].id>"' in step
    assert '--channel-id "<benchmark.channels[1].id>"' in step
    assert "先頭 1 件だけで済ませない" in step


def test_channel_new_regeneration_config_templates_include_audio_json() -> None:
    regeneration_mode = _read(".claude/skills/setup/references/regeneration-mode.md")
    step = regeneration_mode.split("### Step R2.2:", 1)[1].split("### Step R2.3:", 1)[0]

    assert "責務別 5 ファイル" in step
    assert "meta / content / youtube / analytics / audio" in step
    assert "責務別 4 ファイル" not in step


def test_channel_new_regeneration_uses_real_channel_research_output_path() -> None:
    mode = _read(".claude/skills/setup/references/regeneration-mode.md")

    assert "docs/channel-research.md" in mode
    assert "docs/channel/channel-research.md" not in mode
    assert "`channel-research.md`" not in mode


def test_config_generation_rules_reference_existing_templates_and_step_ids() -> None:
    rules = _read(".claude/skills/setup/references/config-generation-rules.md")

    assert "config-template" + ".json" not in rules
    assert "config-template/" in rules
    assert "config-template/*.json" in rules
    assert "config-template/skills/*.yaml" in rules
    assert "Step R2.3" in rules
    assert "Step " + "2.3" not in rules

    for path in (
        ".claude/skills/setup/references/config-template/meta.json",
        ".claude/skills/setup/references/config-template/content.json",
        ".claude/skills/setup/references/config-template/youtube.json",
        ".claude/skills/setup/references/config-template/analytics.json",
        ".claude/skills/setup/references/config-template/audio.json",
        ".claude/skills/setup/references/config-template/skills/music.yaml",
        ".claude/skills/setup/references/config-template/skills/thumbnail.yaml",
    ):
        assert (ROOT / path).is_file(), f"{path} が存在しない"


def test_channel_new_regeneration_does_not_recopy_youtube_json_after_config_completion() -> None:
    regeneration_mode = _read(".claude/skills/setup/references/regeneration-mode.md")

    assert "`config/channel/youtube.json::youtube.{category_id,privacy_status}`" in regeneration_mode

    step_r5 = regeneration_mode.split("## Step R5: 残りファイル生成", 1)[1].split("## Step R6:", 1)[0]
    assert "`config/channel/youtube.json`" not in step_r5


_INSIGHTS_VALIDATOR = ROOT / ".claude/skills/analytics/references/validate_insights.py"
_INSIGHTS_SCHEMA_PATH = ".claude/skills/analytics/references/insights-entry.schema.json"


def _insights_entry(**overrides: object) -> dict:
    entry: dict = {
        "schema_version": 1,
        "id": "20260717-analysis-thumbnail-text-size",
        "date": "2026-07-17",
        "source": "analysis",
        "source_path": "reports/analysis_20260717.json",
        "lever": "thumbnail",
        "finding": "サムネの文字が 320px で読めない",
        "recommended_action": "タイトル文字サイズを 1.5 倍にする",
        "evidence": "analysis_20260717.json#$.cli_outputs.launch_curve.target.ratio_vs_median = 0.42",
        "status": "open",
    }
    entry.update(overrides)
    return entry


def _run_insights_validator(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_INSIGHTS_VALIDATOR), str(path)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_insights_entry_schema_is_single_source_for_writers_and_readers() -> None:
    schema = json.loads(_read(_INSIGHTS_SCHEMA_PATH))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version",
        "id",
        "date",
        "source",
        "lever",
        "finding",
        "recommended_action",
        "evidence",
        "status",
    }
    properties = schema["properties"]
    assert properties["schema_version"]["const"] == 1
    assert properties["source"]["enum"] == ["analysis", "postmortem", "experiment"]
    assert properties["lever"]["enum"] == ["thumbnail", "title", "topic", "bgm", "metadata", "other"]
    assert properties["status"]["enum"] == ["open", "adopted", "dismissed"]

    analytics_analyze = _read(".claude/skills/analytics/references/analyze.md")
    flop_analysis = _read(".claude/skills/analytics/references/flop.md")
    wf_new = _read_wf_new()
    collection_ideate = _read(".claude/skills/wf-new/references/ideate.md")
    thumbnail = _read(".claude/skills/thumbnail/SKILL.md")

    assert "references/insights-entry.schema.json" in analytics_analyze
    for text in (flop_analysis, wf_new, collection_ideate, thumbnail):
        assert _INSIGHTS_SCHEMA_PATH in text
    for text in (analytics_analyze, flop_analysis, wf_new, collection_ideate, thumbnail):
        assert "data/insights.jsonl" in text

    validator_command = "uv run python3 .claude/skills/analytics/references/validate_insights.py data/insights.jsonl"
    for text in (analytics_analyze, flop_analysis, wf_new, collection_ideate):
        assert validator_command in text

    # 文書型 writer 2 本: 追記契約（source 値 / append-only / schema 再定義禁止）
    for writer in (analytics_analyze, flop_analysis):
        assert "append-only" in writer
        assert "本文で必須キーや enum を再定義しない" in writer
    assert 'source: "analysis"' in analytics_analyze
    assert '`status: "open"`' in analytics_analyze
    assert "重複追記しない" in analytics_analyze
    assert 'source: "postmortem"' in flop_analysis
    assert "「結論 / 反証 / 学び」の 3 項目がすべて記入済み" in flop_analysis
    assert "`未検証` の仮説だけを根拠にした学びは還元しない" in flop_analysis
    for reader in (wf_new, collection_ideate, thumbnail):
        assert "yt-experiment judge" in reader

    # 読み手 3 本: 消費契約（open 選別 / status 反映 / lever=thumbnail）
    assert "jq -c 'select(.status == \"open\")' data/insights.jsonl" in wf_new
    assert "open insights の消費と status 反映" in collection_ideate
    assert "`adopted`" in collection_ideate
    assert "`dismissed`" in collection_ideate
    assert "行の削除・並べ替え・他フィールドの書き換えはしない" in collection_ideate
    assert 'select(.status == "open" and .lever == "thumbnail")' in thumbnail
    assert "`status` を含むエントリの書き換え・追記はしない" in thumbnail


def test_insights_validator_enforces_schema_and_id_uniqueness(tmp_path: Path) -> None:
    missing = _run_insights_validator(tmp_path / "insights.jsonl")
    assert missing.returncode == 0, missing.stderr

    valid_path = tmp_path / "valid.jsonl"
    valid_lines = [
        json.dumps(_insights_entry(), ensure_ascii=False),
        json.dumps(
            _insights_entry(
                id="20260717-postmortem-title-appeal",
                source="postmortem",
                source_path="collections/live/sample/20-documentation/postmortem.md",
                lever="title",
            ),
            ensure_ascii=False,
        ),
        json.dumps(
            _insights_entry(
                id="experiment-20260717-thumbnail-textless",
                source="experiment",
                source_path="data/experiments.jsonl",
            ),
            ensure_ascii=False,
        ),
    ]
    valid_path.write_text("\n".join(valid_lines) + "\n", encoding="utf-8")
    ok = _run_insights_validator(valid_path)
    assert ok.returncode == 0, ok.stderr

    invalid_path = tmp_path / "invalid.jsonl"
    invalid_entries = [
        _insights_entry(id="bad-lever", lever="color"),
        _insights_entry(id="bad-status", status="todo"),
        {k: v for k, v in _insights_entry(id="missing-evidence").items() if k != "evidence"},
        _insights_entry(id="unknown-key", unknown_key="x"),
        _insights_entry(id="bad-date", date="2026/07/17"),
        _insights_entry(id="impossible-date", date="2026-02-30"),
    ]
    invalid_path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in invalid_entries) + "\n",
        encoding="utf-8",
    )
    invalid = _run_insights_validator(invalid_path)
    assert invalid.returncode == 1
    for fragment in ("lever", "status", "evidence", "unknown_key", "date"):
        assert fragment in invalid.stderr

    duplicate_path = tmp_path / "duplicate.jsonl"
    duplicate_path.write_text(
        json.dumps(_insights_entry(), ensure_ascii=False)
        + "\n"
        + json.dumps(_insights_entry(lever="title"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    duplicate = _run_insights_validator(duplicate_path)
    assert duplicate.returncode == 1
    assert "重複" in duplicate.stderr

    malformed_path = tmp_path / "malformed.jsonl"
    malformed_path.write_text('{"id":\n', encoding="utf-8")
    malformed = _run_insights_validator(malformed_path)
    assert malformed.returncode == 1
    assert "JSON として不正" in malformed.stderr

    usage = subprocess.run(
        [sys.executable, str(_INSIGHTS_VALIDATOR)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert usage.returncode == 2
    assert "usage:" in usage.stderr


def test_theme_compare_missing_themes_error_uses_current_config_path(monkeypatch, caplog) -> None:
    from youtube_automation.commands.analytics import theme_compare

    config = SimpleNamespace(content=SimpleNamespace(tags=SimpleNamespace(themes={})))

    caplog.set_level(logging.ERROR, logger="youtube_automation.commands.analytics.theme_compare")
    monkeypatch.setattr(theme_compare, "_channel_dir", lambda: ROOT)
    monkeypatch.setattr(theme_compare, "load_config", lambda: config)
    monkeypatch.setattr(theme_compare, "load_latest_daily_snapshot", lambda _path: {"daily": []})
    monkeypatch.setattr(theme_compare, "_load_video_meta", lambda _channel_dir: {"video": {"title": "x"}})
    monkeypatch.setattr(
        theme_compare,
        "build_launch_curve_frame",
        lambda **_kwargs: pd.DataFrame([{"video_id": "video", "days_since_publish": 0}]),
    )

    assert theme_compare.main([]) == 2
    assert "config/channel/content.json::tags.themes" in caplog.text


def test_automation_schedule_skill_contract() -> None:
    """#1892: `/wf-new --schedule` の reference 群が整合している."""
    skill_path = ".claude/skills/wf-new/references/schedule.md"
    skill = _read(skill_path)

    # references 単一ソース化: 本文で参照するスクリプトが実在する
    for ref in (
        "detect_runtime.sh",
        "schedule_config.py",
        "schedule_backend.py",
        "scheduler_job.sh",
        "run_scheduled.sh",
    ):
        assert ref in skill
        assert (ROOT / ".claude/skills/wf-new/references" / ref).exists()

    # Hard Gates は冒頭 60 行以内（automation-schedule 固有の契約）
    head = "\n".join(skill.splitlines()[:60])
    assert "## Hard Gates" in head
    assert "allow_external_publish" in head

    # 統合後も兄弟スキルとの責務境界を保つ
    assert "/automation --update" in skill
    assert "/automation-release" in skill
    assert "/wf-next" in skill

    # 設定スキーマの正へのポインタ
    assert "ScheduledAutomation" in skill
    assert "Codex" in skill and "claude-code-cloud" in skill and "claude-cowork-local" in skill
    assert "--confirm-os-fallback" in skill


def test_setup_channel_points_scheduled_automation_to_wf_new_schedule() -> None:
    """#1892: setup --channel は scheduled_automation を生成せず後続 skill へ誘導する."""
    setup_channel = _read(".claude/skills/setup/references/channel-mode.md")
    assert "`scheduled_automation`" in setup_channel
    assert "/wf-new --schedule" in setup_channel
