from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"

_WF_NEW_SKILL_MD = _SKILLS_DIR / "wf-new" / "SKILL.md"
_COLLECTION_IDEATE_SKILL_MD = _SKILLS_DIR / "collection-ideate" / "SKILL.md"
_FRESHNESS_RULES_MD = _SKILLS_DIR / "collection-ideate" / "references" / "freshness-rules.md"
_COLLECTION_LIFECYCLE_MD = _SKILLS_DIR / "collection-ideate" / "references" / "collection-lifecycle.md"
_ONBOARD_SKILL_MD = _SKILLS_DIR / "onboard" / "SKILL.md"
_WORKFLOW_CHEATSHEET_MD = _REPO_ROOT / "docs" / "workflow-cheatsheet.md"

_ANALYTICS_REPORT_GLOB = "reports/analysis_*.md"
_BENCHMARK_DATA_GLOB = "data/benchmark_*.json"
_BENCHMARK_DOCS_DIR = "docs/benchmarks/"
_ANALYTICS_MODE = "analytics mode"
_BENCHMARK_FALLBACK_MODE = "benchmark fallback mode"
_MINIMAL_MODE = "minimal mode"
_DIRECT_INPUT_LABEL = "ユーザー直接入力（テーマ / ジャンル / 雰囲気）"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^## |^### |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def test_wf_new_phase_1_declares_analytics_absent_input_modes() -> None:
    text = _read(_WF_NEW_SKILL_MD)
    phase_1 = _section(text, "### Phase 1: 企画（自動実行 + 入力モードに応じた一時停止）")

    for token in (
        _ANALYTICS_REPORT_GLOB,
        _BENCHMARK_DATA_GLOB,
        _ANALYTICS_MODE,
        _BENCHMARK_FALLBACK_MODE,
        _MINIMAL_MODE,
        _DIRECT_INPUT_LABEL,
    ):
        assert token in phase_1, f"wf-new Phase 1 に入力モード契約 `{token}` がありません"

    assert "/collection-ideate" in phase_1
    assert "stale の場合は fallback せず" in phase_1


def test_collection_ideate_preflight_declares_same_input_modes() -> None:
    text = _read(_COLLECTION_IDEATE_SKILL_MD)
    preflight = _section(text, "## 前提スキル状態確認")

    for token in (
        _ANALYTICS_REPORT_GLOB,
        _BENCHMARK_DATA_GLOB,
        _ANALYTICS_MODE,
        _BENCHMARK_FALLBACK_MODE,
        _MINIMAL_MODE,
        _DIRECT_INPUT_LABEL,
    ):
        assert token in preflight, f"collection-ideate 前提チェックに入力モード契約 `{token}` がありません"

    assert "analytics 依存をスキップ" in preflight
    assert "stale → fallback せず中断" in preflight


def test_collection_ideate_no_longer_stops_when_analysis_report_is_absent() -> None:
    text = _read(_COLLECTION_IDEATE_SKILL_MD)
    phase_1_2 = _section(text, "#### Phase 1-2: 自チャンネル Analytics 分析")

    assert f"`{_ANALYTICS_REPORT_GLOB}` が存在しない → 中断せず" in phase_1_2
    assert _BENCHMARK_FALLBACK_MODE in phase_1_2
    assert _MINIMAL_MODE in phase_1_2


def test_collection_ideate_benchmark_fallback_uses_only_benchmark_data_and_config() -> None:
    text = _read(_COLLECTION_IDEATE_SKILL_MD)
    phase_1_3 = _section(text, "#### Phase 1-3: 競合ベンチマーク分析")

    fallback_paragraph = phase_1_3.split(
        f"{_BENCHMARK_FALLBACK_MODE} では",
        maxsplit=1,
    )[1].split("\n\nminimal mode", maxsplit=1)[0]
    assert f"`{_BENCHMARK_DATA_GLOB}` を Read で読み込み" in fallback_paragraph
    assert "config と合わせて企画入力にする" in fallback_paragraph
    assert f"`{_BENCHMARK_DOCS_DIR}` の読み込みはしない" in fallback_paragraph
    assert "存在する場合は `.md` ファイルも補助入力として読み込む" not in fallback_paragraph

    assert "analytics mode の `/benchmark` 更新完了後" in phase_1_3
    assert "benchmark fallback mode の補助入力" not in phase_1_3


