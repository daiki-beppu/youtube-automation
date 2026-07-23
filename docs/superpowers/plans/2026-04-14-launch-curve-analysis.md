# Launch Curve 分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新作動画の投稿後 N 日時点の views/CTR が、過去動画の同日齢ベンチマークと比較して良いか悪いかを即判定する CLI `yt-launch-curve` を実装する。

**Architecture:** 既存の analytics collector 系統に動画 × 日次データ取得メソッドを追加し、pandas ベースの独立モジュール群（data → analyzer → plotter → CLI）を新設する。`utils/analytics_analyzer.py` には触らない。

**Tech Stack:** pandas（DataFrame 構築・ベンチマーク計算）、matplotlib（描画）、YouTube Analytics API (`dimensions='video,day'`)、pytest。

**Spec:** `docs/superpowers/specs/2026-04-14-launch-curve-analysis-design.md`

---

## File Structure

```
src/youtube_automation/utils/
  video_daily_analytics.py       # 新規 Mixin: 動画×日次データ取得
  launch_curve_data.py           # 新規: JSON → pandas DataFrame 構築
  launch_curve_analyzer.py       # 新規: ベンチマーク計算・判定
  launch_curve_plotter.py        # 新規: matplotlib 描画
  analytics_collector.py         # 修正: 新 Mixin を継承に追加
src/youtube_automation/scripts/
  launch_curve.py                # 新規: yt-launch-curve CLI
  analytics_system.py            # 修正: 動画×日次データの永続化フック
tests/
  test_video_daily_analytics.py  # 新規
  test_launch_curve_data.py      # 新規
  test_launch_curve_analyzer.py  # 新規
  test_launch_curve_plotter.py   # 新規（smoke test のみ）
  fixtures/sample_launch_curve/  # 新規: 合成日次データ
pyproject.toml                   # 修正: エントリポイント追加
```

**データファイル（実行時生成）:**
```
{channel_dir}/data/analytics/daily_per_video/{YYYY-MM-DD}_to_{YYYY-MM-DD}.json
{channel_dir}/data/analytics/launch_curves/{YYYY-MM-DD}_{video_id}.png
```

---

## Task 1: 動画×日次データ取得 Mixin

**Files:**
- Create: `src/youtube_automation/utils/video_daily_analytics.py`
- Create: `tests/test_video_daily_analytics.py`

YouTube Analytics API の `dimensions='video,day'` で動画別日次データを取得する Mixin を実装する。impressions 取得成功時とフォールバック分岐は `ctr_analytics.py:_fetch_video_ctr_with_impressions` と同じパターンで書く。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_daily_analytics.py
from unittest.mock import MagicMock

from youtube_automation.domains.analytics.mixins.video_daily_analytics import VideoDailyAnalyticsMixin


