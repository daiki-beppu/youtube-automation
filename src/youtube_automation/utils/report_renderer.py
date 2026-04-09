"""
HTML レポートレンダリング
ReportGenerator が生成したデータを HTML 形式に変換する
"""

from datetime import datetime
from typing import Any, Dict

from .channel_config import ChannelConfig


def render_html_report(report_data: Dict[str, Any]) -> str:
    """レポートデータを HTML 形式に変換"""
    config = ChannelConfig.load()
    report_type = report_data.get('report_type', 'unknown')
    generated_at = report_data.get('generated_at', datetime.now().isoformat())

    channel_overview = report_data.get('performance_summary', {}).get('channel_overview', {})

    report_type_ja = {
        'weekly': '週次レポート',
        'monthly_strategic': '月次戦略レポート',
        'monthly': '月次レポート'
    }.get(report_type, report_type)

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{config.channel_name} - {report_type_ja}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif,
                'Hiragino Sans', 'Yu Gothic', 'Meiryo';
            margin: 0; padding: 20px; background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px; margin: 0 auto; background: white;
            padding: 30px; border-radius: 10px;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
        }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .header h1 {{ color: #2c3e50; margin-bottom: 10px; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px; margin-bottom: 30px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 20px; border-radius: 8px;
            text-align: center;
        }}
        .stat-value {{ font-size: 2em; font-weight: bold; margin-bottom: 5px; }}
        .section {{ margin-bottom: 30px; }}
        .section h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        .recommendations {{ background: #e8f6f3; padding: 20px; border-radius: 8px; border-left: 4px solid #1abc9c; }}
        .action-items {{ background: #fef9e7; padding: 20px; border-radius: 8px; border-left: 4px solid #f39c12; }}
        .footer {{ text-align: center; margin-top: 40px; color: #7f8c8d; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{config.channel_name}</h1>
            <h2>{report_type_ja}</h2>
            <p>{generated_at}</p>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{channel_overview.get('total_videos', 'N/A')}</div>
                <div>総動画数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{channel_overview.get('subscriber_count', 'N/A')}</div>
                <div>登録者数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{channel_overview.get('average_ctr', 0):.2f}%</div>
                <div>平均CTR</div>
            </div>
        </div>"""

    # CTR 戦略セクション（月次レポートの場合）
    if 'ctr_improvement_strategy' in report_data:
        ctr_strategy = report_data['ctr_improvement_strategy']
        recommendations = ctr_strategy.get('recommendations', [])

        html += f"""
        <div class="section">
            <h2>CTR改善戦略</h2>
            <p><strong>現在のCTR:</strong> {ctr_strategy['summary']['current_ctr_percent']:.2f}%</p>
            <p><strong>目標CTR:</strong> {ctr_strategy['summary']['target_ctr_percent']}%</p>
            <p><strong>改善必要度:</strong> {ctr_strategy['summary']['gap_analysis']}</p>
        </div>
        <div class="recommendations">
            <h3>主要推奨事項</h3>
            <ul>"""

        for rec in recommendations:
            html += f"\n                <li>{rec}</li>"

        html += """
            </ul>
        </div>"""

    # アクションアイテム
    if 'action_items' in report_data:
        html += """
        <div class="action-items">
            <h3>アクションアイテム</h3>
            <ul>"""
        for action in report_data['action_items']:
            html += f"\n                <li>{action}</li>"
        html += """
            </ul>
        </div>"""

    html += f"""
        <div class="footer">
            <p>{config.channel_name} アナリティクスシステムにより生成</p>
        </div>
    </div>
</body>
</html>"""

    return html
