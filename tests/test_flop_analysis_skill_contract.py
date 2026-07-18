"""`/flop-analysis` の自律検証契約を配布 SKILL.md の公開境界で検証する。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / ".claude" / "skills" / "flop-analysis" / "SKILL.md"
VIDEO_ANALYZE_CONFIG = ROOT / ".claude" / "skills" / "video-analyze" / "config.default.yaml"


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^##\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def _table_rows(section: str, header: tuple[str, ...]) -> list[dict[str, str]]:
    """公開 SKILL.md の Markdown 判定表を、実行時に読む構造のまま検証する。"""
    lines = section.splitlines()
    header_line = "| " + " | ".join(header) + " |"
    try:
        start = lines.index(header_line)
    except ValueError as error:
        raise AssertionError(f"判定表の見出しがありません: {header}") from error
    assert lines[start + 1].startswith("|-")
    rows: list[dict[str, str]] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells, strict=True)))
    return rows


def test_flop_analysis_keeps_identity_symptom_mapping_and_output_contract() -> None:
    """Issue #1972 scope外: 名称、Phase 2〜3、出力先の既存契約を維持する。"""
    text = _skill_text()
    frontmatter = text.split("---\n", 2)[1]
    phase_2 = _section(text, "### Phase 2: 症状の定量化")
    phase_3 = _section(text, "### Phase 3: 仮説マッピング")
    phase_5 = _section(text, "### Phase 5: postmortem.md の生成")

    assert "name: flop-analysis" in frontmatter
    assert (
        'description: "Use when 公開済み動画が伸びなかった原因を video_id、collection、または --since で切り分け、'
        "postmortem.md に出力するとき。「伸びなかった」「flop 分析」で発動。横断戦略は /analytics-analyze、"
        '事前監査は /alignment-check"'
    ) in frontmatter

    for metric in (
        "`cumulative_views` ベンチマーク比",
        "日別 `daily_views` / `daily_impressions` / `ctr`",
        "平均視聴時間（全期間）",
        "CTR（全期間集計）",
        "インプレッション（全期間集計）",
        "サムネ A/B テスト",
    ):
        assert metric in phase_2
    assert "`thresholds.ratio_vs_median`" in phase_2

    for hypothesis in (
        "サムネ訴求弱",
        "中身の弱さ（音源 / 編集 / テーマ）",
        "タイトル / タグ SEO 弱",
        "初動エンゲージメント低",
        "テーマ自体の市場性不足",
    ):
        assert hypothesis in phase_3
    assert "`hypothesis_ratios`" in phase_3
    assert "`thresholds.neutral_band_pct`" in phase_3

    output_path = "collections/live/<collection>/20-documentation/postmortem.md"
    assert output_path in phase_5
    assert "フォールバック用の新規ディレクトリ規約は作らない" in phase_5


def test_flop_analysis_keeps_phase_2_and_phase_3_decision_tables_unchanged() -> None:
    """Issue #1972 scope外: Phase 2〜3 の全行・閾値・対応関係を固定する。"""
    text = _skill_text()
    phase_2 = _section(text, "### Phase 2: 症状の定量化")
    phase_3 = _section(text, "### Phase 3: 仮説マッピング")

    assert _table_rows(phase_2, ("指標", "判定")) == [
        {"指標": "`ratio_vs_median < strong`", "判定": "強い症状（赤）"},
        {
            "指標": "`strong ≦ ratio_vs_median < moderate`",
            "判定": "中程度の症状（黄）",
        },
        {
            "指標": "`moderate ≦ ratio_vs_median < mild`",
            "判定": "軽症（薄黄）",
        },
        {"指標": "`ratio_vs_median ≧ mild`", "判定": "健常（緑）"},
    ]
    assert _table_rows(phase_3, ("主症状", "副症状", "主仮説", "副仮説")) == [
        {
            "主症状": "`ctr_percentage` が自チャンネル `aggregated_ctr_percentage` の `ctr_low` 倍未満",
            "副症状": "`impressions` は過去平均同等以上",
            "主仮説": "サムネ訴求弱",
            "副仮説": "タイトル訴求弱<br>ターゲット層ミスマッチ<br>差別化不足",
        },
        {
            "主症状": "`ctr_percentage` が自チャンネル `aggregated_ctr_percentage` の `ctr_healthy` 倍以上",
            "副症状": "`average_view_duration` が自チャンネル中央値の `avd_low` 倍未満",
            "主仮説": "中身の弱さ（音源 / 編集 / テーマ）",
            "副仮説": "サムネと中身の不一致",
        },
        {
            "主症状": "`impressions` が過去平均の `impressions_low` 倍未満",
            "副症状": "—",
            "主仮説": "タイトル / タグ SEO 弱<br>初動エンゲージメント低",
            "副仮説": "公開時刻ミス<br>再生リスト未登録",
        },
        {
            "主症状": "全指標が中央値前後（±`neutral_band_pct` %）で `ratio_vs_median < mild`",
            "副症状": "—",
            "主仮説": "テーマ自体の市場性不足",
            "副仮説": "競合過密ジャンル",
        },
    ]