class DummyCollector(VideoDailyAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"


def test_get_video_daily_analytics_parses_rows_with_impressions():
    mock_service = MagicMock()
    mock_service.reports().query().execute.return_value = {
        "rows": [
            ["vid_A", "2026-04-01", 100, 5000, 2.0],
            ["vid_A", "2026-04-02", 150, 7000, 2.1],
            ["vid_B", "2026-04-01", 200, 10000, 2.0],
        ],
    }
    collector = DummyCollector(mock_service)
    result = collector.get_video_daily_analytics(
        "2026-04-01", "2026-04-02", video_ids=["vid_A", "vid_B"]
    )
    assert len(result) == 3
    assert result[0] == {
        "video_id": "vid_A",
        "date": "2026-04-01",
        "views": 100,
        "impressions": 5000,
        "impression_ctr": 2.0,
    }
    assert result[2]["video_id"] == "vid_B"


def test_get_video_daily_analytics_fallback_without_impressions():
    from googleapiclient.errors import HttpError

    mock_service = MagicMock()
    # First call raises HttpError, second (fallback) returns rows
    mock_service.reports().query().execute.side_effect = [
        HttpError(MagicMock(status=400), b"impressions unavailable"),
        {"rows": [["vid_A", "2026-04-01", 100]]},
    ]
    collector = DummyCollector(mock_service)
    result = collector.get_video_daily_analytics(
        "2026-04-01", "2026-04-01", video_ids=["vid_A"]
    )
    assert result[0] == {
        "video_id": "vid_A",
        "date": "2026-04-01",
        "views": 100,
        "impressions": 0,
        "impression_ctr": 0.0,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_video_daily_analytics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'youtube_automation.domains.analytics.mixins.video_daily_analytics'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/youtube_automation/utils/video_daily_analytics.py
"""動画 × 日次データ取得 Mixin（launch curve 分析用）"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class VideoDailyAnalyticsMixin:
    """動画 × 日次粒度で views/impressions/CTR を取得する"""

    def get_video_daily_analytics(
        self,
        start_date: str,
        end_date: str,
        video_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        dimensions='video,day' で日次データを取得する。

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            video_ids: 対象動画 ID リスト（None で全動画。API 上限に注意）

        Returns:
            List[Dict]: [{video_id, date, views, impressions, impression_ctr}, ...]
        """
        if not self.analytics_service:
            self.initialize()  # type: ignore[attr-defined]

        query_kwargs = {
            "ids": f"channel=={self.channel_id}",
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": "video,day",
            "sort": "day",
            "maxResults": 10000,
        }
        if video_ids:
            query_kwargs["filters"] = "video==" + ",".join(video_ids)

        try:
            response = self.analytics_service.reports().query(
                metrics="views,impressions,impressionClickThroughRate",
                **query_kwargs,
            ).execute()
            return self._parse_video_daily_rows(response, impressions_available=True)
        except HttpError as e:
            logger.warning(f"impressions 取得不可、フォールバック: {e}")
            response = self.analytics_service.reports().query(
                metrics="views",
                **query_kwargs,
            ).execute()
            return self._parse_video_daily_rows(response, impressions_available=False)

    @staticmethod
    def _parse_video_daily_rows(response: Dict, impressions_available: bool) -> List[Dict]:
        rows = response.get("rows", [])
        result = []
        for row in rows:
            if impressions_available:
                result.append({
                    "video_id": row[0],
                    "date": row[1],
                    "views": row[2],
                    "impressions": row[3],
                    "impression_ctr": row[4],
                })
            else:
                result.append({
                    "video_id": row[0],
                    "date": row[1],
                    "views": row[2],
                    "impressions": 0,
                    "impression_ctr": 0.0,
                })
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_video_daily_analytics.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire Mixin into collector**

Modify `src/youtube_automation/domains/analytics/service.py`:

```python
# Add import
from youtube_automation.domains.analytics.mixins.video_daily_analytics import VideoDailyAnalyticsMixin

# Add to class parents (insert after VideoAnalyticsMixin)
class YouTubeAnalyticsCollector(
    ChannelAnalyticsMixin,
    VideoListingMixin,
    VideoAnalyticsMixin,
    VideoDailyAnalyticsMixin,      # ← new
    StrategicAnalyticsMixin,
    CTRAnalyticsMixin,
    TrafficSourceMixin,
    AudienceAnalyticsMixin,
    RetentionAnalyticsMixin,
):
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/youtube_automation/utils/video_daily_analytics.py \
        src/youtube_automation/domains/analytics/service.py \
        tests/test_video_daily_analytics.py
git commit -m "feat: 動画×日次データ取得 Mixin (VideoDailyAnalyticsMixin) を追加"
```

---

## Task 2: 日次データの永続化

**Files:**
- Modify: `src/youtube_automation/scripts/analytics_system.py`

launch curve 分析は過去データに基づくベンチマーク計算が必要なため、動画 × 日次データを永続化する。既存の `collect_analytics_data()` の後ろにフックを追加して、全動画の日次データを JSON ファイルに保存する。

- [ ] **Step 1: Read current persistence code**

Read `src/youtube_automation/scripts/analytics_system.py` lines 57-97 (既存 `collect_analytics_data` メソッド)。

- [ ] **Step 2: Add daily-per-video persistence**

Modify `src/youtube_automation/scripts/analytics_system.py` — locate `if save_data:` block (around line 83) and add after the existing `json.dump` block:

```python
            # --- 動画×日次データを別ファイルに保存（launch curve 分析用）---
            try:
                video_list = self.collector.get_video_listing()  # 全動画 ID 取得
                video_ids = [v["video_id"] for v in video_list]
                daily_rows = self.collector.get_video_daily_analytics(
                    start_date.strftime('%Y-%m-%d'),
                    end_date.strftime('%Y-%m-%d'),
                    video_ids=video_ids,
                )
                daily_dir = ChannelConfig.channel_dir() / 'data' / 'analytics' / 'daily_per_video'
                daily_dir.mkdir(parents=True, exist_ok=True)
                daily_file = daily_dir / (
                    f"{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.json"
                )
                with open(daily_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        "start_date": start_date.strftime('%Y-%m-%d'),
                        "end_date": end_date.strftime('%Y-%m-%d'),
                        "video_ids": video_ids,
                        "rows": daily_rows,
                    }, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 動画×日次データ保存完了: {daily_file}")
            except Exception as e:
                logger.warning(f"⚠️ 動画×日次データ保存失敗（続行）: {e}")
```

Note: `get_video_listing` が存在するか Task 1 step 6 のテスト実行で検証済み（`VideoListingMixin` が既に継承されている）。メソッド名が違う場合はここで差し替える。

- [ ] **Step 3: Smoke test the script**

Run: `uv run yt-analytics --help`
Expected: コマンドがエラーなく起動し help を表示する。

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_automation/scripts/analytics_system.py
git commit -m "feat: yt-analytics で動画×日次データを永続化"
```

---

## Task 3: Launch Curve DataFrame 構築

**Files:**
- Create: `src/youtube_automation/utils/launch_curve_data.py`
- Create: `tests/fixtures/sample_launch_curve/daily_sample.json`
- Create: `tests/fixtures/sample_launch_curve/video_meta.json`
- Create: `tests/test_launch_curve_data.py`

保存済み JSON を読み込み、動画メタデータ（`published_at`）と結合して `days_since_publish` を計算した pandas DataFrame を構築する。

- [ ] **Step 1: Create test fixtures**

Create `tests/fixtures/sample_launch_curve/daily_sample.json`:

```json
{
  "start_date": "2026-04-01",
  "end_date": "2026-04-05",
  "video_ids": ["vid_A", "vid_B"],
  "rows": [
    {"video_id": "vid_A", "date": "2026-04-01", "views": 100, "impressions": 5000, "impression_ctr": 2.0},
    {"video_id": "vid_A", "date": "2026-04-02", "views": 80,  "impressions": 4000, "impression_ctr": 2.0},
    {"video_id": "vid_A", "date": "2026-04-03", "views": 60,  "impressions": 3000, "impression_ctr": 2.0},
    {"video_id": "vid_B", "date": "2026-04-03", "views": 200, "impressions": 8000, "impression_ctr": 2.5},
    {"video_id": "vid_B", "date": "2026-04-04", "views": 150, "impressions": 6000, "impression_ctr": 2.5},
    {"video_id": "vid_B", "date": "2026-04-05", "views": 100, "impressions": 4000, "impression_ctr": 2.5}
  ]
}
```

Create `tests/fixtures/sample_launch_curve/video_meta.json`:

```json
{
  "vid_A": {"title": "Video A", "published_at": "2026-04-01T00:00:00Z"},
  "vid_B": {"title": "Video B", "published_at": "2026-04-03T00:00:00Z"}
}
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_launch_curve_data.py
import json
from pathlib import Path

import pandas as pd

from youtube_automation.utils.launch_curve_data import build_launch_curve_frame

FIXTURES = Path(__file__).parent / "fixtures" / "sample_launch_curve"


def test_build_launch_curve_frame_computes_days_since_publish():
    with open(FIXTURES / "daily_sample.json") as f:
        daily = json.load(f)
    with open(FIXTURES / "video_meta.json") as f:
        meta = json.load(f)

    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)

    # Both videos should start at day 0 on their publish date
    vid_a_day0 = df[(df["video_id"] == "vid_A") & (df["days_since_publish"] == 0)]
    assert vid_a_day0["daily_views"].iloc[0] == 100

    vid_b_day0 = df[(df["video_id"] == "vid_B") & (df["days_since_publish"] == 0)]
    assert vid_b_day0["daily_views"].iloc[0] == 200


def test_build_launch_curve_frame_computes_cumulative_views():
    with open(FIXTURES / "daily_sample.json") as f:
        daily = json.load(f)
    with open(FIXTURES / "video_meta.json") as f:
        meta = json.load(f)

    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)

    vid_a = df[df["video_id"] == "vid_A"].sort_values("days_since_publish")
    assert list(vid_a["cumulative_views"]) == [100, 180, 240]


