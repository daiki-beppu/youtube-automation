"""yt-stream-bandwidth — Vultr 帯域モニタリング + 月次レポート + 80% アラート。

Usage:
    yt-stream-bandwidth [--instance-id <ID> | --terraform-dir <PATH>]
        現状サマリ (今月の使用量) を stdout に出力。webhook 投稿はしない。

    yt-stream-bandwidth --report [--month YYYY-MM] [--instance-id <ID>] [--terraform-dir <PATH>]
        対象月 (省略時は前月) の月次レポートを生成し、STREAM_WEBHOOK_URL に投稿。

    yt-stream-bandwidth --check-threshold [--instance-id <ID>] [--terraform-dir <PATH>]
        当月の使用量が 80% 閾値を超えていれば webhook へアラート。未超は静黙。

    yt-stream-bandwidth --probe-bitrate <PATH>
        ローカル MP4 のビットレートを ffprobe で実測し、想定 4 Mbps と比較。
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import sys
from pathlib import Path

from youtube_automation.utils.notification import notify
from youtube_automation.utils.probe import probe_bitrate
from youtube_automation.utils.secrets import get_secret
from youtube_automation.utils.streaming import (
    MONTHLY_QUOTA_GB,
    THEORETICAL_BITRATE_MBPS,
    THRESHOLD_RATIO,
)
from youtube_automation.utils.streaming.archive_counter import count_archives
from youtube_automation.utils.streaming.instance_resolver import resolve_instance_id
from youtube_automation.utils.streaming.monthly_report import format_monthly_report
from youtube_automation.utils.streaming.threshold import is_over_threshold
from youtube_automation.utils.streaming.vultr_bandwidth import (
    fetch_bandwidth,
    monthly_total_gb,
)
from youtube_automation.utils.youtube_service import get_youtube


def today() -> datetime.date:
    """システム日付を返す。テストから patch するためだけに切り出した薄いラッパー。"""
    return datetime.date.today()


def _previous_month(d: datetime.date) -> tuple[int, int]:
    """`d` の属する月の 1 つ前の (year, month) を返す。"""
    if d.month == 1:
        return d.year - 1, 12
    return d.year, d.month - 1


def _parse_month(value: str) -> tuple[int, int]:
    """`YYYY-MM` を (year, month) に分解する。"""
    parts = value.split("-")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"--month は YYYY-MM 形式で指定してください: {value}")
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--month のパースに失敗: {value}") from e
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError(f"--month の月が範囲外: {value}")
    return year, month


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vultr 帯域モニタリング + 月次レポート + 80% アラート (Issue #110)")
    parser.add_argument("--instance-id", help="Vultr インスタンス ID (省略時は terraform output から解決)")
    parser.add_argument(
        "--terraform-dir",
        type=Path,
        help="`terraform output -raw instance_id` を実行するディレクトリ",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true", help="月次レポートを生成して webhook に投稿")
    mode.add_argument(
        "--check-threshold",
        action="store_true",
        help="当月使用量が 80%% 閾値を超えていれば webhook にアラート",
    )
    mode.add_argument(
        "--probe-bitrate",
        type=Path,
        metavar="PATH",
        help="ffprobe でローカル MP4 のビットレートを実測し想定値と比較",
    )
    parser.add_argument("--month", help="--report の対象月 (YYYY-MM)。省略時は前月")
    parser.add_argument(
        "--channel-id",
        help="アーカイブ計数対象の YouTube チャンネル ID (省略時は認証ユーザーのチャンネル)",
    )
    return parser


def _run_probe_bitrate(path: Path) -> int:
    """`--probe-bitrate <PATH>` モード。"""
    bps = probe_bitrate(path)
    if bps is None:
        print(
            f"ffprobe で {path} のビットレートを取得できませんでした (ffprobe 未インストール / 不正フォーマット)",
            file=sys.stderr,
        )
        return 1
    actual_mbps = bps / 1_000_000
    print(
        f"ビットレート照合: 実測 {actual_mbps:.2f} Mbps / 想定 {THEORETICAL_BITRATE_MBPS} Mbps "
        f"(差分 {actual_mbps - THEORETICAL_BITRATE_MBPS:+.2f} Mbps)"
    )
    return 0


def _resolve_bandwidth(args: argparse.Namespace) -> dict[str, dict[str, int]]:
    """instance_id を解決し Vultr API から bandwidth を取得する境界処理。"""
    instance_id = resolve_instance_id(override=args.instance_id, terraform_dir=args.terraform_dir)
    api_key = get_secret("VULTR_API_KEY")
    return fetch_bandwidth(instance_id=instance_id, api_key=api_key)


def _run_report(args: argparse.Namespace) -> int:
    """`--report` モード。"""
    if args.month:
        target_year, target_month = _parse_month(args.month)
    else:
        target_year, target_month = _previous_month(today())

    bandwidth = _resolve_bandwidth(args)
    usage_gb = monthly_total_gb(bandwidth, year=target_year, month=target_month)

    prev_year, prev_month = _previous_month(datetime.date(target_year, target_month, 1))
    previous_usage_gb: float | None = monthly_total_gb(bandwidth, year=prev_year, month=prev_month)
    if previous_usage_gb == 0:
        # 前月のデータが Vultr API のレンジ外で完全に欠落しているケースは N/A 扱い
        # (0 GB と区別できない場合は N/A の方が誤読を招きにくい)
        previous_usage_gb = None

    archives = count_archives(get_youtube(), channel_id=args.channel_id, year=target_year, month=target_month)
    days_in_month = calendar.monthrange(target_year, target_month)[1]
    text = format_monthly_report(
        year=target_year,
        month=target_month,
        usage_gb=usage_gb,
        previous_usage_gb=previous_usage_gb,
        archives=archives,
        days_in_month=days_in_month,
    )
    webhook_url = get_secret("STREAM_WEBHOOK_URL")
    notify(content=text, webhook_url=webhook_url)
    return 0


def _run_check_threshold(args: argparse.Namespace) -> int:
    """`--check-threshold` モード。"""
    bandwidth = _resolve_bandwidth(args)
    d = today()
    usage_gb = monthly_total_gb(bandwidth, year=d.year, month=d.month)
    if not is_over_threshold(usage_gb=usage_gb, quota_gb=MONTHLY_QUOTA_GB, ratio=THRESHOLD_RATIO):
        return 0
    threshold_pct = int(THRESHOLD_RATIO * 100)
    text = (
        f":warning: 帯域 {threshold_pct}% 到達アラート ({d.year:04d}-{d.month:02d})\n"
        f"使用量: {usage_gb:.1f} GB / {MONTHLY_QUOTA_GB} GB"
    )
    webhook_url = get_secret("STREAM_WEBHOOK_URL")
    notify(content=text, webhook_url=webhook_url)
    return 0


def _run_default_summary(args: argparse.Namespace) -> int:
    """引数なしのデフォルトモード。当月使用量サマリを stdout に出力。"""
    bandwidth = _resolve_bandwidth(args)
    d = today()
    usage_gb = monthly_total_gb(bandwidth, year=d.year, month=d.month)
    pct = (usage_gb / MONTHLY_QUOTA_GB) * 100
    print(f"{d.year:04d}-{d.month:02d} 帯域使用量: {usage_gb:.1f} GB / {MONTHLY_QUOTA_GB} GB ({pct:.1f}%)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.probe_bitrate is not None:
        return _run_probe_bitrate(args.probe_bitrate)
    if args.report:
        return _run_report(args)
    if args.check_threshold:
        return _run_check_threshold(args)
    return _run_default_summary(args)


if __name__ == "__main__":
    sys.exit(main())
