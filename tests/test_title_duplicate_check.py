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


def test_main_rejects_title_over_100_codepoints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Given 100 codepoint を超えるタイトル
    When yt-title-duplicate-check を --title で実行する
    Then --strict なしでも exit 1 で超過を報告する（upload preflight で必ず fail するため前倒し検出）。
    """
    from youtube_automation.scripts.title_duplicate_check import main

    long_title = "Late Night Smooth Jazz | " + "a" * 80
    assert len(long_title) > 100
    rc = main([str(tmp_path), "--title", long_title, "--collections-root", str(tmp_path / "collections")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "YouTube 制限 100 を超過" in captured.out


def test_main_accepts_title_at_exactly_100_codepoints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Given ちょうど 100 codepoint のタイトル
    When yt-title-duplicate-check を実行する
    Then 長さでは reject されない（live タイトルが無ければ OK 終了）。
    """
    from youtube_automation.scripts.title_duplicate_check import main

    title = "x" * 100
    rc = main([str(tmp_path), "--title", title, "--collections-root", str(tmp_path / "collections")])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK" in captured.out
