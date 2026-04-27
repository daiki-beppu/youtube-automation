#!/usr/bin/env python3
"""YouTube Analytics データ収集

YouTube Analytics API を使用してデータを収集し、JSON ファイルに保存する。
認証テストは auth_test.py、データ表示は analytics_display.py を使用。
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from youtube_automation.utils.analytics_collector import YouTubeAnalyticsCollector  # noqa: E402
from youtube_automation.utils.config import channel_dir, load_config  # noqa: E402

logger = logging.getLogger(__name__)


def _save_dated_analytics_json(
    subdir: str,
    start_date: datetime,
    end_date: datetime,
    payload: dict[str, Any],
    label: str,
) -> Path:
    """`data/analytics/<subdir>/<start>_to_<end>.json` に payload を保存する。"""
    dir_path = channel_dir() / "data" / "analytics" / subdir
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(f"💾 {label}保存完了: {file_path}")
    return file_path


class AnalyticsSystem:
    """YouTube Analytics データ収集システム"""

    def __init__(self):
        """システム初期化"""
        config = load_config()
        logger.info(f"🎵 {config.meta.channel_name} - Analytics System v1.0")

        self.collector = YouTubeAnalyticsCollector()
        self.authenticated = False

    def authenticate(self, force_reauth=False):
        """
        YouTube API認証

        Args:
            force_reauth (bool): 強制再認証フラグ
        """
        logger.info("🔐 YouTube API認証中...")

        try:
            from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

            handler = YouTubeOAuthHandler()
            handler.authenticate(force_reauth=force_reauth)

            if handler.test_connection():
                self.authenticated = True
                logger.info("✅ 認証完了 - システム準備完了")
                return True
            else:
                logger.error("❌ 認証失敗 - 接続テストに失敗")
                return False

        except Exception as e:
            logger.error(f"❌ 認証エラー: {e}")
            return False

    def collect_analytics_data(self, days=30, save_data=True, include_reporting=False):
        """
        アナリティクスデータ収集

        Args:
            days (int): 収集期間（日数）
            save_data (bool): データ保存フラグ
            include_reporting (bool): YouTube Reporting API による thumbnail impressions / CTR を含めるか

        Returns:
            Dict: 収集されたアナリティクスデータ
        """
        if not self.authenticated:
            logger.error("❌ 認証が必要です。先に authenticate() を実行してください。")
            return None

        logger.info(f"📊 過去{days}日間のアナリティクスデータ収集中...")

        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            analytics_data = self.collector.collect_basic_analytics(
                start_date=start_date.strftime("%Y-%m-%d"), end_date=end_date.strftime("%Y-%m-%d")
            )

            if include_reporting:
                logger.info("📊 Reporting API による impressions / CTR 取得中...")
                summary = self.collector.get_reporting_impressions_summary(days=days)
                if summary is not None:
                    analytics_data["reporting_api"] = {"impressions_summary": summary}
                    if save_data:
                        _save_dated_analytics_json(
                            "reporting_api",
                            start_date,
                            end_date,
                            summary,
                            "Reporting API impressions/CTR",
                        )
                else:
                    logger.warning("⚠️ Reporting API データ取得失敗（続行）")

            if save_data:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                data_file = channel_dir() / "data" / f"analytics_data_{timestamp}.json"
                data_file.parent.mkdir(exist_ok=True)

                with open(data_file, "w", encoding="utf-8") as f:
                    json.dump(analytics_data, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 データ保存完了: {data_file}")

                # 動画×日次データ（launch curve 分析用）
                try:
                    video_list = self.collector.get_all_channel_videos()
                    video_ids = [v["video_id"] for v in video_list]
                    daily_rows = self.collector.get_video_daily_analytics(
                        start_date.strftime("%Y-%m-%d"),
                        end_date.strftime("%Y-%m-%d"),
                        video_ids=video_ids,
                    )
                    _save_dated_analytics_json(
                        "daily_per_video",
                        start_date,
                        end_date,
                        {
                            "start_date": start_date.strftime("%Y-%m-%d"),
                            "end_date": end_date.strftime("%Y-%m-%d"),
                            "video_ids": video_ids,
                            "rows": daily_rows,
                        },
                        "動画×日次データ",
                    )
                except Exception as e:
                    logger.warning(f"⚠️ 動画×日次データ保存失敗（続行）: {e}")

            logger.info("✅ アナリティクスデータ収集完了")
            return analytics_data

        except Exception as e:
            logger.error(f"❌ データ収集エラー: {e}")
            return None

    def run_data_collection(self, days=30, include_reporting=False):
        """
        データ収集実行 (認証 → データ収集 → JSONデータ保存)

        Args:
            days (int): データ収集期間

        Returns:
            Dict: 実行結果
        """
        config = load_config()
        logger.info(f"🚀 {config.meta.channel_short} YouTube Analytics データ収集開始...")
        logger.info(f"📊 収集期間: 過去{days}日間")

        results = {"success": False}

        if not self.authenticate():
            results["error"] = "Authentication failed"
            return results

        try:
            analytics_data = self.collect_analytics_data(days=days, include_reporting=include_reporting)
            if not analytics_data:
                results["error"] = "Data collection failed"
                logger.error("🛑 データ収集に失敗したため処理を終了します")
                return results
        except Exception as e:
            results["error"] = f"Data collection error: {e}"
            logger.error("🛑 データ収集エラーのため処理を終了します")
            return results

        logger.info("✅ YouTube Analyticsデータ収集完了")

        results["success"] = True
        results["analytics_data"] = analytics_data

        logger.info("🎉 データ収集完了！")

        return results


def _make_reporting_client():
    from youtube_automation.utils.reporting_api import ReportingAPIClient
    from youtube_automation.utils.youtube_service import get_credentials, get_reporting

    return ReportingAPIClient(get_reporting(), credentials=get_credentials())


def _run_reporting_dry_run() -> int:
    """Reporting API の現状観察（副作用なし）。終了コードを返す。"""
    print("🔍 YouTube Reporting API dry-run inspection")
    print("=" * 60)

    try:
        from youtube_automation.utils.exceptions import AutomationError

        client = _make_reporting_client()
        report = client.dry_run_inspection()
    except AutomationError as e:
        print(f"❌ dry-run 失敗: {e}")
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print()
    if report["selected_report_type"]:
        print(f"✅ 選定 reportType: {report['selected_report_type']}")
        if report["existing_job"]:
            print(f"✅ 既存ジョブあり: jobId={report['existing_job']['id']}")
            print(f"   過去 60 日に生成されたレポート数: {report['recent_reports_count']}")
            if report["recent_reports_count"] == 0:
                print("   ⚠️  まだレポートが生成されていません（ジョブ作成後 最大 48h 待ち）")
        else:
            print("ℹ️  既存ジョブなし。--include-reporting 実行で新規作成されます")
    else:
        print(f"⚠️  選定可能な reportType が見つかりません。利用可能: {report['available_priority_matches']}")

    return 0


def _run_reporting_create_job() -> int:
    """Reporting API ジョブを冪等に作成して終了（CSV DL・Analytics 全体収集なし）。"""
    print("🛠️  YouTube Reporting API job creation")
    print("=" * 60)

    try:
        from youtube_automation.utils.exceptions import AutomationError

        client = _make_reporting_client()
        report_type_id = client.select_report_type()
        job_id = client.ensure_job(report_type_id)
    except AutomationError as e:
        print(f"❌ ジョブ作成失敗: {e}")
        return 1

    print(f"✅ reportType: {report_type_id}")
    print(f"✅ jobId: {job_id}")
    print()
    print("ℹ️  最初のレポート取得可能まで最大 48 時間。")
    print("   初回取得時はジョブ作成日から過去 30 日分が backfill されます。")
    print("   以降は日次（D+2）でレポートが生成され、`--include-reporting` で CSV を取得・集計できます。")
    return 0


def main():
    """メイン関数 - CLI実行用"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="YouTube Analytics データ収集")
    parser.add_argument("--days", type=int, default=30, help="データ収集期間（日数）")
    parser.add_argument("--all-time", action="store_true", help="全期間データを取得（チャンネル開設から現在まで）")
    parser.add_argument(
        "--include-reporting",
        action="store_true",
        help="YouTube Reporting API v1 経由で thumbnail impressions / CTR を取得（初回最大 48h、以降 D+2 ラグ）",
    )
    parser.add_argument(
        "--reporting-dry-run",
        action="store_true",
        help="Reporting API の reportTypes.list() / jobs.list() を観察するだけ（ジョブ作成・CSV DL なし）",
    )
    parser.add_argument(
        "--reporting-create-job",
        action="store_true",
        help="Reporting API のジョブのみを冪等に作成して終了（CSV DL・Analytics 全体収集なし）",
    )

    args = parser.parse_args()

    # Reporting API 関連サブモードはチャンネル config に依存しないので先に処理
    if args.reporting_dry_run:
        sys.exit(_run_reporting_dry_run())
    if args.reporting_create_job:
        sys.exit(_run_reporting_create_job())

    config = load_config()
    logger.info(f"🎵 {config.meta.channel_short} Analytics データ収集")

    system = AnalyticsSystem()

    if args.all_time:
        print("🌟 全期間データ取得モード（チャンネル開設～現在）")
        collection_days = 365
    else:
        collection_days = args.days

    results = system.run_data_collection(
        days=collection_days,
        include_reporting=args.include_reporting,
    )

    if not results["success"]:
        print(f"\n❌ データ収集失敗: {results.get('error', 'Unknown error')}")
        sys.exit(1)

    print("\n📁 データ収集が正常に完了しました")
    print("💡 データ表示は analytics_display.py を使用してください:")
    print("   python3 analytics_display.py --data-file <FILE> --show-all")

    sys.exit(0)


if __name__ == "__main__":
    main()