def test_flop_analysis_calls_executable_verification_reference() -> None:
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")

    assert ".claude/skills/flop-analysis/references/verification.py" in phase_4
    assert "--operation" in phase_4


def test_flop_analysis_runs_every_primary_verification_without_approval_and_records_results() -> None:
    """Requirement 1: 全主仮説を承認なしで検証し、結果を記録する。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")

    assert "主仮説（全件）" in phase_4
    assert "ユーザーの承認プロンプトを挟まず" in phase_4
    assert "対応する検証手段を自動実行" in phase_4
    assert "postmortem.md の「検証ステップ」欄" in phase_4
    assert "実行結果" in phase_4

    mappings = _table_rows(
        phase_4,
        ("仮説", "read-only 入力", "operation / hypothesis"),
    )
    phase_3 = _section(_skill_text(), "### Phase 3: 仮説マッピング")
    hypothesis_rows = _table_rows(
        phase_3,
        ("主症状", "副症状", "主仮説", "副仮説"),
    )
    phase_3_hypotheses = {
        hypothesis
        for row in hypothesis_rows
        for column in ("主仮説", "副仮説")
        for hypothesis in row[column].split("<br>")
        if hypothesis != "—"
    }
    assert {row["仮説"] for row in mappings} == phase_3_hypotheses

    expected_operations = {
        "サムネ訴求弱": "`thumbnail`",
        "タイトル訴求弱": "`title-alignment`",
        "ターゲット層ミスマッチ": "`hypothesis: target-mismatch`",
        "差別化不足": "`hypothesis: differentiation`",
        "中身の弱さ（音源 / 編集 / テーマ）": "`content-signals`",
        "サムネと中身の不一致": "`hypothesis: thumbnail-content-alignment`",
        "タイトル / タグ SEO 弱": "`hypothesis: seo`",
        "初動エンゲージメント低": "`hypothesis: engagement`",
        "公開時刻ミス": "`hypothesis: publish-time`",
        "再生リスト未登録": "`hypothesis: playlist`",
        "テーマ自体の市場性不足": "`hypothesis: marketability`",
        "競合過密ジャンル": "`hypothesis: competition`",
    }
    assert set(expected_operations) == phase_3_hypotheses
    for mapping in mappings:
        assert all(mapping[column] for column in mapping)
        assert mapping["operation / hypothesis"] == expected_operations[mapping["仮説"]]


def test_flop_analysis_uses_noninteractive_analysis_boundaries() -> None:
    """無承認経路から対話・設定更新・別成果物保存へ進まない。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")
    mappings = _table_rows(
        phase_4,
        ("仮説", "read-only 入力", "operation / hypothesis"),
    )

    assert "**非対話・分析専用境界**" in phase_4
    assert "スキルとして起動しない" in phase_4
    assert "read-only 入力として読む" in phase_4
    assert "config 更新は行わない" in phase_4
    prohibited_routes = (
        "/alignment-check",
        "/viewer-voice",
        "/audience-persona-design",
        "/viewing-scene",
        "/channel-new",
        "/discover-competitors",
    )
    for mapping in mappings:
        assert not any(route in mapping["read-only 入力"] for route in prohibited_routes)

    interactive_skill_paths = (
        ROOT / ".claude/skills/alignment-check/SKILL.md",
        ROOT / ".claude/skills/viewing-scene/SKILL.md",
        ROOT / ".claude/skills/channel-new/SKILL.md",
    )
    for skill_path in interactive_skill_paths:
        assert "AskUserQuestion" in skill_path.read_text(encoding="utf-8")


