#!/usr/bin/env python3
"""公開済み動画の ``status.containsSyntheticMedia`` を遡及的に True へ一括是正する CLI.

#603 / PR #604 で新規アップロード分は ``containsSyntheticMedia=True`` に是正済みだが、
それ以前にアップロードされた公開動画は ``False`` のまま残る。本ツールはチャンネルの
全公開動画を YouTube Data API で列挙し、現状 ``True`` でないものを抽出して
``videos().update(part='status')`` で ``True`` に反映する（#606）。

公式ドキュメント上 ``status.containsSyntheticMedia`` は videos.insert / videos.update
の **両方** で書き込み可能（developers.google.com/youtube/v3/docs/videos）。

安全性: ``videos.update(part='status')`` は status リソース **全体を置換** するため、
``videos.list`` で取得した現 status を起点に ``containsSyntheticMedia`` だけを差し替えて
送る（read-modify-write）。これにより privacyStatus / publishAt / selfDeclaredMadeForKids
等の既存値を壊さない。

Usage:
    yt-bulk-update-synthetic-media                   # dry-run（デフォルト。API は read のみ）
    yt-bulk-update-synthetic-media --apply           # 実反映
    yt-bulk-update-synthetic-media --include-private  # private 動画も対象に含める
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from googleapiclient.errors import HttpError

from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.cost_tracker import log_quota
from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.infrastructure.google.youtube import YouTubeClients

logger = logging.getLogger(__name__)


# per-video スリープ。quota 急上昇防止
SLEEP_SEC_PER_VIDEO = 0.5

# videos().list / update のバッチ上限
BATCH_SIZE = 50

# videos.update(part="status") に送ってはいけない read-only キー（送ると 400 の恐れ）
READONLY_STATUS_KEYS = {
    "uploadStatus",
    "failureReason",
    "rejectionReason",
    "madeForKids",
}

# デフォルトで対象とする公開状態（issue #606 は「公開済み動画」が主眼）
PUBLIC_PRIVACY = {"public", "unlisted"}

# YouTube Data API quota 記録（Issue #2058）。units は公式 quota 表に従う
# （https://developers.google.com/youtube/v3/determine_quota_cost）。
QUOTA_SERVICE = "youtube-data-api"
QUOTA_UNITS = {
    "channels.list": 1,
    "playlistItems.list": 1,
    "videos.list": 1,
    "videos.update": 50,
}


def _execute_with_quota(request, bucket: str, metadata: dict | None = None) -> dict:
    """request を実行しつつ quota を記録する.

    quota はリクエストの成否に関わらず消費されるため、失敗時も記録してから
    例外を伝播させる（Issue #2058）。
    """
    try:
        return request.execute()
    finally:
        log_quota(QUOTA_SERVICE, bucket, QUOTA_UNITS[bucket], metadata=metadata)


def list_uploads_video_ids(youtube) -> list[str]:
    """認証チャンネルの uploads playlist から全 video_id を列挙する.

    ``channels().list(mine=True)`` で uploads playlist を解決し、``playlistItems``
    をページング全走査する（``utils/video_listing.py`` のロジックを踏襲）。
    """
    try:
        channel_response = _execute_with_quota(
            youtube.channels().list(part="contentDetails", mine=True),
            "channels.list",
        )
        items = channel_response.get("items") or []
        if not items:
            raise YouTubeAPIError("認証チャンネルが取得できませんでした（items 空）")
        uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        video_ids: list[str] = []
        next_page_token = None
        while True:
            playlist_response = _execute_with_quota(
                youtube.playlistItems().list(
                    part="contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=BATCH_SIZE,
                    pageToken=next_page_token,
                ),
                "playlistItems.list",
            )
            for item in playlist_response.get("items") or []:
                video_id = item.get("contentDetails", {}).get("videoId")
                if video_id:
                    video_ids.append(video_id)
            next_page_token = playlist_response.get("nextPageToken")
            if not next_page_token:
                break
        return video_ids
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, "uploads playlist の取得に失敗") from e


def fetch_status_batch(youtube, video_ids: list[str]) -> list[dict]:
    """video_id を 50 件ずつ ``videos().list(part='status,snippet')`` で取得する.

    Returns:
        [{"video_id": str, "title": str, "status": dict}, ...]
    """
    results: list[dict] = []
    try:
        for start in range(0, len(video_ids), BATCH_SIZE):
            batch = video_ids[start : start + BATCH_SIZE]
            response = _execute_with_quota(
                youtube.videos().list(part="status,snippet", id=",".join(batch)),
                "videos.list",
                metadata={"video_count": len(batch)},
            )
            for item in response.get("items") or []:
                results.append(
                    {
                        "video_id": item["id"],
                        "title": item.get("snippet", {}).get("title", ""),
                        "status": item.get("status", {}) or {},
                    }
                )
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, "動画 status の取得に失敗") from e
    return results


def select_targets(items: list[dict], include_private: bool) -> tuple[list[dict], int, int]:
    """``containsSyntheticMedia`` が True でない動画を抽出する.

    Returns:
        (targets, skipped_already_true, skipped_privacy)
    """
    allowed_privacy = set(PUBLIC_PRIVACY)
    if include_private:
        allowed_privacy.add("private")

    targets: list[dict] = []
    skipped_already_true = 0
    skipped_privacy = 0
    for item in items:
        status = item["status"]
        if status.get("containsSyntheticMedia") is True:
            skipped_already_true += 1
            continue
        if status.get("privacyStatus") not in allowed_privacy:
            skipped_privacy += 1
            continue
        targets.append(item)
    return targets, skipped_already_true, skipped_privacy


def build_update_body(video_id: str, status: dict) -> dict:
    """現 status を保持したまま ``containsSyntheticMedia=True`` を立てた update body を返す.

    ``videos.update(part='status')`` は status リソース全体を置換するため、現値を
    コピーして read-only キーを除去し、``containsSyntheticMedia`` だけ差し替える。
    """
    new_status = {k: v for k, v in status.items() if k not in READONLY_STATUS_KEYS}
    new_status["containsSyntheticMedia"] = True
    return {"id": video_id, "status": new_status}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "公開済み動画の status.containsSyntheticMedia を遡及的に True へ一括是正する。"
            "デフォルトは dry-run（read のみ）。実反映には --apply を付ける。"
        )
    )
    parser.add_argument("--apply", action="store_true", help="実際に YouTube へ反映する（無指定時は dry-run）")
    parser.add_argument(
        "--include-private",
        action="store_true",
        help="private 動画も対象に含める（デフォルトは public / unlisted のみ）",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    try:
        youtube = YouTubeClients(full_handler=YouTubeOAuthHandler()).youtube
        video_ids = list_uploads_video_ids(youtube)
        if not video_ids:
            print("❌ 対象動画が見つかりません（uploads playlist が空）")
            sys.exit(1)

        items = fetch_status_batch(youtube, video_ids)
    except YouTubeAPIError as e:
        print(f"❌ {e}")
        sys.exit(1)

    targets, skipped_true, skipped_privacy = select_targets(items, args.include_private)

    print(f"🔎 走査: {len(items)} 件 / 既に True: {skipped_true} 件 / 非公開で除外: {skipped_privacy} 件")
    if not targets:
        print("✅ 遡及対象なし（全動画が containsSyntheticMedia=True 済み）")
        return

    print(f"🎯 対象: {len(targets)} 件")
    for t in targets:
        current = t["status"].get("containsSyntheticMedia")
        current_repr = "false" if current is False else "unset"
        print(f"  - {t['video_id']}  [{current_repr}]  {t['title']}")

    if not args.apply:
        print(f"\n🔍 dry-run; {len(targets)} 件を更新します（実反映には --apply）")
        return

    updated = 0
    failed = 0
    for t in targets:
        body = build_update_body(t["video_id"], t["status"])
        try:
            _execute_with_quota(
                youtube.videos().update(part="status", body=body),
                "videos.update",
                metadata={"video_id": t["video_id"]},
            )
            updated += 1
            print(f"  ✅ {t['video_id']} updated")
        except HttpError as e:
            failed += 1
            err = YouTubeAPIError.from_http_error(e, f"{t['video_id']} の更新に失敗")
            print(f"  ❌ {err}")
            continue
        time.sleep(SLEEP_SEC_PER_VIDEO)

    print(f"\n📊 対象 {len(targets)} 件 / 成功 {updated} 件 / 失敗 {failed} 件")
    if failed:
        sys.exit(1)
    print("✅ done")


if __name__ == "__main__":
    main()