def test_collection_ideate_allows_missing_persona_in_fallback_modes() -> None:
    text = _read(_COLLECTION_IDEATE_SKILL_MD)
    persona = _section(text, "## ペルソナベース企画フレームワーク")

    assert "analytics mode で存在しない場合は ideate を進めず" in persona
    assert f"{_BENCHMARK_FALLBACK_MODE} / {_MINIMAL_MODE} では停止せず" in persona
    assert "初回仮説の視聴者像" in persona

    fallback_guidance = persona.split(
        f"{_BENCHMARK_FALLBACK_MODE} / {_MINIMAL_MODE} では停止せず",
        maxsplit=1,
    )[1].split("今回のターゲットペルソナ", maxsplit=1)[0]
    assert "/audience-persona" not in fallback_guidance
    assert "チャンネル立ち上げ直後なら" not in fallback_guidance


def test_collection_ideate_target_persona_rotation_uses_fallback_hypothesis() -> None:
    text = _read(_COLLECTION_IDEATE_SKILL_MD)
    rotation = _section(text, "### ペルソナローテーション")

    assert "`docs/channel/personas/persona-definition.md` が存在する場合" in rotation
    assert "analytics mode で persona 文書が存在しない場合は停止" in rotation
    assert f"{_BENCHMARK_FALLBACK_MODE} / {_MINIMAL_MODE} で persona 文書が存在しない場合" in rotation
    assert "入力モードごとの材料から作る初回仮説の視聴者像" in rotation
    assert f"{_BENCHMARK_FALLBACK_MODE}: ベンチマークデータ + config" in rotation
    assert f"{_MINIMAL_MODE}: {_DIRECT_INPUT_LABEL}+ config" in rotation
    assert "ユーザー直接入力 + config から作る初回仮説の視聴者像" not in rotation
    assert "初回 or 不明 → `docs/channel/personas/persona-definition.md` の先頭ペルソナ" not in rotation


def test_wf_new_overview_declares_minimal_mode_extra_pause() -> None:
    text = _read(_WF_NEW_SKILL_MD)
    overview = _section(text, "## Overview")
    phase_1 = _section(text, "### Phase 1: 企画（自動実行 + 入力モードに応じた一時停止）")

    assert "通常は企画選択 + サムネイル承認の2箇所" in overview
    assert "minimal mode では企画候補生成前にテーマ / ジャンル / 雰囲気の直接入力確認が追加" in overview
    assert "minimal mode: テーマ / ジャンル / 雰囲気をユーザーに確認" in phase_1


def test_wf_new_cross_references_document_fallback_differences() -> None:
    text = _read(_WF_NEW_SKILL_MD)
    cross_references = _section(text, "## Cross References")

    assert _ANALYTICS_MODE in cross_references
    assert _BENCHMARK_FALLBACK_MODE in cross_references
    assert _MINIMAL_MODE in cross_references
    assert _BENCHMARK_DATA_GLOB in cross_references
    assert _DIRECT_INPUT_LABEL in cross_references


def test_workflow_cheatsheet_documents_fallback_and_minimal_pause() -> None:
    text = _read(_WORKFLOW_CHEATSHEET_MD)
    responsibility_table = _section(text, "## 4 つの skill の責務早見表")
    phase_flow = _section(text, "## 制作の 3 フェーズと skill の流れ")
    faq = _section(text, "## よくある質問")

    assert _ANALYTICS_MODE in responsibility_table
    assert _BENCHMARK_FALLBACK_MODE in responsibility_table
    assert _MINIMAL_MODE in responsibility_table
    assert "企画候補生成前にテーマ / ジャンル / 雰囲気の直接入力確認を追加" in responsibility_table
    assert "通常は (1) 企画選択 (2) サムネ承認" in responsibility_table
    assert "2 箇所" not in responsibility_table
    assert _BENCHMARK_FALLBACK_MODE in phase_flow
    assert "analytics やベンチマークが無いと `/collection-ideate` は止まる？" in faq
    assert "minimal mode では企画候補生成前にテーマ / ジャンル / 雰囲気を直接確認" in faq
    assert "`reports/analysis_*.md` が最新 `data/analytics_data_*.json` より古い場合だけ fallback せず" in faq


def test_collection_lifecycle_documents_three_input_modes() -> None:
    text = _read(_COLLECTION_LIFECYCLE_MD)
    planning = _section(text, "### 1. 企画段階（planning/）")

    assert _ANALYTICS_MODE in planning
    assert _BENCHMARK_FALLBACK_MODE in planning
    assert _MINIMAL_MODE in planning
    assert "テーマ / ジャンル / 雰囲気を直接確認" in planning
    assert "fallback せず、`/analytics-analyze` 再実行を案内して停止" in planning
    assert "/analytics-collect` → `/analytics-analyze`" not in planning


