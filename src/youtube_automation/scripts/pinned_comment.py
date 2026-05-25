"""yt-pinned-comment — YouTube 固定コメント（オーナーコメント）自動投稿 CLI.

YouTube Data API v3 の ``commentThreads().insert`` で、自チャンネルの動画に
オーナーとしてトップレベルコメントを投稿する。ピン留めは Data API v3 非対応のため
投稿後に Studio UI で手動。`comments-reply` と同じ dry-run / apply / history パターン。

Examples:
    # 最新コレクションを対象にプレビュー（API 書き込みなし）
    yt-pinned-comment --collection collections/live/<dir> --dry-run --lang en

    # video_id 直接指定で投稿（--apply は必須）
    yt-pinned-comment --video-id POf4HDmhUZA --apply --lang ja

設計方針:
    dry-run / apply のどちらか明示を要求する（非破壊コマンドのうっかり投稿防止）。
    preflight として ``videos.list(part="status")`` を一括で叩き、削除済み / private 動画を
    投稿前に skip する（apply 段階で 404/403 を踏む設計バグの回避）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from googleapiclient.errors import HttpError

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import AutomationError, ValidationError, YouTubeAPIError
from youtube_automation.utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_STATUS_CHUNK_SIZE = 50


def load_history(path: Path) -> dict:
    """履歴 JSON をロードする（存在しなければ空 schema を返す）."""
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "posted": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("posted", {})
    return data


def save_history(path: Path, data: dict) -> None:
    """履歴 JSON を atomic write（.tmp → os.replace）で保存する."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def render_template(
    template: str,
    *,
    video_title: str = "",
    scene_phrase: str = "",
    theme: str = "",
    scene_emoji: str = "",
) -> str:
    """テンプレート文字列のプレースホルダを展開する."""
    return template.format(
        video_title=video_title,
        scene_phrase=scene_phrase,
        theme=theme,
        scene_emoji=scene_emoji,
    )


def resolve_targets_from_collection(collection_path: Path) -> list[tuple[str, dict | None]]:
    """コレクションから ``(video_id, workflow_state)`` のペアを解決する.

    video_id 解決の fallback chain（upstream の書き込み先差異を吸収）:
        1. ``20-documentation/upload_tracking.json`` の ``complete_collection.video_id``
           （`CollectionUploader` が書く正規の場所）
        2. ``workflow-state.json`` の ``upload.video_id``
        3. ``workflow-state.json`` トップレベルの ``video_id``（後方互換）

    scene 情報（scene_phrases / planning.scene_emoji / theme）は workflow-state.json から取る。
    """
    paths = CollectionPaths(collection_path)

    state: dict | None = None
    if paths.workflow_state_path.exists():
        with open(paths.workflow_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

    video_id: str | None = None
    if paths.tracking_path.exists():
        with open(paths.tracking_path, "r", encoding="utf-8") as f:
            tracking = json.load(f)
        video_id = (tracking.get("complete_collection") or {}).get("video_id")

    if not video_id and state:
        video_id = (state.get("upload") or {}).get("video_id") or state.get("video_id")

    if not video_id:
        raise ValidationError(
            f"video_id を解決できません: {collection_path}\n"
            "20-documentation/upload_tracking.json または workflow-state.json に "
            "video_id が記録されているか確認してください（アップロード完了後に実行）"
        )
    return [(video_id, state)]


def fetch_video_status(youtube, video_ids: list[str]) -> dict[str, dict | None]:
    """``videos.list(part="status")`` を 50 件 chunk で叩き status_map を作る.

    返り値の各 video_id について、YouTube 上に存在しなければ ``None``。
    削除済み / private な動画への ``commentThreads.insert`` は失敗するため、
    dry-run / apply 共に事前 skip するための preflight チェック用。
    """
    result: dict[str, dict | None] = {vid: None for vid in video_ids}
    for i in range(0, len(video_ids), _STATUS_CHUNK_SIZE):
        chunk = video_ids[i : i + _STATUS_CHUNK_SIZE]
        try:
            resp = youtube.videos().list(part="status", id=",".join(chunk)).execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "videos.list (preflight status check)")
        for item in resp.get("items", []):
            result[item["id"]] = item.get("status", {})
    return result


def fetch_video_title(youtube, video_id: str) -> str:
    """``videos.list(part="snippet")`` でタイトルを取得する（--video-id 経路用）."""
    try:
        resp = youtube.videos().list(part="snippet", id=video_id).execute()
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, f"videos.list (video_id={video_id})")
    items = resp.get("items") or []
    if not items:
        return ""
    return items[0]["snippet"].get("title", "")


def post_top_level_comment(youtube, video_id: str, text: str) -> str:
    """``commentThreads.insert`` でオーナーコメントを投稿し comment_id を返す."""
    resp = (
        youtube.commentThreads()
        .insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": text}},
                }
            },
        )
        .execute()
    )
    return resp["snippet"]["topLevelComment"]["id"]


def _resolve_scene(state: dict | None, lang: str) -> dict[str, str]:
    """workflow-state からテンプレート展開用の値を取り出す."""
    state = state or {}
    planning = state.get("planning") or {}
    scene_phrases = state.get("scene_phrases") or {}
    video_title = (
        planning.get("final_title_en")
        or planning.get("final_title")
        or state.get("collection_name", "")
    )
    scene_phrase = scene_phrases.get(lang) or scene_phrases.get("en", "")
    return {
        "video_title": video_title,
        "scene_phrase": scene_phrase,
        "theme": state.get("theme", ""),
        "scene_emoji": planning.get("scene_emoji", ""),
    }


