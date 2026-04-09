#!/usr/bin/env python3
"""
YouTube Video Uploader
Complete Collection video upload with thumbnail and playlist creation

Features:
- Video file upload with progress tracking
- Custom thumbnail setting
- Playlist creation and video addition
- Retry logic for error handling
- Detailed status reporting
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


from youtube_automation.utils.channel_config import ChannelConfig  # noqa: E402
from youtube_automation.utils.upload_core import YouTubeUploadCore  # noqa: E402


class VideoUploader(YouTubeUploadCore):
    """YouTube Video Upload Manager (legacy)

    レガシーアップローダー。コアのアップロード・サムネイル・リトライロジックは
    YouTubeUploadCore に委譲。プレイリスト操作メソッドは PlaylistManager が依存
    しているため維持する。
    """

    def __init__(self, auth_dir=None):
        """
        Initialize uploader

        Args:
            auth_dir (str): Authentication directory path (unused, kept for backward compat)
        """
        super().__init__()

    def authenticate(self):
        """Execute OAuth authentication (後方互換エイリアス)"""
        self.initialize()

    def upload_video(
        self,
        video_file: str,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = "10",  # Music category
        privacy_status: str = "public"
    ) -> Optional[Dict]:
        """
        Upload video to YouTube

        Args:
            video_file (str): Path to video file
            title (str): Video title
            description (str): Video description
            tags (List[str]): Video tags
            category_id (str): YouTube category ID (default: 10 for Music)
            privacy_status (str): Privacy status (public/private/unlisted)

        Returns:
            Dict: Upload response with video ID and URL
        """
        logger.info(f"Uploading video: {title}")
        logger.info(f"File: {video_file}")
        logger.info(f"File size: {os.path.getsize(video_file) / (1024*1024):.2f} MB")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": False,
            },
        }

        video_id = super().upload_video(video_file, body)

        if video_id:
            video_url = f"https://youtu.be/{video_id}"
            result = {
                "video_id": video_id,
                "video_url": video_url,
                "title": title,
                "status": "success",
            }
            logger.info(f"Video ID: {video_id}")
            logger.info(f"Video URL: {video_url}")
            return result
        else:
            return {
                "status": "failed",
                "error": "Upload failed",
                "title": title,
            }

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy_status: str = "public"
    ) -> Optional[Dict]:
        """
        Create new playlist

        Args:
            title (str): Playlist title
            description (str): Playlist description
            privacy_status (str): Privacy status (public/private/unlisted)

        Returns:
            Dict: Playlist information with ID and URL
        """
        if not self.youtube:
            self.authenticate()

        logger.info(f"📋 Creating playlist: {title}")

        try:
            # Prepare request body
            body = {
                "snippet": {
                    "title": title,
                    "description": description
                },
                "status": {
                    "privacyStatus": privacy_status
                }
            }

            # Execute playlist creation
            response = self.youtube.playlists().insert(
                part="snippet,status",
                body=body
            ).execute()

            playlist_id = response['id']
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

            result = {
                "playlist_id": playlist_id,
                "playlist_url": playlist_url,
                "title": title,
                "status": "success"
            }

            logger.info("✅ Playlist created successfully")
            logger.info(f"📋 Playlist ID: {playlist_id}")
            logger.info(f"🔗 Playlist URL: {playlist_url}")

            return result

        except Exception as e:
            logger.error(f"❌ Playlist creation failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "title": title
            }

    def add_video_to_playlist(
        self,
        playlist_id: str,
        video_id: str,
        position: int = 0
    ) -> bool:
        """
        Add video to playlist

        Args:
            playlist_id (str): Playlist ID
            video_id (str): Video ID to add
            position (int): Position in playlist (0 = first)

        Returns:
            bool: Success status
        """
        if not self.youtube:
            self.authenticate()

        logger.info(f"➕ Adding video {video_id} to playlist {playlist_id}")

        try:
            # Prepare request body
            body = {
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    },
                    "position": position
                }
            }

            # Execute playlist item insertion
            self.youtube.playlistItems().insert(
                part="snippet",
                body=body
            ).execute()

            logger.info(f"✅ Video added to playlist at position {position}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to add video to playlist: {e}")
            return False


def main():
    """Main function - Upload any collection via CLI arguments"""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f"{config.channel_short} YouTube Video Uploader")
    parser.add_argument("collection_dir", help="Path to collection directory")
    parser.add_argument("--title", required=True, help="Video title")
    parser.add_argument("--playlist-title", help="Playlist title (optional)")
    parser.add_argument("--playlist-description", default="", help="Playlist description")
    parser.add_argument("--privacy", default="public", choices=["public", "private", "unlisted"])
    parser.add_argument("--tags", nargs="+", default=config.default_tags)
    parser.add_argument("--config", help="Path to upload_config.json (overrides other args)")

    args = parser.parse_args()

    print(f"🎮 {config.channel_name} - Video Upload System")
    print("=" * 80)

    # Resolve collection directory
    COLLECTION_DIR = Path(args.collection_dir).resolve()
    if not COLLECTION_DIR.exists():
        print(f"❌ Collection directory not found: {COLLECTION_DIR}")
        sys.exit(1)

    # Load config file if provided
    if args.config:
        with open(args.config, 'r', encoding='utf-8') as f:
            config = json.load(f)
        title = config.get("title", args.title)
        tags = config.get("tags", args.tags)
        playlist_title = config.get("playlist_title", args.playlist_title)
        playlist_description = config.get("playlist_description", args.playlist_description)
        privacy_status = config.get("privacy", args.privacy)
    else:
        title = args.title
        tags = args.tags
        playlist_title = args.playlist_title
        playlist_description = args.playlist_description
        privacy_status = args.privacy

    # File paths (standard collection structure)
    video_file = str(COLLECTION_DIR / "01-master/00-master.mp4")
    description_file = COLLECTION_DIR / "20-documentation/youtube-description-complete-collection.txt"
    thumbnail_file = str(COLLECTION_DIR / "10-assets/thambnaile-base.png")

    try:
        # Load description
        if description_file.exists():
            print(f"\n📄 Loading description from: {description_file}")
            with open(description_file, 'r', encoding='utf-8') as f:
                description = f.read()
        else:
            description = title
            print("⚠️  Description file not found, using title as description")

        # Verify files exist
        print("\n🔍 Verifying files...")
        if not os.path.exists(video_file):
            raise FileNotFoundError(f"Video file not found: {video_file}")
        if not os.path.exists(thumbnail_file):
            print("⚠️  Thumbnail file not found, will skip thumbnail upload")
            thumbnail_file = None
        print("✅ Files verified")

        # Initialize uploader
        auth_dir = Path(__file__).resolve().parent / "auth"
        uploader = VideoUploader(auth_dir=str(auth_dir))
        uploader.authenticate()

        # Upload video
        print("\n" + "=" * 80)
        print("📤 STEP 1: VIDEO UPLOAD")
        print("=" * 80)

        upload_result = uploader.upload_video(
            video_file=video_file,
            title=title,
            description=description,
            tags=tags,
            category_id="10",
            privacy_status=privacy_status,
        )

        if upload_result["status"] != "success":
            print("\n❌ Video upload failed. Aborting.")
            sys.exit(1)

        video_id = upload_result["video_id"]
        video_url = upload_result["video_url"]

        # Set thumbnail
        thumbnail_success = False
        if thumbnail_file:
            print("\n" + "=" * 80)
            print("🖼️  STEP 2: THUMBNAIL UPLOAD")
            print("=" * 80)
            thumbnail_success = uploader.set_thumbnail(video_id, thumbnail_file)

        # Create playlist
        playlist_result = {"status": "skipped"}
        if playlist_title:
            print("\n" + "=" * 80)
            print("📋 STEP 3: PLAYLIST CREATION")
            print("=" * 80)

            playlist_result = uploader.create_playlist(
                title=playlist_title,
                description=playlist_description,
                privacy_status=privacy_status,
            )

            if playlist_result["status"] == "success":
                print("\n" + "=" * 80)
                print("➕ STEP 4: ADD VIDEO TO PLAYLIST")
                print("=" * 80)
                uploader.add_video_to_playlist(
                    playlist_id=playlist_result["playlist_id"],
                    video_id=video_id,
                    position=0,
                )

        # Final report
        print("\n" + "=" * 80)
        print("✅ UPLOAD COMPLETE - FINAL REPORT")
        print("=" * 80)
        print(f"\n📺 Video: {title}")
        print(f"   ID: {video_id} | URL: {video_url}")
        print(f"   Thumbnail: {'✅ Set' if thumbnail_success else '⏭️ Skipped'}")

        if playlist_result.get("status") == "success":
            print(f"\n📋 Playlist: {playlist_title}")
            print(f"   URL: {playlist_result['playlist_url']}")

        # Save upload tracking
        tracking_file = COLLECTION_DIR / "20-documentation/upload_tracking.json"
        tracking_file.parent.mkdir(parents=True, exist_ok=True)
        tracking_data = {
            "upload_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "video": upload_result,
            "playlist": playlist_result if playlist_result.get("status") == "success" else None,
            "thumbnail_set": thumbnail_success,
        }
        with open(tracking_file, 'w', encoding='utf-8') as f:
            json.dump(tracking_data, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Upload tracking saved: {tracking_file}")
        print("\n🎉 All operations completed successfully!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
