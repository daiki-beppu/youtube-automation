"""Gemini で YouTube 動画を直接解析するユーティリティ。

Issue #103 で追加: ベンチマーク競合・自チャンネル動画・任意 URL を Gemini に
直接渡し、`hook_structure` / `bgm_arc` / `scene_timeline` / `thumbnail_alignment`
/ `editing_metrics` を含む構造化 JSON を得る。

責務分割:
- `VideoTarget`        : 解析対象 1 件分の入力データ (CLI 層で構築)
- `VideoAnalyzer`      : Gemini 呼出 + JSON パース + ファイル保存
- `VideoAnalysisReport`: 解析結果を slug 単位の監査 JSON+HTML へ集約

Gemini Client は外部から DI する (テスト容易性 + 認証戦略の分裂回避)。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.analytics.video_analysis import VIDEO_ANALYSIS_DIRNAME, VideoTarget
from youtube_automation.domains.analytics.video_analysis import VideoAnalysisReport as VideoAnalysisReport

logger = logging.getLogger(__name__)


# Gemini レスポンスのコードフェンス除去用 (benchmark_collector.py:561-563 と同方式)
_CODE_FENCE_HEAD = re.compile(r"^```(?:json)?\s*")
_CODE_FENCE_TAIL = re.compile(r"\s*```$")

# Gemini に渡す YouTube URL Part の MIME type
_VIDEO_MIME_TYPE = "video/*"


def _build_video_part(url: str, *, processing: str, analysis_window_sec: int) -> types.Part:
    """Encode the mutually exclusive static window and agentic processing options."""
    file_data = types.FileData(file_uri=url, mime_type=_VIDEO_MIME_TYPE)
    if processing == "agentic":
        video_part = types.Part(
            file_data=file_data,
            media_processing=types.MediaProcessing.AGENTIC,
        )
    else:
        video_part = types.Part(
            file_data=file_data,
            video_metadata=types.VideoMetadata(
                start_offset="0s",
                end_offset=f"{analysis_window_sec}s",
            ),
        )
    return video_part


class VideoAnalyzer:
    """Gemini に YouTube URL を直接渡して構造化 JSON を得る。

    `client` / `model` / `prompt` / `delay_sec` / `data_dir` /
    `analysis_window_sec` / `processing` は CLI 層 (境界) で 1 度だけ解決して渡す。
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
        processing: str = "static",
    ) -> None:
        self.client = client
        self.model = model
        self.prompt = prompt
        self.delay_sec = delay_sec
        self.data_dir = data_dir
        self.analysis_window_sec = analysis_window_sec
        self.processing = processing

    def analyze_url(self, target: VideoTarget) -> dict[str, Any]:
        """処理モードに従って target.url を Gemini に渡し、JSON をパースして返す。

        static は offset 付き `video_metadata`、agentic は窓なしの
        `media_processing=AGENTIC` を排他的に Part へ設定する。

        Raises:
            ValidationError: Gemini レスポンスが JSON にパースできない場合
        """
        logger.info("Gemini 動画解析 (%s): %s (%s)", self.processing, target.title[:40], target.video_id)
        video_part = _build_video_part(
            target.url, processing=self.processing, analysis_window_sec=self.analysis_window_sec
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=[
                video_part,
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
            processing=self.processing,
        )

    def json_path(self, target: VideoTarget) -> Path:
        """解析結果 JSON の保存先 `data_dir/video_analysis/<slug>/<video_id>.json` を返す。"""
        return self.data_dir / VIDEO_ANALYSIS_DIRNAME / target.slug / f"{target.video_id}.json"

    def load_cached_json(self, target: VideoTarget) -> dict | None:
        """既存の解析結果 JSON を読み込む。有効な結果がなければ None を返す。

        再実行時の Gemini 再課金を防ぐキャッシュ判定 (#1693)。以下はすべて
        「キャッシュなし」として None を返し、呼び出し側で再解析させる:

        - ファイルが存在しない
        - JSON としてパースできない (部分書き込み等の破損)
        - パース結果が dict でない (null / 配列など。壊れた結果のサイレント再利用を防ぐ)
        """
        cache_path = self.json_path(target)
        if not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            logger.warning("既存の解析 JSON が破損しているため再解析します: %s (%s)", cache_path, err)
            return None
        if not isinstance(payload, dict):
            logger.warning(
                "既存の解析 JSON が object ではないため再解析します: %s (type=%s)",
                cache_path,
                type(payload).__name__,
            )
            return None
        return payload

    def save_json(self, target: VideoTarget, payload: dict[str, Any]) -> Path:
        """`data_dir/video_analysis/<slug>/<video_id>.json` に書き出す。"""
        out_path = self.json_path(target)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("動画分析 JSON 保存: %s", out_path)
        return out_path


def _parse_json_response(text: str) -> dict[str, Any]:
    """Gemini レスポンス文字列からコードフェンスを剥がし JSON にパースする。"""
    stripped = text.strip()
    stripped = _CODE_FENCE_HEAD.sub("", stripped)
    stripped = _CODE_FENCE_TAIL.sub("", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as err:
        # 握りつぶさず ValidationError へ昇格 (Fail Fast)
        raise ValidationError(f"Gemini レスポンスの JSON パースに失敗: {err}") from err
    if not isinstance(payload, dict):
        raise ValidationError(
            f"Gemini レスポンスは JSON object である必要があります (received: {type(payload).__name__})"
        )
    return payload


def _attach_metadata(
    payload: dict[str, Any],
    *,
    target: VideoTarget,
    model: str,
    analysis_window_sec: int,
    processing: str = "static",
) -> dict[str, Any]:
    """ドメインキーは payload を保ち、メタデータは target で上書きする (envelope)。

    agentic は窓を渡さずに解析するため、窓由来のキーは `null` にして全尺スコープを名乗る。
    """
    is_static = processing == "static"
    return {
        **payload,
        "video_id": target.video_id,
        "slug": target.slug,
        "url": target.url,
        "title": target.title,
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "analysis_window_sec": analysis_window_sec if is_static else None,
        "analysis_scope": {
            "start_offset_sec": 0 if is_static else None,
            "end_offset_sec": analysis_window_sec if is_static else None,
            "description": "opening clip window" if is_static else "full video (agentic processing)",
        },
    }
