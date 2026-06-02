"""動画生成 / 長時間処理の進捗表示ヘルパー（Issue #641）。

veo_generator / generate_videos.sh の進捗表示で共通利用する純粋関数群。

設計方針:
    - 副作用ゼロの純粋関数だけを export する（ユニットテスト容易性を最優先）。
    - 描画 I/O（print / stdout.write）はここでは行わない — 呼び出し側で
      `is_tty(stream)` を見て `\r` アニメか行ごと出力かを切り替える。
    - Veo は API が真の進捗を返さないため、典型生成時間ベースの**推定値**を出す。
      推定値であることは表示文字列に "≈" を付けて明示する。
"""

from __future__ import annotations

import sys
from typing import IO

# ─── スピナー文字列 ─────────────────────────────────────
# Braille spinner（generate_videos.sh と同一の 10 フレーム）。
SPINNER_FRAMES: tuple[str, ...] = (
    "⠋",
    "⠙",
    "⠹",
    "⠸",
    "⠼",
    "⠴",
    "⠦",
    "⠧",
    "⠇",
    "⠏",
)


def spinner_frame(tick: int) -> str:
    """`tick` 番目のスピナーフレームを返す（負数も剰余で安全に丸める）。

    >>> spinner_frame(0)
    '⠋'
    >>> spinner_frame(10) == spinner_frame(0)
    True
    >>> spinner_frame(-1) == spinner_frame(9)
    True
    """
    return SPINNER_FRAMES[tick % len(SPINNER_FRAMES)]


# ─── 時間フォーマット ───────────────────────────────────


def format_elapsed(seconds: float) -> str:
    """経過時間を `Mm SSs` 形式で返す（1 時間未満は分秒、それ以上は時分秒）。

    >>> format_elapsed(0)
    '0m00s'
    >>> format_elapsed(65)
    '1m05s'
    >>> format_elapsed(3725)
    '1h02m05s'
    >>> format_elapsed(-5)  # 負値は 0 にクランプ
    '0m00s'
    """
    if seconds < 0:
        seconds = 0
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


def format_eta(seconds: float | None) -> str:
    """ETA を `≈Xs` / `≈Mm SSs` で返す（None や非正は `--`）。

    "≈" は推定値であることを明示するための prefix。

    >>> format_eta(None)
    '--'
    >>> format_eta(0)
    '--'
    >>> format_eta(45)
    '≈45s'
    >>> format_eta(125)
    '≈2m05s'
    """
    if seconds is None or seconds <= 0:
        return "--"
    total = int(round(seconds))
    if total < 60:
        return f"≈{total}s"
    m, s = divmod(total, 60)
    return f"≈{m}m{s:02d}s"


# ─── 進捗率推定 ─────────────────────────────────────────


def estimate_progress(elapsed: float, expected_total: float) -> float:
    """経過秒と典型総時間から進捗率（0.0〜0.99）を推定する。

    `expected_total` 到達後は 0.99 で頭打ちにする（API 完了通知を待つ間に
    100% と誤解させないため）。`expected_total <= 0` は 0.0 を返す。

    >>> estimate_progress(0, 60)
    0.0
    >>> estimate_progress(30, 60)
    0.5
    >>> estimate_progress(60, 60)
    0.99
    >>> estimate_progress(120, 60)
    0.99
    >>> estimate_progress(10, 0)
    0.0
    """
    if expected_total <= 0:
        return 0.0
    if elapsed <= 0:
        return 0.0
    ratio = elapsed / expected_total
    return min(ratio, 0.99)


def estimate_eta(elapsed: float, expected_total: float) -> float | None:
    """経過秒と典型総時間から ETA（残り秒）を推定する。

    `expected_total` を超過したら None を返す（"未確定" の意）。

    >>> estimate_eta(0, 60)
    60.0
    >>> estimate_eta(30, 60)
    30.0
    >>> estimate_eta(60, 60)
    >>> estimate_eta(10, 0)
    """
    if expected_total <= 0:
        return None
    remaining = expected_total - max(elapsed, 0.0)
    if remaining <= 0:
        return None
    return remaining


# ─── ステップ表示 ───────────────────────────────────────


def format_step(step_index: int, total_steps: int, label: str) -> str:
    """`[Step 1/3] Generating` のような行を返す。

    >>> format_step(1, 3, "Generating")
    '[Step 1/3] Generating'
    >>> format_step(2, 3, "Saving")
    '[Step 2/3] Saving'
    """
    return f"[Step {step_index}/{total_steps}] {label}"


# ─── TTY 判定 ───────────────────────────────────────────


def is_tty(stream: IO | None = None) -> bool:
    """`stream` (デフォルト `sys.stdout`) が TTY か判定する。

    非 TTY（CI / log redirect / pipe）では `\\r` アニメを抑止し、
    呼び出し側は行ごとの定期出力にフォールバックする。

    `isatty()` を持たない fake stream は False 扱い。
    """
    s = stream if stream is not None else sys.stdout
    isatty = getattr(s, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):
        # 閉じた stream / OSError は非 TTY 扱い
        return False


# ─── 進捗 1 行レンダラー ────────────────────────────────


def render_progress_line(
    *,
    label: str,
    elapsed: float,
    expected_total: float | None = None,
    tick: int = 0,
) -> str:
    """進捗 1 行を組み立てて返す（描画はしない）。

    `expected_total` が指定されていれば「スピナー + ラベル + 経過 + 推定 % + ETA」、
    未指定なら「スピナー + ラベル + 経過」だけを返す。

    >>> render_progress_line(label="Veo 動画生成中", elapsed=30, expected_total=60, tick=0)
    '⠋ Veo 動画生成中... 0m30s (≈50%, ETA ≈30s)'
    >>> render_progress_line(label="Veo 動画生成中", elapsed=30, tick=0)
    '⠋ Veo 動画生成中... 0m30s'
    """
    frame = spinner_frame(tick)
    elapsed_fmt = format_elapsed(elapsed)
    if expected_total and expected_total > 0:
        progress = estimate_progress(elapsed, expected_total)
        eta = estimate_eta(elapsed, expected_total)
        pct = int(round(progress * 100))
        eta_fmt = format_eta(eta)
        return f"{frame} {label}... {elapsed_fmt} (≈{pct}%, ETA {eta_fmt})"
    return f"{frame} {label}... {elapsed_fmt}"


__all__ = [
    "SPINNER_FRAMES",
    "estimate_eta",
    "estimate_progress",
    "format_elapsed",
    "format_eta",
    "format_step",
    "is_tty",
    "render_progress_line",
    "spinner_frame",
]