def test_flop_analysis_fixes_period_baseline_threshold_and_result_fields() -> None:
    """判定に必要な期間・比較元・閾値・成果物フィールドを固定する。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")

    assert "day 0〜6 の 7 日間" in phase_4
    assert "比較可能な他動画が 3 本未満" in phase_4
    for field in (
        "`hypothesis`",
        "`method`",
        "`period`",
        "`target_value`",
        "`baseline_value`",
        "`threshold`",
        "`evidence_path`",
        "`verdict`",
    ):
        assert field in phase_4
    assert "startDate=<published_atのYYYY-MM-DD>" in phase_4
    assert "endDate=<公開初期の最終日>" in phase_4
    assert "ids=channel==<channel_id>" in phase_4


def test_flop_analysis_uses_video_analyze_output_schema_for_content_verdicts() -> None:
    """video-analyze の実出力契約にない信号を Phase 4 判定へ配線しない。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")
    schema = VIDEO_ANALYZE_CONFIG.read_text(encoding="utf-8")
    mappings = _table_rows(
        phase_4,
        ("仮説", "read-only 入力", "operation / hypothesis"),
    )
    content = next(row for row in mappings if row["仮説"] == "中身の弱さ（音源 / 編集 / テーマ）")

    for field in (
        '"intro_sec"',
        '"peak"',
        '"scene_timeline"',
        '"avg_cut_sec"',
    ):
        assert field in schema
        assert field.strip('"') in content["read-only 入力"]
    assert content["operation / hypothesis"] == "`content-signals`"
    assert "competitor_avg_cut_median" in content["read-only 入力"]
    assert "同ジャンル競合3本以上" in content["read-only 入力"]
    assert "M:SS" in phase_4

    assert "入力 JSON のキー・閾値" in phase_4


def test_flop_analysis_delegates_thumbnail_verdict_to_executable_reference() -> None:
    """サムネ verdict を Markdown 内で再実装せず公開 reference へ委譲する。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")
    mappings = _table_rows(
        phase_4,
        ("仮説", "read-only 入力", "operation / hypothesis"),
    )
    thumbnail = next(row for row in mappings if row["仮説"] == "サムネ訴求弱")

    assert thumbnail["operation / hypothesis"] == "`thumbnail`"
    assert "A/B 履歴" in thumbnail["read-only 入力"]
    assert "| A/B 根拠 | 320px 視覚評価 | 判定 |" not in phase_4


def test_flop_analysis_defines_deterministic_term_extraction_and_ctr_lag_gate() -> None:
    """語彙比較と公開直後 CTR の判定が実行者依存にならない。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")

    assert "NFKC" in phase_4
    assert "単一ソース" in phase_4
    assert "genre_vocabulary" in phase_4
    assert "scene_vocabulary" in phase_4
    assert "duration_seconds" in phase_4
    assert "actual_content_type" in phase_4
    assert "対象だけに限定しない" in phase_4
    assert "`主対象` または `primary` と明記" in phase_4
    assert "data/thumbnail_compare/small/" in phase_4
    assert "主観評価は verdict の入力にしない" in phase_4
    assert "公開後 3 日未満" in phase_4
    assert "CTR を使う仮説" in phase_4
    assert "`未検証（理由: Reporting API の D+2 ラグ）`" in phase_4