def test_build_launch_curve_frame_has_required_columns():
    with open(FIXTURES / "daily_sample.json") as f:
        daily = json.load(f)
    with open(FIXTURES / "video_meta.json") as f:
        meta = json.load(f)

    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)
    required = {
        "video_id", "date", "published_at", "days_since_publish",
        "daily_views", "cumulative_views", "daily_impressions", "ctr",
    }
    assert required.issubset(set(df.columns))
    assert isinstance(df, pd.DataFrame)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_launch_curve_data.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement `launch_curve_data.py`**

```python
# src/youtube_automation/utils/launch_curve_data.py
"""Launch curve 分析用の DataFrame 構築ユーティリティ"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


def build_launch_curve_frame(
    daily_data: Dict,
    video_meta: Dict[str, Dict],
) -> pd.DataFrame:
    """
    永続化 JSON と動画メタから launch curve 用 DataFrame を構築する。

    Args:
        daily_data: {"rows": [{video_id, date, views, impressions, impression_ctr}, ...]}
        video_meta: {video_id: {"title": ..., "published_at": "ISO-8601"}}

    Returns:
        DataFrame with columns:
          video_id, date (datetime), published_at (datetime),
          days_since_publish (int), daily_views, cumulative_views,
          daily_impressions, ctr
    """
    rows = daily_data.get("rows", [])
    if not rows:
        return pd.DataFrame(columns=[
            "video_id", "date", "published_at", "days_since_publish",
            "daily_views", "cumulative_views", "daily_impressions", "ctr",
        ])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # Attach published_at from meta
    meta_df = pd.DataFrame([
        {"video_id": vid, "published_at": pd.to_datetime(m["published_at"]).tz_localize(None)}
        for vid, m in video_meta.items()
    ])
    df = df.merge(meta_df, on="video_id", how="inner")

    df["days_since_publish"] = (df["date"] - df["published_at"]).dt.days
    df = df[df["days_since_publish"] >= 0]

    # Rename to target schema + compute cumulative
    df = df.rename(columns={
        "views": "daily_views",
        "impressions": "daily_impressions",
        "impression_ctr": "ctr",
    })
    df = df.sort_values(["video_id", "days_since_publish"])
    df["cumulative_views"] = df.groupby("video_id")["daily_views"].cumsum()

    return df[[
        "video_id", "date", "published_at", "days_since_publish",
        "daily_views", "cumulative_views", "daily_impressions", "ctr",
    ]].reset_index(drop=True)


def load_latest_daily_snapshot(channel_data_dir: Path) -> Optional[Dict]:
    """data/analytics/daily_per_video/ から最新の JSON を読み込む"""
    daily_dir = channel_data_dir / "analytics" / "daily_per_video"
    if not daily_dir.exists():
        return None
    files = sorted(daily_dir.glob("*.json"))
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_launch_curve_data.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/youtube_automation/utils/launch_curve_data.py \
        tests/test_launch_curve_data.py \
        tests/fixtures/sample_launch_curve/
git commit -m "feat: launch_curve_data で pandas DataFrame 構築を追加"
```