def build_plan(
    targets: list[tuple[str, dict | None]],
    *,
    history: dict,
    status_map: dict[str, dict | None],
    template: str,
    lang: str,
    dry_run: bool,
    youtube=None,
    delay: float = 0.0,
    history_path: Path | None = None,
) -> dict:
    """preflight skip + テンプレート展開 + （apply 時）投稿を行い plan を返す.

    plan: ``{"planned", "skipped", "posted", "errors"}`` の 4 リスト。
    """
    plan: dict[str, list[dict]] = {"planned": [], "skipped": [], "posted": [], "errors": []}

    for vid, state in targets:
        if vid in history["posted"]:
            plan["skipped"].append({"video_id": vid, "reason": "already_posted"})
            continue

        status = status_map.get(vid)
        if status is None:
            plan["skipped"].append({"video_id": vid, "reason": "video_not_found"})
            continue
        if status.get("privacyStatus") == "private":
            plan["skipped"].append({"video_id": vid, "reason": "video_private"})
            continue
        # unlisted はオーナーがコメント投稿可能なので通過させる

        if state:
            scene = _resolve_scene(state, lang)
        else:
            title = fetch_video_title(youtube, vid)
            scene = {"video_title": title, "scene_phrase": title, "theme": "", "scene_emoji": ""}

        text = render_template(template, **scene)
        record = {
            "video_id": vid,
            "video_title": scene["video_title"],
            "language": lang,
            "text": text,
        }
        plan["planned"].append(record)

        if dry_run:
            continue

        try:
            comment_id = post_top_level_comment(youtube, vid, text)
        except HttpError as e:
            status_code = getattr(getattr(e, "resp", None), "status", None)
            plan["errors"].append(
                {"video_id": vid, "error": f"commentThreads.insert 失敗: status={status_code} {e}"}
            )
            continue

        metadata = {**record, "comment_id": comment_id, "posted_at": datetime.now(timezone.utc).isoformat()}
        history["posted"][vid] = metadata
        if history_path is not None:
            save_history(history_path, history)
        plan["posted"].append(metadata)
        if delay:
            time.sleep(delay)

    return plan


def _print_summary(plan: dict, *, dry_run: bool, as_json: bool) -> None:
    if as_json:
        payload = {"dry_run": dry_run, **plan}
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    print(
        f"planned={len(plan['planned'])} skipped={len(plan['skipped'])} "
        f"posted={len(plan['posted'])} errors={len(plan['errors'])}"
    )
    for r in plan["planned"]:
        print(f"  [{r['language']}] {r['video_id']}: {r['text']!r}")
    for s in plan["skipped"]:
        print(f"  SKIP {s['video_id']}: {s['reason']}")
    for e in plan["errors"]:
        print(f"  ERR  {e['video_id']}: {e['error']}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-pinned-comment",
        description="自チャンネルの動画にオーナー固定コメントを投稿する（ピン留めは Studio UI で手動）",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--collection",
        help="collections/live/<dir> パス（upload_tracking.json / workflow-state.json から video_id を自動解決）",
    )
    target.add_argument(
        "--video-id",
        dest="video_ids",
        action="append",
        help="対象 video_id（複数指定可）",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="API 投稿せず計画のみ出力")
    mode.add_argument("--apply", action="store_true", help="実際に YouTube へコメントを投稿する")

    parser.add_argument("--lang", default=None, help="テンプレート言語（省略時は pinned_comment.default_language）")
    parser.add_argument("--json", action="store_true", help="結果を JSON で出力")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        config = load_config()
    except AutomationError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    cfg = config.pinned_comment
    if not cfg.enabled:
        print(
            "[error] pinned_comment.enabled=false です。"
            "config/channel/pinned-comment.json を編集して true にしてください",
            file=sys.stderr,
        )
        return 1

    lang = args.lang or cfg.default_language
    template = cfg.templates.get(lang)
    if not template:
        print(
            f"[error] テンプレート言語が見つかりません: {lang}（pinned_comment.templates に追加してください）",
            file=sys.stderr,
        )
        return 1

    history_path = _channel_dir() / cfg.history_file
    history = load_history(history_path)

    try:
        if args.collection:
            targets = resolve_targets_from_collection(Path(args.collection))
        else:
            targets = [(vid, None) for vid in args.video_ids]

        youtube = get_youtube()

        # preflight は history 未記録 video のみ status check（quota 節約）
        pending_vids = [vid for vid, _ in targets if vid not in history["posted"]]
        status_map = fetch_video_status(youtube, pending_vids) if pending_vids else {}

        plan = build_plan(
            targets,
            history=history,
            status_map=status_map,
            template=template,
            lang=lang,
            dry_run=args.dry_run,
            youtube=youtube,
            delay=cfg.delay_between_posts_sec,
            history_path=history_path,
        )
    except AutomationError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    _print_summary(plan, dry_run=args.dry_run, as_json=args.json)

    if args.apply:
        if plan["posted"]:
            print("\n✅ 投稿完了。Studio UI で各コメントを手動ピン留めしてください。", file=sys.stderr)
        else:
            print("\n投稿されたコメントはありません（skip / error を確認してください）。", file=sys.stderr)

    return 0 if not plan["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
