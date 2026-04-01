#!/usr/bin/env python3
"""
自動レポート生成システム
YouTube Analytics データを基にした戦略的レポートを自動生成

Features:
- 週次・月次パフォーマンスレポート
- CTR改善戦略レポート
- コレクション推奨レポート
- HTML形式レポート出力
- JSON形式データエクスポート
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from .analytics_analyzer import AnalyticsAnalyzer
from .analytics_collector import YouTubeAnalyticsCollector
from .channel_config import ChannelConfig
from .report_renderer import render_html_report


class ReportGenerator:
    """自動レポート生成クラス"""

    def __init__(self, output_dir=None):
        """
        初期化

        Args:
            output_dir (str): レポート出力ディレクトリのパス
        """
        if output_dir is None:
            output_dir = ChannelConfig.channel_dir() / 'reports'
        else:
            output_dir = Path(output_dir)

        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)

        # 分析システム初期化
        self.collector = YouTubeAnalyticsCollector()
        self.analyzer = AnalyticsAnalyzer()

    def generate_weekly_report(self) -> Dict[str, Any]:
        """
        週次パフォーマンスレポート生成

        Returns:
            Dict: 週次レポートデータ
        """
        print("📅 週次レポート生成中...")

        # 過去7日間のデータ取得
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        # アナリティクスデータ収集
        analytics_data = self.collector.collect_comprehensive_analytics(
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d')
        )

        # 分析実行
        performance_report = self.analyzer.generate_performance_report(analytics_data)

        # 週次特有の分析
        weekly_insights = self._generate_weekly_insights(analytics_data)

        report = {
            'report_type': 'weekly',
            'period': {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'days': 7
            },
            'generated_at': datetime.now().isoformat(),
            'performance_summary': performance_report,
            'weekly_insights': weekly_insights,
            'action_items': self._generate_weekly_action_items(analytics_data, performance_report)
        }

        return report

    def generate_monthly_report(self) -> Dict[str, Any]:
        """
        月次戦略レポート生成

        Returns:
            Dict: 月次レポートデータ
        """
        print("📊 月次戦略レポート生成中...")

        # 過去30日間のデータ取得
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        # アナリティクスデータ収集
        analytics_data = self.collector.collect_comprehensive_analytics(
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d')
        )

        # 詳細分析実行
        performance_report = self.analyzer.generate_performance_report(analytics_data)
        ctr_strategy = self.analyzer.analyze_ctr_improvement_strategy(analytics_data)

        # 月次特有の戦略分析
        strategic_insights = self._generate_strategic_insights(analytics_data, ctr_strategy)
        collection_recommendations = self._generate_collection_recommendations(ctr_strategy)

        report = {
            'report_type': 'monthly_strategic',
            'period': {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'days': 30
            },
            'generated_at': datetime.now().isoformat(),
            'performance_summary': performance_report,
            'ctr_improvement_strategy': ctr_strategy,
            'strategic_insights': strategic_insights,
            'collection_recommendations': collection_recommendations,
            'strategic_action_plan': self._generate_strategic_action_plan(ctr_strategy)
        }

        return report

    def _generate_weekly_insights(self, analytics_data: Dict) -> Dict[str, Any]:
        """週次インサイト生成"""
        video_data = analytics_data.get('video_analytics', {})

        # 今週の動画パフォーマンス
        weekly_videos = []
        total_views = 0
        total_impressions = 0

        for video_id, data in video_data.items():
            views = data.get('views', 0)
            impressions = data.get('impressions', 0)
            ctr = data.get('click_through_rate', 0) * 100

            weekly_videos.append({
                'title': data.get('title', 'N/A'),
                'views': views,
                'ctr': ctr,
                'performance_score': views * (ctr / 100)  # 独自指標
            })

            total_views += views
            total_impressions += impressions

        # パフォーマンス順にソート
        weekly_videos.sort(key=lambda x: x['performance_score'], reverse=True)

        return {
            'total_videos_analyzed': len(weekly_videos),
            'total_views': total_views,
            'total_impressions': total_impressions,
            'average_ctr': (total_views / total_impressions * 100) if total_impressions > 0 else 0,
            'top_performing_video': weekly_videos[0] if weekly_videos else None,
            'performance_trend': '上昇' if total_views > 1000 else '安定',  # 簡易判定
            'engagement_quality': 'High' if len([v for v in weekly_videos if v['ctr'] > 1.0]) > 0 else 'Medium'
        }

    def _generate_strategic_insights(self, analytics_data: Dict, ctr_strategy: Dict) -> Dict[str, Any]:
        """戦略的インサイト生成 (月次用)"""
        config = ChannelConfig.load()

        # CTR改善への道筋分析
        current_ctr = ctr_strategy['summary']['current_ctr_percent']
        target_ctr = ctr_strategy['summary']['target_ctr_percent']
        improvement_needed = ctr_strategy['summary']['improvement_needed']

        # 最適戦略特定
        best_bit_type = ctr_strategy.get('bit_type_comparison', {}).get('strategy_recommendation', '8-bit')

        # テーマ戦略
        theme_analysis = ctr_strategy.get('theme_analysis', {})
        top_themes = sorted(theme_analysis.items(), key=lambda x: x[1]['average_ctr'], reverse=True)[:3]

        return {
            'ctr_improvement_roadmap': {
                'current_position': f"{current_ctr:.2f}%",
                'target_position': f"{target_ctr}%",
                'improvement_multiplier': f"{improvement_needed:.1f}x",
                'feasibility': (
                    'Achievable with strategic optimization'
                    if improvement_needed < 5
                    else 'Requires major strategy shift'
                )
            },
            'optimal_content_strategy': {
                'recommended_bit_type': best_bit_type,
                'top_performing_themes': [theme[0] for theme in top_themes],
                'focus_areas': [
                    f"{best_bit_type} 音源の強化",
                    f"高パフォーマンステーマ ({', '.join([t[0] for t in top_themes[:2]])}) の展開",
                    "midjourney-prompt-generator-agent によるサムネイル最適化"
                ]
            },
            'competitive_positioning': {
                'unique_strengths': [
                    f'{config.genre_context}特化{config.genre_primary}',
                    'コレクション完成度', '楽曲資産',
                ],
                'market_opportunity': 'CTR改善によるリーチ拡大 → 登録者数成長可能性',
                'differentiation_strategy': f'{config.channel_short}独自の世界観 + 高品質{config.genre_primary}'
            }
        }

    def _generate_collection_recommendations(self, ctr_strategy: Dict) -> Dict[str, Any]:
        """次期コレクション推奨生成"""

        # 高パフォーマンステーマ特定
        theme_analysis = ctr_strategy.get('theme_analysis', {})
        top_themes = sorted(theme_analysis.items(), key=lambda x: x[1]['average_ctr'], reverse=True)

        # bit type 推奨
        bit_comparison = ctr_strategy.get('bit_type_comparison', {})
        eight_bit_ctr = bit_comparison.get('8_bit', {}).get('average_ctr', 0)
        sixteen_bit_ctr = bit_comparison.get('16_bit', {}).get('average_ctr', 0)
        recommended_bit = '8-bit' if eight_bit_ctr > sixteen_bit_ctr else '16-bit'

        # 次期コレクション提案
        next_collections = []

        if top_themes:
            # トップテーマでの新コレクション
            top_theme = top_themes[0][0]
            next_collections.append({
                'title': f"{recommended_bit.title()} {top_theme.title()} Collection ver.3",
                'rationale': f"最高CTRテーマ ({top_theme}) + 推奨bit type ({recommended_bit})",
                'expected_ctr': f"{top_themes[0][1]['average_ctr'] * 1.2:.2f}%",  # 20%向上期待
                'priority': 'High'
            })

        # 未開拓テーマでの新規コレクション
        next_collections.append({
            'title': f"{recommended_bit.title()} Forest & Nature Collection",
            'rationale': "未開拓の自然テーマ + プロファイルされた推奨bit type",
            'expected_ctr': "1.2-1.8%",
            'priority': 'Medium'
        })

        return {
            'recommended_next_collections': next_collections,
            'optimization_focus': [
                f"{recommended_bit} 音源の継続使用",
                "高パフォーマンステーマの深掘り",
                "未開拓テーマへの戦略的展開"
            ],
            'production_schedule': {
                'immediate': next_collections[0] if next_collections else None,
                'next_month': next_collections[1] if len(next_collections) > 1 else None,
                'quarterly_target': '3-4 新規コレクション'
            }
        }

    def _generate_weekly_action_items(self, analytics_data: Dict, performance_report: Dict) -> List[str]:
        """週次アクションアイテム生成"""
        actions = []

        # CTRベースのアクション
        current_ctr = performance_report['channel_overview']['average_ctr']
        if current_ctr < 1.0:
            actions.append("🎯 サムネイル最適化 - midjourney-prompt-generator-agent使用")
            actions.append("📝 タイトル改善 - 高CTRコレクションのパターン分析")

        # 動画パフォーマンスベース
        video_count = performance_report['channel_overview']['total_videos']
        if video_count > 0:
            actions.append("📊 低パフォーマンス動画の分析と改善点特定")
            actions.append("🔄 高パフォーマンス要素の他動画への適用")

        actions.append("🎵 次期コレクション企画 - rpg-collection-research-agent活用")

        return actions

    def _generate_strategic_action_plan(self, ctr_strategy: Dict) -> Dict[str, List[str]]:
        """戦略的アクションプラン生成 (月次用)"""

        return {
            'immediate_actions': [
                "CTR 2.0%目標のための高パフォーマンス要素特定完了",
                "midjourney-prompt-generator-agent による次期サムネイル戦略策定",
                "最高CTRコレクションの成功要因詳細分析"
            ],
            'short_term_goals': [
                "8-bit vs 16-bit戦略の最適化完了",
                "高パフォーマンステーマでの新コレクション企画3件",
                "CTR 1.5%中間目標達成"
            ],
            'long_term_strategy': [
                "CTR 2.0%目標達成による登録者数大幅成長",
                "チャンネル独自ブランドの確立と差別化",
                "完全自動化ワークフローでの効率的コンテンツ生産"
            ]
        }

    def save_report_as_json(self, report_data: Dict, filename: str = None) -> str:
        """JSONファイルとしてレポート保存"""
        if filename is None:
            config = ChannelConfig.load()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{config.channel_short.lower()}_report_{report_data['report_type']}_{timestamp}.json"

        filepath = self.output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        print(f"💾 レポート保存完了: {filepath}")
        return str(filepath)

    def save_report_as_html(self, report_data: Dict, filename: str = None) -> str:
        """HTMLファイルとしてレポート保存"""
        if filename is None:
            config = ChannelConfig.load()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{config.channel_short.lower()}_report_{report_data['report_type']}_{timestamp}.html"

        html_content = self._generate_html_report(report_data)
        filepath = self.output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"📄 HTMLレポート保存完了: {filepath}")
        return str(filepath)

    def _generate_html_report(self, report_data: Dict) -> str:
        """HTML形式レポート生成"""
        return render_html_report(report_data)

    def run_automated_report_generation(self) -> Dict[str, str]:
        """自動レポート生成実行"""
        config = ChannelConfig.load()
        print(f"🚀 {config.channel_short}自動レポート生成システム開始...")

        results = {}

        try:
            # 週次レポート生成
            print("\n📅 週次レポート生成...")
            weekly_report = self.generate_weekly_report()
            weekly_json = self.save_report_as_json(weekly_report)
            weekly_html = self.save_report_as_html(weekly_report)

            results['weekly'] = {
                'json': weekly_json,
                'html': weekly_html
            }

            # 月次レポート生成
            print("\n📊 月次戦略レポート生成...")
            monthly_report = self.generate_monthly_report()
            monthly_json = self.save_report_as_json(monthly_report)
            monthly_html = self.save_report_as_html(monthly_report)

            results['monthly'] = {
                'json': monthly_json,
                'html': monthly_html
            }

            print("\n✅ 自動レポート生成完了！")
            print(f"📁 出力ディレクトリ: {self.output_dir}")

        except Exception as e:
            print(f"❌ レポート生成エラー: {e}")
            results['error'] = str(e)

        return results

def main():
    """メイン関数 - スタンドアロン実行用"""
    config = ChannelConfig.load()
    print(f"🎵 {config.channel_name} - 自動レポート生成システム")
    print("=" * 60)

    try:
        # レポートジェネレーター初期化
        report_generator = ReportGenerator()

        # 自動レポート生成実行
        results = report_generator.run_automated_report_generation()

        if 'error' not in results:
            print("\n🎉 レポート生成システム正常動作確認完了！")
            print("📊 週次・月次レポートが自動生成されました。")
        else:
            print(f"\n❌ エラーが発生: {results['error']}")

    except Exception as e:
        print(f"\n❌ システムエラー: {e}")

if __name__ == "__main__":
    main()