---

## Task 4: ベンチマーク計算・判定ロジック

**Files:**
- Create: `src/youtube_automation/domains/analytics/analysis/launch_curve_analyzer.py`
- Create: `tests/test_launch_curve_analyzer.py`

DataFrame から同日齢ベンチマーク（中央値・IQR）を計算し、対象動画の位置づけを判定する。

- [ ] **Step 1: Write failing tests**

```python
# tests/test_launch_curve_analyzer.py
import pandas as pd
import pytest

from youtube_automation.domains.analytics.analysis.launch_curve_analyzer import (
    compute_benchmark,
    judge_video_vs_benchmark,
)


def _make_frame():
    # 5 videos, each with cumulative views at day 0..6
    # Known distribution: at day 3, cumulative_views = [100, 200, 300, 400, 500]
    # → p25=200, p50=300, p75=400
    records = []
    base_cumvals = [
        [10, 30, 60, 100, 150, 210, 280],
        [20, 60, 120, 200, 300, 420, 560],
        [30, 90, 180, 300, 450, 630, 840],
        [40, 120, 240, 400, 600, 840, 1120],
        [50, 150, 300, 500, 750, 1050, 1400],
    ]
    for i, vals in enumerate(base_cumvals):
        for day, cum in enumerate(vals):
            records.append({
                "video_id": f"vid_{i}",
                "days_since_publish": day,
                "cumulative_views": cum,
                "daily_views": cum - (vals[day - 1] if day > 0 else 0),
                "daily_impressions": 0,
                "ctr": 0.0,
            })
    return pd.DataFrame(records)


def test_compute_benchmark_returns_percentiles_per_day():
    df = _make_frame()
    bench = compute_benchmark(df, metric="cumulative_views")
    row = bench.loc[bench["days_since_publish"] == 3].iloc[0]
    assert row["p50"] == 300
    assert row["p25"] == 200
    assert row["p75"] == 400
    assert row["sample_size"] == 5


def test_compute_benchmark_excludes_target_video():
    df = _make_frame()
    bench = compute_benchmark(df, metric="cumulative_views", exclude_video_id="vid_4")
    row = bench.loc[bench["days_since_publish"] == 3].iloc[0]
    # Without vid_4: [100, 200, 300, 400] → p50=250
    assert row["p50"] == 250
    assert row["sample_size"] == 4


def test_judge_video_vs_benchmark_labels_quartile():
    df = _make_frame()
    bench = compute_benchmark(df, metric="cumulative_views", exclude_video_id="vid_4")
    judgement = judge_video_vs_benchmark(
        df, bench, video_id="vid_4", at_day=3, metric="cumulative_views",
    )
    # vid_4 day 3 cum_views=500, p75 of others=350 → 上位25%
    assert judgement["value"] == 500
    assert judgement["benchmark_median"] == 250
    assert judgement["ratio_vs_median"] == pytest.approx(2.0)
    assert judgement["quartile_label"] == "上位25%"


def test_compute_benchmark_flags_small_sample():
    df = _make_frame().head(2)  # only 2 rows total
    bench = compute_benchmark(df, metric="cumulative_views")
    # sample_size < 3 should be flagged (used by plotter to suppress band)
    assert (bench["sample_size"] < 3).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_launch_curve_analyzer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement analyzer**

```python
# src/youtube_automation/domains/analytics/analysis/launch_curve_analyzer.py
"""Launch curve ベンチマーク計算と判定ロジック"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd


def compute_benchmark(
    df: pd.DataFrame,
    metric: str = "cumulative_views",
    exclude_video_id: Optional[str] = None,
) -> pd.DataFrame:
    """
    各 days_since_publish 値で過去動画の percentile ベンチマークを計算する。

    Returns:
        DataFrame with columns: days_since_publish, p10, p25, p50, p75, p90, sample_size
    """
    source = df if exclude_video_id is None else df[df["video_id"] != exclude_video_id]

    grouped = source.groupby("days_since_publish")[metric]
    result = grouped.agg(
        p10=lambda s: s.quantile(0.10),
        p25=lambda s: s.quantile(0.25),
        p50=lambda s: s.quantile(0.50),
        p75=lambda s: s.quantile(0.75),
        p90=lambda s: s.quantile(0.90),
        sample_size="count",
    ).reset_index()
    return result


def judge_video_vs_benchmark(
    df: pd.DataFrame,
    benchmark: pd.DataFrame,
    video_id: str,
    at_day: int,
    metric: str = "cumulative_views",
) -> Dict:
    """
    対象動画の指定日齢時点の値をベンチマークと比較して判定する。
    """
    target = df[(df["video_id"] == video_id) & (df["days_since_publish"] == at_day)]
    if target.empty:
        return {"error": f"video {video_id} has no data at day {at_day}"}

    value = float(target[metric].iloc[0])
    bench_row = benchmark[benchmark["days_since_publish"] == at_day]
    if bench_row.empty or bench_row["sample_size"].iloc[0] < 3:
        return {
            "value": value,
            "benchmark_median": None,
            "ratio_vs_median": None,
            "quartile_label": "サンプル不足",
            "sample_size": int(bench_row["sample_size"].iloc[0]) if not bench_row.empty else 0,
        }

    p25 = float(bench_row["p25"].iloc[0])
    p50 = float(bench_row["p50"].iloc[0])
    p75 = float(bench_row["p75"].iloc[0])

    if value >= p75:
        label = "上位25%"
    elif value >= p50:
        label = "中央値〜上位25%"
    elif value >= p25:
        label = "下位25%〜中央値"
    else:
        label = "下位25%"

    return {
        "value": value,
        "benchmark_median": p50,
        "benchmark_p25": p25,
        "benchmark_p75": p75,
        "ratio_vs_median": value / p50 if p50 > 0 else None,
        "quartile_label": label,
        "sample_size": int(bench_row["sample_size"].iloc[0]),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_launch_curve_analyzer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/youtube_automation/domains/analytics/analysis/launch_curve_analyzer.py \
        tests/test_launch_curve_analyzer.py
git commit -m "feat: launch_curve_analyzer でベンチマーク計算と判定を追加"
```

---

## Task 5: matplotlib 描画

**Files:**
- Create: `src/youtube_automation/utils/launch_curve_plotter.py`
- Create: `tests/test_launch_curve_plotter.py`

PNG を 1 枚出力する描画関数。テストは smoke test のみ（ファイルが作られ、空でないこと）。

- [ ] **Step 1: Write smoke test**

```python
# tests/test_launch_curve_plotter.py
import pandas as pd

from youtube_automation.domains.analytics.analysis.launch_curve_plotter import plot_launch_curve


def _make_frame():
    records = []
    for vid in ["vid_0", "vid_1", "vid_2", "vid_3", "vid_4"]:
        for day in range(31):
            records.append({
                "video_id": vid,
                "days_since_publish": day,
                "cumulative_views": (int(vid.split("_")[1]) + 1) * day * 10,
                "daily_views": (int(vid.split("_")[1]) + 1) * 10,
                "daily_impressions": 500,
                "ctr": 2.0,
            })
    return pd.DataFrame(records)


def test_plot_launch_curve_writes_png(tmp_path):
    df = _make_frame()
    out = tmp_path / "curve.png"
    plot_launch_curve(
        df=df,
        target_video_id="vid_4",
        output_path=out,
        window=30,
    )
    assert out.exists()
    assert out.stat().st_size > 1000  # non-trivial PNG
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_launch_curve_plotter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement plotter**

```python
# src/youtube_automation/utils/launch_curve_plotter.py
"""Launch curve 可視化（matplotlib）"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import pandas as pd

