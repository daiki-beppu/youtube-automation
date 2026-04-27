#!/usr/bin/env python3
"""
YouTube OAuth 2.0 認証ハンドラー
YouTube Data API v3を使用した自動アップロードのための認証システム

Required setup:
1. Google Cloud Console でプロジェクト作成
2. YouTube Data API v3 を有効化
3. OAuth 2.0 認証情報作成
4. client_secrets.json をダウンロードして auth/ に配置
"""

import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


class YouTubeOAuthHandler:
    """YouTube Data API v3 OAuth 2.0 認証管理クラス"""

    # YouTube Full Access + Analytics + Reporting スコープ
    # yt-analytics-monetary.readonly は Reporting API v1 (#84) で
    # videoThumbnailImpressions / videoThumbnailImpressionsClickThroughRate を取得するため必須。
    SCOPES = [
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    ]

    def __init__(self, auth_dir=None):
        """
        初期化

        Args:
            auth_dir (str): token.json を格納するチャンネル固有 auth ディレクトリのパス
        """
        from youtube_automation.utils.config import channel_dir as _channel_dir

        channel_dir = _channel_dir()

        # client_secrets.json の検索順:
        #   1. CLIENT_SECRETS_DIR 環境変数 (明示的オーバーライド)
        #   2. <channel_dir>/auth/client_secrets.json (pip install 時の既定配置)
        #   3. <channel_dir>/automation/auth/client_secrets.json (submodule 互換)
        #   4. 1Password (op read) から動的取得
        client_secrets_dir = os.environ.get("CLIENT_SECRETS_DIR")
        if client_secrets_dir:
            self.client_secrets_file = Path(client_secrets_dir) / "client_secrets.json"
        else:
            candidates = [
                channel_dir / "auth" / "client_secrets.json",
                channel_dir / "automation" / "auth" / "client_secrets.json",
            ]
            found = next((c for c in candidates if c.exists()), None)
            if found:
                self.client_secrets_file = found
            else:
                # ファイルが見つからない場合、1Password から取得を試みる
                try:
                    from youtube_automation.utils.secrets import get_client_secrets_path

                    self.client_secrets_file = get_client_secrets_path()
                except Exception:
                    # op read も失敗した場合はデフォルトパスを設定
                    # (_validate_client_secrets で適切なエラーメッセージを表示)
                    self.client_secrets_file = candidates[0]

        # token.json: チャンネル固有
        if auth_dir is None:
            auth_dir = channel_dir / "auth"
        else:
            auth_dir = Path(auth_dir)
        self.auth_dir = auth_dir
        self.token_file = self.auth_dir / "token.json"
        self.credentials = None

    def _validate_client_secrets(self):
        """client_secrets.json の存在確認"""
        if not self.client_secrets_file.exists():
            raise FileNotFoundError(
                f"❌ client_secrets.json が見つかりません: {self.client_secrets_file}\n"
                "設定手順:\n"
                "1. Google Cloud Console (https://console.cloud.google.com/)\n"
                "2. YouTube Data API v3 を有効化\n"
                "3. OAuth 2.0 認証情報を作成\n"
                "4. client_secrets.json をダウンロード\n"
                "5. <channel_dir>/auth/ に配置 (または CLIENT_SECRETS_DIR 環境変数を指定)\n"
                "   または 1Password に CLIENT_SECRETS_JSON として登録"
            )

    def authenticate(self, force_reauth=False):
        """
        OAuth 2.0 認証実行

        Args:
            force_reauth (bool): 強制再認証フラグ

        Returns:
            Credentials: Google OAuth 2.0 認証情報
        """
        print("🔐 YouTube Data API OAuth 2.0 認証開始...")

        # client_secrets.json の確認
        self._validate_client_secrets()

        # 既存トークンの読み込み
        if not force_reauth and self.token_file.exists():
            try:
                print("📁 既存トークンファイルを確認中...")
                self.credentials = Credentials.from_authorized_user_file(str(self.token_file), self.SCOPES)
                print("✅ 既存トークン読み込み成功")
            except Exception as e:
                print(f"⚠️  既存トークン読み込み失敗: {e}")
                self.credentials = None

        # トークンの有効性確認・更新
        if self.credentials:
            if self.credentials.expired and self.credentials.refresh_token:
                try:
                    print("🔄 トークンの更新中...")
                    self.credentials.refresh(Request())
                    print("✅ トークン更新成功")
                    self._save_credentials()
                except Exception as e:
                    print(f"❌ トークン更新失敗: {e}")
                    print("🔄 新規認証を実行します...")
                    self.credentials = None

        # 新規認証が必要な場合
        if not self.credentials or not self.credentials.valid:
            print("🌐 ブラウザで認証を実行します...")
            print("📝 注意: 初回認証時はブラウザが開き、Googleアカウントでのログインが必要です")

            try:
                flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_file), self.SCOPES)
                self.credentials = flow.run_local_server(port=0)
                print("✅ OAuth 2.0 認証成功")
                self._save_credentials()
            except Exception as e:
                print(f"❌ OAuth 2.0 認証失敗: {e}")
                raise

        return self.credentials

    def _save_credentials(self):
        """認証情報をファイルに保存"""
        try:
            with open(self.token_file, "w") as token:
                token.write(self.credentials.to_json())
            print(f"💾 認証トークン保存完了: {self.token_file}")
        except Exception as e:
            print(f"❌ 認証トークン保存失敗: {e}")

    def get_youtube_service(self):
        """
        YouTube Data API サービスオブジェクト取得

        Returns:
            googleapiclient.discovery.Resource: YouTube API サービス
        """
        if not self.credentials:
            self.authenticate()

        try:
            service = build("youtube", "v3", credentials=self.credentials)
            print("✅ YouTube Data API サービス接続成功")
            return service
        except Exception as e:
            print(f"❌ YouTube Data API サービス接続失敗: {e}")
            raise

    def test_connection(self):
        """
        API接続テスト

        Returns:
            bool: 接続成功可否
        """
        try:
            service = self.get_youtube_service()
            # チャンネル情報取得でテスト
            response = service.channels().list(part="snippet,statistics", mine=True).execute()

            if response["items"]:
                channel = response["items"][0]
                channel_title = channel["snippet"]["title"]
                subscriber_count = channel["statistics"].get("subscriberCount", "N/A")
                print("✅ API接続テスト成功")
                print(f"📺 チャンネル名: {channel_title}")
                print(f"👥 登録者数: {subscriber_count}")
                return True
            else:
                print("❌ チャンネル情報が取得できませんでした")
                return False

        except Exception as e:
            print(f"❌ API接続テスト失敗: {e}")
            return False


def main():
    """メイン関数 - スタンドアロン実行用"""
    print("🎵 YouTube OAuth 2.0 認証テスト")
    print("=" * 60)

    try:
        # OAuth ハンドラー初期化
        auth_handler = YouTubeOAuthHandler()

        # 認証実行
        auth_handler.authenticate()

        # 接続テスト
        if auth_handler.test_connection():
            print("\n🎉 認証・接続テスト完了！YouTube自動アップロードの準備ができました。")
        else:
            print("\n❌ 接続テストに失敗しました。設定を確認してください。")

    except Exception as e:
        print(f"\n❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
