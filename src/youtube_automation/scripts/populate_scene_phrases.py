#!/usr/bin/env python3
"""コレクションの workflow-state.json.scene_phrases を投入する CLI.

`config/channel/content.json::title.theme_scenes[<theme>].scene` を英語ソースとして
取得し、`config/localizations.json::supported_languages` に列挙された全言語向けに
呼び出し側エージェントが生成した翻訳 JSON と合わせて
`collections/<sub>/<collection>/workflow-state.json` の `scene_phrases` フィールドに
書き込む。

`/wf-new` の Phase 2a（コレクション初期化直後）から呼ばれる想定。多言語非対応チャンネル
（`supported_languages` が 1 言語以下）では no-op で正常終了する。

Usage:
    yt-populate-scene-phrases <collection-name>
    yt-populate-scene-phrases <collection-name> --translations-json '{"ja":"..."}'
    yt-populate-scene-phrases <collection-name> --translations-file /tmp/phrases.json
    yt-populate-scene-phrases <collection-name> --en "Custom English phrase" --translations-json '{"ja":"..."}'
    yt-populate-scene-phrases <collection-name> --overwrite
    yt-populate-scene-phrases <collection-name> --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from youtube_automation.utils.config import channel_dir, load_config
from youtube_automation.utils.exceptions import AutomationError, ConfigError, ValidationError
from youtube_automation.utils.preflight_checks import requires_scene_phrases

logger = logging.getLogger(__name__)

SOURCE_LANG = "en"


def _resolve_collection_path(name: str) -> Path:
    root = channel_dir() / "collections"
    for sub in ("planning", "live"):
        candidate = root / sub / name
        if candidate.is_dir():
            return candidate
    raise ConfigError(
        f"コレクション '{name}' が collections/planning/ にも collections/live/ にも見つかりません. "
        "ディレクトリ名を確認してください"
    )


def _build_prompt(en_phrase: str, target_langs: list[str]) -> str:
    return (
        "You are a music YouTube channel localizer. Translate the following English "
        "scene phrase into each target language for use in video titles. Keep each "
        "translation evocative and concise (target 30-50 codepoints, max 80).\n\n"
        f"English source: {en_phrase}\n\n"
        f"Target languages (BCP-47 codes): {', '.join(target_langs)}\n\n"
        "Output a single JSON object mapping language code to translation. "
        'Example: {"ja": "...", "ko": "..."}\n'
        "No code fences, no explanation, JSON only."
    )


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline != -1 else text[3:]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


def translate_phrase(
    en_phrase: str,
    target_langs: list[str],
    *,
    translations_json: str,
) -> dict[str, str]:
    """エージェント生成済み JSON を target_langs 用の翻訳 dict として検証する.

    Args:
        en_phrase: 英語ソースフレーズ
        target_langs: 翻訳先の BCP-47 言語コード（`en` を含めても自動で除外する）
        translations_json: 呼び出し側エージェントが作成した JSON object

    Returns:
        {lang: translated_phrase} の辞書（`en` は含まない）

    Raises:
        ValidationError: JSON dict として解釈できない / 言語欠落
    """
    targets = [lang for lang in target_langs if lang != SOURCE_LANG]
    if not targets:
        return {}

    try:
        payload = json.loads(_strip_fence(translations_json))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"scene_phrases 翻訳 JSON をパースできません: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("scene_phrases 翻訳 JSON は object でなければなりません")

    missing = [lang for lang in targets if lang not in payload]
    if missing:
        prompt = _build_prompt(en_phrase, targets)
        raise ValidationError(
            f"scene_phrases 翻訳 JSON に翻訳欠落: {missing}. keys={sorted(str(key) for key in payload)}\n"
            f"Claude Agent には次のプロンプトで再生成させてください:\n{prompt}"
        )
    translations: dict[str, str] = {}
    invalid = [lang for lang in targets if not isinstance(payload[lang], str) or not payload[lang].strip()]
    if invalid:
        raise ValidationError(
            f"scene_phrases 翻訳 JSON の各言語値は非空文字列でなければなりません: invalid_languages={invalid}"
        )
    for lang in targets:
        translations[lang] = payload[lang].strip()
    return translations


def _load_translations_json(args: argparse.Namespace) -> str | None:
    if args.translations_json and args.translations_file:
        raise ConfigError("--translations-json と --translations-file は同時指定できません")
    if args.translations_json:
        return args.translations_json
    if args.translations_file:
        path = Path(args.translations_file)
        if not path.is_file():
            raise ConfigError(f"--translations-file は通常ファイルを指定してください: {path}")
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"--translations-file を読めません: {path}: {exc}") from exc
    return None


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="コレクションの workflow-state.json.scene_phrases を多言語翻訳で投入する"
    )
    parser.add_argument(
        "collection",
        help="コレクションディレクトリ名 (collections/planning/ または live/ 配下)",
    )
    parser.add_argument(
        "--en",
        help="英語フレーズの明示指定。省略時は content.json の title.theme_scenes[theme].scene を使用",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既に scene_phrases が存在する場合も上書きする",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="翻訳結果を表示するだけで workflow-state.json を更新しない",
    )
    parser.add_argument(
        "--translations-json",
        help='Claude Agent が生成した翻訳 JSON object（例: \'{"ja":"...","ko":"..."}\'）',
    )
    parser.add_argument(
        "--translations-file",
        help="Claude Agent が生成した翻訳 JSON object を保存したファイルパス",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)

    try:
        config = load_config()
        col_path = _resolve_collection_path(args.collection)
        ws_path = col_path / "workflow-state.json"
        if not ws_path.exists():
            raise ConfigError(f"{ws_path} が存在しません")
        state = json.loads(ws_path.read_text(encoding="utf-8"))

        supported = list(config.localizations.supported_languages)
        if not requires_scene_phrases(supported):
            print(
                f"⏭️  {args.collection}: localizations.supported_languages が 1 言語以下 → "
                "scene_phrases は不要、スキップ"
            )
            return 0

        if state.get("scene_phrases") and not args.overwrite:
            print(f"⏭️  {args.collection}: scene_phrases は既に存在します （--overwrite で上書き可能）")
            return 0

        theme = state.get("theme", "")
        en_phrase = args.en or config.content.title.scene_for_theme(theme)
        if not en_phrase:
            raise ConfigError(
                f"英語フレーズを解決できません: theme={theme!r}. "
                "--en で明示指定するか、config/channel/content.json の "
                f"title.theme_scenes[{theme!r}].scene を設定してください"
            )

        translations_json = _load_translations_json(args)
        if translations_json is None:
            target_langs = [lang for lang in supported if lang != SOURCE_LANG]
            prompt = _build_prompt(en_phrase, target_langs)
            raise ConfigError(
                "多言語 scene_phrases には Claude Agent が生成した翻訳 JSON が必要です。"
                "--translations-json または --translations-file を指定してください。\n"
                f"Claude Agent へのプロンプト:\n{prompt}"
            )

        translations = translate_phrase(en_phrase, supported, translations_json=translations_json)
        scene_phrases: dict[str, str] = {SOURCE_LANG: en_phrase, **translations}

        if args.dry_run:
            print(json.dumps(scene_phrases, ensure_ascii=False, indent=2))
            print(f"\n--dry-run: {ws_path} には書き込みません")
            return 0

        state["scene_phrases"] = scene_phrases
        ws_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"✅ {args.collection}: scene_phrases に {len(scene_phrases)} 言語を書き込みました")
        return 0
    except AutomationError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
