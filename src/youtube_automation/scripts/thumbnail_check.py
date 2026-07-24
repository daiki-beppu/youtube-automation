#!/usr/bin/env python3
"""yt-thumbnail-check CLI (#489)

生成済みサムネ画像を Gemini Vision に投げ、`collection-ideate.yaml` の
`objects.fixed` と `self_check.no_logo_guard` から組み立てた YES/NO
チェックリストに対する合否判定を取得する。

Usage:
    yt-thumbnail-check <image-path> [<image-path> ...]
        [--check 'Does the thumbnail ...?'] [--json] [--quiet]

終了コード:
    0 : 全画像が全項目 YES (合格)
    1 : 1 件以上の画像が不合格、または Gemini 応答が JSON パースできない
    2 : 入力エラー (画像が存在しない、空 list, etc.)

Design:
- 解釈フェーズ (`main`): argparse → skill-config → Gemini Client 解決
- 実行フェーズ (`_check_image` per image): Gemini 呼出 + JSON パース
- 出力フェーズ (`_render_text` / `_render_json`): TTY/--json 出力

skill-config / Gemini Client は **境界で 1 回だけ解決し** ループ内で
再解決しない (phase separation)。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.utils.composition_lock import build_self_check_prompt
from youtube_automation.utils.skill_config import load_skill_config

logger = logging.getLogger(__name__)

SKILL_NAME = "collection-ideate"
_DEFAULT_MODEL = "gemini-2.5-flash"

# benchmark_collector.py:561-563 / video_analyzer と同方式のコードフェンス除去
_CODE_FENCE_HEAD = re.compile(r"^```(?:json)?\s*")
_CODE_FENCE_TAIL = re.compile(r"\s*```$")


@dataclass(frozen=True)
class CheckResult:
    """1 画像分の Gemini 判定結果。"""

    image_path: Path
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    raw_response: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# skill-config からの設定組み立て
# ---------------------------------------------------------------------------


def _resolve_check_config(extra_checks: list[str] | None) -> dict[str, Any]:
    """`collection-ideate.yaml` から self_check / objects.fixed を取り出す。

    Returns dict:
        {
            "prompt": <Gemini に渡す文字列>,
            "model": <モデル名>,
            "fixed_objects": [...],
            "no_logo_guard": {...},
            "self_check_enabled": <bool>,
        }
    """
    cfg = load_skill_config(SKILL_NAME)
    self_check_cfg = cfg.get("self_check", {}) or {}
    if not isinstance(self_check_cfg, dict):
        raise ValidationError("collection-ideate.self_check は mapping である必要があります")

    fixed_objects: list[Any] = []
    if self_check_cfg.get("verify_fixed_objects", True):
        objects_cfg = cfg.get("objects", {}) or {}
        if isinstance(objects_cfg, dict):
            fixed_objects = list(objects_cfg.get("fixed") or [])

    no_logo_guard = self_check_cfg.get("no_logo_guard", {}) or {}
    if not isinstance(no_logo_guard, dict):
        no_logo_guard = {}

    prompt = build_self_check_prompt(
        fixed_objects=fixed_objects,
        no_logo_guard=no_logo_guard,
        extra_checks=extra_checks,
    )

    return {
        "prompt": prompt,
        "model": self_check_cfg.get("model") or _DEFAULT_MODEL,
        "fixed_objects": fixed_objects,
        "no_logo_guard": no_logo_guard,
        "self_check_enabled": bool(self_check_cfg.get("enabled", True)),
    }


# ---------------------------------------------------------------------------
# Gemini 呼出 (mock 可能な単純関数)
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> dict[str, Any]:
    """Gemini 応答からコードフェンスを剥がして JSON へパースする。"""
    if not text:
        raise ValidationError("Gemini 応答が空です")
    body = _CODE_FENCE_HEAD.sub("", text.strip())
    body = _CODE_FENCE_TAIL.sub("", body)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Gemini 応答を JSON にパースできませんでした: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"Gemini 応答の root は object である必要があります: {type(data).__name__}")
    return data


def _check_image(
    *,
    image_path: Path,
    prompt: str,
    client: Any,
    model: str,
) -> CheckResult:
    """1 枚を Gemini に投げて CheckResult を返す。失敗時は error 入りで返す。"""
    if not image_path.exists():
        return CheckResult(
            image_path=image_path,
            passed=False,
            error=f"image not found: {image_path}",
        )

    try:
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        return CheckResult(
            image_path=image_path,
            passed=False,
            error=f"google-genai がインストールされていません: {exc}",
        )

    ref_bytes = image_path.read_bytes()
    mime = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=ref_bytes, mime_type=mime),
                prompt,
            ],
        )
    except Exception as exc:
        return CheckResult(
            image_path=image_path,
            passed=False,
            error=f"Gemini 呼出失敗: {exc}",
        )

    raw_text = getattr(response, "text", None) or ""
    try:
        payload = _parse_json_response(raw_text)
    except ValidationError as exc:
        return CheckResult(
            image_path=image_path,
            passed=False,
            raw_response=raw_text,
            error=str(exc),
        )

    checks = payload.get("checks") or []
    if not isinstance(checks, list):
        checks = []
    passed_raw = payload.get("pass")
    if isinstance(passed_raw, bool):
        passed = passed_raw
    else:
        # `pass` が無い / 型違いの場合は全 YES から導出
        passed = bool(checks) and all(isinstance(c, dict) and str(c.get("answer", "")).upper() == "YES" for c in checks)
    return CheckResult(
        image_path=image_path,
        passed=passed,
        checks=checks,
        raw_response=raw_text,
    )


# ---------------------------------------------------------------------------
# 出力フォーマッタ
# ---------------------------------------------------------------------------


def _render_text(results: list[CheckResult]) -> str:
    lines: list[str] = []
    for result in results:
        verdict = "PASS" if result.passed else "FAIL"
        lines.append(f"[{verdict}] {result.image_path}")
        if result.error:
            lines.append(f"  ERROR: {result.error}")
        for entry in result.checks:
            if not isinstance(entry, dict):
                continue
            ans = entry.get("answer", "?")
            q = entry.get("question", "?")
            reason = entry.get("reason", "")
            lines.append(f"  - [{ans}] {q}")
            if reason:
                lines.append(f"      reason: {reason}")
    return "\n".join(lines)


def _render_json(results: list[CheckResult]) -> str:
    return json.dumps(
        [
            {
                "image_path": str(r.image_path),
                "passed": r.passed,
                "error": r.error,
                "checks": r.checks,
            }
            for r in results
        ],
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-thumbnail-check",
        description=(
            "生成したサムネを Gemini Vision で objects.fixed + no_logo_guard 条件に照らしてセルフチェックする (#489)"
        ),
    )
    parser.add_argument(
        "images",
        nargs="+",
        type=Path,
        help="検査対象の画像パス (1 つ以上)",
    )
    parser.add_argument(
        "--check",
        action="append",
        default=None,
        metavar="QUESTION",
        help="追加チェック項目 (YES/NO 形式の英文)。複数指定可",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果を JSON で標準出力に書き出す",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="標準出力を抑制し、終了コードのみ返す",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="使用する Gemini モデル (省略時は skill-config の self_check.model)",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="組み立てたチェック prompt を表示して終了する (Gemini 呼出なし)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.images:
        print("error: 検査対象の画像を 1 つ以上指定してください", file=sys.stderr)
        return 2

    config = _resolve_check_config(args.check)
    if not config["self_check_enabled"] and not args.print_prompt:
        print(
            "[skip] collection-ideate.self_check.enabled=false のため検査をスキップ",
            file=sys.stderr,
        )
        return 0

    model = args.model or config["model"]
    prompt = config["prompt"]

    if args.print_prompt:
        print(prompt)
        return 0

    # Gemini Client を境界で 1 回だけ解決
    try:
        from youtube_automation.utils.genai_client import create_genai_client

        client = create_genai_client(location="global")
    except Exception as exc:
        print(f"error: Gemini Client 初期化失敗: {exc}", file=sys.stderr)
        return 2

    results: list[CheckResult] = []
    for image in args.images:
        results.append(
            _check_image(
                image_path=image,
                prompt=prompt,
                client=client,
                model=model,
            )
        )

    if args.json:
        if not args.quiet:
            print(_render_json(results))
    else:
        if not args.quiet:
            print(_render_text(results))

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
