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
"""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


from youtube_automation.utils.collection_paths import CollectionPaths  # noqa: E402
from youtube_automation.utils.config import channel_dir, load_config  # noqa: E402
from youtube_automation.utils.metadata_generator import BAHMetadataGenerator  # noqa: E402
from youtube_automation.utils.preflight_checks import (  # noqa: E402
    check_chapter_count,
    check_chapter_variation_suffix,
    check_duration,
    check_tags_count,
    check_tags_yt_chars,
    extract_descriptions_md_tags,
)
from youtube_automation.utils.probe import probe_duration  # noqa: E402
from youtube_automation.utils.upload_core import YouTubeUploadCore  # noqa: E402

UPLOAD_SOURCE_EXISTING = "existing_video"
UPLOAD_SOURCE_NEW = "new_upload"
YOUTUBE_VIDEO_URL_PREFIX = "https://www.youtube.com/watch?v="
_REUSABLE_UPLOAD_STATUSES = {"processed", "uploaded"}


class YouTubeAutoUploader(YouTubeUploadCore):
    """YouTube自動アップロードメインクラス

    YouTubeUploadCore を継承し、コレクション単位のアップロード機能を提供する。
    コアのアップロード・サムネイル・リトライロジックは YouTubeUploadCore に委譲。
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
        # タイトル長バリデーション（YouTube上限100文字）
        title = metadata.get("title", "")
        if len(title) > 100:
            raise ValueError(f"タイトルが100文字を超えています（{len(title)}文字）: {title}")

        # リクエストボディ作成
        status_body = {
            "privacyStatus": metadata.get("privacy_status", "private"),
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": False,
        }

        # スケジュール公開: publishAt 指定時は private 必須
        if metadata.get("publish_at"):
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = metadata["publish_at"]
            logger.info(f"スケジュール公開: {metadata['publish_at']}")

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

    def _find_existing_video_by_title(self, title: str) -> Optional[Dict[str, str]]:
        """own channel 内に同タイトル（完全一致）の動画があれば video_id / video_url を返す。

        publish 直前の dedup 安全網。session URI 持ち越し（一次対策）が破れた場合の
        二次防衛線として、`videos().insert()` を呼ぶ前に既存動画の有無を確認する。
        search index は eventual-consistent なため、候補 ID は videos.list で再検証する。

        Args:
            title: 完全一致で検索するタイトル文字列

        Returns:
            hit: `{"video_id": ..., "video_url": ...}` / miss: None / 検索エラー: None（fail-open）
        """
        self._ensure_service()
        try:
            resp = (
                self.youtube.search().list(forMine=True, type="video", q=title, maxResults=10, part="snippet").execute()
            )
            candidate_ids = self._exact_title_video_ids(resp.get("items", []), title)
            if not candidate_ids:
                return None

            videos_response = (
                self.youtube.videos().list(id=",".join(candidate_ids), part="status,snippet").execute()
            )
            return self._first_reusable_video(videos_response.get("items", []), title)
        except HttpError as e:
            # fail-open: 安全網のエラーは upload を block しない（一次対策は session URI 持ち越し）
            logger.warning(f"⚠️  既存動画検索失敗（upload 続行）: {e}")
            return None

    @staticmethod
    def _exact_title_video_ids(items: list[dict], title: str) -> list[str]:
        video_ids = []
        for item in items:
            if item["snippet"]["title"] == title:
                video_ids.append(item["id"]["videoId"])
        return video_ids

    @staticmethod
    def _first_reusable_video(videos: list[dict], title: str) -> Optional[Dict[str, str]]:
        for video in videos:
            if not YouTubeAutoUploader._is_reusable_exact_title_video(video, title):
                continue
            video_id = video["id"]
            return {
                "video_id": video_id,
                "video_url": f"{YOUTUBE_VIDEO_URL_PREFIX}{video_id}",
            }
        return None

    @staticmethod
    def _is_reusable_exact_title_video(video: dict, title: str) -> bool:
        upload_status = video.get("status", {}).get("uploadStatus")
        return video["snippet"]["title"] == title and upload_status in _REUSABLE_UPLOAD_STATUSES

    def _load_descriptions_md(self, collection_dir: Path) -> dict | None:
        """descriptions.md から事前生成メタデータを読み込み

        /video-description スキルが生成した descriptions.md が存在する場合、
        title / description / tags を抽出して返す。
        ファイルが存在しない or パース失敗時は None（BAHMetadataGenerator にフォールバック）。
        """
        paths = CollectionPaths(collection_dir)
        desc_path = paths.descriptions_md_path
        if not desc_path.exists():
            # 過去事例: description.txt 等の別名でもファイルが存在し、
            # その場合 fallback 経路で「Track 01」のような汎用名が
            # アップロードされてしまった。意図しないフォールバックを早期発見する。
            stray = list(paths.docs_dir.glob("description*"))
            if stray:
                raise RuntimeError(
                    f"descriptions.md が無いのに別名ファイルが存在します: "
                    f"{[p.name for p in stray]}\n"
                    f"→ ファイル名は `descriptions.md` 固定。リネームして /video-description を再実行してください"
                )
            return None

        text = desc_path.read_text(encoding="utf-8")

        title = self._extract_md_section(text, "タイトル案")
        description = self._extract_md_section(text, "Complete Collection 概要欄")
        tags_raw = self._extract_md_section(text, "タグ（YouTube タグ欄）")

        if not (title and description):
            logger.warning("⚠️  descriptions.md のパースに失敗 — BAHMetadataGenerator にフォールバック")
            return None

        tags = [t.strip() for t in tags_raw.replace("\n", ",").split(",") if t.strip()] if tags_raw else []

        logger.info("📄 descriptions.md からメタデータを読み込み")
        return {"title": title.strip(), "description": description.strip(), "tags": tags}

    @staticmethod
    def _extract_body_for_localizations(description: str) -> str | None:
        """キュレーション済み概要欄からタイムスタンプ部分を抽出

        ローカライゼーション用: トラックリスト（タイムスタンプ行）のみを返す。
        概要欄の他セクションは generate_localizations() がテンプレートから構築する。
        """
        import re

        lines = description.split("\n")
        timestamp_lines = [line for line in lines if re.match(r"^\d{1,2}:\d{2}", line.strip())]
        return "\n".join(timestamp_lines) if timestamp_lines else None

    @staticmethod
    def _extract_md_section(text: str, heading: str) -> str | None:
        """Markdown の ## heading 直後のコードフェンス内容を抽出"""
        pattern = rf"## {re.escape(heading)}\s*\n+```\n(.*?)```"
        m = re.search(pattern, text, re.DOTALL)
        return m.group(1).strip() if m else None

    def _preflight_check(self, collection_dir: Path) -> None:
        """アップロード前メタデータ品質チェック (fail-loud)。

        過去事例の再発防止:
        1. descriptions.md が存在すること（Track 01 仮名フォールバックを防ぐ）
        2. workflow-state.json.scene_phrases に EN + 全 supported_languages が
           揃っていること（多言語タイトルが EN ベタコピーになる事故を防ぐ）
        3. タイムスタンプ件数が `audio.chapter_max` 以内かつ chapter 名に
           パターン展開接尾辞（v1〜v6 / ロマン数字 I〜VIII）を含まないこと
           （個別トラック = 1 chapter の per-track 命名はデフォルトで許容）
        4. タイトルが 100 codepoint 以内（YouTube 制限）
        5. タグ件数が `tags.min_count` を満たすこと（戦略書違反防止）
        6. タグの quotation 込み文字数が YouTube の 500 制限内
        7. master 動画尺が `audio.target_duration_min/max` 範囲内
        """
        paths = CollectionPaths(collection_dir)
        desc_path = paths.descriptions_md_path
        if not desc_path.exists():
            raise RuntimeError(f"❌ {desc_path} が存在しません。/video-description を実行してください。")

        text = desc_path.read_text(encoding="utf-8")
        title = (self._extract_md_section(text, "タイトル案") or "").strip()
        description = (self._extract_md_section(text, "Complete Collection 概要欄") or "").strip()

        if not title or not description:
            raise RuntimeError(f"❌ {desc_path}: タイトル案 / Complete Collection 概要欄 が空")

        if len(title) > 100:
            raise RuntimeError(f"❌ タイトルが {len(title)} codepoint。YouTube 制限 100 を超過。\n  {title}")

        config = load_config()

        # タイムスタンプ粒度検証
        ts_lines = [line for line in description.split("\n") if re.match(r"^\d{1,2}:\d{2}", line.strip())]
        if len(ts_lines) < 3:
            raise RuntimeError(f"❌ タイムスタンプ {len(ts_lines)} 個 (最低 3 必要)")
        msg = check_chapter_count(len(ts_lines), config.audio.chapter_max)
        if msg:
            raise RuntimeError(f"❌ {msg}。config.audio.chapter_max を見直してください。")
        msg = check_chapter_variation_suffix(ts_lines)
        if msg:
            raise RuntimeError(f"❌ {msg}: 1 パターン = 1 chapter で再生成してください。")

        # scene_phrases 完全性検証
        ws_path = paths.workflow_state_path
        state = json.loads(ws_path.read_text(encoding="utf-8")) if ws_path.exists() else {}
        scene_phrases = state.get("scene_phrases") or {}

        required_langs = ["en"] + list(config.localizations.supported_languages)
        missing = [lang for lang in required_langs if not scene_phrases.get(lang)]
        if missing:
            raise RuntimeError(
                f"❌ workflow-state.json.scene_phrases に翻訳が不足: {missing}\n"
                f"→ /video-description で多言語翻訳を含めて再生成してください。\n"
                f"→ 既存例: collections/live/20260322-rjn-city-collection/workflow-state.json"
            )

        # タグ件数 / quotation 文字数チェック
        # descriptions.md の「タグ（YouTube タグ欄）」が _upload_complete_collection で
        # for_collection() を上書きするため、本番と同じソースを検証する。
        prebuilt_tags = extract_descriptions_md_tags(desc_path)
        tags = prebuilt_tags if prebuilt_tags is not None else config.content.tags.for_collection(collection_dir.name)
        issues: list[str] = []
        for msg in (
            check_tags_count(tags, config.content.tags.min_count),
            check_tags_yt_chars(tags),
        ):
            if msg:
                issues.append(msg)

        # 動画尺チェック（target_duration が設定済みかつ master mp4 が存在する場合のみ）
        if config.audio.target_duration_min is not None or config.audio.target_duration_max is not None:
            master_video = paths.find_master_video()
            if master_video:
                dur = probe_duration(master_video)
                if dur is None:
                    issues.append(f"duration probe failed for {master_video.name}")
                else:
                    msg = check_duration(
                        dur,
                        config.audio.target_duration_min,
                        config.audio.target_duration_max,
                    )
                    if msg:
                        issues.append(msg)

        if issues:
            raise RuntimeError("❌ preflight failed:\n  - " + "\n  - ".join(issues))

        logger.info(f"✅ preflight OK — title={len(title)}c, chapters={len(ts_lines)}, langs={len(scene_phrases)}")

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

        logger.info(f"🎵 コレクションアップロード開始: {collection_dir.name}")
        logger.info(f"📁 パス: {collection_dir}")

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

    def _upload_complete_collection(
        self,
        collection_dir: Path,
        metadata_gen: BAHMetadataGenerator,
        publish_at: str = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Optional[Dict]:
        """Complete Collection 動画アップロード"""
        logger.info("📹 Complete Collection アップロード準備中...")

        paths = CollectionPaths(collection_dir)

        # マスター動画ファイル検索
        video_files = list(paths.movie_dir.glob("*master*.mp4"))
        if not video_files:
            video_files = list(paths.master_dir.glob("*.mp4"))

        if not video_files:
            error_msg = "マスター動画ファイルが見つかりません"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}

        master_video = video_files[0]

        # メタデータ生成（BAHMetadataGenerator — localizations 等）
        metadata = metadata_gen.generate_complete_collection_metadata()

        # descriptions.md が存在すれば title/description/tags を上書き
        prebuilt = self._load_descriptions_md(collection_dir)
        if prebuilt:
            metadata["title"] = prebuilt["title"]
            metadata["description"] = prebuilt["description"]
            if prebuilt["tags"]:
                metadata["tags"] = prebuilt["tags"]

            # ローカライゼーションにもキュレーション済みのタイムスタンプを使用
            curated_timestamps = self._extract_body_for_localizations(prebuilt["description"])
            scene_phrases = getattr(metadata_gen, "_last_scene_phrases", {})
            scene_emoji = metadata_gen._load_scene_emoji()
            if curated_timestamps:
                metadata["localizations"] = metadata_gen.generate_localizations(
                    metadata["title"], curated_timestamps, scene_phrases, scene_emoji=scene_emoji
                )

        if publish_at:
            metadata["publish_at"] = publish_at

        # サムネイル検索（thumbnail.jpg を優先）
        thumbnail_path = None
        for tn in ["thumbnail.jpg", "thumbnail.png", "main.jpg", "main.png"]:
            candidate = paths.assets_dir / tn
            if candidate.exists():
                thumbnail_path = str(candidate)
                break

        # publish 直前の dedup 安全網: 同タイトル動画が own channel に既に存在すれば
        # `videos().insert()` を呼ばず既存 video_id を採用する
        existing = self._find_existing_video_by_title(metadata["title"])
        if existing:
            logger.info(f"⚠️  既存動画を検出（upload skip）: {existing['video_url']}")
            return {
                "video_id": existing["video_id"],
                "video_url": existing["video_url"],
                "upload_source": UPLOAD_SOURCE_EXISTING,
                "title": metadata["title"],
                "file_path": str(master_video),
                "thumbnail_path": thumbnail_path,
            }

        # アップロード実行
        video_id = self.upload_video(
            str(master_video),
            metadata,
            thumbnail_path,
            resume_session_uri=resume_session_uri,
            on_session_uri_changed=on_session_uri_changed,
            on_upload_complete=on_upload_complete,
        )

        if video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            return {
                "video_id": video_id,
                "video_url": video_url,
                "upload_source": UPLOAD_SOURCE_NEW,
                "title": metadata["title"],
                "file_path": str(master_video),
                "thumbnail_path": thumbnail_path,
            }
        else:
            return {"error": "Complete Collection アップロード失敗"}

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
            else:
                logger.error(f"❌ Complete Collection: {results['complete_video']['error']}")

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
