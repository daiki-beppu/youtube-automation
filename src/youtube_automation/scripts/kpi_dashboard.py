#!/usr/bin/env python3
"""yt-kpi-dashboard: 成長 KPI 定点ビュー（スナップショット横断の週次推移）CLI

data/analytics_data_*.json 群を時系列に読み、レバー別 KPI（views / Imp / CTR /
平均視聴維持率 / 登録者純増）の週次推移テーブルを前週比付きで出力する。
Reporting API の保持期間（60 日）を超えた過去の Imp / CTR もスナップショットに
残っていれば時系列に含める。

デフォルトは構造化 JSON を stdout へ。--markdown で Markdown レポートを stdout へ。
--save で reports/kpi_weekly_YYYYMMDD.json / .md の両方を保存する。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from youtube_automation.configuration import channel_dir as _channel_dir
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.kpi_dashboard import analyze_kpi_dashboard, render_markdown

logger = logging.getLogger(__name__)


def _load_snapshots(channel_dir: Path) -> List[Dict]:
    """data/analytics_data_*.json を古い順にすべて読み込む。

    ファイル名がタイムスタンプ形式のため辞書順ソート = 時系列順。
    パース不能なファイルは warning を出してスキップする（横断集計を止めない）。
    """
    snapshots: List[Dict] = []
    for path in sorted((channel_dir / "data").glob("analytics_data_*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                snapshots.append(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"スナップショットを読めないためスキップ: {path.name} ({e})")
    return snapshots


def _save_reports(channel_dir: Path, analysis: Dict, markdown: str) -> List[Path]:
    reports_dir = channel_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    json_path = reports_dir / f"kpi_weekly_{stamp}.json"
    md_path = reports_dir / f"kpi_weekly_{stamp}.md"
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return [json_path, md_path]


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="成長 KPI 定点ビュー（スナップショット横断のレバー別週次推移）")
    parser.add_argument("--markdown", action="store_true", help="Markdown レポートを stdout へ出力")
    parser.add_argument(
        "--save",
        action="store_true",
        help="reports/kpi_weekly_YYYYMMDD.json と .md を保存する",
    )
    args = parser.parse_args()

    try:
        channel_dir = _channel_dir()
        snapshots = _load_snapshots(channel_dir)
        analysis = analyze_kpi_dashboard(snapshots)
        markdown = render_markdown(analysis)

        if args.save:
            for path in _save_reports(channel_dir, analysis, markdown):
                logger.warning(f"保存しました: {path}")

        if args.markdown:
            print(markdown, end="")
        else:
            print(json.dumps(analysis, ensure_ascii=False, indent=2))
        return 0

    except ConfigError as e:
        logger.error(str(e))
        return 2
    except Exception as e:
        logger.exception(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
