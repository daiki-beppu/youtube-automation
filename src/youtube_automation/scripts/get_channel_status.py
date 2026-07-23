#!/usr/bin/env python3
"""
Channel Status Getter - Claude Code用シンプル情報取得
分析なしで、Claude Codeが理解しやすい最新情報を取得
"""

import contextlib
import json
import logging
import sys
from datetime import datetime, timedelta

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.domains.analytics.service import YouTubeAnalyticsCollector
from youtube_automation.infrastructure.analytics_adapter import AnalyticsAdapter, YouTubeDataAdapter
from youtube_automation.utils import cost_tracker
from youtube_automation.utils.exceptions import AutomationError, YouTubeAPIError
from youtube_automation.utils.reporting_api import ReportingAPIClient
from youtube_automation.utils.youtube_service import (
    get_analytics,
    get_credentials_readonly,
    get_reporting,
    get_youtube_readonly,
)

logger = logging.getLogger(__name__)

_QUOTA_SERVICE = "youtube-data-api"
_ANALYTICS_QUOTA_SERVICE = "youtube-analytics-api"
_READ_QUOTA_UNITS = 1


class _DeferredService:
    """サービス取得を最初の実 API 操作まで遅延する薄い DI アダプター。"""

    def __init__(self, factory):
        self._factory = factory
        self._service = None

    def __getattr__(self, name):
        if self._service is None:
            self._service = self._factory()
        return getattr(self._service, name)


def _record_read_quota(bucket: str, *, service: str = _QUOTA_SERVICE) -> None:
    """read 1 リクエスト分の quota 消費を記録する。tracker の書き込み失敗は内部で処理する。"""
    # tracker 内部の警告 print が stdout 契約（--json 等）を汚さないよう stderr へ逃がす
    with contextlib.redirect_stdout(sys.stderr):
        cost_tracker.log_quota(service, bucket, _READ_QUOTA_UNITS)


def get_channel_latest_status():
    """チャンネルの最新状況をシンプルに取得"""
    config = load_config()
    logger.info(f"📊 {config.meta.channel_short} 最新状況取得中...")

    try:
        collector = YouTubeAnalyticsCollector(
            youtube_client=YouTubeDataAdapter(
                _DeferredService(get_youtube_readonly),
                retry_requests=False,
                on_request=lambda bucket: _record_read_quota(bucket, service=_QUOTA_SERVICE),
            ),
            analytics_client=AnalyticsAdapter(
                _DeferredService(get_analytics),
                retry_requests=False,
                on_request=lambda bucket: _record_read_quota(bucket, service=_ANALYTICS_QUOTA_SERVICE),
            ),
            reporting_client=ReportingAPIClient(
                _DeferredService(get_reporting),
                credentials=_DeferredService(get_credentials_readonly),
            ),
            channel_root=channel_dir(),
        )
        collector.initialize()

        # 基本チャンネル情報
        channel_response = collector.youtube_service.resolve_channel()

        if not channel_response:
            return {"error": "チャンネル情報取得失敗"}

        channel = channel_response
        stats = channel["statistics"]

        # 最新コレクション情報（Complete Collection形式の動画を抽出）
        uploads_response = collector.youtube_service.list_uploads(collector.channel_id)

        uploads_playlist_id = uploads_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # Complete Collection再生リストから直接取得
        logger.info("🔍 Complete Collection再生リストから取得中...")
        collections = []

        # チャンネルの全再生リストを取得
        playlists_response = collector.youtube_service.list_playlists(collector.channel_id)

        # config からフィルタキーワードを取得
        filter_keywords = list(config.analytics.collection_filter_keywords)

        target_playlists = []
        for playlist in playlists_response["items"]:
            title = playlist["snippet"]["title"]
            if all(keyword in title for keyword in filter_keywords):
                target_playlists.append({"id": playlist["id"], "title": title})
                logger.info(f"📋 対象再生リスト発見: {title}")

        # 各Complete Collection再生リストから動画を取得
        for playlist in target_playlists:
            logger.info(f"🎵 {playlist['title']} から動画取得中...")

            playlist_items_response = collector.youtube_service.list_playlist_items_for_display(
                playlist["id"], max_results=50
            )

            for item in playlist_items_response["items"]:
                video_title = item["snippet"]["title"]
                collections.append(
                    {
                        "collection_name": video_title,
                        "published_at": item["snippet"]["publishedAt"][:10],
                        "video_id": item["snippet"]["resourceId"]["videoId"],
                        "url": f"https://youtu.be/{item['snippet']['resourceId']['videoId']}",
                        "playlist_source": playlist["title"],
                    }
                )
                logger.info(f"  ✅ {video_title}")

        # 投稿日時で降順ソート（新しい順）
        collections.sort(key=lambda x: x["published_at"], reverse=True)

        logger.info(f"📊 Complete Collection再生リストから{len(collections)}個を取得")

        # もしコレクションが見つからない場合は、uploadsプレイリストから最新動画を表示
        if not collections:
            recent_videos_response = collector.youtube_service.list_playlist_items_for_display(
                uploads_playlist_id, max_results=10
            )
            for item in recent_videos_response.get("items", []):
                collections.append(
                    {
                        "collection_name": item["snippet"]["title"],
                        "published_at": item["snippet"]["publishedAt"][:10],
                        "video_id": item["snippet"]["resourceId"]["videoId"],
                        "url": f"https://youtu.be/{item['snippet']['resourceId']['videoId']}",
                    }
                )

        # 個別動画の Analytics 統計を OAuth で一括取得
        video_ids = [c["video_id"] for c in collections if "video_id" in c]
        if video_ids:
            logger.info(f"📊 {len(video_ids)}本の動画 Analytics を取得中...")
            stats_map = {}
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            try:
                response = collector.analytics_service.query(
                    ids=f"channel=={collector.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,averageViewDuration",
                    dimensions="video",
                    filters=f"video=={','.join(video_ids)}",
                    sort="-views",
                )
                for row in response.get("rows", []):
                    stats_map[row[0]] = {
                        "views": row[1],
                        "watch_time_min": round(row[2], 1),
                        "avg_view_duration_sec": row[3],
                    }
            except YouTubeAPIError as e:
                logger.warning(f"⚠️ Analytics 取得エラー: {e}")
            for c in collections:
                vid = c.get("video_id")
                if vid and vid in stats_map:
                    c["stats"] = stats_map[vid]

        # コレクション数とトラック数を動的算出
        collections_count = len(collections)
        # 動画総数からComplete Collection数を除いた数がおおよその個別トラック数
        video_count = int(stats.get("videoCount", 0))
        estimated_tracks = video_count - collections_count if video_count > collections_count else video_count

        # シンプルな状況サマリー
        status = {
            "channel_name": channel["snippet"]["title"],
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": video_count,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recent_collections": collections,
            "collections_count": collections_count,
            "estimated_tracks": estimated_tracks,
        }

        return status

    except AutomationError as e:
        return {"error": f"取得エラー: {e!s}"}