def test_flop_analysis_template_records_all_eight_fields_for_secondary_states() -> None:
    """実行済み・未実行の副仮説を共通8フィールドで記録する。"""
    text = _skill_text()
    executed = text.split("<実行した副仮説 1>", 1)[1].split("<未実行の副仮説 1>", 1)[0]
    unrun = text.split("<未実行の副仮説 1>", 1)[1].split("## 結論", 1)[0]

    for field in (
        "hypothesis=<仮説>",
        "method=<検証手段>",
        "period=<対象期間>",
        "target_value=<実測>",
        "baseline_value=<比較値>",
        "threshold=<判定閾値>",
        "evidence_path=<成果物パス>",
        "verdict=<支持 / 反証 / 未検証と理由>",
    ):
        assert field in executed
    for field in (
        "hypothesis=<仮説>",
        "method=<検証手段または N/A>",
        "period=<対象期間または N/A>",
        "target_value=<実測または N/A>",
        "baseline_value=<比較値または N/A>",
        "threshold=<判定閾値または N/A>",
        "evidence_path=<成果物パスまたは N/A>",
        "verdict=<未検証と理由>",
    ):
        assert field in unrun


def test_flop_analysis_escalates_to_secondary_only_after_all_primaries_are_refuted() -> None:
    """Requirement 2: 状態遷移は実行可能 reference の出力へ委譲する。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")

    assert "--operation secondary-transition" in phase_4
    assert "`action` と `reason` に従う" in phase_4
    assert "| 全主仮説の判定 | 副仮説の処理 |" not in phase_4


def test_flop_analysis_populates_conclusion_refutation_and_learning_from_results() -> None:
    """Requirement 3: 結論・反証・学びを検証結果から埋める。"""
    text = _skill_text()
    phase_5 = _section(text, "### Phase 5: postmortem.md の生成")

    assert "検証結果を根拠に自動記入" in phase_5
    assert "結論 / 反証 / 学び" in phase_5
    assert "3 項目を空欄にしない" in phase_5
    assert "（検証完了後に運用で記入）" not in phase_5
    assert "空のまま出力" not in phase_5
    for field in (
        "hypothesis=<仮説>",
        "method=<検証手段>",
        "period=<対象期間>",
        "target_value=<実測>",
        "baseline_value=<比較値>",
        "threshold=<判定閾値>",
        "evidence_path=<成果物パス>",
        "verdict=<支持 / 反証 / 未検証>",
    ):
        assert field in text


def test_flop_analysis_records_unverified_reason_and_continues_after_individual_failure() -> None:
    """Requirement 4: 個別検証の失敗を明示し、残りの検証を継続する。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")
    guidance = _section(_skill_text(), "## 障害時ガイダンス")

    for section in (phase_4, guidance):
        assert "未検証（理由: <具体的な理由>）" in section
        assert "残りの検証を続行" in section
    assert "データ不足" in guidance
    assert "子スキル失敗" in guidance
    assert "postmortem.md 保存失敗" in guidance
    assert "完了を報告せずエラーで停止" in guidance


def test_flop_analysis_keeps_engagement_verification_read_only() -> None:
    """無承認の検証から、承認必須のコメント返信を到達不能にする。"""
    phase_4 = _section(_skill_text(), "### Phase 4: 検証の自律実行")
    mappings = _table_rows(
        phase_4,
        ("仮説", "read-only 入力", "operation / hypothesis"),
    )
    engagement = next(row for row in mappings if row["仮説"] == "初動エンゲージメント低")

    assert "`commentThreads.list`" in engagement["read-only 入力"]
    assert "/comments-reply" not in engagement["read-only 入力"]
    assert engagement["operation / hypothesis"] == "`hypothesis: engagement`"


def test_flop_analysis_completion_requires_verification_and_written_conclusion() -> None:
    """Requirement 5: 案内だけでは完了せず、検証と結論記入までを必須にする。"""
    completion = _section(_skill_text(), "## 完了条件")

    assert "検証の実行" in completion
    assert "結論 / 反証 / 学び" in completion
    assert "すべて記入" in completion
    assert "検証ステップ一覧をユーザーに提示した時点で完了" not in completion
    assert "実検証の実行は完了条件に含まない" not in completion

    next_step = _section(_skill_text(), "## Next Step")
    assert "検証の再実行手順ではなく" in next_step
    assert "改善策の実行は本スキルの完了条件に含めない" in next_step

    assert "`/comments-reply` をそのスキル固有の明示承認ゲート付きで実行" in next_step
