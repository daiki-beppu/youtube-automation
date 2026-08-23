"""Shorts upload domain decisions."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Optional

from youtube_automation.configuration import channel_dir, load_config, load_schedule_config
from youtube_automation.core.adapters.media import CollectionPaths
from youtube_automation.core.adapters.runtime import get_schedule_timezone
from youtube_automation.core.errors import (
    AutomationError,
    QuotaExhaustedError,
    UploadError,
    UploadJournalError,
    ValidationError,
    WorkflowStateError,
)
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read_or_none as read_workflow_state_or_none
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.metadata import BAHMetadataGenerator
from youtube_automation.domains.uploads._published_dates import PublishedDatesScheduler
from youtube_automation.domains.uploads._tracking_io import TrackingStore
from youtube_automation.domains.uploads.upload_journal import UploadJournal
from youtube_automation.domains.uploads.youtube import YouTubeAutoUploader
from youtube_automation.infrastructure.filesystem import list_directory, path_exists
from youtube_automation.infrastructure.google.youtube import YouTubeClients

logger = logging.getLogger(__name__)

_TRACKING_READ_ERROR = "upload tracking could not be read"
_SHORT_UPLOAD_ERROR = "short upload failed"


# action 文字列（戻り値の `action` キー）。test では magic string で assert するため
# enum/定数化せずそのまま使うが、定数として 1 箇所に集約しておく（読み手向け）。
ACTION_UPLOADED = "short_uploaded"
ACTION_BLOCKED = "short_upload_blocked"
ACTION_FAILED = "short_upload_failed"


def _short_upload_kind(short_num: int | None) -> str:
    return f"short:{short_num if short_num is not None else 'default'}"


def _legacy_short_resume_uri(workflow_state_path: Path, short_num: int | None) -> str | None:
    """移行前 workflow-state にだけ残る resume URI を journal 初回利用時に引き継ぐ。"""
    state = read_workflow_state_or_none(workflow_state_path)
    if state is None or state.post_upload is None:
        return None
    for entry in state.post_upload.shorts:
        if entry.get("short_num") == short_num:
            uri = entry.get("resume_session_uri")
            return uri if isinstance(uri, str) else None
    return None


class ShortUploader:
    """Shorts 投稿エージェント — `YouTubeAutoUploader` 委譲版.

    継承禁止（plan 要件 6.6）。`self.uploader = YouTubeAutoUploader(...)` で
    アップロード I/O を委譲し、本クラスは Shorts 固有のロジック
    （interval check / video 探索 / upload orchestration）だけ持つ。
    公開日計算と tracking / workflow-state I/O は Collection upload と同じ
    ``PublishedDatesScheduler`` / ``TrackingStore`` を利用する。
    """

    def __init__(
        self,
        collections_root: Optional[str] = None,
        youtube_clients: YouTubeClients | None = None,
        tracking_store: TrackingStore | None = None,
        upload_journal_factory: Callable[[Path], UploadJournal] = UploadJournal,
        published_dates: PublishedDatesScheduler | None = None,
    ):
        self.config = load_config()
        if not self.config.shorts.enabled:
            raise UploadError(
                "Shorts 機能が無効です。`config/channel/shorts.json` で `shorts.enabled: true` にしてください"
            )
        if collections_root is None:
            collections_root = str(channel_dir() / "collections")
        self.collections_root = Path(collections_root)
        self.uploader = YouTubeAutoUploader(collections_root, youtube_clients)
        self.channel_dir = channel_dir()
        self.schedule_config = load_schedule_config(self.channel_dir)
        self.tracking_store = (
            tracking_store if tracking_store is not None else TrackingStore(self.collections_root, self.schedule_config)
        )
        self.upload_journal_factory = upload_journal_factory
        self.published_dates = (
            published_dates
            if published_dates is not None
            else PublishedDatesScheduler(self.schedule_config, lambda: self.uploader.youtube)
        )

    # ─── 投稿間隔チェック (plan 要件 6.1) ─────────────

    def _check_upload_interval(self) -> tuple[bool, str]:
        """直近の Shorts 投稿から `shorts.min_hours_between_shorts_per_collection` 経過しているか.

        Returns:
            (ok, msg): ok=True なら投稿可、False なら blocked。
        """
        min_hours = self.config.shorts.min_hours_between_shorts_per_collection
        tz = get_schedule_timezone(self.schedule_config)
        now = datetime.now(tz)

        live_dir = self.channel_dir / "collections" / "live"
        if not path_exists(live_dir):
            return True, "no previous short upload"

        latest_dt: Optional[datetime] = None
        for col_dir in list_directory(live_dir):
            ws_path = CollectionPaths(col_dir).workflow_state_path
            if not path_exists(ws_path):
                continue
            state = self.tracking_store.load_workflow_state(ws_path)
            if state is None:
                continue
            shorts = (state.get("post_upload") or {}).get("shorts") or []
            for entry in shorts:
                uploaded_at = entry.get("uploaded_at")
                if not uploaded_at:
                    continue
                dt = self.published_dates.parse_persisted_datetime(
                    uploaded_at,
                    source=ws_path,
                    field="post_upload.shorts[].uploaded_at",
                )
                if dt is None:
                    continue
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt

        if latest_dt is None:
            return True, "no previous short upload"

        elapsed_hours = (now - latest_dt).total_seconds() / 3600
        if elapsed_hours < min_hours:
            return False, f"前回 short 投稿から {elapsed_hours:.1f}h（min {min_hours}h）"
        return True, "ok"

    # ─── 動画ファイル探索 (plan 要件 6.3) ─────────────

    def _find_short_video(self, collection_path: Path, short_num: Optional[int]) -> Path:
        """Shorts 用動画ファイルを探索する.

        探索順:
            1. `short_num` 指定時のみ: `01-master/shorts/short-NN-*.mp4`
               （複数マッチは `sorted()` 先頭、補足設計判断 §155）
            2. fallback: `01-master/short.mp4`

        Raises:
            FileNotFoundError: 両方無いとき（plan §171 厳密準拠）
        """
        paths = CollectionPaths(collection_path)
        video = paths.find_short_video(short_num)
        if video is not None:
            return video

        searched = paths.short_video_search_paths(short_num)
        raise FileNotFoundError(f"Shorts 動画が見つかりません。探索パス: {', '.join(searched)}")

    # ─── upload オーケストレーション (plan 要件 6.4) ──

    def upload_short(self, collection_path: Path, short_num: Optional[int] = None) -> dict:
        """Shorts を YouTube にアップロードする.

        Args:
            collection_path: 対象コレクション (`collections/live/<name>/`)
            short_num: `01-master/shorts/short-NN-*.mp4` の NN（None なら `short.mp4` 経路）

        Returns:
            {"action": str, "details": dict}
                action: "short_uploaded" / "short_upload_blocked" / "short_upload_failed"
        """
        # 1. 投稿間隔チェック（24h 制約）
        ok, msg = self._check_upload_interval()
        if not ok:
            logger.info(f"⏸  Shorts 投稿スキップ: {msg}")
            return {"action": ACTION_BLOCKED, "details": {"reason": msg}}

        # 2. tracking 読み込み（CC URL 抽出のため）
        tracking_path = CollectionPaths(collection_path).tracking_path
        if not path_exists(tracking_path):
            logger.error(f"❌ upload_tracking.json が無いため Shorts 投稿不可: {tracking_path}")
            return {"action": ACTION_FAILED, "details": {"error": f"tracking missing: {tracking_path}"}}
        try:
            tracking = self.tracking_store.read(collection_path)
        except (json.JSONDecodeError, OSError):
            logger.error("❌ upload_tracking.json 読み込み失敗")
            return {"action": ACTION_FAILED, "details": {"error": _TRACKING_READ_ERROR}}

        cc = tracking.get("complete_collection") or {}
        cc_video_url = cc.get("video_url", "")

        # 3. 動画ファイル探索（両方無→FileNotFoundError を握り潰し）
        try:
            video_path = self._find_short_video(collection_path, short_num)
        except FileNotFoundError:
            logger.error("❌ Shorts 動画が見つかりません")
            return {"action": ACTION_FAILED, "details": {"error": "short video not found"}}

        # 4. メタデータ生成
        try:
            generator = BAHMetadataGenerator(str(collection_path))
            metadata = generator.generate_shorts_metadata(cc_video_url)
        except AutomationError:
            logger.error("❌ Shorts メタデータ生成失敗")
            return {"action": ACTION_FAILED, "details": {"error": "short metadata generation failed"}}

        # 5. publish_at 算出
        publish_at = self.published_dates.calculate_short_publish_at(
            tracking,
            tracking_path=tracking_path,
            publish_time=self.config.shorts.publish_time,
        )
        if publish_at:
            metadata["publish_at"] = publish_at

        # 6. サムネイル探索（plan 要件 6.5: .jpg → .png → None）
        thumbnail_path = self._find_short_thumbnail(collection_path)

        # 7. 委譲 upload（resumable upload session URI を workflow-state に永続化, #466）。
        #    CC 経路（#381 / collection_uploader._execute_complete_collection）と同思想で、
        #    中断→再実行時に同一 session を再開し video_id 重複を防ぐ。tracking 媒体は
        #    CC の upload_tracking.json ではなく workflow-state.json.post_upload.shorts[]。
        ws_path = CollectionPaths(collection_path).workflow_state_path
        journal = self.upload_journal_factory(collection_path)
        try:
            attempt = journal.begin(_short_upload_kind(short_num))
            resume_session_uri = attempt.resume_uri
            if resume_session_uri is None:
                resume_session_uri = _legacy_short_resume_uri(ws_path, short_num)
                if resume_session_uri is not None:
                    attempt.record_session(resume_session_uri)
        except UploadJournalError:
            logger.error("❌ upload journal 読み込み失敗")
            return {"action": ACTION_FAILED, "details": {"error": _TRACKING_READ_ERROR}}

        def _on_session_uri_changed(uri: Optional[str]) -> None:
            """upload 中の session URI 変化を該当 short entry に永続化する。"""
            attempt.record_session(uri)

        def _on_upload_complete() -> None:
            """upload 成功通知。後続の最終記録と整合させるため URI を消す。"""
            _on_session_uri_changed(None)

        try:
            video_id = self.uploader.upload_video(
                str(video_path),
                metadata,
                thumbnail_path,
                resume_session_uri=resume_session_uri,
                on_session_uri_changed=_on_session_uri_changed,
                on_upload_complete=_on_upload_complete,
            )
        except QuotaExhaustedError as e:
            logger.error("⏸️  quota 枯渇のため中断・時間をおいて再実行してください")
            return {
                "action": ACTION_FAILED,
                "details": {
                    "error": "quota exhausted",
                    "retryable": True,
                    "retry_after_seconds": e.retry_after_seconds,
                },
            }
        except (RuntimeError, ValidationError, UploadError):
            logger.error("❌ upload_video 失敗")
            return {"action": ACTION_FAILED, "details": {"error": _SHORT_UPLOAD_ERROR}}
        if not video_id:
            return {"action": ACTION_FAILED, "details": {"error": "upload_video returned None"}}

        # 8. workflow-state 更新（list 形式 upsert by short_num）
        entry = {
            "short_num": short_num,
            "video_id": video_id,
            "uploaded_at": datetime.now(get_schedule_timezone(self.schedule_config)).isoformat(),
            "publish_at": publish_at,
        }

        def project(state: WorkflowState) -> None:
            state.record_short_upload(entry)

        try:
            attempt.complete({"video_id": video_id})
            update_workflow_state(ws_path, project)
        except (UploadJournalError, WorkflowStateError) as error:
            logger.error("❌ short upload 完了記録失敗: %s", error)
            return {"action": ACTION_FAILED, "details": {"error": _SHORT_UPLOAD_ERROR}}

        return {
            "action": ACTION_UPLOADED,
            "details": {
                "video_id": video_id,
                "publish_at": publish_at,
                "thumbnail": thumbnail_path,
                "short_num": short_num,
            },
        }

    def _find_short_thumbnail(self, collection_path: Path) -> Optional[str]:
        """plan 要件 6.5: `10-assets/short-thumbnail.{jpg,png}` の順に探索。両方無は None."""
        paths = CollectionPaths(collection_path)
        candidate = paths.find_short_thumbnail()
        if candidate is not None:
            return str(candidate)
        assets = paths.assets_dir
        logger.warning(f"short-thumbnail.{{jpg,png}} が見つかりません — サムネ未設定で upload します: {assets}")
        return None

    # ─── ドライラン ──────────────────────────────────

    def show_plan(self, collection_path: Path, short_num: Optional[int] = None) -> None:
        """ドライラン: 投稿予定の計算結果のみ表示."""
        ok, msg = self._check_upload_interval()
        tracking = self.tracking_store.load(collection_path)
        publish_at = (
            self.published_dates.calculate_short_publish_at(
                tracking,
                tracking_path=self.tracking_store.tracking_path(collection_path),
                publish_time=self.config.shorts.publish_time,
            )
            if tracking is not None
            else None
        )
        paths = CollectionPaths(collection_path)
        target_path = paths.short_video_search_paths(short_num)[0]
        display_target = Path(target_path).relative_to(paths.root)

        print(f"📋 Shorts 投稿計画: {collection_path.name}")
        print()
        print(f"  対象: {display_target}")
        print(f"  投稿可否: {'✅' if ok else '⛔'} ({msg})")
        if publish_at:
            print(f"  📅 公開予定: {publish_at}")
        else:
            print("  📅 公開設定: 即時公開 (public)")
