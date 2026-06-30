"""画像・動画・音楽生成のコストを統一的に追跡する。

4 カテゴリを別ファイルに記録しつつ、共通スキーマ・共通 API で扱う:

- data/image_costs.json      画像生成（Nano Banana / Imagen 系）
- data/video_costs.json      動画生成（Veo 系）
- data/audio_costs.json      音楽生成（Lyria 系）
- data/analysis_costs.json   分析（Gemini サムネイル分析等）

エントリ共通スキーマ（Issue #132 で `estimated_cost_usd` は新規エントリで
`null` 固定。実コストは GCP Cloud Console > Billing で確認する）:

    {
      "timestamp": "2026-04-22T12:34:56+00:00",
      "category":  "image" | "video" | "audio",
      "model":     "...",
      "quantity":  1,                 # image 枚数 / 動画秒数 / song 数 等
      "unit":      "image" | "second" | "song" | "30sec",
      "estimated_cost_usd": null,
      "metadata":  { 任意の補足情報 }
    }

旧形式のログ（`estimated_cost_usd` が float 数値 / `unit` キー欠落）は読み出し時に
互換吸収するのでそのまま残してよい。
"""

from __future__ import annotations

import contextlib
import errno
import json
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Literal

try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

from youtube_automation.utils.profile import section

Category = Literal["image", "video", "audio", "analysis"]

_LOG_FILENAMES: dict[Category, str] = {
    "image": "image_costs.json",
    "video": "video_costs.json",
    "audio": "audio_costs.json",
    "analysis": "analysis_costs.json",
}

_CATEGORY_LABELS: dict[Category, str] = {
    "image": "画像",
    "video": "動画",
    "audio": "音楽",
    "analysis": "分析",
}

# 旧エントリで `unit` キーが欠落しているときの読み出しフォールバック。
# audio は song/30sec の曖昧性が残るが、旧 lyria-3-pro 系の単価が song だったため
# 旧データのデフォルトは "song" とする（新規書き込みでは使われない）。
_LEGACY_UNIT_BY_CATEGORY: dict[Category, str] = {
    "image": "image",
    "video": "second",
    "audio": "song",
    "analysis": "call",
}

_LOCK_FILE_SUFFIX = ".lock"
_LOCK_REGION_BYTES = 1
_MSVCRT_LOCK_RETRY_DELAY_SECONDS = 0.05
_MSVCRT_LOCK_MAX_ATTEMPTS = 20
_MSVCRT_LOCK_RETRY_ERRNOS = {
    errno.EACCES,
    errno.EAGAIN,
    getattr(errno, "EDEADLK", errno.EACCES),
}
_MSVCRT_LOCK_RETRY_WINERRORS = {
    32,  # ERROR_SHARING_VIOLATION
    33,  # ERROR_LOCK_VIOLATION
}
_IN_PROCESS_LOCK = threading.Lock()


def _channel_dir() -> Path:
    """チャンネルディレクトリを ChannelConfig 経由で解決。"""
    from youtube_automation.utils.config import channel_dir

    return channel_dir()


def _log_path(category: Category) -> Path:
    return _channel_dir() / "data" / _LOG_FILENAMES[category]


def relative_to_channel_dir(path: Path) -> str:
    """チャンネルディレクトリ相対のパス文字列に正規化。範囲外なら絶対パス文字列。"""
    try:
        return str(path.relative_to(_channel_dir()))
    except ValueError:
        return str(path)


@contextlib.contextmanager
def _file_lock(path: Path):
    """生成履歴ファイルの読み書き競合を防ぐ排他ロック。"""
    lock_path = path.with_suffix(path.suffix + _LOCK_FILE_SUFFIX)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_f:
        _prepare_lock_file(lock_f)
        _acquire_lock(lock_f)
        try:
            yield
        finally:
            _release_lock(lock_f)


