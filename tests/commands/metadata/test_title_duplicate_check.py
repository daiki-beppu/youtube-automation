"""title_duplicate_check の descriptions.json 読み込み契約テスト."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.video_description import write_video_description_pair
from youtube_automation.commands.metadata.title_duplicate_check import read_descriptions_title


def _write_description_pair(collection_dir: Path, title: str) -> None:
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True)
    write_video_description_pair(docs_dir, title=title)


def test_read_descriptions_title_rejects_legacy_markdown(tmp_path: Path) -> None:
    docs_dir = tmp_path / "20-documentation"
    docs_dir.mkdir(parents=True)
    (docs_dir / "descriptions.md").write_text("legacy", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="descriptions.json"):
        read_descriptions_title(tmp_path)


def test_main_rejects_title_over_100_codepoints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Given 100 codepoint を超えるタイトル
    When yt-title-duplicate-check を --title で実行する
    Then --strict なしでも exit 1 で超過を報告する（upload preflight で必ず fail するため前倒し検出）。
    """
    from youtube_automation.commands.metadata.title_duplicate_check import main

    long_title = "Late Night Smooth Jazz | " + "a" * 80
    assert len(long_title) > 100
    rc = main([str(tmp_path), "--title", long_title, "--collections-root", str(tmp_path / "collections")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "YouTube 制限 100 を超過" in captured.out
    assert "title duplicate warning" not in captured.out


def test_main_rejects_long_title_before_duplicate_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Given 100 codepoint 超過かつ既存タイトルと重複するタイトル
    When yt-title-duplicate-check を実行する
    Then duplicate warning より先に長さ超過で fail-loud する。
    """
    from youtube_automation.commands.metadata.title_duplicate_check import main

    long_title = "Late Night Smooth Jazz | " + "a" * 80
    rc = main(["--title", long_title, "--collections-root", str(tmp_path / "collections")])

    captured = capsys.readouterr()
    assert rc == 1
    assert "YouTube 制限 100 を超過" in captured.out
    assert "title duplicate warning" not in captured.out


@pytest.mark.parametrize(("strict_args", "expected_rc"), [([], 0), (["--strict"], 1)])
def test_main_duplicate_warning_respects_strict_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    strict_args: list[str],
    expected_rc: int,
) -> None:
    """REQ-2792-01: duplicate warning の strict/non-strict 終了コードを固定する."""
    from youtube_automation.commands.metadata.title_duplicate_check import main

    title = "Rainy Night Focus Mix"
    existing = tmp_path / "collections" / "live" / "published"
    _write_description_pair(existing, title)

    rc = main(
        [
            "--title",
            title,
            "--collections-root",
            str(tmp_path / "collections"),
            *strict_args,
        ]
    )

    assert rc == expected_rc
    assert "title duplicate warning" in capsys.readouterr().out


def test_main_excludes_the_current_live_collection_from_duplicate_check(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-2792-02: 現在の live collection は自己重複から除外する."""
    from youtube_automation.commands.metadata.title_duplicate_check import main

    current = tmp_path / "collections" / "live" / "current"
    title = "Rainy Night Focus Mix"
    _write_description_pair(current, title)

    rc = main(
        [
            str(current),
            "--collections-root",
            str(tmp_path / "collections"),
            "--strict",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "title duplicate check OK" in captured.out
    assert "title duplicate warning" not in captured.out


def test_main_accepts_title_at_exactly_100_codepoints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Given ちょうど 100 codepoint のタイトル
    When yt-title-duplicate-check を実行する
    Then 長さでは reject されない（live タイトルが無ければ OK 終了）。
    """
    from youtube_automation.commands.metadata.title_duplicate_check import main

    title = "x" * 100
    rc = main([str(tmp_path), "--title", title, "--collections-root", str(tmp_path / "collections")])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK" in captured.out