from youtube_automation.domains.analytics.analysis.launch_curve_analyzer import (
    compute_benchmark,
    judge_video_vs_benchmark,
)


def plot_launch_curve(
    df: pd.DataFrame,
    target_video_id: Optional[str],
    output_path: Path,
    window: int = 30,
) -> None:
    """
    3 段サブプロット（累積 views / 日次 impressions / CTR）を 1 PNG に描画する。
    """
    df = df[df["days_since_publish"] <= window]

    fig, axes = plt.subplots(3, 1, figsize=(10, 12), sharex=True)

    _plot_metric_panel(
        axes[0], df, target_video_id, metric="cumulative_views",
        title="累積 views (benchmark: past videos)", ylabel="cumulative views",
    )
    _plot_metric_panel(
        axes[1], df, target_video_id, metric="daily_impressions",
        title="日次 impressions", ylabel="impressions/day",
    )
    _plot_ctr_panel(axes[2], df, target_video_id, window=window)

    axes[-1].set_xlabel("days since publish")

    if target_video_id:
        bench = compute_benchmark(df, metric="cumulative_views", exclude_video_id=target_video_id)
        # Judge at the latest day available for the target
        target = df[df["video_id"] == target_video_id]
        if not target.empty:
            latest_day = int(target["days_since_publish"].max())
            j = judge_video_vs_benchmark(df, bench, target_video_id, latest_day)
            ratio_text = (
                f"中央値の {j['ratio_vs_median']:.2f}x" if j.get("ratio_vs_median") else "n/a"
            )
            fig.suptitle(
                f"{target_video_id} @ day {latest_day}: {j['quartile_label']} ({ratio_text})",
                fontsize=14,
            )

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)


