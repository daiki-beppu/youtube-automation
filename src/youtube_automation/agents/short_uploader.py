#!/usr/bin/env python3
"""Short Uploader - YouTube Shorts 投稿エージェント

`YouTubeAutoUploader` を **委譲** で利用し、Shorts 専用のメタデータ生成・
スケジュール公開（CC 公開日 + 1day + `config.shorts.publish_time`）・投稿間隔チェック
（`config.shorts.min_hours_between_shorts_per_collection`、default 24h）を実装する。

`CollectionUploader` と同じ委譲パターン。継承は禁止。

機能の有効化は `config/channel/shorts.json` の `shorts.enabled: true` で行う
（未配置 / false の場合は `__init__` で `UploadError`）。

公開 API:
    - `upload_short(collection_path, short_num=None)` → 投稿実行
    - `show_plan(collection_path)` → ドライラン
    - `main()` → CLI entry (`yt-upload-shorts`)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader
from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.domains.metadata import BAHMetadataGenerator
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import QuotaExhaustedError, UploadError
from youtube_automation.utils.schedule import get_schedule_timezone, now_in_schedule_tz

logger = logging.getLogger(__name__)


# action 文字列（戻り値の `action` キー）。test では magic string で assert するため
# enum/定数化せずそのまま使うが、定数として 1 箇所に集約しておく（読み手向け）。
ACTION_UPLOADED = "short_uploaded"
ACTION_BLOCKED = "short_upload_blocked"
ACTION_FAILED = "short_upload_failed"


def _backfill_naive_datetime(dt: datetime, tz, *, source: Path, field: str, raw: str) -> datetime:
    """TZ-naive な datetime を schedule timezone で backfill する（レガシーデータ救済）.

    #359 で書き込み側は `datetime.now(tz).isoformat()` の TZ-aware ISO 8601 に統一済みのため、
    ここを踏むのは既存 live/ 配下に永続化されたレガシーデータのみ。将来 backfill 補正を
    撤去するタイミングを判断するシグナルとして、どのファイル・どのフィールドが TZ-naive
    だったかを warning で記録する（#532）。

    Args:
        dt: 判定対象の datetime
        tz: backfill に使う schedule timezone
        source: 値の出所ファイルパス（ログ用）
        field: TZ-naive だったフィールド名（ログ用）
        raw: パース前の生文字列（ログ用）

    Returns:
        TZ-aware な datetime（元から aware ならそのまま返す）。
    """
    if dt.tzinfo is not None:
        return dt
    logger.warning(
        "%s に TZ-naive な %s=%r が含まれます; schedule timezone %s で backfill します（レガシーデータ救済 / #532）",
        source,
        field,
        raw,
        tz,
    )
    return dt.replace(tzinfo=tz)


class ShortUploader:
    """Shorts 投稿エージェント — `YouTubeAutoUploader` 委譲版.

    継承禁止（plan 要件 6.6）。`self.uploader = YouTubeAutoUploader(...)` で
    アップロード I/O を委譲し、本クラスは Shorts 固有のロジック
    （interval check / publish_at 算出 / video 探索 / state 更新）だけ持つ。
    """

    def __init__(self, collections_root: Optional[str] = None):
        self.config = load_config()
        if not self.config.shorts.enabled:
            raise UploadError(
                "Shorts 機能が無効です。`config/channel/shorts.json` で `shorts.enabled: true` にしてください"
            )
        if collections_root is None:
            collections_root = str(channel_dir() / "collections")
        self.collections_root = Path(collections_root)
        self.uploader = YouTubeAutoUploader(collections_root)
        self.channel_dir = channel_dir()
        self.schedule_config = self._load_schedule_config()

    # ─── 設定読み込み ────────────────────────────────

    def _load_schedule_config(self) -> dict:
        """`config/schedule_config.json` を読み込む（存在しなければ空 dict）.

        schedule_config は新 ChannelConfig には含めず、JSON を都度読みする
        旧 `CollectionUploader` のパターンを踏襲（タイムゾーンや投稿間隔は
        運用ごとに上書きされやすいため、シングルトンに乗せない）。
        """
        path = self.channel_dir / "config" / "schedule_config.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"schedule_config.json 読み込み失敗: {e}")
            return {}

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
        if not live_dir.exists():
            return True, "no previous short upload"

        latest_dt: Optional[datetime] = None
        for col_dir in live_dir.iterdir():
            ws_path = CollectionPaths(col_dir).workflow_state_path
            if not ws_path.exists():
                continue
            try:
                with open(ws_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            shorts = (state.get("post_upload") or {}).get("shorts") or []
            for entry in shorts:
                uploaded_at = entry.get("uploaded_at")
                if not uploaded_at:
                    continue
                try:
                    dt = datetime.fromisoformat(uploaded_at)
                except ValueError:
                    continue
                dt = _backfill_naive_datetime(
                    dt, tz, source=ws_path, field="post_upload.shorts[].uploaded_at", raw=uploaded_at
                )
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt

        if latest_dt is None:
            return True, "no previous short upload"

        elapsed_hours = (now - latest_dt).total_seconds() / 3600
        if elapsed_hours < min_hours:
            return False, f"前回 short 投稿から {elapsed_hours:.1f}h（min {min_hours}h）"
        return True, "ok"

    # ─── publish_at 算出 (plan 要件 6.2) ─────────────

    def _calculate_short_publish_at(self, collection_path: Path) -> Optional[str]:
        """Shorts のスケジュール公開日時を算出.

        CC `publish_at` （無ければ `upload_time`）の翌日 `short_publish_time` 時刻.
        結果が現在より過去なら None（即時公開扱い）.

        Returns:
            ISO 8601 文字列 or None
        """
        tracking_path = CollectionPaths(collection_path).tracking_path
        if not tracking_path.exists():
            return None
        try:
            with open(tracking_path, "r", encoding="utf-8") as f:
                tracking = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        cc = tracking.get("complete_collection") or {}
        base_str = cc.get("publish_at")
        base_field = "complete_collection.publish_at"
        if not base_str:
            base_str = cc.get("upload_time")
            base_field = "complete_collection.upload_time"
        if not base_str:
            return None

        tz = get_schedule_timezone(self.schedule_config)
        short_publish_time = self.config.shorts.publish_time
        try:
            hour, minute = (int(x) for x in short_publish_time.split(":"))
        except ValueError:
            logger.warning(f"short_publish_time のパース失敗: {short_publish_time}（HH:MM 形式が必要）")
            return None

        try:
            base_dt = datetime.fromisoformat(base_str)
        except ValueError:
            return None
        base_dt = _backfill_naive_datetime(base_dt, tz, source=tracking_path, field=base_field, raw=base_str)

        publish_dt = base_dt.astimezone(tz) + timedelta(days=1)
        publish_dt = publish_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if publish_dt <= datetime.now(tz):
            return None
        return publish_dt.isoformat()

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
        if not tracking_path.exists():
            logger.error(f"❌ upload_tracking.json が無いため Shorts 投稿不可: {tracking_path}")
            return {"action": ACTION_FAILED, "details": {"error": f"tracking missing: {tracking_path}"}}
        try:
            with open(tracking_path, "r", encoding="utf-8") as f:
                tracking = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"❌ upload_tracking.json 読み込み失敗: {e}")
            return {"action": ACTION_FAILED, "details": {"error": str(e)}}

        cc = tracking.get("complete_collection") or {}
        cc_video_url = cc.get("video_url", "")

        # 3. 動画ファイル探索（両方無→FileNotFoundError を握り潰し）
        try:
            video_path = self._find_short_video(collection_path, short_num)
        except FileNotFoundError as e:
            logger.error(f"❌ {e}")
            return {"action": ACTION_FAILED, "details": {"error": str(e)}}

        # 4. メタデータ生成
        try:
            generator = BAHMetadataGenerator(str(collection_path))
            metadata = generator.generate_shorts_metadata(cc_video_url)
        except Exception as e:
            logger.error(f"❌ メタデータ生成失敗: {e}")
            return {"action": ACTION_FAILED, "details": {"error": str(e)}}

        # 5. publish_at 算出
        publish_at = self._calculate_short_publish_at(collection_path)
        if publish_at:
            metadata["publish_at"] = publish_at

        # 6. サムネイル探索（plan 要件 6.5: .jpg → .png → None）
        thumbnail_path = self._find_short_thumbnail(collection_path)

        # 7. 委譲 upload（resumable upload session URI を workflow-state に永続化, #466）。
        #    CC 経路（#381 / collection_uploader._execute_complete_collection）と同思想で、
        #    中断→再実行時に同一 session を再開し video_id 重複を防ぐ。tracking 媒体は
        #    CC の upload_tracking.json ではなく workflow-state.json.post_upload.shorts[]。
        ws_path = CollectionPaths(collection_path).workflow_state_path
        resume_session_uri = self._read_short_resume_uri(ws_path, short_num)

        def _on_session_uri_changed(uri: Optional[str]) -> None:
            """upload 中の session URI 変化を該当 short entry に永続化する。"""
            self._persist_short_resume_uri(ws_path, short_num, uri)

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
            logger.error(f"⏸️  quota 枯渇のため中断・時間をおいて再実行してください: {e}")
            return {
                "action": ACTION_FAILED,
                "details": {"error": str(e), "retryable": True, "retry_after_seconds": e.retry_after_seconds},
            }
        except Exception as e:
            logger.error(f"❌ upload_video 失敗: {e}")
            return {"action": ACTION_FAILED, "details": {"error": str(e)}}
        if not video_id:
            return {"action": ACTION_FAILED, "details": {"error": "upload_video returned None"}}

        # 8. workflow-state 更新（list 形式 upsert by short_num）
        self._update_workflow_state(
            collection_path,
            short_num=short_num,
            video_id=video_id,
            publish_at=publish_at,
        )

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

    # ─── workflow-state I/O ──────────────────────────

    def _load_workflow_state(self, ws_path: Path) -> Optional[dict]:
        """workflow-state.json を読み込む。ファイル無 / パース失敗時は None（warning）。"""
        if not ws_path.exists():
            return None
        try:
            with open(ws_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"workflow-state.json 読み込み失敗: {e}")
            return None

    def _save_workflow_state(self, ws_path: Path, state: dict) -> None:
        """workflow-state.json を書き戻す。失敗時は warning のみ（致命的にしない）。"""
        try:
            with open(ws_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.warning(f"workflow-state.json 書き込み失敗: {e}")

    @staticmethod
    def _find_short_entry(shorts: list, short_num: Optional[int]) -> Optional[dict]:
        """`post_upload.shorts` から short_num 一致の entry を返す（無ければ None）。"""
        for entry in shorts:
            if isinstance(entry, dict) and entry.get("short_num") == short_num:
                return entry
        return None

    def _read_short_resume_uri(self, ws_path: Path, short_num: Optional[int]) -> Optional[str]:
        """該当 short entry に永続化済みの resumable upload session URI を読む (#466)。

        ファイル無 / entry 無 / 未保存なら None（＝フレッシュ実行）。
        """
        state = self._load_workflow_state(ws_path)
        if not state:
            return None
        shorts = (state.get("post_upload") or {}).get("shorts") or []
        entry = self._find_short_entry(shorts, short_num)
        return entry.get("resume_session_uri") if entry else None

    def _persist_short_resume_uri(self, ws_path: Path, short_num: Optional[int], uri: Optional[str]) -> None:
        """該当 short entry の `resume_session_uri` を upsert / 削除する (#466)。

        並行更新に備え毎回 disk から再ロードしてから書き戻す（CC の
        `_on_session_uri_changed` と同思想）。`uri=None` で削除。entry が未作成なら
        short_num のみの entry を append して URI を載せる。ファイル無 → warning skip。
        """
        if not ws_path.exists():
            logger.warning(f"workflow-state.json が無いため resume URI 永続化を skip: {ws_path}")
            return
        state = self._load_workflow_state(ws_path)
        if state is None:
            return

        post_upload = state.setdefault("post_upload", {})
        shorts = post_upload.get("shorts")
        if not isinstance(shorts, list):
            shorts = []
            post_upload["shorts"] = shorts

        entry = self._find_short_entry(shorts, short_num)
        if entry is None:
            entry = {"short_num": short_num}
            shorts.append(entry)

        if uri is None:
            entry.pop("resume_session_uri", None)
        else:
            entry["resume_session_uri"] = uri

        self._save_workflow_state(ws_path, state)

    # ─── workflow-state 更新 (plan アンチパターン #10) ─

    def _update_workflow_state(
        self,
        collection_path: Path,
        *,
        short_num: Optional[int],
        video_id: str,
        publish_at: Optional[str],
    ) -> None:
        """`post_upload.shorts: list[dict]` に short_num をキーに upsert.

        ファイル無 → warning ログのみで skip（致命的にしない）.
        書き手（本メソッド）と読み手（`bulk_update_short_localizations.collect_short_videos`）が
        同 PR 内で対称検証されるスキーマ.
        """
        ws_path = CollectionPaths(collection_path).workflow_state_path
        if not ws_path.exists():
            logger.warning(f"workflow-state.json が無いため short upload 記録を skip: {ws_path}")
            return

        state = self._load_workflow_state(ws_path)
        if state is None:
            return

        post_upload = state.setdefault("post_upload", {})
        shorts = post_upload.get("shorts")
        if not isinstance(shorts, list):
            shorts = []
            post_upload["shorts"] = shorts

        entry = {
            "short_num": short_num,
            "video_id": video_id,
            "uploaded_at": now_in_schedule_tz(self.schedule_config).isoformat(),
            "publish_at": publish_at,
        }

        for i, existing in enumerate(shorts):
            if existing.get("short_num") == short_num:
                shorts[i] = entry
                break
        else:
            shorts.append(entry)

        self._save_workflow_state(ws_path, state)

    # ─── ドライラン ──────────────────────────────────

    def show_plan(self, collection_path: Path, short_num: Optional[int] = None) -> None:
        """ドライラン: 投稿予定の計算結果のみ表示."""
        ok, msg = self._check_upload_interval()
        publish_at = self._calculate_short_publish_at(collection_path)
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube Shorts uploader")
    parser.add_argument("collection", help="コレクションパス (collections/live/<name>/)")
    parser.add_argument("--short-num", type=int, default=None, help="複数 Shorts 時の番号 (NN)")
    parser.add_argument("--plan", action="store_true", help="ドライラン (公開予定のみ表示)")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    collection_path = Path(args.collection)
    if not collection_path.is_absolute():
        collection_path = Path.cwd() / collection_path

    try:
        uploader = ShortUploader()
        if args.plan:
            uploader.show_plan(collection_path, short_num=args.short_num)
            return
        result = uploader.upload_short(collection_path, short_num=args.short_num)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["action"] == ACTION_FAILED:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 中断されました")
        sys.exit(130)
    except Exception as e:
        logger.exception("❌ 予期せぬエラー")
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
