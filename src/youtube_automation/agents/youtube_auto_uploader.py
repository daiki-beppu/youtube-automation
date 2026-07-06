#!/usr/bin/env python3
"""
YouTube 自動アップローダー
collections/ の動画を自動的にYouTubeにアップロード

Features:
- Complete Collection 自動アップロード
- メタデータ自動生成・最適化
- サムネイル自動設定
- アップロード結果レポート
- エラーハンドリング・リトライ機能

責務分割（挙動不変・Issue #465）:
- ``_uploader_constants``           : 共有定数
- ``_dedup_search.DedupSearchMixin`` : publish 直前の同タイトル dedup 安全網
- ``_descriptions_md.DescriptionsMdMixin`` : descriptions.md パース
- ``_preflight.PreflightMixin``      : アップロード前メタデータ検証
- ``_complete_collection_strategy.CompleteCollectionMixin`` : CC アップロード経路
本モジュールはクラス本体（初期化 / upload_video / dispatcher / レポート / CLI）を保持する。
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _normalize_publish_at(value: str) -> str:
    """`status.publishAt` を YouTube Data API が受け付ける ISO 8601 文字列に正規化する.

    入力例:

    - `"2026-06-15T20:00:00+09:00"` → `"2026-06-15T11:00:00Z"`（UTC 化）
    - `"2026-06-15T11:00:00Z"` → そのまま
    - `"2026-06-15T11:00:00"`（naive） → そのまま（ローカル TZ 仮定）

    Args:
        value: ISO 8601 形式の文字列。

    Returns:
        UTC（Z 終端）に正規化された ISO 8601 文字列。パース失敗時は入力をそのまま返す。
    """
    if not isinstance(value, str):
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        # naive datetime は API 側でローカルとして解釈される可能性がある。
        # ここでは入力を尊重しそのまま返す（呼び出し側で TZ aware にする責務）。
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


from youtube_automation.agents._complete_collection_strategy import CompleteCollectionMixin  # noqa: E402
from youtube_automation.agents._dedup_search import DedupSearchMixin  # noqa: E402
from youtube_automation.agents._descriptions_md import DescriptionsMdMixin  # noqa: E402
from youtube_automation.agents._preflight import PreflightMixin  # noqa: E402
from youtube_automation.agents._uploader_constants import (  # noqa: E402
    UPLOAD_SOURCE_EXISTING,
    UPLOAD_SOURCE_NEW,
    YOUTUBE_VIDEO_URL_PREFIX,
)
from youtube_automation.utils.channel_settings import build_upload_status_flags  # noqa: E402
from youtube_automation.utils.config import channel_dir, load_config  # noqa: E402
from youtube_automation.utils.metadata_generator import BAHMetadataGenerator  # noqa: E402
from youtube_automation.utils.preflight_checks import check_title_codepoint_limit  # noqa: E402
from youtube_automation.utils.publish_schedule import (  # noqa: E402
    resolve_default_publish_at as _resolve_default_publish_at,
)
from youtube_automation.utils.upload_core import YouTubeUploadCore  # noqa: E402

# 後方互換 / 公開 API: 定数は従来どおり本モジュールから import できるよう再エクスポートする。
__all__ = [
    "YouTubeAutoUploader",
    "UPLOAD_SOURCE_EXISTING",
    "UPLOAD_SOURCE_NEW",
    "YOUTUBE_VIDEO_URL_PREFIX",
    "main",
]


class YouTubeAutoUploader(
    CompleteCollectionMixin,
    DedupSearchMixin,
    DescriptionsMdMixin,
    PreflightMixin,
    YouTubeUploadCore,
):
    """YouTube自動アップロードメインクラス

    YouTubeUploadCore を継承し、コレクション単位のアップロード機能を提供する。
    コアのアップロード・サムネイル・リトライロジックは YouTubeUploadCore に委譲。
    責務別のロジック（dedup / descriptions.md / preflight / CC 経路）は mixin に分離。
    """

    def __init__(self, collections_root: str = None):
        """
        初期化

        Args:
            collections_root (str): collections/ ディレクトリのパス
        """
        super().__init__()

        if collections_root is None:
            collections_root = channel_dir() / "collections"

        self.collections_root = Path(collections_root)

    @property
    def youtube_service(self):
        """後方互換: youtube_service は youtube の別名"""
        return self.youtube

    @youtube_service.setter
    def youtube_service(self, value):
        self.youtube = value

    def upload_video(
        self,
        video_path: str,
        metadata: Dict,
        thumbnail_path: str = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Optional[str]:
        """
        メタデータ辞書から YouTube API ボディを構築してアップロード

        Args:
            video_path (str): 動画ファイルパス
            metadata (Dict): メタデータ（title, description, tags, privacy_status 等）
            thumbnail_path (str): サムネイルファイルパス
            resume_session_uri: 前回中断時の resumable upload session URI
            on_session_uri_changed: session URI 変化通知コールバック
            on_upload_complete: アップロード成功通知コールバック

        Returns:
            str: アップロードされた動画のID（失敗時はNone）
        """
        # タイトル長バリデーション（YouTube上限100 codepoint）
        title = metadata.get("title", "")
        if msg := check_title_codepoint_limit(title):
            raise ValueError(msg)

        # リクエストボディ作成
        # AI 開示（containsSyntheticMedia）/ 子供向け申告（selfDeclaredMadeForKids）は
        # config/channel/youtube.json で上書き可能。未設定時は現行の振る舞い
        # （synthetic=True / made_for_kids=False）を維持する (#605)。
        # AI 生成音楽（Lyria / Suno）を主軸とするチャンネルは YouTube の AI 開示
        # （altered or synthetic content）ポリシー上 true を申告する (#603)。
        status_body = {
            "privacyStatus": metadata.get("privacy_status", "private"),
            **build_upload_status_flags(load_config().youtube.api),
        }

        # スケジュール公開: publishAt 指定時は private 必須
        # YouTube Data API は ISO 8601 形式を要求する。`+09:00` のような
        # timezone offset 付き値も受け付けるが、明示的に Z 終端の UTC へ
        # 変換しておくと不要な失敗を避けられる（#647 予約投稿不発の再発防止）。
        if metadata.get("publish_at"):
            normalized = _normalize_publish_at(metadata["publish_at"])
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = normalized
            logger.info(f"スケジュール公開（private + publishAt={normalized}）")
        else:
            # publishAt 未指定でユーザーが privacy_status="public" を明示している場合、
            # その動画は即時公開される。スケジュール公開を期待していたユーザー向けの
            # 早期可視化として INFO ログを残す（#647）。
            if status_body.get("privacyStatus") == "public":
                logger.info("即時公開: status.privacyStatus=public でアップロードします")

        body = {
            "snippet": {
                "title": metadata["title"],  # YouTube上限100文字
                "description": metadata["description"][:5000],  # YouTube上限5000文字
                "tags": metadata["tags"][:50],  # YouTube上限50タグ
                "categoryId": metadata.get("category_id", "10"),
                "defaultLanguage": metadata.get("language", "en"),
                "defaultAudioLanguage": metadata.get("language", "en"),
            },
            "status": status_body,
        }

        if metadata.get("localizations"):
            body["localizations"] = metadata["localizations"]

        return super().upload_video(
            video_path,
            body,
            thumbnail_path,
            resume_session_uri=resume_session_uri,
            on_session_uri_changed=on_session_uri_changed,
            on_upload_complete=on_upload_complete,
        )

    def upload_collection(
        self,
        collection_path: str,
        publish_at: str = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Dict:
        """
        Complete Collection のアップロード

        Args:
            collection_path (str): コレクションディレクトリパス
            publish_at (str): スケジュール公開日時（ISO 8601）
            resume_session_uri: 前回中断時の resumable upload session URI
            on_session_uri_changed: session URI 変化通知コールバック
            on_upload_complete: アップロード成功通知コールバック

        Returns:
            Dict: アップロード結果
        """
        collection_dir = Path(collection_path)
        if not collection_dir.exists():
            raise FileNotFoundError(f"コレクションディレクトリが見つかりません: {collection_path}")

        self._log_active_channel()
        logger.info(f"🎵 コレクションアップロード開始: {collection_dir.name}")
        logger.info(f"📁 パス: {collection_dir}")

        if publish_at is None:
            publish_at = _resolve_default_publish_at(load_config())
            if publish_at:
                logger.info(f"チャンネル既定の予約投稿時刻を適用: publish_at={publish_at}")

        # アップロード前メタデータ検証
        self._preflight_check(collection_dir)

        # メタデータ生成器初期化
        metadata_gen = BAHMetadataGenerator(str(collection_dir))

        results = {
            "collection_name": metadata_gen.collection_name,
            "collection_path": str(collection_dir),
            "start_time": datetime.now(),
            "complete_video": None,
            "errors": [],
        }

        # Complete Collection アップロード
        complete_result = self._upload_complete_collection(
            collection_dir,
            metadata_gen,
            publish_at=publish_at,
            resume_session_uri=resume_session_uri,
            on_session_uri_changed=on_session_uri_changed,
            on_upload_complete=on_upload_complete,
        )
        results["complete_video"] = complete_result

        results["end_time"] = datetime.now()
        results["duration"] = results["end_time"] - results["start_time"]

        # 結果レポート
        self._print_upload_report(results)

        return results

    def _log_active_channel(self) -> None:
        """誤投稿防止のため、現在操作対象のチャンネルを明示表示する。"""
        config = load_config()
        parts = [config.meta.channel_name]
        if config.meta.youtube_handle:
            parts.append(config.meta.youtube_handle)
        if config.meta.channel_id:
            parts.append(config.meta.channel_id)
        logger.info(f"🎯 操作中チャンネル: {' / '.join(parts)}")

    def _print_upload_report(self, results: Dict):
        """アップロード結果レポート表示"""
        logger.info("📊 YouTube アップロード結果レポート")
        logger.info(f"🎵 コレクション: {results['collection_name']}")
        logger.info(f"📁 パス: {results['collection_path']}")
        logger.info(f"⏱️  実行時間: {results['duration']}")
        logger.info(f"📅 実行日時: {results['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")

        # Complete Collection 結果
        if results["complete_video"]:
            if "video_id" in results["complete_video"]:
                if results["complete_video"].get("upload_source") == UPLOAD_SOURCE_EXISTING:
                    logger.info(f"⏭️  Complete Collection: 既存動画を流用 {results['complete_video']['video_url']}")
                else:
                    logger.info(f"✅ Complete Collection: {results['complete_video']['video_url']}")
                    self._print_post_upload_manual_checklist(results["complete_video"]["video_url"])
            else:
                logger.error(f"❌ Complete Collection: {results['complete_video']['error']}")

    def _print_post_upload_manual_checklist(self, video_url: str) -> None:
        """YouTube Studio で手動確認が必要な項目をアップロード直後に表示する。"""
        logger.info("📝 アップロード後の手動チェックリスト")
        logger.info("  [ ] YouTube Studio で AI コンテンツの開示設定を確認")
        logger.info("  [ ] YouTube Studio で収益化が ON になっているか確認")
        logger.info(f"  Studio: https://studio.youtube.com/video/{video_url.rsplit('=', 1)[-1]}/edit")

    def process_collections_directory(self, status_filter: List[str] = None) -> Dict:
        """
        collections/ ディレクトリ内の対象コレクションを一括処理

        Args:
            status_filter (List[str]): 処理対象ステータス（例: ['ready']）

        Returns:
            Dict: 全体の処理結果
        """
        if status_filter is None:
            status_filter = ["ready"]  # デフォルトはready状態のみ

        config = load_config()
        logger.info(f"🎵 {config.meta.channel_name} - 一括YouTube アップロード")
        logger.info(f"📁 collections ディレクトリ: {self.collections_root}")
        logger.info(f"🎯 対象ステータス: {status_filter}")

        # 対象コレクション検索
        target_collections = []

        for status in status_filter:
            status_dir = self.collections_root / status
            if status_dir.exists():
                collections = [d for d in status_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
                target_collections.extend([(status, col) for col in collections])

        if not target_collections:
            logger.error("❌ 処理対象のコレクションが見つかりません")
            return {"error": "処理対象コレクションなし"}

        logger.info(f"📋 処理対象: {len(target_collections)}コレクション")

        all_results = {
            "start_time": datetime.now(),
            "target_collections": len(target_collections),
            "results": [],
            "summary": {"success": 0, "error": 0},
        }

        # 各コレクションを処理
        for i, (status, collection_dir) in enumerate(target_collections, 1):
            logger.info(f"🎵 [{i}/{len(target_collections)}] {collection_dir.name}")

            try:
                result = self.upload_collection(str(collection_dir))
                all_results["results"].append(result)

                # 成功判定
                has_success = bool(result.get("complete_video", {}).get("video_id"))

                if has_success:
                    all_results["summary"]["success"] += 1
                    # ready -> live への移動（オプション）
                    # self._move_collection_to_live(collection_dir)
                else:
                    all_results["summary"]["error"] += 1

            except Exception as e:
                error_msg = f"コレクション処理エラー {collection_dir.name}: {e}"
                logger.error(f"❌ {error_msg}")
                all_results["results"].append({"collection_name": collection_dir.name, "error": error_msg})
                all_results["summary"]["error"] += 1

        all_results["end_time"] = datetime.now()
        all_results["duration"] = all_results["end_time"] - all_results["start_time"]

        # 全体結果レポート
        self._print_batch_report(all_results)

        return all_results

    def _print_batch_report(self, all_results: Dict):
        """一括処理結果レポート"""
        logger.info("🎉 YouTube 一括アップロード完了レポート")
        logger.info(f"📊 処理結果: {all_results['summary']['success']} 成功 / {all_results['summary']['error']} エラー")
        logger.info(f"⏱️  総実行時間: {all_results['duration']}")
        logger.info(f"📅 実行日時: {all_results['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    """メイン関数"""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = load_config()
    parser = argparse.ArgumentParser(description=f"{config.meta.channel_short} YouTube 自動アップローダー")
    parser.add_argument("--collection", "-c", help="特定コレクションのパス")
    parser.add_argument("--batch", "-b", action="store_true", help="collections/ready/ の一括処理")
    parser.add_argument("--status", "-s", nargs="+", default=["ready"], help="一括処理対象ステータス")

    args = parser.parse_args()

    try:
        uploader = YouTubeAutoUploader()
        uploader.initialize()

        if args.collection:
            # 単一コレクション処理
            uploader.upload_collection(args.collection)
        elif args.batch:
            # 一括処理
            uploader.process_collections_directory(args.status)
        else:
            print("使用法:")
            print("  単一コレクション: python youtube_auto_uploader.py -c path/to/collection")
            print("  一括処理: python youtube_auto_uploader.py --batch")

    except KeyboardInterrupt:
        print("\n🛑 ユーザーによって中断されました")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
