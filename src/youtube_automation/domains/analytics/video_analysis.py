"""Provider-independent video analysis inputs, storage naming, and report formatting."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Preserve the logger observed by existing report consumers.
logger = logging.getLogger("youtube_automation.infrastructure.media.video_analyzer")
VIDEO_ANALYSIS_DIRNAME = "video_analysis"


@dataclass(frozen=True)
class VideoTarget:
    """解析対象 1 件分の入力データ。

    benchmark / own / url の 3 経路で CLI 層が組み立て、analyzer に渡す。
    """

    video_id: str
    slug: str
    url: str
    title: str


class VideoAnalysisReport:
    """slug 単位の監査レポート owner（legacy Markdown render は互換用）。"""

    @staticmethod
    def render(*, slug: str, results: list[dict[str, object]], failures: list[dict[str, object]]) -> str:
        """成功 results と失敗 failures を 1 つの Markdown にまとめる。"""
        lines: list[str] = [f"# 動画分析レポート — {slug}", ""]
        lines.append(f"対象: **{slug}** / 成功 {len(results)} 件 / 失敗 {len(failures)} 件")
        lines.append("")

        if results:
            lines.append("## 動画別サマリー")
            lines.append("")
            for r in results:
                lines.extend(_render_video_section(r))

        if failures:
            lines.append("## 失敗した動画")
            lines.append("")
            lines.append(f"全 {len(results) + len(failures)} 件中 {len(failures)} 件が失敗しました。")
            lines.append("")
            lines.append("| video_id | URL | エラー |")
            lines.append("|---|---|---|")
            for f in failures:
                vid = f.get("video_id", "")
                url = f.get("url", "")
                err = str(f.get("error", "")).replace("|", "\\|")
                lines.append(f"| {vid} | {url} | {err} |")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def write(*, reports_dir: Path, slug: str, content: str) -> Path:
        """`reports_dir/video_analysis/<slug>.md` に書き出す。"""
        out_dir = reports_dir / VIDEO_ANALYSIS_DIRNAME
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slug}.md"
        out_path.write_text(content, encoding="utf-8")
        logger.info("動画分析レポート保存: %s", out_path)
        return out_path

    @staticmethod
    def document(
        *, slug: str, results: list[dict[str, object]], failures: list[dict[str, object]]
    ) -> dict[str, object]:
        """解析結果を audit report schema の固定 matrix へ写像する。"""
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        matrix = [
            {
                "check": str(result.get("video_id") or result.get("title") or "video"),
                "status": "PASS",
                "evidence": [
                    str(result.get("url") or "local video analysis"),
                    f"analysis_window_sec={result.get('analysis_window_sec', 'unknown')}",
                ],
                "next_action": None,
            }
            for result in results
        ]
        matrix.extend(
            {
                "check": str(failure.get("video_id") or "video"),
                "status": "FAIL",
                "evidence": [str(failure.get("error") or "analysis failed")],
                "next_action": "入力とAPI状態を確認して /audit --video を再実行",
            }
            for failure in failures
        )
        if not matrix:
            matrix.append(
                {
                    "check": "video analysis target",
                    "status": "WARN",
                    "evidence": ["解析対象が0件"],
                    "next_action": "公開済み動画を確認",
                }
            )
        status = "FAIL" if failures else ("PASS" if results else "WARN")
        return {
            "schema_version": 1,
            "generated_at": generated_at,
            "audit_type": "video",
            "subject": slug,
            "status": status,
            "summary": f"成功 {len(results)} 件 / 失敗 {len(failures)} 件",
            "matrix": matrix,
            "recommended_actions": (["失敗動画を再解析"] if failures else []),
            "results": results,
            "failures": failures,
        }


def _render_video_section(result: dict[str, object]) -> list[str]:
    """1 動画分の Markdown ブロックを生成する。"""
    video_id = result.get("video_id", "")
    title = result.get("title", "")
    url = result.get("url", "")
    analyzed_at = result.get("analyzed_at", "")
    analysis_window_sec = result.get("analysis_window_sec", "")

    block: list[str] = [
        f"### {title} ({video_id})",
        "",
        f"- URL: {url}",
        f"- analyzed_at: {analyzed_at}",
        f"- model: {result.get('model', '')}",
        f"- analysis_window_sec: {analysis_window_sec}",
        "",
        "**Hook (`hook_structure`)**",
        "",
        f"```json\n{json.dumps(result.get('hook_structure', {}), ensure_ascii=False, indent=2)}\n```",
        "",
        "**BGM (`bgm_arc`)**",
        "",
        f"```json\n{json.dumps(result.get('bgm_arc', {}), ensure_ascii=False, indent=2)}\n```",
        "",
        "**Scene timeline (`scene_timeline`)**",
        "",
        f"```json\n{json.dumps(result.get('scene_timeline', []), ensure_ascii=False, indent=2)}\n```",
        "",
        "**Thumbnail alignment (`thumbnail_alignment`)**",
        "",
        f"```json\n{json.dumps(result.get('thumbnail_alignment', {}), ensure_ascii=False, indent=2)}\n```",
        "",
        "**Editing metrics (`editing_metrics`)**",
        "",
        f"```json\n{json.dumps(result.get('editing_metrics', {}), ensure_ascii=False, indent=2)}\n```",
        "",
        "**Suno preset (`suno_preset`)**",
        "",
        f"```json\n{json.dumps(result.get('suno_preset', {}), ensure_ascii=False, indent=2)}\n```",
        "",
    ]
    return block
