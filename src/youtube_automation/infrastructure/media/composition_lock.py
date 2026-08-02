"""composition_lock ヘルパー (#489)

`/collection-ideate` の Phase 4 でサムネ構図が `differentiation_axes`
(location / time_of_day / weather / activity / mood ...) を字義通り受け
入れると TTP 参照画像のスタイルアンカーが効かなくなる問題への対処。

役割:
- `is_composition_locked()`         : skill-config の lock フラグを読む
- `expand_fixed_objects()`           : `objects.fixed` を TTP プロンプト
  定型文に展開する
- `build_self_check_prompt()`       : `objects.fixed` + `no_logo_guard`
  から Gemini Vision 用の YES/NO チェックリストプロンプトを組み立てる
- `axes_in_thumbnail_prompt()`     : 生成したサムネプロンプトに
  `differentiation_axes` のキーが書き出されていないかを軽量に検査する
  (composition_lock=true 時のドリフト警告用)

スキーマ検証は最小限。コール側は `.get()` で広めに受ける想定。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# `objects.fixed` で記号として書かれがちな短いキーを TTP プロンプトの
# 定型節へ展開する辞書。チャンネル側がここに無いキーを書いた場合は
# キー名そのままを passthrough する (空白アンダースコアはスペース化)。
_FIXED_OBJECT_PHRASES: dict[str, str] = {
    "wet_runway": "wet asphalt airport runway with reflective puddles",
    "wet_road": "wet asphalt road with reflective puddles",
    "blue_hour": "blue hour ambient lighting (post-sunset, deep cyan sky)",
    "golden_hour": "golden hour warm low-angle lighting",
    "matte_black_car": "single matte-black car as the foreground subject",
    "aircraft_mid_distance": "aircraft positioned at mid-distance background, not foreground",
    "low_three_quarter_angle": "low three-quarter camera angle",
    "rain_window": "rain-streaked glass window in mid-distance",
    "turntable": "vinyl turntable in foreground left",
    "campfire": "small campfire in mid-foreground",
    "character": "fixed channel character (use existing visual reference)",
}


def is_composition_locked(skill_cfg: Mapping[str, Any] | None) -> bool:
    """`composition_lock` フラグを取り出す (デフォルト True)。

    Args:
        skill_cfg: `load_skill_config("collection-ideate")` の結果 (dict)。
            None を渡したときはデフォルト True を返す。
    """
    if not isinstance(skill_cfg, Mapping):
        return True
    value = skill_cfg.get("composition_lock", True)
    if isinstance(value, bool):
        return value
    # 明示的に bool 以外を書いた場合はデフォルトに倒す (例: "true"/"false" 文字列)。
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "off", "no"}
    return bool(value)


def expand_fixed_objects(fixed: Iterable[Any] | None) -> list[str]:
    """`objects.fixed` のキー list を TTP プロンプト定型節 list に展開する。

    既知キーは辞書から定型文へ展開し、未知キーはキー名のアンダースコアを
    スペースに置換した passthrough を返す。None / 非 iterable / 空 list は
    空 list を返す。

    Args:
        fixed: 例 ["wet_runway", "matte_black_car", "aircraft_mid_distance"]
    """
    if not fixed:
        return []
    if isinstance(fixed, (str, bytes)):
        return []
    phrases: list[str] = []
    for item in fixed:
        if not isinstance(item, str):
            continue
        key = item.strip()
        if not key:
            continue
        phrases.append(_FIXED_OBJECT_PHRASES.get(key, key.replace("_", " ")))
    return phrases


def axes_in_thumbnail_prompt(
    prompt_text: str,
    axes_values: Iterable[Any] | None,
) -> list[str]:
    """サムネプロンプトに `differentiation_axes` の値が書き出されていないか検査する。

    composition_lock=true のとき、サムネ生成プロンプトに axes 値 (location 名 /
    時間帯 / 天候 ...) がそのまま入っていれば TTP 構図逸脱の予兆。caller は
    返り値が非空なら warn / 自動修正 (axes 値を削る) のいずれかを行う。

    比較は大文字小文字を無視した部分一致。値が短すぎる (3 文字未満) ものは
    誤検出が多いため除外する。

    Args:
        prompt_text: 生成済みサムネプロンプト本文。
        axes_values: `differentiation_axes` の各企画候補が割り当てた
            location / time_of_day 等の **具体的な値** (例: "mountain airstrip",
            "urban tunnel exit")。axes キー自体ではない点に注意。

    Returns:
        prompt に入っていた axes 値 list (空ならドリフトなし)。
    """
    if not prompt_text or not axes_values:
        return []
    if isinstance(axes_values, (str, bytes)):
        candidates: list[str] = [axes_values] if isinstance(axes_values, str) else []
    else:
        candidates = []
        for item in axes_values:
            if isinstance(item, str):
                candidates.append(item)
    haystack = prompt_text.lower()
    hits: list[str] = []
    for value in candidates:
        token = value.strip()
        if len(token) < 3:
            continue
        if token.lower() in haystack:
            hits.append(value)
    return hits


def build_self_check_prompt(
    *,
    fixed_objects: Iterable[Any] | None,
    no_logo_guard: Mapping[str, Any] | None,
    extra_checks: Iterable[str] | None = None,
) -> str:
    """Gemini Vision に投げる YES/NO チェックリスト prompt を組み立てる。

    `yt-thumbnail-check` から呼ばれ、画像と一緒に Gemini へ渡す。Gemini
    側は各項目に対して YES/NO + 短い理由を返す前提。Caller は応答を JSON
    パースして合否判定する。

    Args:
        fixed_objects: `objects.fixed` (例: ["wet_runway", "matte_black_car"])。
        no_logo_guard: `self_check.no_logo_guard` (detect_text / detect_logo /
            detect_watermark)。
        extra_checks: チャンネル側で追加したい任意のチェック項目。

    Returns:
        Gemini に渡す自然言語 prompt 1 本。
    """
    checklist: list[str] = []
    for phrase in expand_fixed_objects(fixed_objects):
        checklist.append(f"Does the thumbnail clearly show: {phrase}?")

    guard = no_logo_guard or {}
    if guard.get("detect_text", True):
        checklist.append(
            "Is the image free of typography, captions, or overlaid text "
            "(any letters, numbers, or words burned into the pixels)?"
        )
    if guard.get("detect_logo", True):
        checklist.append(
            "Is the image free of brand logos, manufacturer marks, or "
            "model identifiers (e.g. car badges, aircraft model names)?"
        )
    if guard.get("detect_watermark", True):
        checklist.append("Is the image free of watermarks, stock-photo footers, or AI provider signatures?")

    if extra_checks:
        for item in extra_checks:
            if isinstance(item, str) and item.strip():
                checklist.append(item.strip())

    if not checklist:
        checklist.append(
            "Does the thumbnail meet a generic Flow365 TTP composition? (single subject, clear focal point, no logos)"
        )

    numbered = "\n".join(f"{idx}. {line}" for idx, line in enumerate(checklist, start=1))
    return (
        "You are auditing a YouTube thumbnail for Flow365 TTP composition "
        "compliance. Answer each numbered question with strict YES or NO "
        "followed by a short reason (<= 12 words).\n\n"
        "Respond with valid JSON in this exact shape:\n"
        '{"checks": [{"index": <int>, "question": <str>, "answer": '
        '"YES"|"NO", "reason": <str>}], "pass": <bool>}\n\n'
        "`pass` is true only when every answer is YES.\n\n"
        f"Checklist:\n{numbered}"
    )
