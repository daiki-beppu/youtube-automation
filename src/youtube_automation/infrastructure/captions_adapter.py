"""YouTube Data API adapter for caption track updates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from youtube_automation.utils.cost_tracker import log_quota
from youtube_automation.utils.exceptions import ValidationError, YouTubeAPIError

ExistingPolicy = Literal["ask", "update", "skip"]


@dataclass(frozen=True)
class CaptionUploadResult:
    action: Literal["inserted", "updated", "skipped"]
    caption_id: str | None


def _list_language_captions(youtube, *, video_id: str, language: str) -> list[dict]:
    try:
        response = youtube.captions().list(part="snippet", videoId=video_id).execute()
    except HttpError as exc:
        log_quota(
            "youtube-data-api",
            "captions.list",
            50,
            metadata={"video_id": video_id, "language": language, "error": True},
        )
        raise YouTubeAPIError.from_http_error(exc, f"captions.list (video_id={video_id})") from exc
    log_quota("youtube-data-api", "captions.list", 50, metadata={"video_id": video_id, "language": language})
    return [item for item in response.get("items", []) if item.get("snippet", {}).get("language") == language]


def upload_caption(
    youtube,
    *,
    video_id: str,
    language: str,
    name: str,
    srt_path: Path,
    existing_policy: ExistingPolicy = "ask",
    confirm_update: Callable[[dict], bool] | None = None,
) -> CaptionUploadResult:
    if existing_policy not in {"ask", "update", "skip"}:
        raise ValidationError(f"不正な existing_policy です: {existing_policy}")
    if not srt_path.is_file():
        raise ValidationError(f"SRT ファイルが見つかりません: {srt_path}")
    if not language.strip():
        raise ValidationError("字幕言語は空にできません")
    if not name.strip() or len(name) > 150:
        raise ValidationError("字幕トラック名は 1〜150 文字で指定してください")

    existing = _list_language_captions(youtube, video_id=video_id, language=language)
    if len(existing) > 1:
        ids = ", ".join(str(item.get("id", "<unknown>")) for item in existing)
        raise ValidationError(f"同一言語 {language} の字幕が複数あり更新対象を一意に選べません: {ids}")
    current = existing[0] if existing else None
    if current is not None:
        should_update = existing_policy == "update"
        if existing_policy == "ask":
            if confirm_update is None:
                raise ValidationError("existing_policy=ask には confirm_update が必要です")
            should_update = confirm_update(current)
        if existing_policy == "skip" or not should_update:
            return CaptionUploadResult(action="skipped", caption_id=str(current["id"]) if current.get("id") else None)

    media = MediaFileUpload(str(srt_path), mimetype="application/octet-stream", resumable=False)
    if current is None:
        body = {"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}}
        request = youtube.captions().insert(part="snippet", body=body, media_body=media)
        operation, units, action = "captions.insert", 400, "inserted"
    else:
        request = youtube.captions().update(part="id", body={"id": current["id"]}, media_body=media)
        operation, units, action = "captions.update", 450, "updated"
    metadata = {"video_id": video_id, "language": language}
    try:
        response = request.execute()
    except HttpError as exc:
        log_quota("youtube-data-api", operation, units, metadata={**metadata, "error": True})
        raise YouTubeAPIError.from_http_error(exc, f"{operation} (video_id={video_id}, language={language})") from exc
    log_quota("youtube-data-api", operation, units, metadata=metadata)
    caption_id = response.get("id") if isinstance(response, dict) else None
    return CaptionUploadResult(action=action, caption_id=str(caption_id) if caption_id else None)
