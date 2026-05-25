"""yt-generate-image の codex provider ガードに関する静的契約テスト。"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GENERATE_IMAGE = _REPO_ROOT / "src" / "youtube_automation" / "scripts" / "generate_image.py"


def _read_generate_image() -> str:
    return _GENERATE_IMAGE.read_text(encoding="utf-8")


def test_generate_image_rejects_codex_before_model_override() -> None:
    """Given yt-generate-image の API 経路
    When provider=codex が config から来る
    Then replace_model 前に明示エラーで codex-image.sh 経路へ誘導する。
    """
    text = _read_generate_image()
    codex_guard = text.find('cfg.provider == "codex"')
    if codex_guard == -1:
        codex_guard = text.find("cfg.provider == 'codex'")
    replace_model_call = text.find("replace_model(cfg, args.model)")

    assert codex_guard != -1, "provider=codex の早期ガードが見つかりません"
    assert replace_model_call != -1, "既存の --model override 経路が見つかりません"
    assert codex_guard < replace_model_call, "codex ガードは replace_model より前に置く必要があります"


def test_generate_image_codex_error_mentions_script_route() -> None:
    """Given provider=codex の誤配線
    When yt-generate-image が拒否する
    Then エラー文に codex-image.sh と yt-generate-image の API 経路差が含まれる。
    """
    text = _read_generate_image()

    assert "codex-image.sh" in text
    assert "yt-generate-image" in text
    assert "sys.exit(1)" in text
