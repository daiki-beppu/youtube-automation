"""Structured document HTML resources."""

from __future__ import annotations

from importlib.resources import files

_FOUNDATION_CSS = "foundation.css"


def load_css(*names: str) -> str:
    """共通デザイン基盤 CSS を先頭に置いて画面固有 CSS と結合する。"""
    return "\n".join(
        files(__name__).joinpath(name).read_text(encoding="utf-8").strip() for name in (_FOUNDATION_CSS, *names)
    )