def main():
    """メイン実行"""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = load_config()
    parser = argparse.ArgumentParser(description=f"{config.meta.channel_short}最新状況取得（Claude Code用）")
    parser.add_argument("--json", action="store_true", help="JSON形式で出力")
    parser.add_argument("--summary", action="store_true", help="サマリーのみ表示")

    args = parser.parse_args()

    status = get_channel_latest_status()

    if "error" in status:
        print(f"❌ {status['error']}")
        sys.exit(1)

    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    elif args.summary:
        print(f"チャンネル: {status['channel_name']}")
        print(f"登録者: {status['subscriber_count']:,}人")
        print(f"総動画数: {status['video_count']:,}本")
        print(f"コレクション: {status['collections_count']}個")
        print(f"推定トラック数: {status['estimated_tracks']}曲")
    else:
        # Claude Code用の詳細表示
        print("=" * 50)
        print(f"🎵 {config.meta.channel_name} ({config.meta.channel_short}) - 最新状況")
        print("=" * 50)
        print(f"📺 チャンネル名: {status['channel_name']}")
        print(f"👥 登録者数: {status['subscriber_count']:,}人")
        print(f"👀 総再生回数: {status['total_views']:,}回")
        print(f"🎬 総動画数: {status['video_count']:,}本")
        print(f"🎵 完成コレクション: {status['collections_count']}個")
        print(f"🎶 推定トラック数: {status['estimated_tracks']}曲")
        print(f"📅 更新日時: {status['updated_at']}")

        print("\n🎵 すべてのコレクション:")
        for i, collection in enumerate(status["recent_collections"], 1):
            s = collection.get("stats", {})
            if s:
                avg_min = s["avg_view_duration_sec"] / 60
                print(f"  {i:2d}. {collection['collection_name']} ({collection['published_at']})")
                print(
                    f"      👀 {s['views']:,} views  ⏱ {s['watch_time_min']:,.0f}min watched"
                    f"  📊 avg {avg_min:.1f}min/view"
                )
            else:
                print(f"  {i:2d}. {collection['collection_name']} ({collection['published_at']})")

        print(f"\n💾 データ更新: {status['updated_at']}")


if __name__ == "__main__":
    main()
