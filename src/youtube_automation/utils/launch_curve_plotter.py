"""Launch curve 可視化（matplotlib）"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # non-interactive backend
import japanize_matplotlib  # noqa: E402, F401 — registers Japanese fonts
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from youtube_automation.utils.launch_curve_analyzer import (  # noqa: E402
    compute_benchmark,
    judge_video_vs_benchmark,
)

logger = logging.getLogger(__name__)


def plot_launch_curve(
    df: pd.DataFrame,
    target_video_id: Optional[str],
    output_path: Path,
    window: int = 30,
) -> None:
    """累積 views（＋利用可能なら 日次 impressions / CTR）を PNG に描画する。

    動画×日次 impressions/CTR は API 仕様上取得できず欠損することがあるため、
    欠損時は views 単独の 1 段プロットにフォールバックする。
    """
    df = df[df["days_since_publish"] <= window]

    has_impressions = "daily_impressions" in df.columns and df["daily_impressions"].notna().any()
    has_ctr = "ctr" in df.columns and df["ctr"].notna().any()

    panels = 1 + (1 if has_impressions else 0) + (1 if has_ctr else 0)
    if panels == 1:
        logger.info("launch curve: impressions/CTR が利用不可のため views のみ描画します")

    fig, axes = plt.subplots(panels, 1, figsize=(10, 4 * panels), sharex=True)
    if panels == 1:
        axes = [axes]

    idx = 0
    _plot_metric_panel(
        axes[idx],
        df,
        target_video_id,
        metric="cumulative_views",
        title="累積 views (benchmark: past videos)",
        ylabel="cumulative views",
    )
    idx += 1

    if has_impressions:
        _plot_metric_panel(
            axes[idx],
            df,
            target_video_id,
            metric="daily_impressions",
            title="日次 impressions",
            ylabel="impressions/day",
        )
        idx += 1

    if has_ctr:
        _plot_ctr_panel(axes[idx], df, target_video_id)

    axes[-1].set_xlabel("days since publish")

    if target_video_id:
        bench = compute_benchmark(df, metric="cumulative_views", exclude_video_id=target_video_id)
        target = df[df["video_id"] == target_video_id]
        if not target.empty:
            latest_day = int(target["days_since_publish"].max())
            j = judge_video_vs_benchmark(df, bench, target_video_id, latest_day)
            ratio_text = f"中央値の {j['ratio_vs_median']:.2f}x" if j.get("ratio_vs_median") else "n/a"
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

    for vid, g in df.groupby("video_id"):
        if vid == target_video_id:
            continue
        ax.plot(g["days_since_publish"], g[metric], color="gray", alpha=0.3, linewidth=0.8)

    valid = bench[bench["sample_size"] >= 3]
    if not valid.empty:
        ax.fill_between(
            valid["days_since_publish"],
            valid["p25"],
            valid["p75"],
            alpha=0.2,
            color="steelblue",
            label="IQR (p25-p75)",
        )
        ax.plot(valid["days_since_publish"], valid["p50"], color="steelblue", linewidth=2, label="median")

    if target_video_id:
        target = df[df["video_id"] == target_video_id]
        if not target.empty:
            ax.plot(
                target["days_since_publish"],
                target[metric],
                color="crimson",
                linewidth=2.5,
                marker="o",
                markersize=3,
                label=target_video_id,
            )

    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)


def _plot_ctr_panel(ax, df, target_video_id):
    smoothed = df.copy()
    smoothed["ctr_smooth"] = smoothed.groupby("video_id")["ctr"].transform(
        lambda s: s.rolling(window=3, min_periods=1).mean()
    )
    _plot_metric_panel(
        ax,
        smoothed,
        target_video_id,
        metric="ctr_smooth",
        title="CTR (3日移動平均)",
        ylabel="CTR %",
    )
