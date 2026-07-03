#!/usr/bin/env python3
"""yt-thumbnail-text CLI (#1332)

textless 背景 (main.png/jpg 系) に実フォントファイルでタイトル文字を
決定的に描画し、テキスト付きサムネ候補を出力する。AI 画像生成の
フォント再現バラつきを回避する経路。

Usage:
    yt-thumbnail-text --background <path> --title <line> [--title <line>]
        [--channel-name <name>] --output <path>

設定は skill-config `thumbnail` の
`image_generation.gemini.thumbnail_text.overlay` から読む。

終了コード:
    0 : 合成成功
    1 : 設定エラー (フォント未設定・ファイル不在など。理由と代替手順を表示)
    2 : 入力エラー (背景画像が存在しない、タイトル未指定, etc.)

Design:
- 解釈フェーズ (`main`): argparse → skill-config → OverlaySpec 解決
- 実行フェーズ: `compose_thumbnail_text()` で描画・保存
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.thumbnail_text.config import overlay_spec_from_overlay_config
from youtube_automation.utils.thumbnail_text.renderer import (
    compose_thumbnail_text,
    validate_thumbnail_output_path,
)

SKILL_NAME = "thumbnail"
_OVERLAY_CONFIG_PATH = "image_generation.gemini.thumbnail_text.overlay"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-thumbnail-text",
        description="textless 背景に実フォントでタイトル文字を決定的に合成する (#1332)",
    )
    parser.add_argument(
        "--background",
        required=True,
        type=Path,
        help="textless 背景画像のパス (main.png / main-v1.png など)",
    )
    parser.add_argument(
        "--title",
        action="append",
        required=True,
        metavar="LINE",
        help="タイトル行 (複数指定で複数行。上から順に描画)",
    )
    parser.add_argument(
        "--channel-name",
        default=None,
        help="チャンネル名 (省略時は描画しない)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="出力先パス (thumbnail-v1.jpg など。既存の thumbnail.jpg へ直接上書きしない)",
    )
    return parser


def _is_input_config_error(exc: ConfigError) -> bool:
    message = str(exc)
    return (
        message.startswith("背景画像が見つかりません")
        or message.startswith("背景画像を読み込めません")
        or message.startswith("出力画像を保存できません")
        or message.startswith("最終サムネイル名への直接出力はできません")
        or message.startswith("出力先")
    )


def _mapping_at(parent: Mapping[str, object], name: str, *, key: str) -> Mapping[str, object]:
    if name not in parent:
        return {}
    value = parent[name]
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key} はマッピングで指定してください (config/skills/thumbnail.yaml)")
    return value


def _overlay_config_from_skill_config(skill_config: object) -> Mapping[str, object]:
    if not isinstance(skill_config, Mapping):
        raise ConfigError("thumbnail skill-config はマッピングで指定してください (config/skills/thumbnail.yaml)")
    image_generation = _mapping_at(skill_config, "image_generation", key="image_generation")
    gemini = _mapping_at(image_generation, "gemini", key="image_generation.gemini")
    thumbnail_text = _mapping_at(
        gemini,
        "thumbnail_text",
        key="image_generation.gemini.thumbnail_text",
    )
    return _mapping_at(
        thumbnail_text,
        "overlay",
        key=_OVERLAY_CONFIG_PATH,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.background.is_file():
        print(f"[ERROR] 背景画像が見つかりません: {args.background}", file=sys.stderr)
        return 2
    title_lines = [line for line in (s.strip() for s in args.title) if line]
    if not title_lines:
        print("[ERROR] --title に空でないタイトル行を 1 行以上指定してください", file=sys.stderr)
        return 2
    try:
        channel_root = channel_dir()
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    try:
        validate_thumbnail_output_path(args.output, channel_root=channel_root)
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    try:
        spec = overlay_spec_from_overlay_config(
            _overlay_config_from_skill_config(load_skill_config(SKILL_NAME)),
            channel_root=channel_root,
            with_channel_name=bool(args.channel_name),
            key_prefix=_OVERLAY_CONFIG_PATH,
        )
        output = compose_thumbnail_text(
            background=args.background,
            output=args.output,
            channel_root=channel_root,
            spec=spec,
            title_lines=title_lines,
            channel_name=args.channel_name,
        )
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        if _is_input_config_error(exc):
            return 2
        return 1

    print(f"[OK] テキスト付きサムネ候補を出力しました: {output}")
    print(
        "[INFO] 同一の背景・テキスト・設定なら常に同一の出力になります "
        "(フォントは image_generation.gemini.thumbnail_text.overlay.font で固定)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
