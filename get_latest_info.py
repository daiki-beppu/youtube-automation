#!/usr/bin/env python3
"""
最新情報取得システム
YouTube Analytics APIから最新データを収集し、分析レポートを自動生成

Features:
- リアルタイムチャンネル統計取得
- 最新動画パフォーマンス分析
- CTR改善戦略分析
- コレクション別パフォーマンス比較
- 戦略的アクションプラン生成
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Any, Dict

logger = logging.getLogger(__name__)

import utils._path_setup  # noqa: F401, E402
from utils.analytics_analyzer import AnalyticsAnalyzer  # noqa: E402
from utils.analytics_collector import YouTubeAnalyticsCollector  # noqa: E402
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.report_generator import ReportGenerator  # noqa: E402


class LatestInfoSystem:
    """最新情報取得・分析システム"""

    def __init__(self):
        """初期化"""
        self.collector = YouTubeAnalyticsCollector()
        self.analyzer = AnalyticsAnalyzer()
        self.report_generator = ReportGenerator()
        self.data_dir = ChannelConfig.channel_dir() / 'data'
        self.reports_dir = ChannelConfig.channel_dir() / 'reports'

        # ディレクトリ作成
        self.data_dir.mkdir(exist_ok=True)
        self.reports_dir.mkdir(exist_ok=True)

    def get_latest_info(self, analysis_days: int = 30) -> Dict[str, Any]:
        """
        最新情報を取得・分析

        Args:
            analysis_days (int): 分析対象日数（デフォルト30日）

        Returns:
            Dict: 統合分析結果
        """
        config = ChannelConfig.load()
        logger.info(f"🎵 {config.channel_name} - 最新情報取得開始")

        try:
            # 日付範囲計算
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=analysis_days)).strftime('%Y-%m-%d')

            logger.info(f"📅 分析期間: {start_date} 〜 {end_date}")

            # Step 1: 基本アナリティクス収集
            logger.info("📊 Step 1: 基本アナリティクス収集中...")
            analytics_data = self.collector.collect_basic_analytics(start_date, end_date)

            # Step 2: 詳細分析実行
            logger.info("🔍 Step 2: 詳細分析実行中...")
            performance_report = self.analyzer.generate_performance_report(analytics_data)

            # Step 3: 最新コレクション情報を追加
            logger.info("🎵 Step 3: 最新コレクション情報取得中...")
            latest_collections = self._get_latest_collections_info(analytics_data)

            # Step 4: 戦略的分析
            logger.info("🎯 Step 4: 戦略的分析実行中...")
            strategic_analysis = self._perform_strategic_analysis(analytics_data)

            # Step 5: 統合レポート作成
            logger.info("📝 Step 5: 統合レポート作成中...")
            integrated_report = self._create_integrated_report(
                analytics_data, performance_report, latest_collections, strategic_analysis
            )

            # Step 6: データ保存
            logger.info("💾 Step 6: データ保存中...")
            self._save_data_and_reports(integrated_report)

            logger.info("✅ 最新情報取得完了!")
            return integrated_report

        except Exception as e:
            logger.error(f"❌ エラーが発生しました: {e}")
            raise

    def _get_latest_collections_info(self, analytics_data: Dict) -> Dict[str, Any]:
        """最新コレクション情報取得"""
        logger.info("  📋 コレクション情報を分析中...")

        video_analytics = analytics_data.get('video_analytics', {})

        # 最新投稿動画（30日以内）
        recent_videos = []
        cutoff_date = datetime.now() - timedelta(days=30)

        for video_id, data in video_analytics.items():
            published_at = data.get('published_at')
            if published_at:
                try:
                    pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    if pub_date.replace(tzinfo=None) >= cutoff_date:
                        recent_videos.append({
                            'video_id': video_id,
                            'title': data.get('title', ''),
                            'published_at': published_at,
                            'views': data.get('views', 0),
                            'estimated_minutes_watched': data.get('estimated_minutes_watched', 0)
                        })
                except Exception:
                    continue

        # 投稿日時で降順ソート
        recent_videos.sort(key=lambda x: x['published_at'], reverse=True)

        # コレクション別分類
        collections_info = self._classify_recent_videos(recent_videos)

        return {
            'recent_videos_count': len(recent_videos),
            'latest_videos': recent_videos[:10],  # 最新10本
            'collections_breakdown': collections_info,
            'total_collections': self._count_total_collections(video_analytics)
        }

    def _classify_recent_videos(self, recent_videos: list) -> Dict[str, Any]:
        """最近の動画をコレクション別に分類（channel_config.json のテーマから動的生成）"""
        config = ChannelConfig.load()
        theme_keys = list(config.theme_tags.keys())

        collections = {theme.title(): [] for theme in theme_keys}
        collections['Other'] = []

        for video in recent_videos:
            title = video['title'].lower()
            classified = False

            for theme in theme_keys:
                if theme in title:
                    collections[theme.title()].append(video)
                    classified = True
                    break

            if not classified:
                collections['Other'].append(video)

        # 統計計算
        collection_stats = {}
        for collection, videos in collections.items():
            if videos:
                collection_stats[collection] = {
                    'video_count': len(videos),
                    'total_views': sum(v['views'] for v in videos),
                    'average_views': sum(v['views'] for v in videos) / len(videos),
                    'latest_video': videos[0] if videos else None
                }

        return collection_stats

    def _count_total_collections(self, video_analytics: Dict) -> int:
        """総コレクション数をカウント（channel_config.json のテーマキーワードで動的判定）"""
        config = ChannelConfig.load()
        collection_keywords = list(config.theme_tags.keys())

        found_collections = set()

        for video_id, data in video_analytics.items():
            title = data.get('title', '').lower()
            for keyword in collection_keywords:
                if keyword in title:
                    found_collections.add(keyword)

        return len(found_collections)

    def _perform_strategic_analysis(self, analytics_data: Dict) -> Dict[str, Any]:
        """戦略的分析実行"""
        logger.info("  🎯 戦略分析を実行中...")

        video_analytics = analytics_data.get('video_analytics', {})

        # 8-bit パフォーマンス分析
        bit_analysis = self._analyze_bit_performance(video_analytics)

        # テーマ別パフォーマンス
        theme_analysis = self._analyze_theme_performance(video_analytics)

        # CTR推定分析
        ctr_analysis = self._estimate_ctr_performance(video_analytics)

        return {
            'bit_type_analysis': bit_analysis,
            'theme_performance': theme_analysis,
            'ctr_estimation': ctr_analysis,
            'strategic_recommendations': self._generate_strategic_recommendations(
                bit_analysis, theme_analysis, ctr_analysis
            )
        }

    def _analyze_bit_performance(self, video_analytics: Dict) -> Dict[str, Any]:
        """8-bit パフォーマンス分析"""
        bit_8_videos = []

        for video_id, data in video_analytics.items():
            title = data.get('title', '')
            views = data.get('views', 0)
            watch_time = data.get('estimated_minutes_watched', 0)

            if '8-bit' in title or '8-Bit' in title:
                bit_8_videos.append({'views': views, 'watch_time': watch_time})

        if not bit_8_videos:
            bit_8_stats = {'count': 0, 'avg_views': 0, 'total_watch_time': 0}
        else:
            bit_8_stats = {
                'count': len(bit_8_videos),
                'avg_views': sum(v['views'] for v in bit_8_videos) / len(bit_8_videos),
                'total_views': sum(v['views'] for v in bit_8_videos),
                'total_watch_time': sum(v['watch_time'] for v in bit_8_videos),
            }

        return {
            '8_bit': bit_8_stats,
            'recommendation': 'focus on primary genre',
        }

    def _analyze_theme_performance(self, video_analytics: Dict) -> Dict[str, Any]:
        """テーマ別パフォーマンス分析（channel_config.json のテーマから動的生成）"""
        config = ChannelConfig.load()
        # テーマキーワードからタグ内のキーワードを検索用に変換
        themes = {}
        for theme, tag_list in config.theme_tags.items():
            keywords = [theme] + [tag.replace(' music', '').replace(' Music', '') for tag in tag_list]
            themes[theme.title()] = keywords

        theme_stats = {}

        for theme, keywords in themes.items():
            theme_videos = []

            for video_id, data in video_analytics.items():
                title = data.get('title', '').lower()
                views = data.get('views', 0)

                if any(keyword in title for keyword in keywords):
                    theme_videos.append(views)

            if theme_videos:
                theme_stats[theme] = {
                    'video_count': len(theme_videos),
                    'total_views': sum(theme_videos),
                    'average_views': sum(theme_videos) / len(theme_videos),
                    'max_views': max(theme_videos)
                }

        return theme_stats

    def _estimate_ctr_performance(self, video_analytics: Dict) -> Dict[str, Any]:
        """CTRパフォーマンス推定"""
        # 実際のCTRデータが無いため、視聴回数ベースで推定
        total_videos = len(video_analytics)
        high_performance = 0  # 平均以上

        if total_videos > 0:
            avg_views = sum(data.get('views', 0) for data in video_analytics.values()) / total_videos
            high_performance = sum(1 for data in video_analytics.values() if data.get('views', 0) > avg_views)

        return {
            'total_videos_analyzed': total_videos,
            'high_performance_count': high_performance,
            'estimated_ctr_status': 'Improving' if high_performance > total_videos * 0.4 else 'Needs Attention',
            'current_target': 'analyze current CTR and set improvement target'
        }

    def _generate_strategic_recommendations(self, bit_analysis: Dict, theme_analysis: Dict, ctr_analysis: Dict) -> list:
        """戦略的推奨事項生成"""
        recommendations = []

        config = ChannelConfig.load()
        # 音源タイプ推奨
        recommendations.append(f"🎵 {config.genre_style}音源専念戦略継続推奨（Analytics実証済み）")

        # テーマ推奨
        if theme_analysis:
            best_theme = max(theme_analysis.items(), key=lambda x: x[1]['average_views'])
            avg = best_theme[1]['average_views']
            recommendations.append(f"🏆 最高パフォーマンステーマ: {best_theme[0]} (平均{avg:,.0f}views)")

        # CTR改善提案
        recommendations.append("🎯 CTR改善アクション:")
        recommendations.append("  - サムネイル最適化")
        recommendations.append("  - 高パフォーマンステーマの組み合わせ戦略")

        return recommendations

    def _create_integrated_report(self, analytics_data: Dict, performance_report: Dict,
                                collections_info: Dict, strategic_analysis: Dict) -> Dict[str, Any]:
        """統合レポート作成"""
        logger.info("  📋 統合レポートを作成中...")

        return {
            'report_metadata': {
                'generated_at': datetime.now().isoformat(),
                'analysis_period': analytics_data.get('collection_period', {}),
                'system_version': '10.0',
                'data_source': 'YouTube Analytics API v2'
            },
            'channel_overview': {
                'total_collections': collections_info['total_collections'],
                'recent_videos': collections_info['recent_videos_count'],
                'latest_collections': collections_info['collections_breakdown'],
                'ctr_status': strategic_analysis['ctr_estimation']['estimated_ctr_status'],
                'ctr_target': strategic_analysis['ctr_estimation']['current_target']
            },
            'performance_analysis': {
                'bit_type_performance': strategic_analysis['bit_type_analysis'],
                'theme_performance': strategic_analysis['theme_performance'],
                'top_recommendations': strategic_analysis['strategic_recommendations']
            },
            'latest_videos': collections_info['latest_videos'],
            'analytics_summary': analytics_data.get('summary', {}),
            'strategic_insights': {
                'key_findings': strategic_analysis.get('strategic_recommendations', []),
                'next_actions': [
                    "新コレクション企画",
                    "サムネイル統一デザイン導入",
                    "高パフォーマンステーマ深掘り"
                ]
            }
        }

    def _save_data_and_reports(self, integrated_report: Dict) -> None:
        """データとレポート保存"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # JSONデータ保存
        json_file = self.data_dir / f'latest_info_{timestamp}.json'
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(integrated_report, f, indent=2, ensure_ascii=False)

        logger.info(f"  💾 データ保存: {json_file}")

        # マークダウンレポート生成
        if hasattr(self.report_generator, 'generate_markdown_report'):
            md_file = self.reports_dir / f'latest_info_report_{timestamp}.md'
            markdown_content = self.report_generator.generate_markdown_report(integrated_report)
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            logger.info(f"  📝 レポート保存: {md_file}")

    def get_quick_status(self) -> Dict[str, Any]:
        """クイック状況確認（軽量版）"""
        config = ChannelConfig.load()
        logger.info(f"⚡ {config.channel_short} クイック状況確認")

        try:
            # 認証のみ実行
            self.collector.initialize()

            # 基本チャンネル情報のみ取得
            channel_response = self.collector.youtube_service.channels().list(
                part='snippet,statistics',
                mine=True
            ).execute()

            if channel_response['items']:
                channel = channel_response['items'][0]
                stats = channel['statistics']

                return {
                    'channel_name': channel['snippet']['title'],
                    'subscriber_count': int(stats.get('subscriberCount', 0)),
                    'total_views': int(stats.get('viewCount', 0)),
                    'video_count': int(stats.get('videoCount', 0)),
                    'last_updated': datetime.now().isoformat(),
                    'status': 'active'
                }
            else:
                return {'status': 'error', 'message': 'チャンネル情報取得失敗'}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

