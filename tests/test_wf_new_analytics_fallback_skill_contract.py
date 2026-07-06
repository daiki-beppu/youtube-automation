from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"

_WF_NEW_SKILL_MD = _SKILLS_DIR / "wf-new" / "SKILL.md"
_COLLECTION_IDEATE_SKILL_MD = _SKILLS_DIR / "collection-ideate" / "SKILL.md"
_FRESHNESS_RULES_MD = _SKILLS_DIR / "collection-ideate" / "references" / "freshness-rules.md"
_COLLECTION_LIFECYCLE_MD = _SKILLS_DIR / "collection-ideate" / "references" / "collection-lifecycle.md"
_SETUP_SKILL_MD = _SKILLS_DIR / "setup" / "SKILL.md"
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
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^#{{2,4}}\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def _freshness_pseudo_code() -> str:
    pseudo_code = _section(_read(_FRESHNESS_RULES_MD), "## 判定擬似コード")
    match = re.search(r"```bash\n(?P<body>.*?)\n```", pseudo_code, flags=re.DOTALL)
    if not match:
        raise AssertionError("freshness-rules の bash 擬似コードが見つかりません")
    return match.group("body")


def _write_fixture(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_freshness_pseudo_code(
    tmp_path: Path,
    *,
    data_date: str,
    report_date: str,
    today: str,
    freshness_days: int | None,
) -> subprocess.CompletedProcess[str]:
    _write_fixture(tmp_path / f"data/analytics_data_{data_date}.json")
    _write_fixture(tmp_path / f"reports/analysis_{report_date}.md", "# analysis\n")
    _write_fixture(tmp_path / "docs/channel/personas/persona-definition.md", "# persona\n")
    _write_fixture(tmp_path / "docs/plans/viewing-scene-matrix.md", "# scene\n")

    script = tmp_path / "freshness-check.sh"
    script.write_text(_freshness_pseudo_code(), encoding="utf-8")
    script.chmod(0o755)

    env = {
        **os.environ,
        "TODAY": today,
    }
    if freshness_days is not None:
        env["COLLECTION_IDEATE_FRESHNESS_DAYS"] = str(freshness_days)

    return subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


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
    assert "config/skills/collection-ideate.yaml" in phase_1
    assert "deep-merge した解決済み `freshness_days`" in phase_1


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
    assert "/audience-persona-design" not in fallback_guidance
    assert "チャンネル立ち上げ直後なら" not in fallback_guidance


def test_collection_ideate_single_persona_variations_use_fallback_hypothesis() -> None:
    text = _read(_COLLECTION_IDEATE_SKILL_MD)
    variations = _section(text, "### 第一ペルソナの企画バリエーション")

    assert "`docs/channel/personas/persona-definition.md` が存在する場合" in variations
    assert "第一ペルソナ 1 人" in variations
    assert "複数ペルソナをローテーションせず" in variations
    assert "別シーン・別感情・別利用文脈" in variations
    assert "analytics mode で persona 文書が存在しない場合は停止" in variations
    assert f"{_BENCHMARK_FALLBACK_MODE} / {_MINIMAL_MODE} で persona 文書が存在しない場合" in variations
    assert "入力モードごとの材料から作る初回仮説の視聴者像" in variations
    assert f"{_BENCHMARK_FALLBACK_MODE}: ベンチマークデータ + config" in variations
    assert f"{_MINIMAL_MODE}: {_DIRECT_INPUT_LABEL}+ config" in variations
    assert "ユーザー直接入力 + config から作る初回仮説の視聴者像" not in variations
    assert "初回 or 不明 → `docs/channel/personas/persona-definition.md` の先頭ペルソナ" not in variations
    assert "直近の選択ペルソナの次" not in variations


def test_collection_ideate_persona_framework_uses_single_persona_candidate_count() -> None:
    text = _read(_COLLECTION_IDEATE_SKILL_MD)
    framework = _section(text, "## ペルソナベース企画フレームワーク")

    assert "第一ペルソナ 1 人" in framework
    assert "`preview.candidate_count` 個の企画候補を生成" in framework
    assert "別シーン・別感情・別利用文脈" in framework
    assert "ペルソナに対し、各 1 企画" not in framework
    assert "ペルソナ × 差別化軸" not in framework


def test_wf_new_overview_declares_minimal_mode_extra_pause() -> None:
    text = _read(_WF_NEW_SKILL_MD)
    overview = _section(text, "## Overview")
    phase_1 = _section(text, "### Phase 1: 企画（自動実行 + 入力モードに応じた一時停止）")

    assert "子スキルを順番に呼び" in overview
    assert "通常は企画選択 + サムネイル承認の2箇所" in overview
    assert "minimal mode では企画候補生成前にテーマ / ジャンル / 雰囲気の直接入力確認が追加" in overview
    assert "minimal mode: テーマ / ジャンル / 雰囲気をユーザーに確認" in phase_1


def test_wf_new_declares_sequential_child_skill_orchestration() -> None:
    text = _read(_WF_NEW_SKILL_MD)
    rules = _section(text, "### 呼び出しルール")
    sequence = _section(text, "### 実行シーケンス")

    assert "子スキルは必ず上から順に呼ぶ" in rules
    assert "並列 Agent は使わない" in rules
    assert "子スキルの内部手順を `/wf-new` で再実装しない" in rules

    expected_order = (
        "/collection-ideate",
        "bunx tayk init-collection",
        "bunx tayk populate-scene-phrases",
        "/thumbnail",
        "/suno",
        "/lyria",
        "/loop-video",
        "bunx tayk collection-serve",
    )
    cursor = -1
    for token in expected_order:
        index = sequence.find(token, cursor + 1)
        assert index != -1, f"wf-new 実行シーケンスに `{token}` がありません"
        assert index > cursor, f"wf-new 実行シーケンスで `{token}` の順序が崩れています"
        cursor = index


def test_wf_new_starts_suno_helper_server_before_handoff() -> None:
    text = _read(_WF_NEW_SKILL_MD)
    phase_2f = _section(text, "#### 2f. Suno helper server 起動（Suno のみ）")
    phase_2g = _section(text, "#### 2g. 完了ガイダンス")
    overview = _section(text, "## Overview")

    for token in (
        "Suno チャンネルでは",
        "bunx tayk collection-serve",
        "Chrome 拡張でのブラウザ実行だけを user に引き継ぐ",
    ):
        assert token in overview, f"wf-new Overview に Suno server 起動責務 `{token}` がありません"

    for token in (
        '"$CHANNEL_DIR/collections/planning"',
        "PORT=7873",
        "--allow-origin",
        "chrome-extension://<EXTENSION_ID>",
        "--port",
        "/collections",
        "/auth/token",
        '"status": "ready"',
        '"pattern_count"',
    ):
        assert token in phase_2f, f"wf-new Phase 2f に Suno server 契約 `{token}` がありません"

    assert "Suno-helper server" in phase_2g
    assert "collection 単体パスや `suno-prompts.json` 直指定は playlist phase がスキップ" in phase_2f
    assert "`/wf-new` が自動で行うのは Suno 用ローカル server の起動と疎通確認まで" in text


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


def test_collection_lifecycle_documents_three_input_modes() -> None:
    text = _read(_COLLECTION_LIFECYCLE_MD)
    planning = _section(text, "### 1. 企画段階（planning/）")

    assert _ANALYTICS_MODE in planning
    assert _BENCHMARK_FALLBACK_MODE in planning
    assert _MINIMAL_MODE in planning
    assert "テーマ / ジャンル / 雰囲気を直接確認" in planning
    assert "fallback せず、`/analytics-analyze` 再実行を案内して停止" in planning
    assert "最新 `data/analytics_data_*.json` より古い" in planning
    assert "実行日から `freshness_days`" in planning
    assert "/analytics-collect` → `/analytics-analyze`" in planning


def test_setup_benchmark_data_respects_analytics_mode_priority() -> None:
    text = _read(_SETUP_SKILL_MD)
    benchmark_data = _section(text, "#### `benchmark_data` — ベンチマークデータ状態")

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
    assert "`/audience-persona-design` で `/viewing-scene` 実行と最終 `persona-definition.md` 更新" in triggers
    assert "`/viewing-scene` の先行実行を案内" not in triggers
    assert f"{_BENCHMARK_FALLBACK_MODE} / {_MINIMAL_MODE} で `viewing-scene-matrix.md` が存在しない" in triggers
    assert f"| `{_ANALYTICS_REPORT_GLOB}` が存在しない | `/collection-ideate` を中断" not in triggers
    assert f"| `{_BENCHMARK_DATA_GLOB}` が `config/skills/benchmark.yaml`" not in triggers

    benchmark_trigger = next(
        line for line in triggers.splitlines() if "freshness_days" in line and "config/skills/benchmark.yaml" in line
    )
    assert benchmark_trigger.startswith(f"| {_ANALYTICS_MODE} で `{_BENCHMARK_DATA_GLOB}`")
    assert _BENCHMARK_FALLBACK_MODE not in benchmark_trigger
    assert _MINIMAL_MODE not in benchmark_trigger

    # 絶対鮮度チェック (#1427): 収集データ自体が実行日から freshness_days を超えたら stale
    absolute_trigger = next(
        line
        for line in triggers.splitlines()
        if "freshness_days" in line and "config/skills/collection-ideate.yaml" in line
    )
    assert absolute_trigger.startswith("| analytics mode で最新 `data/analytics_data_*.json`")
    assert "実行日 (today)" in absolute_trigger
    assert "`/analytics-collect` → `/analytics-analyze`" in absolute_trigger


def test_freshness_rules_route_viewing_scene_gap_through_persona_design_finalization() -> None:
    text = _read(_FRESHNESS_RULES_MD)
    table = _section(text, "## 鮮度判定表")
    pseudo_code = _section(text, "## 判定擬似コード")

    assert "| 3 | `/audience-persona-design` finalization | `docs/plans/viewing-scene-matrix.md` |" in table
    assert "`/audience-persona-design` で `/viewing-scene` 実行と最終 `persona-definition.md` 更新" in table
    assert "/viewing-scene 実行と最終 persona-definition.md 更新を案内" in pseudo_code
    assert "viewing-scene 未定義 → /collection-ideate 中断、/viewing-scene を案内" not in pseudo_code


def test_freshness_rules_select_latest_by_filename_date_not_mtime() -> None:
    text = _read(_FRESHNESS_RULES_MD)
    pseudo_code = _section(text, "## 判定擬似コード")

    assert "ls -t" not in pseudo_code
    assert "compgen" not in pseudo_code
    assert "latest_by_filename_date" in pseudo_code
    assert "grep -oE '[0-9]{8}'" in pseudo_code
    assert '[ ! -f "$file" ]' in pseudo_code
    assert 'LATEST_DATA=$(latest_by_filename_date "data/analytics_data_*.json")' in pseudo_code
    assert 'LATEST_REPORT=$(latest_by_filename_date "reports/analysis_*.md")' in pseudo_code
    assert 'LATEST_BENCHMARK=$(latest_by_filename_date "data/benchmark_*.json")' in pseudo_code


def test_freshness_rules_absolute_check_uses_resolved_config_value(tmp_path: Path) -> None:
    pseudo_code = _freshness_pseudo_code()

    assert "FRESHNESS_DAYS=7" not in pseudo_code
    assert "COLLECTION_IDEATE_FRESHNESS_DAYS=${COLLECTION_IDEATE_FRESHNESS_DAYS:-7}" not in pseudo_code
    assert "freshness_days が未解決" in pseudo_code
    assert 'FRESHNESS_DAYS="$COLLECTION_IDEATE_FRESHNESS_DAYS"' in pseudo_code
    assert "TODAY=${TODAY:-$(date +%Y%m%d)}" in pseudo_code

    relative_stale = _run_freshness_pseudo_code(
        tmp_path / "relative-stale",
        data_date="20260702",
        report_date="20260622",
        today="20260702",
        freshness_days=7,
    )
    assert relative_stale.returncode == 1
    assert "/analytics-analyze" in relative_stale.stdout

    stale = _run_freshness_pseudo_code(
        tmp_path / "stale",
        data_date="20260622",
        report_date="20260622",
        today="20260702",
        freshness_days=7,
    )
    assert stale.returncode == 1
    assert "/analytics-collect" in stale.stdout
    assert "/analytics-analyze" in stale.stdout

    override_fresh = _run_freshness_pseudo_code(
        tmp_path / "override-fresh",
        data_date="20260622",
        report_date="20260622",
        today="20260702",
        freshness_days=14,
    )
    assert override_fresh.returncode == 0, override_fresh.stderr

    boundary_fresh = _run_freshness_pseudo_code(
        tmp_path / "boundary-fresh",
        data_date="20260625",
        report_date="20260625",
        today="20260702",
        freshness_days=7,
    )
    assert boundary_fresh.returncode == 0, boundary_fresh.stderr

    missing_resolved_config = _run_freshness_pseudo_code(
        tmp_path / "missing-config",
        data_date="20260625",
        report_date="20260625",
        today="20260702",
        freshness_days=None,
    )
    assert missing_resolved_config.returncode == 1
    assert "freshness_days" in missing_resolved_config.stderr


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
