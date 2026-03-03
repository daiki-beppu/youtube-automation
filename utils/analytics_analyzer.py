#!/usr/bin/env python3
"""
8-Bit Adventure Hub (8BAH) - アナリティクス分析システム
YouTube Analytics APIで収集したデータを8BAH特化で分析する機能

Functions:
- CTR改善戦略分析 (現在の0.58% → 目標2.0%+)
- コレクション別パフォーマンス比較
- 8-bit vs 16-bit音源効果分析
- 投稿タイミング最適化
- サムネイル効果測定
"""

import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .channel_config import ChannelConfig


class EightBAHAnalyzer:
    """チャンネル専用アナリティクス分析クラス"""

    def __init__(self, data_dir=None):
        """
        初期化

        Args:
            data_dir (str): データディレクトリのパス
        """
        if data_dir is None:
            data_dir = ChannelConfig.channel_dir() / 'data' / 'analytics'
        else:
            data_dir = Path(data_dir)

        self.data_dir = data_dir
        self.config = ChannelConfig.load()
        self.collections_metadata = self._load_collections_metadata()

    def _load_collections_metadata(self):
        """channel_config.json のテーマ情報からメタデータを構築"""
        return {
            'themes': self.config.theme_tags
        }

    def analyze_ctr_improvement_strategy(self, analytics_data: Dict) -> Dict[str, Any]:
        """
        CTR改善戦略分析 (0.58% → 2.0%目標)

        Args:
            analytics_data: analytics_collector.pyから取得したデータ

        Returns:
            Dict: CTR改善戦略レポート
        """
        print("🎯 CTR改善戦略分析を実行中...")

        # 現在のCTR分析
        current_ctr = analytics_data.get('channel_ctr', {}).get('average_ctr', 0)
        target_ctr = 2.0
        improvement_ratio = target_ctr / (current_ctr * 100) if current_ctr > 0 else 0

        # コレクション別CTR比較
        collection_ctrs = self._analyze_collection_ctrs(analytics_data)

        # 8-bit vs 16-bit CTR比較
        bit_comparison = self._analyze_bit_type_performance(analytics_data)

        # テーマ別CTR分析
        theme_analysis = self._analyze_theme_performance(analytics_data)

        # サムネイル効果分析
        thumbnail_analysis = self._analyze_thumbnail_effectiveness(analytics_data)

        return {
            'summary': {
                'current_ctr_percent': current_ctr * 100,
                'target_ctr_percent': target_ctr,
                'improvement_needed': improvement_ratio,
                'gap_analysis': f"{improvement_ratio:.1f}x improvement required"
            },
            'collection_performance': collection_ctrs,
            'bit_type_comparison': bit_comparison,
            'theme_analysis': theme_analysis,
            'thumbnail_effectiveness': thumbnail_analysis,
            'recommendations': self._generate_ctr_recommendations(
                collection_ctrs, bit_comparison, theme_analysis
            )
        }

    def _analyze_collection_ctrs(self, analytics_data: Dict) -> Dict[str, Any]:
        """コレクション別CTR分析"""
        video_data = analytics_data.get('video_analytics', {})

        collection_ctrs = {}
        for video_id, data in video_data.items():
            title = data.get('title', '')
            ctr = data.get('click_through_rate', 0)

            # タイトルからコレクション名を推定
            collection_name = self._extract_collection_name(title)
            if collection_name:
                if collection_name not in collection_ctrs:
                    collection_ctrs[collection_name] = []
                collection_ctrs[collection_name].append(ctr * 100)

        # 統計計算
        collection_stats = {}
        for collection, ctrs in collection_ctrs.items():
            if ctrs:
                collection_stats[collection] = {
                    'average_ctr': statistics.mean(ctrs),
                    'max_ctr': max(ctrs),
                    'min_ctr': min(ctrs),
                    'video_count': len(ctrs),
                    'consistency': statistics.stdev(ctrs) if len(ctrs) > 1 else 0
                }

        return collection_stats

    def _analyze_bit_type_performance(self, analytics_data: Dict) -> Dict[str, Any]:
        """8-bit vs 16-bit パフォーマンス比較"""
        video_data = analytics_data.get('video_analytics', {})

        bit_8_ctrs = []
        bit_16_ctrs = []

        for video_id, data in video_data.items():
            title = data.get('title', '')
            ctr = data.get('click_through_rate', 0) * 100

            if '8-bit' in title.lower() or '8-Bit' in title:
                bit_8_ctrs.append(ctr)
            elif '16-bit' in title.lower() or '16-Bit' in title:
                bit_16_ctrs.append(ctr)

        return {
            '8_bit': {
                'average_ctr': statistics.mean(bit_8_ctrs) if bit_8_ctrs else 0,
                'video_count': len(bit_8_ctrs),
                'max_ctr': max(bit_8_ctrs) if bit_8_ctrs else 0
            },
            '16_bit': {
                'average_ctr': statistics.mean(bit_16_ctrs) if bit_16_ctrs else 0,
                'video_count': len(bit_16_ctrs),
                'max_ctr': max(bit_16_ctrs) if bit_16_ctrs else 0
            },
            'strategy_recommendation':
                '8-bit dominant' if (statistics.mean(bit_8_ctrs) if bit_8_ctrs else 0) >
                                  (statistics.mean(bit_16_ctrs) if bit_16_ctrs else 0)
                else '16-bit focus'
        }

    def _analyze_theme_performance(self, analytics_data: Dict) -> Dict[str, Any]:
        """テーマ別パフォーマンス分析（channel_config.json のテーマキーワードを使用）"""
        video_data = analytics_data.get('video_analytics', {})
        theme_performance = {}

        for theme, tag_keywords in self.collections_metadata['themes'].items():
            theme_ctrs = []
            # テーマ名自体 + タグ内のキーワードで検索
            search_keywords = [theme] + [kw.replace(' music', '').replace(' Music', '') for kw in tag_keywords]

            for video_id, data in video_data.items():
                title = data.get('title', '')
                ctr = data.get('click_through_rate', 0) * 100

                if any(keyword.lower() in title.lower() for keyword in search_keywords):
                    theme_ctrs.append(ctr)

            if theme_ctrs:
                theme_performance[theme] = {
                    'average_ctr': statistics.mean(theme_ctrs),
                    'video_count': len(theme_ctrs),
                    'max_ctr': max(theme_ctrs)
                }

        return theme_performance

    def _analyze_thumbnail_effectiveness(self, analytics_data: Dict) -> Dict[str, Any]:
        """サムネイル効果分析 (CTR基準)"""
        video_data = analytics_data.get('video_analytics', {})

        # CTRによる分類
        high_ctr_videos = []  # 1.5%以上
        medium_ctr_videos = []  # 0.8-1.5%
        low_ctr_videos = []  # 0.8%未満

        for video_id, data in video_data.items():
            ctr = data.get('click_through_rate', 0) * 100
            title = data.get('title', '')

            video_info = {'title': title, 'ctr': ctr, 'video_id': video_id}

            if ctr >= 1.5:
                high_ctr_videos.append(video_info)
            elif ctr >= 0.8:
                medium_ctr_videos.append(video_info)
            else:
                low_ctr_videos.append(video_info)

        return {
            'high_performance': {
                'count': len(high_ctr_videos),
                'videos': high_ctr_videos[:5],  # トップ5
                'average_ctr': statistics.mean([v['ctr'] for v in high_ctr_videos]) if high_ctr_videos else 0
            },
            'medium_performance': {
                'count': len(medium_ctr_videos),
                'average_ctr': statistics.mean([v['ctr'] for v in medium_ctr_videos]) if medium_ctr_videos else 0
            },
            'low_performance': {
                'count': len(low_ctr_videos),
                'videos': low_ctr_videos[-5:],  # ワースト5
                'average_ctr': statistics.mean([v['ctr'] for v in low_ctr_videos]) if low_ctr_videos else 0
            }
        }

    def _generate_ctr_recommendations(self, collection_ctrs: Dict, bit_comparison: Dict, theme_analysis: Dict) -> List[str]:
        """CTR改善提案生成"""
        recommendations = []

        # 最高パフォーマンスコレクション特定
        if collection_ctrs:
            best_collection = max(collection_ctrs.items(), key=lambda x: x[1]['average_ctr'])
            recommendations.append(
                f"🏆 最高CTRコレクション: {best_collection[0]} ({best_collection[1]['average_ctr']:.2f}%)"
            )

        # bit type推奨
        if bit_comparison['8_bit']['average_ctr'] > bit_comparison['16_bit']['average_ctr']:
            recommendations.append("🎵 8-bit音源がCTR向上に効果的 - 8-bit中心戦略を継続")
        else:
            recommendations.append("🎵 16-bit音源の効果が高い - 16-bitコレクション増産検討")

        # テーマ別推奨
        if theme_analysis:
            best_theme = max(theme_analysis.items(), key=lambda x: x[1]['average_ctr'])
            recommendations.append(
                f"🎯 高パフォーマンステーマ: {best_theme[0]} ({best_theme[1]['average_ctr']:.2f}%)"
            )

        # CTRギャップ分析
        recommendations.append("📈 目標2.0%達成のため、高パフォーマンス要素の組み合わせを実施")

        return recommendations

    def _extract_collection_name(self, title: str) -> str:
        """タイトルからコレクション名抽出（テーマキーワードベース）"""
        title_lower = title.lower()
        for theme in self.collections_metadata['themes']:
            if theme in title_lower:
                return theme.title()
        return None

    def generate_performance_report(self, analytics_data: Dict) -> Dict[str, Any]:
        """総合パフォーマンスレポート生成"""
        print(f"📊 {self.config.channel_short}総合パフォーマンスレポート生成中...")

        ctr_analysis = self.analyze_ctr_improvement_strategy(analytics_data)

        # チャンネル基本統計
        channel_stats = analytics_data.get('channel_analytics', {})

        report = {
            'generated_at': datetime.now().isoformat(),
            'channel_overview': {
                'total_videos': len(analytics_data.get('video_analytics', {})),
                'subscriber_count': channel_stats.get('subscriber_count', 'N/A'),
                'total_views': channel_stats.get('total_views', 'N/A'),
                'average_ctr': channel_stats.get('average_ctr', 0) * 100
            },
            'ctr_strategy': ctr_analysis,
            'collection_summary': {
                'total_collections': len(analytics_data.get('video_analytics', {})),
                'genre_style': self.config.genre_style,
            },
            'next_actions': [
                "CTR 2.0%目標達成のための高パフォーマンス要素特定",
                f"{self.config.genre_style}優位性を活かした新コレクション企画",
                "高CTRテーマの深掘り戦略実行",
                "サムネイル最適化"
            ]
        }

        return report

def main():
    """メイン関数 - スタンドアロン実行用"""
    config = ChannelConfig.load()
    print(f"🎵 {config.channel_name} - アナリティクス分析システム")
    print("=" * 60)

    # サンプルデータでテスト
    analyzer = EightBAHAnalyzer()

    # 実際の分析データが必要な場合はanalytics_collectorから取得
    sample_data = {
        'channel_analytics': {
            'subscriber_count': 80,
            'total_views': 10000,
            'average_ctr': 0.0058
        },
        'video_analytics': {},
        'channel_ctr': {
            'average_ctr': 0.0058
        }
    }

    report = analyzer.generate_performance_report(sample_data)

    print("\n📊 分析完了")
    print(f"平均CTR: {report['channel_overview']['average_ctr']:.2f}%")
    print(f"目標CTR: 2.0% (改善倍率: {2.0 / report['channel_overview']['average_ctr']:.1f}x)")

if __name__ == "__main__":
    main()
