"""サムネイルテキストの決定的合成 (#1332)

AI 画像生成 (Gemini / OpenAI / codex) はプロンプトでフォント名を指示しても
書体を厳密に再現できず、同一チャンネルでもサムネの文字フォントが毎回
バラつく。本 package は textless 背景 (main.png/jpg 系) に実フォント
ファイル (.ttf / .otf / .ttc) を Pillow で描画することで、同一設定なら
ピクセル単位で再現される決定的なテキスト合成経路を提供する。
"""

from __future__ import annotations

from youtube_automation.utils.thumbnail_text.config import (
    overlay_spec_from_overlay_config,
    resolve_font_path,
)
from youtube_automation.utils.thumbnail_text.models import OverlaySpec, TextStyle
from youtube_automation.utils.thumbnail_text.renderer import compose_thumbnail_text, load_font

__all__ = [
    "OverlaySpec",
    "TextStyle",
    "compose_thumbnail_text",
    "load_font",
    "overlay_spec_from_overlay_config",
    "resolve_font_path",
]
