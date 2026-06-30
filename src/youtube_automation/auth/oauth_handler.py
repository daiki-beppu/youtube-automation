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

import logging
import os
import re
import sys
from pathlib import Path

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from youtube_automation.utils.exceptions import AuthError, ConfigError, YouTubeAPIError

logger = logging.getLogger(__name__)

# `_redact()` で除去する token 値・パターン（モジュール定数として外出し）
_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ya29\.[\w\-]+"),  # Google access token
    re.compile(r"1//[\w\-]+"),  # Google refresh token
    re.compile(r"[\w\-]{20,}\.[\w\-]{20,}\.[\w\-]{20,}"),  # JWT 風 3 セグメント
    re.compile(r"(?i)\b(?:refresh_token|access_token|client_secret|id_token)=[^\s&]+"),
)
# OSError(__str__) の `[Errno N] reason: '<abs path>'` 形式
_OSERRNO_PATH_RE = re.compile(r": '([^']+)'")
_REDACTED_TOKEN = "<redacted-token>"
_REDACTED_PATH = "<redacted-path>"


def _redact(message: str, *paths: object) -> str:
    """ログメッセージから token 値・絶対パスを除去する。

    3 系統のマスクを順に適用する:

    1. ``_OSERRNO_PATH_RE`` で OSErrno 形式 ``: '<abs path>'`` の絶対パスを除去
    2. ``paths`` 引数で渡された ``Path`` / ``str`` を ``os.fspath`` で literal 置換
    3. ``_TOKEN_PATTERNS`` で OAuth token 値 / JWT / 機密 key=value を除去

    呼び出し側は ``self.token_file`` / ``self.client_secrets_file`` のような
    instance 属性をそのまま渡せるよう ``object`` を受ける。
    """
    redacted = _OSERRNO_PATH_RE.sub(f": '{_REDACTED_PATH}'", message)
    for path in paths:
        redacted = redacted.replace(os.fspath(path), _REDACTED_PATH)
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(_REDACTED_TOKEN, redacted)
    return redacted


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

    def __init__(self, auth_dir=None, scopes=None, token_path=None):
        """
        初期化

        Args:
            auth_dir (str): token.json を格納するチャンネル固有 auth ディレクトリのパス
            scopes (list[str] | None): OAuth scopes。未指定時はクラス属性 ``SCOPES``（既存挙動）
            token_path (str | Path | None): token ファイルパス。未指定時は ``<auth_dir>/token.json``。
                stream key 取得用に ``token_streaming.json`` を分離する用途で使用する（issue #135）
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
                except ConfigError:
                    # op read も失敗した場合はデフォルトパスを設定
                    # (_validate_client_secrets で適切なエラーメッセージを表示)
                    self.client_secrets_file = candidates[0]

        # scopes: 未指定時は SCOPES クラス属性（既存 callsite との後方互換）
        self._scopes = list(scopes) if scopes is not None else self.SCOPES

        # auth_dir は従来挙動を維持。未指定なら channel_dir/"auth"
        if auth_dir is None:
            auth_dir = channel_dir / "auth"
        else:
            auth_dir = Path(auth_dir)
        self.auth_dir = auth_dir

        # token_path 指定時はそれを最優先。未指定時は <auth_dir>/token.json
        # （token_path 指定時に auth_dir を上書きしない: 引数の意味を silently 変えない）
        if token_path is not None:
            self.token_file = Path(token_path)
        else:
            self.token_file = self.auth_dir / "token.json"
        self.credentials = None

    def _validate_client_secrets(self):
        """client_secrets.json の存在確認"""
        if not self.client_secrets_file.exists():
            raise FileNotFoundError(
                f"❌ client_secrets.json が見つかりません: {self.client_secrets_file}\n"
                "設定手順:\n"
                "1. Google Cloud Console で YouTube Data API v3 を有効化\n"
                "2. Google Auth Platform > Branding でアプリ情報を保存\n"
                "3. Google Auth Platform > Audience > Test users に OAuth 認証でログインする Google アカウントを追加\n"
                "   (未追加だと初回認証が 403 access_denied で止まります)\n"
                "4. Google Auth Platform > Clients > Create client で Application type Desktop app を作成\n"
                "5. 作成直後の client secret を控えるか JSON をダウンロードし、"
                "<channel_dir>/auth/client_secrets.json に配置\n"
                "6. secret を見失った場合は Clients > 対象 client > Client secrets > Add secret で再発行し、"
                "JSON を再ダウンロード\n"
                "   JSON ダウンロードが表示されない場合は auth/client_secrets_template.json をコピーし、"
                "client_id / project_id / client_secret を手入力\n"
                "   または CLIENT_SECRETS_DIR 環境変数を指定 / 1Password に CLIENT_SECRETS_JSON として登録"
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
                self.credentials = Credentials.from_authorized_user_file(str(self.token_file), self._scopes)
                print("✅ 既存トークン読み込み成功")
            except (OSError, ValueError) as e:
                # 旧トークンが壊れているケースは新規認証へフォールスルーで recovery する
                logger.warning("既存トークン読み込み失敗: %s", _redact(str(e), self.token_file))
                self.credentials = None

        # トークンの有効性確認・更新
        if self.credentials:
            if self.credentials.expired and self.credentials.refresh_token:
                try:
                    print("🔄 トークンの更新中...")
                    self.credentials.refresh(Request())
                    print("✅ トークン更新成功")
                    self._save_credentials()
                except google.auth.exceptions.RefreshError as e:
                    # AuthError を raise すると新規認証へのフォールスルー recovery が壊れる。
                    # credentials=None に落として下の新規認証ブロックで recovery する。
                    logger.warning("token refresh 失敗: %s", _redact(str(e)))
                    self.credentials = None

        # 新規認証が必要な場合
        if not self.credentials or not self.credentials.valid:
            print("🌐 ブラウザで認証を実行します...")
            print("📝 注意: 初回認証時はブラウザが開き、Googleアカウントでのログインが必要です")

            try:
                flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_file), self._scopes)
                self.credentials = flow.run_local_server(port=0)
                print("✅ OAuth 2.0 認証成功")
                self._save_credentials()
            except (ValueError, OSError, google.auth.exceptions.GoogleAuthError) as e:
                logger.error("OAuth 2.0 認証失敗: %s", _redact(str(e), self.client_secrets_file))
                raise AuthError("OAuth 2.0 認証に失敗しました") from e

        return self.credentials

    def _save_credentials(self):
        """認証情報をファイルに 0o600 で保存する。

        プロセス umask に依存せず必ず 0o600 で作成し、既存ファイル上書き時も
        chmod で保険をかける（``O_TRUNC`` は既存ファイルの mode を変更しない）。
        書き込み失敗時は ``ConfigError`` として raise する（握りつぶし禁止 ―
        失敗を黙って成功扱いすると毎回ブラウザ認証が走る運用障害になる）。

        Raises:
            ConfigError: トークンファイルの書き込みに失敗した場合。
        """
        try:
            fd = os.open(self.token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as token:
                token.write(self.credentials.to_json())
            os.chmod(self.token_file, 0o600)  # 既存ファイル上書き時の保険
            print(f"💾 認証トークン保存完了: {self.token_file}")
        except OSError as e:
            raise ConfigError(
                f"認証トークン保存失敗: {self.token_file} ({e})。"
                "親ディレクトリの書き込み権限と空き容量を確認してください。"
            ) from e

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
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "YouTube Data API サービス接続失敗") from e

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

        except (HttpError, AuthError, YouTubeAPIError, google.auth.exceptions.GoogleAuthError, OSError) as e:
            logger.error(
                "API 接続テスト失敗: %s",
                _redact(str(e), self.token_file, self.client_secrets_file),
            )
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

    except KeyboardInterrupt:
        # Ctrl-C: UNIX 慣例 (128 + SIGINT=2 → 130)
        print("\n🛑 処理が中断されました")
        sys.exit(130)
    except (AuthError, ConfigError, YouTubeAPIError, OSError) as e:
        logger.exception("CLI 実行失敗: %s", _redact(str(e)))
        sys.exit(1)
    except Exception as e:  # noqa: BLE001 - CLI top-level panic-handler: exit code 1 で必ず終了させる契約
        # 想定外例外の最終 fallback。traceback は logger.exception が付与し、
        # _redact で token 値・絶対パスの leak を防ぐ。
        logger.exception("CLI 実行中に想定外のエラー: %s", _redact(str(e)))
        sys.exit(1)


if __name__ == "__main__":
    main()
