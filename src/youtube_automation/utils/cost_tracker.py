"""画像・動画・音楽生成のコストを統一的に追跡する。

3 カテゴリを別ファイルに記録しつつ、共通スキーマ・共通 API で扱う:

- data/image_costs.json   画像生成（Nano Banana / Imagen 系）
- data/video_costs.json   動画生成（Veo 系）
- data/audio_costs.json   音楽生成（Lyria 系）

エントリ共通スキーマ:
    {
      "timestamp": "2026-04-22T12:34:56+00:00",
      "category":  "image" | "video" | "audio",
      "model":     "...",
      "quantity":  1,                 # image 枚数 / 動画秒数 / song 数 等
      "unit":      "image" | "second" | "song" | "30sec",
      "estimated_cost_usd": 0.101,
      "metadata":  { 任意の補足情報 }
    }

既存 data/image_costs.json は metadata が無いフラット形式だが、読み込み側が
互換吸収するので上書き削除せずそのまま追記可能。
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.profile import section

Category = Literal["image", "video", "audio"]

_LOG_FILENAMES: dict[Category, str] = {
    "image": "image_costs.json",
    "video": "video_costs.json",
    "audio": "audio_costs.json",
}

_CATEGORY_LABELS: dict[Category, str] = {
    "image": "画像",
    "video": "動画",
    "audio": "音楽",
}

# USD → JPY 換算。env JPY_PER_USD で固定可能。未設定時は 1 日キャッシュで
# open.er-api.com から取得し、ネットワーク失敗時は JPY_PER_USD_FALLBACK。
JPY_PER_USD_FALLBACK = 160.0
_RATE_API_URL = "https://open.er-api.com/v6/latest/USD"
_RATE_CACHE_FILENAME = ".exchange_rate_cache.json"
_RATE_TTL_SEC = 24 * 60 * 60


@dataclass(frozen=True)
class ModelPricing:
    """モデル 1 件分の価格定義。

    - by_size: 解像度別単価（画像用）。key は "1K" / "2K" / "4K"
    - per_unit: 単一単位の価格（動画秒 / 曲 / 30 秒 等）
    - unit: quantity に対応する単位ラベル
    """

    unit: str
    per_unit: float | None = None
    by_size: dict[str, float] | None = None


# Vertex AI / Gemini API の公称価格（2026-04 時点）
PRICING: dict[str, ModelPricing] = {
    # 画像 — Gemini Image (Nano Banana)
    "gemini-3.1-flash-image-preview": ModelPricing(
        unit="image",
        by_size={"512": 0.045, "1K": 0.067, "2K": 0.101, "4K": 0.15},
    ),
    "gemini-3-pro-image-preview": ModelPricing(
        unit="image",
        by_size={"1K": 0.134, "2K": 0.134, "4K": 0.24},
    ),
    # 画像 — OpenAI gpt-image 系（Issue #67, 2026-04 時点）
    # by_size の key は OpenAI の `quality` 値（low / medium / high）に揃える。
    # gpt-image-2 high は order.md "1024×1024 high 品質で約 $0.21/枚" に基づく。
    # gpt-image-1.5 / gpt-image-1-mini の単価は order.md に明示なし（OpenAI 公開時に要再確認）。
    "gpt-image-2": ModelPricing(
        unit="image",
        by_size={"low": 0.04, "medium": 0.10, "high": 0.21},
    ),
    "gpt-image-1.5": ModelPricing(
        unit="image",
        by_size={"low": 0.02, "medium": 0.05, "high": 0.12},
    ),
    "gpt-image-1-mini": ModelPricing(
        unit="image",
        by_size={"low": 0.01, "medium": 0.02, "high": 0.04},
    ),
    # 動画 — Veo
    # NOTE: GA 版 (`-001`) は preview 相当の単価を暫定で採用。正確な Vertex AI 公称価格が判明し次第更新する。
    "veo-3.1-fast-generate-001": ModelPricing(unit="second", per_unit=0.15),
    "veo-3.1-generate-001": ModelPricing(unit="second", per_unit=0.40),
    "veo-3.1-lite-generate-preview": ModelPricing(unit="second", per_unit=0.15),
    "veo-3.1-generate-preview": ModelPricing(unit="second", per_unit=0.40),
    "veo-3.0-generate-001": ModelPricing(unit="second", per_unit=0.40),
    "veo-2.0-generate-001": ModelPricing(unit="second", per_unit=0.50),
    # 音楽 — Lyria
    "lyria-3-pro-preview": ModelPricing(unit="song", per_unit=0.08),
    "lyria-3-clip-preview": ModelPricing(unit="30sec", per_unit=0.06),
    "lyria-002": ModelPricing(unit="30sec", per_unit=0.06),
}


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
    """fcntl.flock による排他ロック。並列書き込み時の読み書き競合を防ぐ。"""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


def _rate_cache_path() -> Path:
    return _channel_dir() / "data" / _RATE_CACHE_FILENAME


def get_jpy_per_usd() -> float:
    """USD → JPY 換算レート。env 上書き → 日次キャッシュ → API → フォールバックの順。"""
    override = os.environ.get("JPY_PER_USD")
    if override:
        try:
            return float(override)
        except ValueError:
            pass

    try:
        cache_path = _rate_cache_path()
    except Exception:
        return JPY_PER_USD_FALLBACK

    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - float(cache.get("fetched_at", 0)) < _RATE_TTL_SEC:
                return float(cache["rate"])
        except (json.JSONDecodeError, ValueError, KeyError, OSError):
            pass

    try:
        req = urllib.request.Request(_RATE_API_URL, headers={"User-Agent": "youtube-automation"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rate = float(data["rates"]["JPY"])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError, OSError):
        return JPY_PER_USD_FALLBACK

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"rate": rate, "fetched_at": time.time()}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return rate


def estimate_cost(model: str, quantity: float = 1, image_size: str | None = None) -> float | None:
    """PRICING からコストを算出する。モデル未登録・必要キー欠落なら None。"""
    pricing = PRICING.get(model)
    if pricing is None:
        return None
    if pricing.by_size is not None:
        if image_size is None:
            raise ConfigError(f"model={model} は image_size が必須です")
        rate = pricing.by_size.get(image_size)
        if rate is None:
            return None
        return rate * quantity
    if pricing.per_unit is not None:
        return pricing.per_unit * quantity
    return None


def unit_for(model: str) -> str | None:
    pricing = PRICING.get(model)
    return pricing.unit if pricing else None


def log_generation(
    category: Category,
    model: str,
    quantity: float = 1,
    *,
    unit: str | None = None,
    cost_usd: float | None = None,
    metadata: dict | None = None,
) -> dict | None:
    """1 件分の生成履歴をカテゴリ別ログに追記する。

    cost_usd を渡さない場合は PRICING から自動算出する（image_size など必要値は metadata から）。
    書き込み失敗は警告のみ（生成処理自体を失敗させない）。戻り値は書き込んだエントリ（失敗時 None）。
    """
    metadata = dict(metadata or {})

    if cost_usd is None:
        image_size = metadata.get("image_size")
        try:
            cost_usd = estimate_cost(model, quantity=quantity, image_size=image_size)
        except ConfigError as e:
            print(f"  [Warn]   コスト算出失敗: {e}")
            cost_usd = None
    if cost_usd is None:
        print(f"  [Warn]   モデル {model!r} の価格が未登録。cost_usd=0 で記録します。")
        cost_usd = 0.0

    resolved_unit = unit or unit_for(model) or "item"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "model": model,
        "quantity": quantity,
        "unit": resolved_unit,
        "estimated_cost_usd": round(float(cost_usd), 6),
        "metadata": metadata,
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
    """旧フォーマット（metadata/category なし）を新スキーマに揃える。"""
    if "metadata" in entry and "category" in entry:
        return entry
    meta_keys = ("image_size", "aspect_ratio", "reference_count", "output_file", "duration_sec")
    metadata = {k: entry[k] for k in meta_keys if k in entry}
    return {
        "timestamp": entry.get("timestamp", ""),
        "category": entry.get("category", default_category),
        "model": entry.get("model", "unknown"),
        "quantity": entry.get("quantity", 1),
        "unit": entry.get("unit", unit_for(entry.get("model", "")) or "item"),
        "estimated_cost_usd": float(entry.get("estimated_cost_usd", 0)),
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


def _format_usd(v: float, rate: float | None = None) -> str:
    jpy_rate = rate if rate is not None else get_jpy_per_usd()
    jpy = v * jpy_rate
    return f"${v:,.4f} (¥{jpy:,.1f})"


def print_last_report(last_entry: dict | None = None) -> None:
    """直近 1 件 + 今月 + 累計 を表示する。生成スクリプトの末尾で呼ぶ想定。"""
    entries = read_all()
    if not entries:
        print("\n=== Generation Cost Report ===")
        print("  履歴なし")
        print()
        return

    rate = get_jpy_per_usd()
    last = last_entry or entries[-1]
    month = _current_month()
    month_total = 0.0
    month_by_cat: dict[str, float] = defaultdict(float)
    for e in entries:
        if _month_key(e["timestamp"]) == month:
            month_total += e["estimated_cost_usd"]
            month_by_cat[e["category"]] += e["estimated_cost_usd"]
    total = sum(e["estimated_cost_usd"] for e in entries)
    cat_label = _CATEGORY_LABELS.get(last["category"], last["category"])

    print()
    print("=== Generation Cost Report ===")
    print(
        f"  今回:   [{cat_label}] {last['model']} / {last['quantity']}{last['unit']} / "
        f"{_format_usd(last['estimated_cost_usd'], rate)}"
    )
    month_detail = " / ".join(
        f"{_CATEGORY_LABELS[c]} {_format_usd(month_by_cat.get(c, 0.0), rate)}" for c in ("image", "video", "audio")
    )
    print(f"  今月({month}): {_format_usd(month_total, rate)}")
    print(f"    内訳: {month_detail}")
    print(f"  累計:   {_format_usd(total, rate)} ({len(entries)} 件)")
    print(f"  換算レート: 1 USD = ¥{rate:,.2f}")
    print()


def print_summary(category: Category | None = None) -> None:
    """全期間のサマリを表示する。category 指定時はそのカテゴリのみ。"""
    entries = read_log(category) if category else read_all()  # type: ignore[arg-type]
    if not entries:
        scope = _CATEGORY_LABELS.get(category, "全カテゴリ") if category else "全カテゴリ"
        print(f"\n生成履歴がまだありません（{scope}）。")
        return

    total = sum(e["estimated_cost_usd"] for e in entries)
    by_cat: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost": 0.0})
    by_model: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost": 0.0})
    by_month: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost": 0.0})
    for e in entries:
        cat = e["category"]
        model = e["model"]
        month = _month_key(e["timestamp"])
        by_cat[cat]["count"] += 1
        by_cat[cat]["cost"] += e["estimated_cost_usd"]
        by_model[model]["count"] += 1
        by_model[model]["cost"] += e["estimated_cost_usd"]
        by_month[month]["count"] += 1
        by_month[month]["cost"] += e["estimated_cost_usd"]

    rate = get_jpy_per_usd()
    print()
    print("=== Generation Cost Summary ===")
    print(f"  総件数:   {len(entries)}")
    print(f"  累積コスト: {_format_usd(total, rate)}")
    print()
    print("  カテゴリ別:")
    for cat in ("image", "video", "audio"):
        d = by_cat.get(cat)
        if not d:
            continue
        label = _CATEGORY_LABELS[cat]
        print(f"    {label}: {int(d['count'])} 件 / {_format_usd(d['cost'], rate)}")
    print()
    print("  月別:")
    for m in sorted(by_month.keys()):
        d = by_month[m]
        print(f"    {m}: {int(d['count'])} 件 / {_format_usd(d['cost'], rate)}")
    print()
    print("  モデル別:")
    for m in sorted(by_model.keys()):
        d = by_model[m]
        print(f"    {m}: {int(d['count'])} 件 / {_format_usd(d['cost'], rate)}")
    print()
    print(f"  換算レート: 1 USD = ¥{rate:,.2f}")
    print("  ログ:")
    for cat in ("image", "video", "audio"):
        print(f"    {cat}: {_log_path(cat)}")
    print()