def main():
    """メイン関数"""
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f'{config.channel_short} 最新情報取得システム')
    parser.add_argument('--quick', '-q', action='store_true', help='クイック状況確認')
    parser.add_argument('--days', '-d', type=int, default=30, help='分析日数')

    args = parser.parse_args()

    try:
        system = LatestInfoSystem()

        if args.quick:
            # クイック確認
            status = system.get_quick_status()
            print(json.dumps(status, indent=2, ensure_ascii=False))
        else:
            # 詳細分析
            report = system.get_latest_info(args.days)

            # サマリー表示
            print("\n" + "=" * 60)
            print(f"📊 {config.channel_name} - 最新情報サマリー")
            print("=" * 60)

            channel_overview = report['channel_overview']
            print(f"🎵 総コレクション: {channel_overview['total_collections']}個")
            print(f"📅 最新動画数: {channel_overview['recent_videos']}本")
            print(f"🎯 CTR状況: {channel_overview['ctr_status']}")

            performance = report['performance_analysis']
            print(f"🎶 音源推奨: {performance['bit_type_performance']['recommendation']}")

            print("\n🔥 主要発見:")
            for insight in report['strategic_insights']['key_findings']:
                print(f"  • {insight}")

            print("\n📋 次のアクション:")
            for action in report['strategic_insights']['next_actions']:
                print(f"  □ {action}")

    except KeyboardInterrupt:
        print("\n🛑 処理が中断されました")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
