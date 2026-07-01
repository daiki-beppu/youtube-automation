from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "masterup" / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_masterup_documents_suno_helper_zip_take_flow() -> None:
    """#1257: masterup must document the ZIP-expanded take selection gate."""
    text = _read()

    for token in (
        "suno-helper ZIP 展開後の入力契約",
        "01a-<title>.mp3",
        "01b-<title>.mp3",
        "Step 2-3 を完全にスキップ",
        "yt-suno-select-tracks",
        "未実行のまま Step 5 へ進まない",
        "未整理の 2 take 群を直接渡してはならない",
    ):
        assert token in text


def test_masterup_documents_instrumental_clip_policy() -> None:
    """#1257: avoid confusing take selection with instrumental ceil(N/2) flow."""
    text = _read()

    assert "tracks_per_collection=N" in text
    assert "ceil(N/2)" in text
    assert "2 clip は両方採用して N 曲に戻す" in text