def test_onboard_benchmark_data_respects_analytics_mode_priority() -> None:
    text = _read(_ONBOARD_SKILL_MD)
    benchmark_data = _section(text, "### `benchmark_data` — ベンチマークデータ状態")

    assert "fresh `reports/analysis_*.md` がある → benchmark の有無に関係なく analytics mode" in benchmark_data
    assert "`reports/analysis_*.md` が無く、`data/benchmark_*.json` がある → benchmark fallback mode" in benchmark_data
    assert "`reports/analysis_*.md` と `data/benchmark_*.json` がどちらも無い → minimal mode" in benchmark_data
    assert "\n- `data/benchmark_*.json` がある → benchmark fallback mode" not in benchmark_data


def test_collection_ideate_minimal_mode_does_not_require_competitor_reference() -> None:
    text = _read(_COLLECTION_IDEATE_SKILL_MD)
    persona = _section(text, "## ペルソナベース企画フレームワーク")
    color_rules = _section(text, "### カラールール")
    competitor_rules = _section(text, "### 競合パターン分析ルール")
    originality = _section(text, "## オリジナリティ保証ルール")

    assert "analytics / benchmark fallback mode では競合パターン再解釈を含め" in persona
    assert "minimal mode では直接入力と config だけを根拠にする" in persona
    assert "**analytics mode / benchmark fallback mode**: 競合パターン参照" in color_rules
    assert "**minimal mode**: 競合パターン参照は要求しない" in color_rules
    assert "ユーザー直接入力（テーマ / ジャンル / 雰囲気）と config からの根拠" in color_rules
    assert "minimal mode ではこの分析をスキップ" in competitor_rules
    assert "minimal mode では競合パターン参照元を要求せず" in originality


def test_freshness_rules_follow_analytics_absent_fallback_contract() -> None:
    text = _read(_FRESHNESS_RULES_MD)
    triggers = _section(text, "## 再実行トリガー条件まとめ")

    assert f"`{_ANALYTICS_REPORT_GLOB}` が存在せず、`{_BENCHMARK_DATA_GLOB}` が存在する" in triggers
    assert _BENCHMARK_FALLBACK_MODE in triggers
    assert f"`{_ANALYTICS_REPORT_GLOB}` と `{_BENCHMARK_DATA_GLOB}` がどちらも存在しない" in triggers
    assert _MINIMAL_MODE in triggers
    assert "analytics mode で `persona-definition.md` が存在しない" in triggers
    assert f"{_BENCHMARK_FALLBACK_MODE} / {_MINIMAL_MODE} で `persona-definition.md` が存在しない" in triggers
    assert "analytics mode で `viewing-scene-matrix.md` が存在しない" in triggers
    assert f"{_BENCHMARK_FALLBACK_MODE} / {_MINIMAL_MODE} で `viewing-scene-matrix.md` が存在しない" in triggers
    assert f"| `{_ANALYTICS_REPORT_GLOB}` が存在しない | `/collection-ideate` を中断" not in triggers
    assert f"| `{_BENCHMARK_DATA_GLOB}` が `config/skills/benchmark.yaml`" not in triggers

    benchmark_trigger = next(line for line in triggers.splitlines() if "freshness_days" in line)
    assert benchmark_trigger.startswith(f"| {_ANALYTICS_MODE} で `{_BENCHMARK_DATA_GLOB}`")
    assert _BENCHMARK_FALLBACK_MODE not in benchmark_trigger
    assert _MINIMAL_MODE not in benchmark_trigger


def test_freshness_rules_select_latest_by_filename_date_not_mtime() -> None:
    text = _read(_FRESHNESS_RULES_MD)
    pseudo_code = _section(text, "## 判定擬似コード")

    assert "ls -t" not in pseudo_code
    assert "latest_by_filename_date" in pseudo_code
    assert "grep -oE '[0-9]{8}'" in pseudo_code
    assert '[ ! -f "$file" ]' in pseudo_code
    assert 'LATEST_DATA=$(latest_by_filename_date "data/analytics_data_*.json")' in pseudo_code
    assert 'LATEST_REPORT=$(latest_by_filename_date "reports/analysis_*.md")' in pseudo_code
    assert 'LATEST_BENCHMARK=$(latest_by_filename_date "data/benchmark_*.json")' in pseudo_code


def test_freshness_workflow_state_table_is_mode_aware() -> None:
    text = _read(_FRESHNESS_RULES_MD)
    sync = _section(text, "## workflow-state.json との同期")

    assert "| workflow-state.phase | 入力モード | 想定される前提スキル状態 |" in sync
    assert f"| `planning` | {_ANALYTICS_MODE} |" in sync
    assert f"| `planning` | {_BENCHMARK_FALLBACK_MODE} |" in sync
    assert f"| `planning` | {_MINIMAL_MODE} |" in sync
    assert "既存 `data/benchmark_*.json` を読むが `/benchmark` は自動実行しない" in sync
    assert "ユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config から初回仮説" in sync
    assert "benchmark / persona / viewing-scene は `/collection-ideate` セッション内で最新化される" not in sync