def _prepare_lock_file(lock_f: BinaryIO) -> None:
    lock_f.seek(0)
    if not lock_f.read(_LOCK_REGION_BYTES):
        lock_f.write(b"\0")
        lock_f.flush()
    lock_f.seek(0)


def _acquire_lock(lock_f: BinaryIO) -> None:
    if _fcntl is not None:
        _fcntl.flock(lock_f.fileno(), _fcntl.LOCK_EX)
        return
    if _msvcrt is not None:
        _acquire_msvcrt_lock(lock_f)
        return
    # Platform file locks are unavailable, but same-process writes still need serialization.
    _IN_PROCESS_LOCK.acquire()


def _acquire_msvcrt_lock(lock_f: BinaryIO) -> None:
    last_error: OSError | None = None
    for attempt in range(_MSVCRT_LOCK_MAX_ATTEMPTS):
        lock_f.seek(0)
        try:
            _msvcrt.locking(lock_f.fileno(), _msvcrt.LK_NBLCK, _LOCK_REGION_BYTES)
            return
        except OSError as e:
            if not _is_msvcrt_lock_contention(e):
                raise
            last_error = e
            if attempt == _MSVCRT_LOCK_MAX_ATTEMPTS - 1:
                break
            time.sleep(_MSVCRT_LOCK_RETRY_DELAY_SECONDS)
    raise TimeoutError(f"msvcrt lock acquisition timed out after {_MSVCRT_LOCK_MAX_ATTEMPTS} attempts") from last_error


def _is_msvcrt_lock_contention(error: OSError) -> bool:
    return error.errno in _MSVCRT_LOCK_RETRY_ERRNOS or getattr(error, "winerror", None) in _MSVCRT_LOCK_RETRY_WINERRORS


def _release_lock(lock_f: BinaryIO) -> None:
    if _fcntl is not None:
        _fcntl.flock(lock_f.fileno(), _fcntl.LOCK_UN)
        return
    if _msvcrt is not None:
        lock_f.seek(0)
        _msvcrt.locking(lock_f.fileno(), _msvcrt.LK_UNLCK, _LOCK_REGION_BYTES)
        return
    _IN_PROCESS_LOCK.release()


