"""Gemini で YouTube 動画を直接解析するユーティリティ。

Issue #103 で追加: ベンチマーク競合・自チャンネル動画・任意 URL を Gemini に
直接渡し、`hook_structure` / `bgm_arc` / `scene_timeline` / `thumbnail_alignment`
/ `editing_metrics` を含む構造化 JSON を得る。

責務分割:
- `VideoTarget`        : 解析対象 1 件分の入力データ (CLI 層で構築)
- `VideoAnalyzer`      : Gemini 呼出 + JSON パース + ファイル保存
- `VideoAnalysisReport`: 解析結果を slug 単位で Markdown 集約

Gemini Client は外部から DI する (テスト容易性 + 認証戦略の分裂回避)。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from youtube_automation.utils.exceptions import ValidationError

logger = logging.getLogger(__name__)

# data_dir / reports_dir 配下に切るサブディレクトリ名
VIDEO_ANALYSIS_DIRNAME = "video_analysis"

# Gemini レスポンスのコードフェンス除去用 (benchmark_collector.py:561-563 と同方式)
_CODE_FENCE_HEAD = re.compile(r"^```(?:json)?\s*")
_CODE_FENCE_TAIL = re.compile(r"\s*```$")

# Gemini に渡す YouTube URL Part の MIME type
_VIDEO_MIME_TYPE = "video/*"


@dataclass(frozen=True)
class VideoTarget:
    """解析対象 1 件分の入力データ。

    benchmark / own / url の 3 経路で CLI 層が組み立て、analyzer に渡す。
    """

    video_id: str
    slug: str
    url: str
    title: str


class VideoAnalyzer:
    """Gemini に YouTube URL を直接渡して構造化 JSON を得る。

    `client` / `model` / `prompt` / `delay_sec` / `data_dir` /
    `analysis_window_sec` は CLI 層 (境界) で 1 度だけ解決して渡す。
    analyze_url ループ内で再解決しない。
    """

    def __init__(
        self,
        *,
        client: genai.Client,
        model: str,
        prompt: str,
        delay_sec: int,
        data_dir: Path,
        analysis_window_sec: int,
    ) -> None:
        self.client = client
        self.model = model
        self.prompt = prompt
        self.delay_sec = delay_sec
        self.data_dir = data_dir
        self.analysis_window_sec = analysis_window_sec

    def analyze_url(self, target: VideoTarget) -> dict[str, Any]:
        """target.url の冒頭 `analysis_window_sec` 秒を Gemini に渡し、JSON をパースして返す。

        `types.Part.from_uri()` は `video_metadata` を受け取れないため、
        `types.Part(file_data=..., video_metadata=...)` で offset 付き Part を組み立てる。

        Raises:
            ValidationError: Gemini レスポンスが JSON にパースできない場合
        """
        logger.info(
            "Gemini 動画解析 (冒頭 %d 秒): %s (%s)",
            self.analysis_window_sec,
            target.title[:40],
            target.video_id,
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=[
                types.Part(
                    file_data=types.FileData(file_uri=target.url, mime_type=_VIDEO_MIME_TYPE),
                    video_metadata=types.VideoMetadata(
                        start_offset="0s",
                        end_offset=f"{self.analysis_window_sec}s",
                    ),
                ),
                self.prompt,
            ],
        )
        payload = _parse_json_response(response.text)
        time.sleep(self.delay_sec)
        return _attach_metadata(
            payload,
            target=target,
            model=self.model,
            analysis_window_sec=self.analysis_window_sec,
        )

    def save_json(self, target: VideoTarget, payload: dict[str, Any]) -> Path:
        """`data_dir/video_analysis/<slug>/<video_id>.json` に書き出す。"""
        out_dir = self.data_dir / VIDEO_ANALYSIS_DIRNAME / target.slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{target.video_id}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("動画分析 JSON 保存: %s", out_path)
        return out_path


def _parse_json_response(text: str) -> dict[str, Any]:
    """Gemini レスポンス文字列からコードフェンスを剥がし JSON にパースする。"""
    stripped = text.strip()
    stripped = _CODE_FENCE_HEAD.sub("", stripped)
    stripped = _CODE_FENCE_TAIL.sub("", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as err:
        # 握りつぶさず ValidationError へ昇格 (Fail Fast)
        raise ValidationError(f"Gemini レスポンスの JSON パースに失敗: {err}") from err


def _attach_metadata(
    payload: dict[str, Any],
    *,
    target: VideoTarget,
    model: str,
    analysis_window_sec: int,
) -> dict[str, Any]:
    """ドメインキーは payload を保ち、メタデータは target で上書きする (envelope)。"""
    return {
        **payload,
        "video_id": target.video_id,
        "slug": target.slug,
        "url": target.url,
        "title": target.title,
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "analysis_window_sec": analysis_window_sec,
        "analysis_scope": {
            "start_offset_sec": 0,
            "end_offset_sec": analysis_window_sec,
            "description": "opening clip window",
        },
    }


class VideoAnalysisReport:
    """slug 単位の Markdown 集約レポート。"""

    @staticmethod
    def render(*, slug: str, results: list[dict[str, Any]], failures: list[dict[str, Any]]) -> str:
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


def _render_video_section(result: dict[str, Any]) -> list[str]:
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
