#!/usr/bin/env python3
"""
Auto Post Comment — 動画公開検知 + コメント自動投稿

予約公開動画が公開状態になったことを検知し、
workflow-state.json に事前登録されたコメントを自動投稿する。

launchd で定期実行（30分間隔）を想定。

Usage:
    python3 automation/auto_post_comment.py                    # 全コレクションをチェック
    python3 automation/auto_post_comment.py --dry-run          # 実際には投稿しない
    python3 automation/auto_post_comment.py --collection PATH  # 特定コレクションのみ
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.youtube_service import get_youtube  # noqa: E402

logger = logging.getLogger(__name__)

LOG_FILE = Path(__file__).parent.parent / "logs" / "auto_post_comment.log"


def setup_logging():
    """ファイル + コンソールのデュアルロギング"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def find_pending_collections(channel_dir: Path) -> list[dict]:
    """コメント未投稿のコレクションを検索

    Returns:
        list[dict]: [{path, video_id, comment_text, collection_name}]
    """
    pending = []

    for stage_dir in ["collections/live", "collections/planning"]:
        base = channel_dir / stage_dir
        if not base.exists():
            continue

        for col_dir in sorted(base.iterdir()):
            if not col_dir.is_dir():
                continue

            ws_path = col_dir / "workflow-state.json"
            tracking_path = col_dir / "20-documentation" / "upload_tracking.json"

            if not ws_path.exists() or not tracking_path.exists():
                continue

            with open(ws_path, "r", encoding="utf-8") as f:
                ws = json.load(f)

            post_upload = ws.get("post_upload")
            if not post_upload:
                continue

            pinned = post_upload.get("pinned_comment", {})
            if pinned.get("done", False):
                continue

            comment_text = pinned.get("text")
            if not comment_text:
                continue

            with open(tracking_path, "r", encoding="utf-8") as f:
                tracking = json.load(f)

            video_id = tracking.get("complete_collection", {}).get("video_id")
            if not video_id:
                continue

            pending.append({
                "path": col_dir,
                "video_id": video_id,
                "comment_text": comment_text,
                "collection_name": ws.get("collection_name", col_dir.name),
            })

    return pending


def check_video_public(youtube, video_id: str) -> bool:
    """動画が公開状態かチェック"""
    response = youtube.videos().list(
        id=video_id,
        part="status"
    ).execute()

    items = response.get("items", [])
    if not items:
        logger.warning(f"動画が見つかりません: {video_id}")
        return False

    privacy = items[0]["status"]["privacyStatus"]
    logger.info(f"動画 {video_id} の状態: {privacy}")
    return privacy == "public"


def post_comment(youtube, video_id: str, comment_text: str) -> str:
    """コメントを投稿し、comment_id を返す"""
    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {
                "snippet": {
                    "textOriginal": comment_text
                }
            }
        }
    }

    response = youtube.commentThreads().insert(
        part="snippet",
        body=body
    ).execute()

    return response["snippet"]["topLevelComment"]["id"]


def update_workflow_state(ws_path: Path, comment_id: str):
    """workflow-state.json を更新"""
    with open(ws_path, "r", encoding="utf-8") as f:
        ws = json.load(f)

    ws["post_upload"]["pinned_comment"]["done"] = True
    ws["post_upload"]["pinned_comment"]["comment_id"] = comment_id
    ws["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(ws_path, "w", encoding="utf-8") as f:
        json.dump(ws, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    setup_logging()
    logger.info("=" * 50)
    logger.info("Auto Post Comment — 実行開始")

    parser = argparse.ArgumentParser(description="動画公開検知 + コメント自動投稿")
    parser.add_argument("--dry-run", action="store_true", help="実際には投稿しない")
    parser.add_argument("--collection", type=str, help="特定コレクションのパス")
    args = parser.parse_args()

    ChannelConfig.load()
    channel_dir = ChannelConfig.channel_dir()

    # 対象コレクション取得
    if args.collection:
        col_path = Path(args.collection).resolve()
        ws_path = col_path / "workflow-state.json"
        tracking_path = col_path / "20-documentation" / "upload_tracking.json"

        with open(ws_path, "r", encoding="utf-8") as f:
            ws = json.load(f)
        with open(tracking_path, "r", encoding="utf-8") as f:
            tracking = json.load(f)

        pinned = ws.get("post_upload", {}).get("pinned_comment", {})
        pending = [{
            "path": col_path,
            "video_id": tracking["complete_collection"]["video_id"],
            "comment_text": pinned.get("text", ""),
            "collection_name": ws.get("collection_name", col_path.name),
        }]
    else:
        pending = find_pending_collections(channel_dir)

    if not pending:
        logger.info("コメント未投稿のコレクションはありません")
        return

    logger.info(f"対象: {len(pending)} コレクション")

    # YouTube API 接続（対象がある場合のみ）
    youtube = get_youtube()

    posted = 0
    for item in pending:
        name = item["collection_name"]
        vid = item["video_id"]

        logger.info(f"チェック中: {name} ({vid})")

        if not check_video_public(youtube, vid):
            logger.info(f"⏳ 未公開のためスキップ: {name}")
            continue

        if args.dry_run:
            logger.info(f"🔍 [DRY RUN] 投稿対象: {name}")
            logger.info(f"   テキスト: {item['comment_text'][:80]}...")
            posted += 1
            continue

        comment_id = post_comment(youtube, vid, item["comment_text"])
        update_workflow_state(item["path"] / "workflow-state.json", comment_id)

        logger.info(f"✅ コメント投稿完了: {name} → {comment_id}")
        logger.info("⚠️  固定は YouTube Studio で手動:")
        logger.info(f"   https://studio.youtube.com/video/{vid}/comments")
        posted += 1

    logger.info(f"完了: {posted}/{len(pending)} 件投稿")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