def log_generation(
    category: Category,
    model: str,
    quantity: float = 1,
    *,
    unit: str | None = None,
    metadata: dict | None = None,
) -> dict | None:
    """1 件分の生成履歴をカテゴリ別ログに追記する。

    Issue #132 以降は per-call の推定コストを算出しない。`estimated_cost_usd` は
    常に `None` で記録され、実コストは GCP Cloud Console > Billing で確認する。
    `unit` は呼び出し側で必須（未指定 / 空文字で `ValueError`）。書き込み失敗は
    警告のみ（生成処理自体を失敗させない）。戻り値は書き込んだエントリ
    （失敗時 `None`）。
    """
    if not unit:
        raise ValueError(f"unit is required for log_generation (category={category}, model={model})")

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "model": model,
        "quantity": quantity,
        "unit": unit,
        "estimated_cost_usd": None,
        "metadata": dict(metadata or {}),
    }

    try:
        path = _log_path(category)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _file_lock(path):
            with section("cost_tracker.read", category=category):
                entries = _read_entries(path)
            entries.append(entry)
            with section("cost_tracker.write", category=category, count=len(entries)):
                path.write_text(
                    json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
    except Exception as e:
        print(f"  [Warn]   コストログ書き込み失敗 ({category}): {e}")
        return None

    return entry


def _read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []


def _normalize_entry(entry: dict, default_category: Category) -> dict:
    """旧フォーマット（metadata/category/unit なし）を新スキーマに揃える。

    `estimated_cost_usd` は新規書き込みでは常に `None` だが、旧 float 値は
    そのまま保持して読めるようにする。
    """
    if "metadata" in entry and "category" in entry and "unit" in entry:
        return entry
    meta_keys = ("image_size", "aspect_ratio", "reference_count", "output_file", "duration_sec")
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {k: entry[k] for k in meta_keys if k in entry}
    category: Category = entry.get("category", default_category)
    return {
        "timestamp": entry.get("timestamp", ""),
        "category": category,
        "model": entry.get("model", "unknown"),
        "quantity": entry.get("quantity", 1),
        "unit": entry.get("unit") or _LEGACY_UNIT_BY_CATEGORY[category],
        "estimated_cost_usd": entry.get("estimated_cost_usd"),
        "metadata": metadata,
    }


def read_log(category: Category) -> list[dict]:
    """カテゴリ別ログを正規化済みエントリのリストとして返す。"""
    raw = _read_entries(_log_path(category))
    return [_normalize_entry(e, category) for e in raw]


def read_all() -> list[dict]:
    entries: list[dict] = []
    for c in ("image", "video", "audio"):
        entries.extend(read_log(c))  # type: ignore[arg-type]
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def _month_key(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m")
    except ValueError:
        return "unknown"


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


_GCP_BILLING_HINT = "  実コストは GCP Cloud Console > Billing で確認してください。"


def print_last_report(last_entry: dict | None = None) -> None:
    """直近 1 件 + 今月 + 累計を件数ベースで表示する。生成スクリプトの末尾で呼ぶ想定。"""
    entries = read_all()
    if not entries:
        print("\n=== Generation Cost Report ===")
        print("  履歴なし")
        print()
        return

    last = last_entry or entries[-1]
    month = _current_month()
    month_total = 0
    month_by_cat: dict[str, int] = defaultdict(int)
    for e in entries:
        if _month_key(e["timestamp"]) == month:
            month_total += 1
            month_by_cat[e["category"]] += 1
    cat_label = _CATEGORY_LABELS.get(last["category"], last["category"])
    output_file = (last.get("metadata") or {}).get("output_file", "-")

    print()
    print("=== Generation Cost Report ===")
    print(f"  今回:   [{cat_label}] {last['model']} / {last['quantity']}{last['unit']} / file={output_file}")
    cats = ("image", "video", "audio", "analysis")
    month_detail = " / ".join(f"{_CATEGORY_LABELS[c]} {month_by_cat.get(c, 0)} 件" for c in cats)
    print(f"  今月({month}): {month_total} 件")
    print(f"    内訳: {month_detail}")
    print(f"  累計:   {len(entries)} 件")
    print(_GCP_BILLING_HINT)
    print()


def print_summary(category: Category | None = None) -> None:
    """全期間のサマリを件数ベースで表示する。category 指定時はそのカテゴリのみ。"""
    entries = read_log(category) if category else read_all()  # type: ignore[arg-type]
    if not entries:
        scope = _CATEGORY_LABELS.get(category, "全カテゴリ") if category else "全カテゴリ"
        print(f"\n生成履歴がまだありません（{scope}）。")
        return

    by_cat: dict[str, int] = defaultdict(int)
    by_model: dict[str, int] = defaultdict(int)
    by_month: dict[str, int] = defaultdict(int)
    for e in entries:
        by_cat[e["category"]] += 1
        by_model[e["model"]] += 1
        by_month[_month_key(e["timestamp"])] += 1

    print()
    print("=== Generation Cost Summary ===")
    print(f"  総件数:   {len(entries)}")
    print()
    print("  カテゴリ別:")
    for cat in ("image", "video", "audio", "analysis"):
        count = by_cat.get(cat)
        if not count:
            continue
        label = _CATEGORY_LABELS[cat]
        print(f"    {label}: {count} 件")
    print()
    print("  月別:")
    for m in sorted(by_month.keys()):
        print(f"    {m}: {by_month[m]} 件")
    print()
    print("  モデル別:")
    for m in sorted(by_model.keys()):
        print(f"    {m}: {by_model[m]} 件")
    print()
    print(_GCP_BILLING_HINT)
    print("  ログ:")
    for cat in ("image", "video", "audio", "analysis"):
        print(f"    {cat}: {_log_path(cat)}")
    print()
