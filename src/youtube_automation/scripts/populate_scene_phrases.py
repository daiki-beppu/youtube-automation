#!/usr/bin/env python3
"""コレクションの workflow-state.json.scene_phrases を多言語翻訳で投入する CLI.

`config/channel/content.json::title.theme_scenes[<theme>].scene` を英語ソースとして
取得し、`config/localizations.json::supported_languages` に列挙された全言語へ
Vertex AI Gemini で翻訳して `collections/<sub>/<collection>/workflow-state.json` の
`scene_phrases` フィールドに書き込む。

`/wf-new` の Phase 2a（コレクション初期化直後）から呼ばれる想定。多言語非対応チャンネル
（`supported_languages` が 1 言語以下）では no-op で正常終了する。

Usage:
    yt-populate-scene-phrases <collection-name>
    yt-populate-scene-phrases <collection-name> --en "Custom English phrase"
    yt-populate-scene-phrases <collection-name> --overwrite
    yt-populate-scene-phrases <collection-name> --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from youtube_automation.utils.config import channel_dir, load_config
from youtube_automation.utils.exceptions import AutomationError, ConfigError, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"
SOURCE_LANG = "en"
_RETRY_MAX = 3
_RETRY_BACKOFF_SEC = (5, 15)


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


def _generate_with_retry(client, *, model: str, contents) -> str:
    """一過性 429/503 に備えた指数バックオフ付き generate_content."""
    last_exc: Exception | None = None
    for attempt in range(_RETRY_MAX):
        try:
            return client.models.generate_content(model=model, contents=contents).text or ""
        except Exception as exc:
            last_exc = exc
            if attempt + 1 >= _RETRY_MAX:
                break
            wait = _RETRY_BACKOFF_SEC[min(attempt, len(_RETRY_BACKOFF_SEC) - 1)]
            logger.warning("Gemini 呼び出し失敗 (%s), %ss 待機して再試行", exc, wait)
            time.sleep(wait)
    raise ValidationError(f"Gemini 呼び出しが {_RETRY_MAX} 回失敗しました: {last_exc}") from last_exc


def translate_phrase(
    en_phrase: str,
    target_langs: list[str],
    *,
    client=None,
    model: str = DEFAULT_GEMINI_MODEL,
) -> dict[str, str]:
    """Vertex AI Gemini で英語フレーズを target_langs に翻訳して dict を返す.

    Args:
        en_phrase: 英語ソースフレーズ
        target_langs: 翻訳先の BCP-47 言語コード（`en` を含めても自動で除外する）
        client: テスト用に DI 可能な google-genai Client。None なら ADC で生成
        model: Gemini モデル名

    Returns:
        {lang: translated_phrase} の辞書（`en` は含まない）

    Raises:
        ValidationError: Gemini レスポンスが JSON dict として解釈できない / 言語欠落
    """
    targets = [lang for lang in target_langs if lang != SOURCE_LANG]
    if not targets:
        return {}

    if client is None:
        from youtube_automation.utils.genai_client import create_genai_client

        client = create_genai_client()

    prompt = _build_prompt(en_phrase, targets)
    logger.info("Gemini 翻訳リクエスト: model=%s, langs=%s", model, targets)
    raw = _generate_with_retry(client, model=model, contents=[prompt])
    try:
        payload = json.loads(_strip_fence(raw))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Gemini レスポンスが JSON としてパースできません: {raw!r}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"Gemini レスポンスが JSON dict ではありません: {payload!r}")

    missing = [lang for lang in targets if not payload.get(lang)]
    if missing:
        raise ValidationError(f"Gemini レスポンスに翻訳欠落: {missing}. payload={payload!r}")
    return {lang: str(payload[lang]) for lang in targets}


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
        "--model",
        default=DEFAULT_GEMINI_MODEL,
        help=f"Gemini モデル名 (デフォルト: {DEFAULT_GEMINI_MODEL})",
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
        if len(supported) <= 1:
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

        translations = translate_phrase(en_phrase, supported, model=args.model)
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
