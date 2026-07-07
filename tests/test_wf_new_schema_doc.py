"""workflow-state schema documentation contract tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_MD = REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "schema.md"


def _schema_text() -> str:
    return SCHEMA_MD.read_text(encoding="utf-8")


def test_assets_table_documents_music_downloaded_field() -> None:
    text = _schema_text()

    assert '"music_downloaded": false' in text
    assert "| `music_downloaded` | boolean | Suno パスで `/suno-helper` の一括 DL 完了を示すフラグ" in text
    assert "`02-Individual-music/` に音源が揃った状態" in text
    assert "`raw_master` 生成前段の DL 完了を独立追跡する" in text


def test_assets_table_documents_downloaded_before_raw_master_state() -> None:
    text = _schema_text()

    assert "`music_downloaded: true` かつ `raw_master: null`" in text
    assert "Suno 楽曲が DL 済みで raw master（クロスフェード結合出力）が未生成の中間状態" in text