def _plot_metric_panel(ax, df, target_video_id, metric, title, ylabel):
    bench = compute_benchmark(df, metric=metric, exclude_video_id=target_video_id)

    # 全動画の薄い線
    for vid, g in df.groupby("video_id"):
        if vid == target_video_id:
            continue
        ax.plot(g["days_since_publish"], g[metric], color="gray", alpha=0.3, linewidth=0.8)

    # ベンチマーク帯
    valid = bench[bench["sample_size"] >= 3]
    if not valid.empty:
        ax.fill_between(
            valid["days_since_publish"], valid["p25"], valid["p75"],
            alpha=0.2, color="steelblue", label="IQR (p25-p75)",
        )
        ax.plot(valid["days_since_publish"], valid["p50"],
                color="steelblue", linewidth=2, label="median")

    # 対象動画
    if target_video_id:
        target = df[df["video_id"] == target_video_id]
        if not target.empty:
            ax.plot(target["days_since_publish"], target[metric],
                    color="crimson", linewidth=2.5, marker="o", markersize=3,
                    label=target_video_id)

    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)


def _plot_ctr_panel(ax, df, target_video_id, window):
    # CTR は 3 日移動平均で滑らか化
    smoothed = df.copy()
    smoothed["ctr_smooth"] = smoothed.groupby("video_id")["ctr"].transform(
        lambda s: s.rolling(window=3, min_periods=1).mean()
    )
    _plot_metric_panel(
        ax, smoothed, target_video_id,
        metric="ctr_smooth",
        title="CTR (3日移動平均)",
        ylabel="CTR %",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_launch_curve_plotter.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/youtube_automation/utils/launch_curve_plotter.py \
        tests/test_launch_curve_plotter.py
git commit -m "feat: launch_curve_plotter で matplotlib 描画を追加"
```

---

## Task 6: CLI エントリポイント

**Files:**
- Create: `src/youtube_automation/scripts/launch_curve.py`
- Modify: `pyproject.toml` ([project.scripts] と `src/youtube_automation/__init__.py` の `__version__` bump)

`yt-launch-curve --video ID` / `--latest` / `--all` を提供する。

- [ ] **Step 1: Implement CLI**

```python
# src/youtube_automation/scripts/launch_curve.py
#!/usr/bin/env python3
"""yt-launch-curve: 新作動画の初速をベンチマーク比較する CLI"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from youtube_automation.utils.channel_config import ChannelConfig
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.domains.analytics.analysis.launch_curve_analyzer import (
    compute_benchmark,
    judge_video_vs_benchmark,
)
from youtube_automation.utils.launch_curve_data import (
    build_launch_curve_frame,
    load_latest_daily_snapshot,
)
from youtube_automation.domains.analytics.analysis.launch_curve_plotter import plot_launch_curve

logger = logging.getLogger(__name__)


def _load_video_meta(channel_dir: Path) -> dict:
    """data/ 配下の最新 analytics_data_*.json から video meta を抽出する"""
    candidates = sorted((channel_dir / "data").glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError(
            "analytics_data_*.json が見つかりません。先に `yt-analytics` を実行してください。"
        )
    with open(candidates[-1], encoding="utf-8") as f:
        data = json.load(f)

    meta = {}
    for v in data.get("video_analytics", []) or []:
        vid = v.get("video_id")
        pub = v.get("published_at")
        if vid and pub:
            meta[vid] = {"title": v.get("title", ""), "published_at": pub}
    return meta


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="動画の launch curve を過去ベンチマークと比較")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video", help="対象動画 ID")
    group.add_argument("--latest", action="store_true", help="最新公開動画を自動選択")
    group.add_argument("--all", action="store_true", help="全動画を重ね描き（ベンチマーク把握用）")
    parser.add_argument("--window", type=int, default=30, help="表示日数 (default: 30)")

    args = parser.parse_args()

    try:
        channel_dir = ChannelConfig.channel_dir()
        daily = load_latest_daily_snapshot(channel_dir / "data")
        if daily is None:
            raise ConfigError(
                "日次データが見つかりません。先に `yt-analytics` を実行してください。"
            )
        meta = _load_video_meta(channel_dir)
        df = build_launch_curve_frame(daily_data=daily, video_meta=meta)
        if df.empty:
            raise ConfigError("launch curve 用データが空です")

        # 対象動画決定
        if args.all:
            target_id = None
        elif args.latest:
            target_id = df.sort_values("published_at", ascending=False)["video_id"].iloc[0]
        else:
            target_id = args.video

        out_dir = channel_dir / "data" / "analytics" / "launch_curves"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d")
        suffix = target_id if target_id else "all"
        out_path = out_dir / f"{stamp}_{suffix}.png"

        plot_launch_curve(df=df, target_video_id=target_id, output_path=out_path, window=args.window)

        # stdout サマリー
        if target_id:
            bench = compute_benchmark(df, metric="cumulative_views", exclude_video_id=target_id)
            target = df[df["video_id"] == target_id]
            latest_day = int(target["days_since_publish"].max())
            j = judge_video_vs_benchmark(df, bench, target_id, latest_day)
            print(f"🎯 {target_id} ({meta.get(target_id, {}).get('title', '')})")
            print(f"   {latest_day}日時点 累積 views: {int(j['value']):,}")
            if j.get("benchmark_median") is not None:
                print(f"   ベンチマーク中央値: {int(j['benchmark_median']):,} "
                      f"(n={j['sample_size']})")
                print(f"   判定: {j['quartile_label']} (中央値の {j['ratio_vs_median']:.2f}x)")
            else:
                print(f"   判定: {j['quartile_label']}")
        print(f"📈 プロット: {out_path}")
        return 0

    except ConfigError as e:
        logger.error(str(e))
        return 2
    except Exception as e:
        logger.exception(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Register CLI entry point**

Modify `pyproject.toml` `[project.scripts]` — insert after `yt-init-collection = ...`:

```toml
yt-launch-curve = "youtube_automation.scripts.launch_curve:main"
```

Also bump version in `pyproject.toml` (e.g., `1.2.0` → `1.3.0`) and sync `src/youtube_automation/__init__.py` `__version__`.

- [ ] **Step 3: Reinstall to register entry point**

Run: `uv sync` または `uv pip install -e .`
Expected: エラーなし。

- [ ] **Step 4: Smoke test help**

Run: `uv run yt-launch-curve --help`
Expected: help が正常に表示され、`--video` / `--latest` / `--all` / `--window` が見える。

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/youtube_automation/scripts/launch_curve.py pyproject.toml \
        src/youtube_automation/__init__.py
git commit -m "feat: yt-launch-curve CLI を追加"
```

---

## Task 7: 統合確認

**Files:**
- Modify: `README.md`（必要ならエントリの 1 行追加のみ）

実データでの動作確認。テスト対象ではなく、動作チェックリスト。

- [ ] **Step 1: 動画×日次データ収集を実行**

Run: `cd $CHANNEL_DIR && uv run yt-analytics --days 60`
Expected: `data/analytics/daily_per_video/2026-02-13_to_2026-04-14.json` が作成される。

- [ ] **Step 2: `--latest` で判定**

Run: `cd $CHANNEL_DIR && uv run yt-launch-curve --latest`
Expected: PNG 生成 + stdout サマリー。

- [ ] **Step 3: `--all` でベンチマーク全体像を確認**

Run: `cd $CHANNEL_DIR && uv run yt-launch-curve --all --window 60`
Expected: PNG 生成（全動画の重ね描き）。

- [ ] **Step 4: README に 1 行追記（任意）**

Modify `README.md` — 既存 CLI 一覧があれば `yt-launch-curve` を追記。なければスキップ。

- [ ] **Step 5: 最終コミット**

```bash
git add README.md 2>/dev/null || true
git diff --quiet || git commit -m "docs: yt-launch-curve を README に追記"
```

---

## Self-Review チェック済み項目

- Spec の「データパイプライン」「分析・可視化」「モジュール配置」「エラーハンドリング」「テスト方針」がすべて Task で実装されている
- プレースホルダなし（全コード展開済み）
- 型/メソッド名の整合性: `compute_benchmark` / `judge_video_vs_benchmark` / `build_launch_curve_frame` / `plot_launch_curve` / `load_latest_daily_snapshot` は Task 間で一貫
- Spec の「非スコープ」を誤って含めていない（Phase 2-4 はここでは実装しない）
