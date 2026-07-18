"""`/market-research` の読み取り専用・任意保存契約を検証する。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "market-research" / "SKILL.md"
REPORT_CONTRACT = SKILL.parent / "references" / "report-contract.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_market_research_hard_gates_are_near_the_top() -> None:
    first_60_lines = "\n".join(_read(SKILL).splitlines()[:60])

    assert "## Hard Gates" in first_60_lines
    assert "## 完了条件" in first_60_lines
    assert "状態を持たない読み取り専用" in first_60_lines
    assert "TTP の自動入替は行わない" in first_60_lines


def test_market_research_reference_exists_and_defines_all_report_sections() -> None:
    skill = _read(SKILL)
    contract = _read(REPORT_CONTRACT)

    assert "references/report-contract.md" in skill
    for heading in (
        "## 調査問い",
        "## 比較対象と評価軸",
        "## 根拠",
        "## TTP 入替候補",
        "## ニッチ仮説",
        "## 不確実性",
        "## 次の検証",
    ):
        assert f"`{heading}`" in contract


def test_dry_run_without_save_request_creates_no_artifact() -> None:
    skill = _read(SKILL)
    contract = _read(REPORT_CONTRACT)

    assert "保存依頼がない場合は「会話内のみ・ファイル未生成」" in skill
    assert "依頼がなければディレクトリもファイルも作らない" in skill
    assert "既定: 会話内だけに返し、ファイルを生成しない" in contract


def test_dry_run_with_save_request_uses_dated_path_only() -> None:
    skill = _read(SKILL)
    contract = _read(REPORT_CONTRACT)
    expected_path = "docs/research/market-<YYYY-MM-DD>.md"

    assert expected_path in skill
    assert expected_path in contract
    assert "明示的に「保存して」と依頼した場合だけ" in skill
    assert "同日ファイルがすでに存在する場合" in skill


def test_dry_run_with_insufficient_evidence_is_fail_closed() -> None:
    skill = _read(SKILL)
    contract = _read(REPORT_CONTRACT)

    assert "根拠不足" in skill
    assert "候補自身を直接観測した根拠が 2 件以上" in contract
    assert "需要を支える根拠が 1 件以上" in contract
    assert "需要根拠とは別の根拠が 1 件以上" in contract
    assert "推奨表現へ格上げしない" in contract


def test_channel_new_and_discovery_keep_distinct_routes() -> None:
    channel_new = _read(ROOT / ".claude" / "skills" / "channel-new" / "SKILL.md")
    discover = _read(ROOT / ".claude" / "skills" / "discover-competitors" / "SKILL.md")

    assert "追加の競合候補を広げたい → `/discover-competitors`" in channel_new
    assert "現行 TTP の入替候補やニッチ仮説" in channel_new
    assert "→ `/market-research`" in channel_new
    assert "横断比較する調査は /market-research を使う" in discover
