"""title_duplicate_check の descriptions.md 読み込み契約テスト."""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.scripts.title_duplicate_check import read_descriptions_title


def _write_descriptions_md(collection_dir: Path, text: str) -> None:
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True)
    (docs_dir / "descriptions.md").write_text(text, encoding="utf-8")


def test_read_descriptions_title_reports_heading_mismatch_diagnostics(tmp_path: Path) -> None:
    _write_descriptions_md(
        tmp_path,
        """## タイトル
```
Continuous Focus Mix
```

## Complete Collection 概要欄
```
A continuous BGM mix without chapter markers.
```
""",
    )

    with pytest.raises(ValueError) as excinfo:
        read_descriptions_title(tmp_path)

    message = str(excinfo.value)
    assert "descriptions.md parse failed" in message
    assert "期待する見出し（完全一致）" in message
    assert "不足/不一致の見出し:\n  - ## タイトル案\n  - ## タグ（YouTube タグ欄）" in message
    assert "検出した ## 見出し" in message
    assert "## タイトル" in message
    assert "修正例" in message
    assert "/video-description を再実行" in message


def test_read_descriptions_title_rejects_level3_heading(tmp_path: Path) -> None:
    _write_descriptions_md(
        tmp_path,
        """### タイトル案
```
Continuous Focus Mix
```

## Complete Collection 概要欄
```
A continuous BGM mix without chapter markers.
```

## タグ（YouTube タグ欄）
```
ambient, focus
```
""",
    )

    with pytest.raises(ValueError) as excinfo:
        read_descriptions_title(tmp_path)

    message = str(excinfo.value)
    assert "不足/不一致の見出し:\n  - ## タイトル案" in message
    assert "検出した ## 見出し:\n  - ## Complete Collection 概要欄\n  - ## タグ（YouTube タグ欄）" in message
