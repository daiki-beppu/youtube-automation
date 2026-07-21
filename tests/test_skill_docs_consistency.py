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

ROOT = Path(__file__).resolve().parents[1]


def test_all_skills_use_machine_readable_chain_block() -> None:
    skill_paths = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))
    chain_block = re.compile(
        r"\A---\n.*?\n---\n\n## 前後工程\n\n"
        r"- `前工程`: (?P<upstream>[^\n]+)\n"
        r"- `後工程`: (?P<downstream>[^\n]+)\n",
        re.DOTALL,
    )
    chain_value = re.compile(
        r"^(?:`なし`|`\*`（共通基盤としてほぼ全スキル）|"
        r"`/[a-z0-9-]+`(?:, `/[a-z0-9-]+`)*)$"
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
            for reference in re.findall(r"`/([a-z0-9-]+)`", value):
                assert reference in known_skills, f"{path}: 存在しない skill 参照 /{reference}"


def test_skill_chain_legacy_summary_formats_are_absent() -> None:
    legacy_summary = re.compile(
        r"^\*\*(?:前|後)工程|^(?:前|後)工程は|^次工程は|^→ |"
        r"^- `/[^\n]+` → (?:前|後)工程|"
        r"^description:.*(?:前|後|次)工程[ :：]/",
        re.MULTILINE,
    )

    for path in sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        assert legacy_summary.search(text) is None, f"{path}: 旧形式の前後工程一覧が残存"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _assert_appears_before(text: str, earlier: str, later: str) -> None:
    earlier_idx = text.find(earlier)
    later_idx = text.find(later)
    assert earlier_idx >= 0, f"{earlier!r} not found"
    assert later_idx >= 0, f"{later!r} not found"
    assert earlier_idx < later_idx


def _frontmatter(path: str) -> dict:
    text = _read(path)
    if not text.startswith("---\n"):
        raise AssertionError(f"{path} does not start with frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise AssertionError(f"{path} frontmatter is not closed")
    parsed = yaml.safe_load(text[4:end])
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


def test_theme_compare_docs_and_error_use_content_tags_themes() -> None:
    for path in (
        ".claude/skills/analytics-analyze/SKILL.md",
        "src/youtube_automation/scripts/theme_compare.py",
    ):
        text = _read(path)
        assert "channel_config.tags.themes" not in text
        assert "config/channel/content.json::tags.themes" in text

    assert "load_config().content.tags.themes" in _read(".claude/skills/analytics-analyze/SKILL.md")


def test_analytics_analyze_documents_playlist_effect_section() -> None:
    analytics_analyze = _read(".claude/skills/analytics-analyze/SKILL.md")
    analytics_collect = _read(".claude/skills/analytics-collect/SKILL.md")

    assert "分析項目」の 7 項目" in analytics_analyze
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
        "src/youtube_automation/scripts/populate_scene_phrases.py",
    ):
        text = _read(path)
        assert "config/channel/localizations.json::supported_languages" not in text
        assert "config/localizations.json::supported_languages" in text


def test_wf_new_theme_scenes_fallback_uses_agent_generated_en_phrase() -> None:
    wf_new = _read(".claude/skills/wf-new/SKILL.md")

    assert "theme_scenes[<theme>] が未定義の場合" in wf_new
    assert '--en "<Agent-generated English scene phrase>"' in wf_new
    assert "--translations-file /tmp/scene-phrases.json" in wf_new


def test_upload_settings_contract_is_nested_in_schedule_config() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    regeneration_mode = _read(".claude/skills/channel-new/references/regeneration-mode.md")
    channel_init = _read("src/youtube_automation/cli/channel_init_templates.py")
    channel_init_test = _read("tests/test_channel_init.py")
    schedule_template = _read(".claude/skills/channel-new/references/schedule-template.json")

    for text in (channel_new, regeneration_mode, channel_init, channel_init_test):
        assert "config/upload_settings.json" not in text

    assert "`config/schedule_config.json`（`upload_settings` を含む）" in channel_new
    assert "投稿頻度と `upload_settings`" in regeneration_mode
    assert '"upload_settings": {' in schedule_template


def test_setup_directory_generation_contract_is_separate_from_channel_config() -> None:
    setup = _read(".claude/skills/setup/SKILL.md")
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    setup_dirs = _read("src/youtube_automation/cli/setup_dirs.py")
    channel_init = _read("src/youtube_automation/cli/channel_init.py")
    setup_directory_contract = _read("src/youtube_automation/cli/setup_directory_contract.py")
    pyproject = _read("pyproject.toml")

    assert "uv run yt-setup-dirs" in setup
    assert "`/setup` では `config/channel/*.json` を生成しない" in setup
    assert "`/setup` が作成済みのディレクトリはそのまま再利用する" in channel_new
    assert "setup_directory_contract" in setup_dirs
    assert "setup_directory_contract" in channel_init
    assert "SETUP_DIRECTORIES" in setup_directory_contract
    assert 'yt-setup-dirs = "youtube_automation.cli_entrypoints:yt_setup_dirs"' in pyproject


def test_channel_new_ttp_confirmation_contract_is_documented() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    branding_snapshot_script = _read(".claude/skills/channel-new/references/fetch_branding_snapshot.py")

    forbidden = (
        "--benchmark-channel",
        "uv run yt-discover-competitors",
        "uv run yt-benchmark-collect",
        "uv run yt-benchmark-comments",
        "data/benchmark_YYYYMMDD.json",
        "data/comments_YYYYMMDD.json",
        "/channel-new  → TTP hearing + benchmark",
        "TTP ベンチマーク収集",
    )
    for text in forbidden:
        assert text not in channel_new

    assert "TTP seed fetch と承認済み対象反映" in channel_new
    assert "承認前に `benchmark.channels` へ書き込まない" in channel_new
    assert "追加調査は後続スキルへ委譲" in channel_new
    assert "docs/channel/ttp-seed-confirmation.md" in channel_new
    assert "docs/channel/competitor-branding-snapshot.json" in channel_new
    assert ".claude/skills/channel-new/references/fetch_branding_snapshot.py" in channel_new
    assert "`description` / `keywords` / `localizations` / `brandingSettings` は含まない" in channel_new
    assert "untrusted data" in channel_new
    assert "承認済み TTP 対象が 0 件の場合は Step 7 以降へ進まない" in channel_new
    assert "TTP 完了条件" in channel_new
    assert "relationship（何を転写するか）" in channel_new
    assert "ttp_wf_new_readiness" in channel_new
    assert "`warn` の場合は成功案内を出さない" in channel_new
    assert "ユーザー承認済み例外" in channel_new

    assert 'CHANNELS_PART = "snippet,brandingSettings,localizations"' in branding_snapshot_script
    assert '"untrusted_data": True' in branding_snapshot_script


def test_channel_new_ttp_hearing_routes_direction_to_integrated_mode() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    overview = channel_new.split("## Overview", 1)[1].split("## モード判別", 1)[0]
    mode_routing = channel_new.split("## モード判別", 1)[1].split("## TTP 原則", 1)[0]
    direction_mode_row = next(line for line in mode_routing.splitlines() if line.startswith("| 方向性検討モード |"))
    direction_mode_stub = channel_new.split("## 方向性検討モード", 1)[1].split("\n## 再生成モード", 1)[0]
    direction_mode = _read(".claude/skills/channel-new/references/direction-mode.md")
    ttp_principles = channel_new.split("## TTP 原則", 1)[1].split("## 外部データの扱い", 1)[0]
    step1 = channel_new.split("### Step 1: TTP ヒアリング", 1)[1].split(
        "### Step 2: 現在のディレクトリを repo 初期化",
        1,
    )[0]
    step4 = channel_new.split("### Step 4: フルパッケージ config / 初期運用ファイル生成", 1)[1].split(
        "### Step 5: TTP seed fetch と承認済み対象反映",
        1,
    )[0]
    step7 = channel_new.split("### Step 7: 本格ペルソナ作成チェーン", 1)[1].split(
        "### Step 8: branding 初回反映",
        1,
    )[0]
    cross_references = channel_new.split("## Cross References", 1)[1]

    assert "「どんなチャンネルにしたいか」より先に" not in ttp_principles
    assert "`/channel-new` では方向性・差別化・ポジショニングを聞かず" in ttp_principles

    assert "TTP 対象への転写要素（タイトル構造 / サムネ構図 / 投稿頻度 / 尺 / ジャンル / branding）に限定" in step1
    step1_questions = [line for line in step1.splitlines() if line.startswith("- **")]
    assert step1_questions == [
        "- **TTP したいチャンネル**: URL / handle / channel ID を 1 件以上",
        "- **転写したい要素**: タイトル構造 / サムネ構図 / 投稿頻度 / 尺 / ジャンル / branding のどれか",
        "- **要素ごとの関係性メモ**: "
        "タイトル構造 / サムネ構図 / 投稿頻度 / 尺 / ジャンル / branding のうち、どの観察をどう転写するか",
        "- **branding 方針**: TTP 対象の description / keywords / localizations をどの程度転写するか",
    ]
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
    assert "検討が必要なら `/channel-new` 完了後の方向性検討モードに委譲" in step1
    assert "Step 1 の TTP ヒアリングとは別に、config 生成に必要な初期値だけをここで確認する" in step4

    assert "方向性の検討・精緻化（必要な場合だけ、方向性検討モード）" in overview
    assert "`/channel-new` は方向性を聞かず" in overview
    assert "旧 `/channel-direction`" not in overview
    assert "方向性検討モード" in mode_routing
    assert "Step D1〜D5" in mode_routing
    assert "方向性の検討・精緻化が必要な場合も、新規開設モードでは質問せず" in mode_routing
    for trigger in ("方向性決めたい", "ポジショニング", "差別化", "ブレスト"):
        assert trigger in direction_mode_row

    assert "references/direction-mode.md" in direction_mode_stub
    for heading in (
        "## Step D1: 分析レポートの読み込みとサマリー",
        "## Step D2: ポジショニング議論",
        "## Step D3: 決定事項の整理",
        "## Step D4: 方向性ドキュメント保存",
        "## Step D5: 次フェーズへの案内",
    ):
        assert heading in direction_mode
    assert "決定事項を `docs/channel/channel-direction.md` に保存" in direction_mode
    assert "`mkdir -p docs/channel`" in direction_mode
    assert "config を再生成・再反映する場合は `/channel-new`（再生成モード）" in direction_mode
    assert "制作に進む場合は `/wf-new`" in direction_mode

    assert "/viewer-voice` → `/audience-persona-design` → `/viewing-scene" in step7
    assert "必須" in step7
    assert "docs/channel/personas/persona-definition.md" in step7
    assert "Step 8 へ進まない" in step7
    assert "channel-new-persona.md" not in channel_new

    audience_persona = _read(".claude/skills/audience-persona-design/SKILL.md")
    assert "新規開設時" in audience_persona
    assert "競合チャンネルのコメント" in audience_persona
    assert "公開前" in audience_persona
    assert "channel-new-persona.md" not in audience_persona

    viewer_voice = _read(".claude/skills/viewer-voice/SKILL.md")
    assert "新規開設モードでは Step 7 の必須前工程" in viewer_voice
    assert "公開後の再分析では" in viewer_voice
    assert "標準フローでは実行せず" not in viewer_voice

    assert "旧 `/channel-direction`" not in cross_references


def test_branding_missing_report_requires_existing_file_check_before_generation() -> None:
    skill_docs = {
        "channel-new": _read(".claude/skills/channel-new/SKILL.md"),
        "automation-update": _read(".claude/skills/automation-update/SKILL.md"),
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


def test_channel_new_frontmatter_keeps_import_dispatch_keywords() -> None:
    frontmatter = _frontmatter(".claude/skills/channel-new/SKILL.md")
    assert frontmatter["name"] == "channel-new"
    description = frontmatter["description"]
    for keyword in (
        "既存チャンネル",
        "チャンネル取り込み",
        "config 生成",
        "channel-import",
        "方向性決めたい",
        "ポジショニング",
        "差別化",
        "ブレスト",
    ):
        assert keyword in description


def test_channel_new_ttp_completion_condition_is_an_early_hard_gate() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    completion_heading = "## 完了条件（新規開設モード）"

    assert channel_new.splitlines().index(completion_heading) < 60
    completion = channel_new.split(completion_heading, 1)[1].split("## Overview", 1)[0]
    assert "docs/channel/personas/persona-definition.md" in completion
    assert "候補ごとの source、seed fetch 要約、承認 / 不採用判断" in completion
    assert "`snippet` / `brandingSettings` / `localizations` snapshot" in completion
    assert "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default" in completion
    assert "data/video_analysis/<slug>/*.json::suno_preset.genre_line" in completion


def test_channel_new_docs_distinguish_required_initial_persona_from_optional_reanalysis() -> None:
    features = _read("docs/features.md")
    onboarding = _read("ONBOARDING.md")

    assert "/viewer-voice` → `/audience-persona-design` → `/viewing-scene`" in features
    assert "`/viewer-voice` は公開後の再分析では任意" in features
    assert "公開前のペルソナチェーンは既存の競合 / TTP / viewer-voice 成果物を入力に完走" in features
    assert "公開後の `/viewing-scene` は従来どおり Analytics report を要求する" in features
    assert "/viewer-voice         → 公開後のコメント再分析" in onboarding
    assert "公開前チェーンは競合 / TTP / viewer-voice 成果物を入力" in onboarding
    assert "自チャンネル Analytics report や任意の本格 benchmark 収集を要求しない" in onboarding
    assert "公開後の見直しでは従来どおりそれらを入力にする" in onboarding


def test_channel_new_prelaunch_persona_chain_propagates_context_without_analytics() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    audience_persona = _read(".claude/skills/audience-persona-design/SKILL.md")
    viewing_scene = _read(".claude/skills/viewing-scene/SKILL.md")

    step7 = channel_new.split("### Step 7: 本格ペルソナ作成チェーン", 1)[1].split(
        "### Step 8: branding 初回反映",
        1,
    )[0]
    assert "実行コンテキスト: 新規開設（公開前）" in step7
    assert "`/audience-persona-design` から同じ実行コンテキストを引き継いで `/viewing-scene`" in step7
    for path in (
        "docs/plans/viewer-voice-analysis.md",
        "docs/channel/ttp-seed-confirmation.md",
        "docs/channel/competitor-branding-snapshot.json",
    ):
        assert path in step7
    assert "任意の `/benchmark`" in step7
    assert "`reports/analysis_*.md` は要求しない" in step7

    entry_contract = audience_persona.split("入口で実行コンテキスト", 1)[1].split("## 完了条件", 1)[0]
    assert "新規開設（公開前）" in entry_contract
    assert "公開後" in entry_contract
    assert "任意の `/benchmark` 成果物" in entry_contract
    for path in (
        "docs/plans/viewer-voice-analysis.md",
        "docs/channel/ttp-seed-confirmation.md",
        "docs/channel/competitor-branding-snapshot.json",
    ):
        assert path in entry_contract
    phase5 = audience_persona.split("### Phase 5: viewing-scene 検証", 1)[1].split(
        "### Phase 6: 最終 persona-definition.md 更新",
        1,
    )[0]
    assert "新規開設（公開前）" in phase5
    assert "公開後" in phase5
    assert "実行コンテキストを明示して渡し" in phase5
    audience_guidance = audience_persona.split("## 障害時ガイダンス", 1)[1].split("## 関連ファイル", 1)[0]
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

    viewing_overview = viewing_scene.split("## Overview", 1)[1].split("## 完了条件", 1)[0]
    assert "新規開設（公開前）" in viewing_overview
    assert "公開後" in viewing_overview
    assert "実行コンテキストが明示されない場合もこちら" in viewing_overview
    guard = viewing_scene.split("### 停止する fail", 1)[1].split("### 許容する fail", 1)[0]
    assert "新規開設（公開前）" in guard
    assert "公開後に `reports/analysis_*.md` が無い" in guard
    assert "`reports/analysis_*.md` が無い" not in guard.replace(
        "公開後に `reports/analysis_*.md` が無い",
        "",
    )
    for path in (
        "docs/plans/viewer-voice-analysis.md",
        "docs/channel/ttp-seed-confirmation.md",
        "docs/channel/competitor-branding-snapshot.json",
    ):
        assert path in guard


def test_viewing_scene_keeps_post_publish_inputs_and_analysis_phases() -> None:
    viewing_scene = _read(".claude/skills/viewing-scene/SKILL.md")
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


def test_channel_new_import_mode_contract_is_separate_from_ttp_completion() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    import_mode = _read(".claude/skills/channel-new/references/import-mode.md")
    config_rules = _read(".claude/skills/channel-new/references/config-generation-rules.md")

    assert "TTP 完了条件（新規開設モード）" in channel_new
    assert "docs/channel/personas/persona-definition.md" in channel_new
    assert "既存チャンネル取り込みモードにはこの TTP 完了条件を適用しない" in channel_new
    assert "取り込み Step 8: 次ステップ案内" in channel_new
    assert "references/import-mode.md" in channel_new
    assert "`music_engine` に入れる値は `suno` / `lyria` のどちらか" in import_mode
    assert "both` は config 契約外" in import_mode
    assert "audio.target_duration_min" in import_mode
    assert "audio.target_duration_max" in import_mode
    assert "meta / content / youtube / analytics / audio" in import_mode
    assert "references/config-template/audio.json" in import_mode
    assert "責務別 5 ファイル" in import_mode
    assert (ROOT / ".claude/skills/channel-new/references/config-template/audio.json").is_file()
    assert (
        "`config/channel/meta.json::channel.channel_id` が未設定の場合は、認証済みチャンネル ID を必ず取得"
        in import_mode
    )
    assert "`channel_id` の `config/channel/meta.json::channel.channel_id` 保存" in import_mode
    for text in (channel_new, import_mode):
        assert "channel_id` 取得またはユーザー承認済み" not in text
        assert "ユーザー承認済みの未完了項目明記" not in text
    assert (
        "benchmark.channels`、`ttp-seed-confirmation.md`、branding snapshot、"
        "`ttp_wf_new_readiness` は取り込みモードの必須完了条件ではない"
    ) in import_mode
    assert "config-template" + ".json" not in config_rules
    assert "config-template/*.json" in config_rules


def test_channel_new_localizations_priority_matches_generation_rules() -> None:
    regeneration_mode = _read(".claude/skills/channel-new/references/regeneration-mode.md")
    rules = _read(".claude/skills/channel-new/references/config-generation-rules.md")

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
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    automation_update = _read(".claude/skills/automation-update/SKILL.md")

    assert "初回保存と automation-update 前の整理" in channel_new
    assert "git status --porcelain" in channel_new
    assert "後続の `/automation-update` は dirty worktree で停止する" in channel_new
    assert "git add -A" in channel_new
    assert "`git add -A` 後の guard を唯一の安全境界にする" in channel_new
    assert "bash .claude/skills/channel-new/references/initial_save_guard.sh || exit 1" in channel_new
    assert 'git commit -m "chore: 初回チャンネル設定を保存"' in channel_new
    assert "secret-like file staged; unstaged before commit" in channel_new
    assert "staged secret を自動で外して停止" in channel_new
    assert "未コミット変更が残っています。/automation-update の前に以下を完了してください" in channel_new
    assert "保存未完了として終了した場合は、以下の成功案内は出さない" in channel_new
    assert "初回保存も完了しているため" in channel_new

    assert "`git status --porcelain` が **非空** の場合" in automation_update
    assert "/channel-new 直後の初回保存が未完了なら" in automation_update


def test_channel_new_pre_wf_new_checks_include_analytics_reporting_and_live_streaming() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    step9 = channel_new.split("### Step 9: wf-new 接続前チェック", 1)[1].split(
        "### Step 10: 初回保存と automation-update 前の整理",
        1,
    )[0]
    success_message = channel_new.split("保存未完了として終了した場合は、以下の成功案内は出さない", 1)[1].split(
        "## 障害時ガイダンス",
        1,
    )[0]

    assert "Analytics / Reporting レポート取得設定が未確認" in step9
    assert "YouTube Analytics / Reporting API" in step9
    assert "Reporting API job 作成状態" in step9
    assert "`/analytics-collect`" in step9
    assert "`/setup`" in step9
    assert "初回制作は止めず" in step9

    assert "ライブ配信を使う可能性がある" in step9
    assert "YouTube Studio で Live streaming を早めに有効化" in step9
    assert "初回配信可能になるまで最大 24 時間" in step9
    assert "`/streaming`" in step9

    assert "公開後の分析は /analytics-collect" in success_message
    assert "Live streaming 有効化" in success_message
    assert "/streaming の準備確認" in success_message


def test_wf_new_fail_fast_contract_points_to_channel_new_and_doctor_readiness() -> None:
    wf_new = _read(".claude/skills/wf-new/SKILL.md")
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    doctor = _read("src/youtube_automation/cli/doctor.py")

    hard_gates = wf_new.split("## Hard Gates", 1)[1].split("## When to Use", 1)[0]

    assert "config/channel/` が存在し、`load_config()` でロードできること" in hard_gates
    assert "存在しない場合は `/channel-new`" in hard_gates
    assert "ロード失敗の場合は `/channel-new`（既存チャンネル取り込みモード）" in hard_gates
    assert "Suno readiness gate" in hard_gates
    assert "uv run yt-video-analyze --source benchmark --competitor <slug> --top 5" in hard_gates

    assert "既存チャンネル取り込みモード" in channel_new
    assert "ttp_wf_new_readiness" in channel_new
    assert "def check_channel_config" in doctor
    assert 'id="channel_config"' in doctor
    assert "def check_ttp_wf_new_readiness" in doctor
    assert 'id="ttp_wf_new_readiness"' in doctor


def test_analytics_collect_documents_reporting_api_preflight() -> None:
    analytics_collect = _read(".claude/skills/analytics-collect/SKILL.md")

    assert "`/analytics-collect reporting`" in analytics_collect
    assert "uv run yt-analytics --reporting-dry-run" in analytics_collect
    assert "uv run yt-analytics --reporting-create-job" in analytics_collect
    assert "uv run yt-analytics --include-reporting" in analytics_collect
    assert "最大 48 時間" in analytics_collect
    assert "youtubereporting.googleapis.com" in analytics_collect


def test_analytics_collect_documents_full_depth_collection_path() -> None:
    analytics_collect = _read(".claude/skills/analytics-collect/SKILL.md")

    assert "`/analytics-collect full`" in analytics_collect
    assert "uv run yt-analytics --depth full" in analytics_collect
    assert "references/validate-depth.sh" in analytics_collect
    assert "retention" in analytics_collect
    assert "by_country" in analytics_collect


def test_analytics_analyze_requires_numeric_retention_evidence_for_full_data() -> None:
    analytics_analyze = _read(".claude/skills/analytics-analyze/SKILL.md")
    validator = _read(".claude/skills/analytics-analyze/references/analysis-json-validator.md")

    assert "視聴維持率分析" in analytics_analyze
    assert "references/analysis-json-validator.md" in analytics_analyze
    assert "retention_analysis" in validator
    assert "data_points > 0" in validator
    assert "空でない `retention_curve`" in validator


@pytest.mark.parametrize(
    "skill_path",
    [
        ".claude/skills/analytics-collect/SKILL.md",
        ".claude/skills/analytics-analyze/SKILL.md",
    ],
)
def test_revised_analytics_skills_stop_when_channel_config_is_invalid(skill_path: str) -> None:
    skill = _read(skill_path)
    prerequisite = skill.split("## 前提", 1)[1].split("\n## ", 1)[0]

    assert "`load_config()` でロード可能" in prerequisite
    assert "ここで停止" in prerequisite
    assert "後続手順へ進まない" in prerequisite


@pytest.mark.parametrize(
    "secret_path",
    [".env", "auth/client_secrets.json", "auth/token.json", "auth/token_streaming.json"],
)
def test_channel_new_initial_save_guard_blocks_staged_secrets(tmp_path: Path, secret_path: str) -> None:
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

    guard = ROOT / ".claude/skills/channel-new/references/initial_save_guard.sh"
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


def test_channel_new_initial_save_plain_add_then_guard_blocks_oauth_secret(tmp_path: Path) -> None:
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

    guard = ROOT / ".claude/skills/channel-new/references/initial_save_guard.sh"
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


def test_channel_new_initial_save_guard_allows_non_secret_staged_files(tmp_path: Path) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "-A")

    guard = ROOT / ".claude/skills/channel-new/references/initial_save_guard.sh"
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


def test_channel_new_initial_save_success_path_commits_and_cleans_worktree(tmp_path: Path) -> None:
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

    guard = ROOT / ".claude/skills/channel-new/references/initial_save_guard.sh"
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


def test_channel_new_followup_skill_routing_uses_new_contract() -> None:
    discover = _read(".claude/skills/discover-competitors/SKILL.md")
    research = _read(".claude/skills/channel-new/references/analysis-mode.md")
    viewer_voice = _read(".claude/skills/viewer-voice/SKILL.md")
    setup = _read(".claude/skills/setup/SKILL.md")
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    channel_regeneration_mode = _read(".claude/skills/channel-new/references/regeneration-mode.md")
    channel_direction_mode = _read(".claude/skills/channel-new/references/direction-mode.md")
    onboarding = _read("ONBOARDING.md")
    features = _read("docs/features.md")

    assert "/channel-new Step 5 の前段" not in discover
    assert "`/channel-new` の標準フローでは実行しない" in discover
    assert "ユーザー承認と relationship メモを必ず残す" in discover
    assert "genre_keywords" not in discover
    assert "target_scene" not in discover
    assert "config/channel/content.json::genre.{primary,style,context}" in discover

    assert "/benchmark` と `/viewer-voice` で収集した" in research
    assert "docs/channel-research.md" in research
    assert "/viewer-voice` → 前提" in research

    assert "チャンネル立ち上げ・方向性見直し時に必ず使用" not in viewer_voice
    assert "`/channel-new` の新規開設モードでは Step 7 の必須前工程として実行する" in viewer_voice
    assert "公開後の再分析では" in viewer_voice
    assert "任意後続スキル" not in viewer_voice
    assert "/audience-persona-design の必須入力（viewer-voice-analysis.md）" in viewer_voice

    for path_text in (setup, channel_new, channel_regeneration_mode, channel_direction_mode, onboarding):
        assert "TTP benchmark" not in path_text
        assert "TTP ベンチマーク収集" not in path_text

    assert "TTP 対象確認、config 生成、ペルソナ、branding" in setup
    assert "TTP 対象確認 / seed fetch / 承認済み benchmark.channels 反映" in channel_regeneration_mode
    assert "旧 `/channel-direction` は本スキルの方向性検討モードに統合済み" not in channel_new
    assert "docs/channel/ttp-seed-confirmation.md" in channel_direction_mode
    assert "docs/channel/competitor-branding-snapshot.json" in channel_direction_mode
    assert "config/channel/analytics.json::benchmark.channels" in channel_direction_mode
    assert "入力がすべて欠けている場合" in channel_direction_mode
    assert "根拠なしに方向性検討を進めない" in channel_direction_mode
    assert "/channel-new` 新規開設モード" in channel_direction_mode
    assert "untrusted data" in channel_direction_mode
    assert "動画尺 / 投稿頻度 / コメント語彙は収集済みデータがある場合だけ使う" in channel_direction_mode

    followup_direction_files = [
        ".claude/skills/alignment-check/SKILL.md",
        ".claude/skills/collection-ideate/SKILL.md",
        ".claude/skills/lyria/SKILL.md",
        ".claude/skills/flop-analysis/SKILL.md",
        ".claude/skills/video-analyze/SKILL.md",
    ]
    for path in followup_direction_files:
        content = _read(path)
        assert "/channel-new" in content
        assert "方向性検討モード" in content
        assert "`/channel-direction`" not in content

    assert "ビジョン共有 + 競合発掘" not in onboarding
    assert "yt-discover-competitors` で 5-10 件" not in onboarding
    assert "ベンチマークデータ + コメント収集まで実行" not in onboarding
    assert "docs/channel/ttp-seed-confirmation.md" in onboarding
    assert "docs/channel/competitor-branding-snapshot.json" in onboarding
    assert "/channel-new 方向性検討モード" in onboarding
    assert "| /channel-direction |" not in features
    assert "untrusted data" in onboarding

    assert "新規チャンネル開設 → 競合発掘 → 方向性決定 → セットアップ" not in features
    assert (
        "`/setup` → `/channel-new`（`/viewer-voice` → `/audience-persona-design` → `/viewing-scene` を含む）→ `/wf-new`"
    ) in features


def test_skill_frontmatter_descriptions_disambiguate_sibling_routes() -> None:
    benchmark_desc = _frontmatter(".claude/skills/benchmark/SKILL.md")["description"]
    channel_new_desc = _frontmatter(".claude/skills/channel-new/SKILL.md")["description"]
    videoup_desc = _frontmatter(".claude/skills/videoup/SKILL.md")["description"]
    video_upload_desc = _frontmatter(".claude/skills/video-upload/SKILL.md")["description"]

    assert "「競合分析」" not in benchmark_desc
    assert "「競合データ収集」" in benchmark_desc
    assert "収集済みデータのチャンネル全体分析は /channel-new 分析モード" in benchmark_desc
    assert "「競合分析」" in channel_new_desc
    assert "データ収集・更新だけなら /benchmark" in channel_new_desc
    assert "サムネイルだけの深掘りは /thumbnail-research" in channel_new_desc

    assert "YouTube への投稿は /video-upload" in videoup_desc
    assert "動画ファイルの生成（MP3→MP4）は /videoup" in video_upload_desc


def test_thumbnail_search_order_is_documented() -> None:
    expected_order = "`10-assets/thumbnail.jpg` → `10-assets/thumbnail.png`"
    for path in (
        ".claude/skills/video-upload/SKILL.md",
        ".claude/skills/video-upload/references/posting-checklist.md",
    ):
        text = _read(path)
        assert expected_order in text
        assert "→ `10-assets/main.jpg` → `10-assets/main.png`" not in text
        assert "textless 動画背景" in text


def test_upload_schedule_plan_must_precede_publish_guidance() -> None:
    video_upload = _read(".claude/skills/video-upload/SKILL.md")
    wf_next = _read(".claude/skills/wf-next/SKILL.md")
    posting_checklist = _read(".claude/skills/video-upload/references/posting-checklist.md")
    scheduled_publish = _read(".claude/skills/video-upload/references/scheduled-publish.md")

    for text in (video_upload, wf_next, posting_checklist, scheduled_publish):
        assert "uv run yt-upload-collection --plan" in text
        assert "📅 公開設定: 即時公開 (public)" in text
        assert "📅 公開設定: 限定公開 (unlisted)" in text
        assert "📅 公開設定: 非公開 (private)" in text
        assert "📅 公開予定" in text

    for text in (video_upload, posting_checklist, scheduled_publish):
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
    _assert_appears_before(wf_next_gate, "uv run yt-upload-collection --plan", "/video-upload")


def test_first_post_playlist_initialization_contract_is_documented() -> None:
    playlist = _read(".claude/skills/playlist/SKILL.md")
    video_upload = _read(".claude/skills/video-upload/SKILL.md")
    wf_next = _read(".claude/skills/wf-next/SKILL.md")
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    checklist = _read(".claude/skills/video-upload/references/posting-checklist.md")

    description = _frontmatter(".claude/skills/playlist/SKILL.md")["description"]
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

    assert "/playlist" in channel_new
    assert "`yt-playlist-status` → `yt-playlist-manager --init --dry-run` → `--init`" in channel_new

    for text in (playlist, video_upload, wf_next, channel_new, checklist):
        assert "playlist_id" in text
        assert "自動 assign" in text

    assert "`collection` 型では `collection_uploader` 内部の `assign_video()`" in video_upload
    assert "プレイリストへの動画追加は後続のアップロード経路が担う" in video_upload
    assert "`skip_upload_approval` とは別の playlist 作成ゲート" in wf_next
    assert "`skip_upload_approval = true` でも" in wf_next
    assert "確認を省略しない" in wf_next
    assert "ユーザーが playlist 初期化を却下した場合" in wf_next
    assert "`/video-upload` を実行せず停止" in wf_next
    assert "`config/channel/playlists.json` が無い" in wf_next
    assert "全 playlist に `playlist_id` がある場合はスキップ" in wf_next
    assert "初投稿プレイリスト初期化ゲート" in wf_next
    assert "`upload.video_id = null`" in wf_next
    assert "初回動画の追加は `/video-upload` 内部の自動 assign に任せる" in checklist


def test_wf_next_skip_approval_keys_are_documented_consistently() -> None:
    """#1744: wf_next の boolean は「true = 手動工程を省く」向きで example / docs が一致する."""
    wf_next = _read(".claude/skills/wf-next/SKILL.md")
    wf_status = _read(".claude/skills/wf-status/SKILL.md")
    schema = _read(".claude/skills/wf-new/references/schema.md")
    example = _read("examples/channel_config.example/workflow.json")
    example_config = json.loads(example)
    wf_next_example = example_config["workflow"]["wf_next"]

    # example は新キーのみ（既定値どおり true = 承認省略）で、旧キーを含まない
    assert '"skip_audio_approval": true' in example
    assert '"skip_upload_approval": true' in example
    assert "approval_gates" not in wf_next_example

    # wf-next は新キーを正として記述し、旧キーは後方互換 alias + 同時指定エラーとして言及する
    for key in ("skip_audio_approval", "skip_upload_approval"):
        assert key in wf_next
    assert "後方互換 alias" in wf_next
    assert "同時指定すると `ConfigError`" in wf_next
    # ゲート発動条件は常に「skip_* = false のとき承認」の向きで書く（旧向きの記述を残さない）
    assert "approval_gates.upload = true" not in wf_next
    assert "approval_gates.audio = true" not in wf_next

    # wf-status / wf-new schema も同じ向きで参照する
    assert "skip_audio_approval" in wf_status
    assert "skip_upload_approval" in wf_status
    assert "skip_audio_approval" in schema


def test_common_docs_list_optional_channel_config_files() -> None:
    required = ("shorts.json", "comments.json", "pinned-comment.json", "distrokid.json")

    for path in ("README.md", "AGENTS.md", "CLAUDE.md", "ONBOARDING.md"):
        text = _read(path)
        for name in required:
            assert name in text, f"{path} missing {name}"


def test_distrokid_skill_uses_helper_name() -> None:
    skill_path = ROOT / ".claude" / "skills" / "distrokid-helper" / "SKILL.md"
    assert skill_path.exists()

    frontmatter = _frontmatter(".claude/skills/distrokid-helper/SKILL.md")
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


def test_suno_helper_docs_use_the_visible_server_source_picker_contract() -> None:
    skill = _read(".claude/skills/suno-helper/SKILL.md")
    readme = _read("extensions/suno-helper/README.md")

    for text in (skill, readme):
        assert '[data-suno-control="server-source-trigger"]' in text
        assert 'role="option"' in text
        assert '[data-suno-control="server-url"]' not in text


def test_community_post_declares_raw_json_loader_exception() -> None:
    text = _read(".claude/skills/community-post/SKILL.md")

    assert "skill-local raw JSON 例外" in text
    assert "utils.config.load_config()" in text
    assert "`community` section を持たない" in text
    assert "投稿本文・Studio URL の実データには使わない" in text
    assert "fallback や merge 元にしない" in text


def test_community_draft_documents_typed_batch_generator_contract() -> None:
    text = _read(".claude/skills/community-draft/SKILL.md")

    assert "load_config().community_draft.posts" in text
    assert "references/generate_batch.py" in text
    assert "planning.publish_target_at" in text
    assert "docs/adr/0019-community-helper-extension.md" in text
    assert "community-posts.json" in text


def test_skill_config_defaults_have_read_gate_in_skill_docs() -> None:
    skill_dirs = sorted(path.parent for path in (ROOT / ".claude" / "skills").glob("*/config.default.yaml"))
    assert skill_dirs

    for skill_dir in skill_dirs:
        skill = skill_dir.name
        rel_skill_md = f".claude/skills/{skill}/SKILL.md"
        text = _read(rel_skill_md)

        assert "## 設定読み込みゲート" in text, f"{skill} missing config read gate"
        assert f".claude/skills/{skill}/config.default.yaml" in text
        assert f"config/skills/{skill}.yaml" in text
        loader_key = "postmortem" if skill == "flop-analysis" else skill
        assert f'load_skill_config("{loader_key}")' in text
        assert "SKILL.md の説明や記憶から設定値を推測しない" in text
        assert "必ず Read" in text
        assert "存在する場合" in text
        assert "勝手に作成しない" in text

        if skill == "community-post":
            assert "default と任意 override を確認する" in text
            assert "gate で Read" in text
        else:
            assert "deep-merge 前提" in text
            assert "チャンネル上書きを優先" in text

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


def test_analytics_report_theme_colors_are_config_driven() -> None:
    skill = _read(".claude/skills/analytics-report/SKILL.md")
    default_config = yaml.safe_load(_read(".claude/skills/analytics-report/config.default.yaml")) or {}

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

    assert "`theme.colors`" in skill
    assert "config/skills/analytics-report.yaml" in skill
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
    text = _read(".claude/skills/collection-ideate/references/collection-lifecycle.md")

    assert "01-master/           # マスター音声・動画（*.mp3, *.mp4）" in text
    assert "02-Individual-music/ # 個別音声ファイル（*.mp3）" in text
    assert "WAV は中間成果物" in text


def test_collection_localization_docs_use_root_localizations_contract() -> None:
    for path in (
        ".claude/skills/video-upload/SKILL.md",
        ".claude/skills/channel-new/SKILL.md",
        ".claude/skills/channel-new/references/config-generation-rules.md",
    ):
        text = _read(path)
        assert "localization.supported_languages" not in text
        assert "config/localizations.json" in text

    rules = _read(".claude/skills/channel-new/references/config-generation-rules.md")
    required_sections = rules.split("以下は **すべて `config/channel/*.json` に含める**:", 1)[1].split(
        "## ルート設定ファイル",
        1,
    )[0]
    assert "`localizations`" not in required_sections
    assert "`config/localizations.json`" in rules


def test_setup_client_secrets_step_uses_download_and_automatic_move() -> None:
    setup = _read(".claude/skills/setup/SKILL.md")
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


def test_onboarding_client_secrets_step_uses_download_and_automatic_move() -> None:
    onboarding = _read("ONBOARDING.md")
    oauth_setup = onboarding.split("### 2.3 OAuth セットアップ", 1)[1].split("### 2.4 初期設定後の GCP 課金確認", 1)[0]

    for expected in (
        "Client secrets > Add secret",
        "Download JSON",
        "done",
        "uv run yt-doctor --fix-client-secrets",
        "uv run yt-doctor --json",
        "client_secrets` が `ok`",
    ):
        assert expected in oauth_setup
    assert "client_secrets.template.json" not in oauth_setup
    assert "転記" not in oauth_setup


def test_oauth_module_and_setup_guide_distinguish_automatic_and_manual_routes() -> None:
    oauth_handler = _read("src/youtube_automation/auth/oauth_handler.py")
    module_docstring = oauth_handler.split('"""', 2)[1]
    for expected in ("Download JSON", "yt-doctor --fix-client-secrets"):
        assert expected in module_docstring
    assert "secret を発行して auth/client_secrets.json に配置" not in module_docstring

    setup_guide = _read("auth/SETUP.md")
    route_zero = setup_guide.split("### ルート 0:", 1)[1].split("### ルート A:", 1)[0]
    for expected in ("Download JSON", "done", "yt-doctor --fix-client-secrets", "yt-doctor --json"):
        assert expected in route_zero
    assert "client_secrets.json` 配置は PKCE / GUI 制約で AI 実行不可" not in route_zero

    manual_routes = setup_guide.split("### ルート A:", 1)[1].split('---\n\n## <a id="step-oauth"', 1)[0]
    assert "ルート A / B では `client_secrets.json` の手動配置を現状どおり行う" in manual_routes


def test_channel_new_regeneration_documents_ttp_wf_new_readiness_gate() -> None:
    regeneration_mode = _read(".claude/skills/channel-new/references/regeneration-mode.md")
    rules = _read(".claude/skills/channel-new/references/config-generation-rules.md")

    for text in (regeneration_mode, rules):
        assert "uv run yt-doctor --json" in text
        assert "ttp_wf_new_readiness" in text
        assert "/channel-new benchmark 反映未完了" in text
        assert "data/benchmark_*.json" in text
        assert "docs/benchmarks/*.md" in text
        assert "data/thumbnail_compare/benchmark/" in text
        assert "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default" in text
        assert "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.channel_branding" in text


def test_channel_new_setting_push_mode_contract_is_documented() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    description = _frontmatter(".claude/skills/channel-new/SKILL.md")["description"]

    for trigger in (
        "設定反映",
        "チャンネル設定更新",
        "branding push",
        "ローカライゼーション同期",
        "meta.json を YouTube に反映",
    ):
        assert trigger in description

    overview = channel_new.split("## Overview", 1)[1].split("## TTP 原則", 1)[0]
    assert "設定 push モード" in overview
    assert "本モードへ直行し、他モードの Step はスキップする" in overview

    mode = channel_new.split("## 設定 push モード", 1)[1].split("## 障害時ガイダンス", 1)[0]
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
    regeneration_mode = _read(".claude/skills/channel-new/references/regeneration-mode.md")
    step = regeneration_mode.split("### Step R2.1:", 1)[1].split("### Step R2.2:", 1)[0]

    assert "benchmark.channels[0]" + "` が指定" not in step
    assert "承認済み TTP 対象" in step
    assert "全件取得" in step
    assert "1 回のコマンド" in step
    assert '--channel-id "<benchmark.channels[0].id>"' in step
    assert '--channel-id "<benchmark.channels[1].id>"' in step
    assert "先頭 1 件だけで済ませない" in step


def test_channel_new_regeneration_config_templates_include_audio_json() -> None:
    regeneration_mode = _read(".claude/skills/channel-new/references/regeneration-mode.md")
    step = regeneration_mode.split("### Step R2.2:", 1)[1].split("### Step R2.3:", 1)[0]

    assert "責務別 5 ファイル" in step
    assert "meta / content / youtube / analytics / audio" in step
    assert "責務別 4 ファイル" not in step


def test_channel_new_regeneration_uses_real_channel_research_output_path() -> None:
    mode = _read(".claude/skills/channel-new/references/regeneration-mode.md")

    assert "docs/channel-research.md" in mode
    assert "docs/channel/channel-research.md" not in mode
    assert "`channel-research.md`" not in mode


def test_config_generation_rules_reference_existing_templates_and_step_ids() -> None:
    rules = _read(".claude/skills/channel-new/references/config-generation-rules.md")

    assert "config-template" + ".json" not in rules
    assert "config-template/" in rules
    assert "config-template/*.json" in rules
    assert "config-template/skills/*.yaml" in rules
    assert "Step R2.3" in rules
    assert "Step " + "2.3" not in rules

    for path in (
        ".claude/skills/channel-new/references/config-template/meta.json",
        ".claude/skills/channel-new/references/config-template/content.json",
        ".claude/skills/channel-new/references/config-template/youtube.json",
        ".claude/skills/channel-new/references/config-template/analytics.json",
        ".claude/skills/channel-new/references/config-template/audio.json",
        ".claude/skills/channel-new/references/config-template/skills/suno.yaml",
        ".claude/skills/channel-new/references/config-template/skills/thumbnail.yaml",
    ):
        assert (ROOT / path).is_file(), f"{path} が存在しない"


def test_channel_new_regeneration_does_not_recopy_youtube_json_after_config_completion() -> None:
    regeneration_mode = _read(".claude/skills/channel-new/references/regeneration-mode.md")

    assert "`config/channel/youtube.json::youtube.{category_id,privacy_status}`" in regeneration_mode

    step_r5 = regeneration_mode.split("## Step R5: 残りファイル生成", 1)[1].split("## Step R6:", 1)[0]
    assert "`config/channel/youtube.json`" not in step_r5


_INSIGHTS_VALIDATOR = ROOT / ".claude/skills/analytics-analyze/references/validate_insights.py"
_INSIGHTS_SCHEMA_PATH = ".claude/skills/analytics-analyze/references/insights-entry.schema.json"


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
    assert properties["source"]["enum"] == ["analysis", "postmortem"]
    assert properties["lever"]["enum"] == ["thumbnail", "title", "topic", "bgm", "metadata", "other"]
    assert properties["status"]["enum"] == ["open", "adopted", "dismissed"]

    analytics_analyze = _read(".claude/skills/analytics-analyze/SKILL.md")
    flop_analysis = _read(".claude/skills/flop-analysis/SKILL.md")
    wf_new = _read(".claude/skills/wf-new/SKILL.md")
    collection_ideate = _read(".claude/skills/collection-ideate/SKILL.md")
    thumbnail = _read(".claude/skills/thumbnail/SKILL.md")

    assert "references/insights-entry.schema.json" in analytics_analyze
    for text in (flop_analysis, wf_new, collection_ideate, thumbnail):
        assert _INSIGHTS_SCHEMA_PATH in text
    for text in (analytics_analyze, flop_analysis, wf_new, collection_ideate, thumbnail):
        assert "data/insights.jsonl" in text

    validator_command = (
        "uv run python3 .claude/skills/analytics-analyze/references/validate_insights.py data/insights.jsonl"
    )
    for text in (analytics_analyze, flop_analysis, wf_new, collection_ideate):
        assert validator_command in text

    # 書き手 2 本: 追記契約（source 値 / append-only / schema 再定義禁止）
    for writer in (analytics_analyze, flop_analysis):
        assert "append-only" in writer
        assert "本文で必須キーや enum を再定義しない" in writer
    assert 'source: "analysis"' in analytics_analyze
    assert '`status: "open"`' in analytics_analyze
    assert "重複追記しない" in analytics_analyze
    assert 'source: "postmortem"' in flop_analysis
    assert "「結論 / 反証 / 学び」の 3 項目がすべて記入済み" in flop_analysis
    assert "`未検証` の仮説だけを根拠にした学びは還元しない" in flop_analysis

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


def test_theme_compare_missing_themes_error_uses_current_config_path(monkeypatch, caplog) -> None:
    from youtube_automation.scripts import theme_compare

    config = SimpleNamespace(content=SimpleNamespace(tags=SimpleNamespace(themes={})))

    caplog.set_level(logging.ERROR, logger="youtube_automation.scripts.theme_compare")
    monkeypatch.setattr(sys, "argv", ["yt-theme-compare"])
    monkeypatch.setattr(theme_compare, "_channel_dir", lambda: ROOT)
    monkeypatch.setattr(theme_compare, "load_config", lambda: config)
    monkeypatch.setattr(theme_compare, "load_latest_daily_snapshot", lambda _path: {"daily": []})
    monkeypatch.setattr(theme_compare, "_load_video_meta", lambda _channel_dir: {"video": {"title": "x"}})
    monkeypatch.setattr(
        theme_compare,
        "build_launch_curve_frame",
        lambda **_kwargs: pd.DataFrame([{"video_id": "video", "days_since_publish": 0}]),
    )

    assert theme_compare.main() == 2
    assert "config/channel/content.json::tags.themes" in caplog.text


def test_automation_schedule_skill_contract() -> None:
    """#1892: /automation-schedule の SKILL.md と references が整合している."""
    skill_path = ".claude/skills/automation-schedule/SKILL.md"
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
        assert (ROOT / ".claude/skills/automation-schedule/references" / ref).exists()

    # Hard Gates は冒頭 60 行以内（skill-authoring-guidelines ルール⑥）
    head = "\n".join(skill.splitlines()[:60])
    assert "## Hard Gates" in head
    assert "allow_external_publish" in head

    # 兄弟スキルとの相互排他（ルール①）
    fm = _frontmatter(skill_path)
    assert "/automation-update" in fm["description"]
    assert "/wf-next" in fm["description"]

    # 設定スキーマの正へのポインタ
    assert "ScheduledAutomation" in skill
    assert "Codex" in skill and "claude-code-cloud" in skill and "claude-cowork-local" in skill
    assert "--confirm-os-fallback" in skill


def test_channel_new_points_scheduled_automation_to_automation_schedule() -> None:
    """#1892: channel-new は scheduled_automation を生成せず /automation-schedule へ誘導する."""
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    assert "`scheduled_automation`" in channel_new
    assert "/automation-schedule" in channel_new
