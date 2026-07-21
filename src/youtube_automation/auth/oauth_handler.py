#!/usr/bin/env python3
"""
YouTube OAuth 2.0 認証ハンドラー
YouTube Data API v3を使用した自動アップロードのための認証システム

Required setup:
1. Google Cloud Console でプロジェクト作成
2. YouTube Data API v3 を有効化
3. Google Auth Platform で Desktop app client を作成
4. Client secrets > Add secret で発行後に Download JSON を実行し、
   yt-doctor --fix-client-secrets で auth/client_secrets.json へ移動
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import ClassVar

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from youtube_automation.utils.config import find_workspace_root, workspace_channels
from youtube_automation.utils.exceptions import AuthError, ConfigError, ValidationError, YouTubeAPIError
from youtube_automation.utils.worktree import main_worktree_root

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


def client_secrets_file_candidates(channel_dir: Path) -> list[Path]:
    """ファイルとして配置された client_secrets.json の候補を検索順で返す。"""
    client_secrets_dir = os.environ.get("CLIENT_SECRETS_DIR")
    if client_secrets_dir:
        return [Path(client_secrets_dir) / "client_secrets.json"]
    candidates = [
        channel_dir / "auth" / "client_secrets.json",
        channel_dir / "automation" / "auth" / "client_secrets.json",
    ]
    workspace_root = find_workspace_root(channel_dir)
    if workspace_root is not None and channel_dir.resolve() in {
        path.resolve() for path in workspace_channels(workspace_root).values()
    }:
        candidates.append(workspace_root / "auth" / "client_secrets.json")
    # git worktree では gitignore された auth/ が複製されないため、
    # main 作業ツリー側の実体を最後のフォールバックとして参照する（#1721）
    main_root = main_worktree_root(channel_dir)
    if main_root is not None:
        candidates.append(main_root / "auth" / "client_secrets.json")
    return candidates


def resolve_client_secrets_location(channel_dir: Path) -> tuple[str, Path]:
    """client_secrets の解決元を判定する。

    Returns:
        tuple[kind, path]:
        - ``file``: path に既存ファイルがある
        - ``invalid-file``: path は存在するが通常ファイルではない
        - ``missing-file``: 明示 path を検査すべきだが未配置
        - ``secret-fallback``: 1Password / CLIENT_SECRETS_JSON fallback を試す
    """
    candidates = client_secrets_file_candidates(channel_dir)
    for candidate in candidates:
        if not candidate.exists():
            continue
        if candidate.is_file():
            return "file", candidate
        return "invalid-file", candidate
    if os.environ.get("CLIENT_SECRETS_DIR"):
        return "missing-file", candidates[0]
    return "secret-fallback", candidates[0]


def resolve_client_secrets_source(channel_dir: Path | None = None) -> tuple[Path, dict[str, object] | None]:
    """client_secrets の表示用パスと任意の in-memory config を解決する。"""
    if channel_dir is None:
        from youtube_automation.utils.config import channel_dir as _channel_dir

        channel_dir = _channel_dir()

    kind, path = resolve_client_secrets_location(channel_dir)
    if kind in {"file", "invalid-file", "missing-file"}:
        return path, None

    try:
        from youtube_automation.utils.secrets import get_client_secrets_config

        return path, get_client_secrets_config()
    except ConfigError:
        return path, None


def resolve_client_secrets_path(channel_dir: Path | None = None) -> Path:
    """後方互換のため client_secrets の表示用パスだけを返す。"""
    return resolve_client_secrets_source(channel_dir)[0]


def _validate_client_secrets_data(data: dict[str, object]) -> None:
    """Google Desktop app 用 client_secrets の JSON 形状を検証する。"""
    installed = data.get("installed")
    if not isinstance(installed, dict):
        raise ValidationError("Desktop app の client_secrets.json が必要です: installed セクションがありません")
    required_keys = ("client_id", "client_secret", "redirect_uris")
    missing = [key for key in required_keys if key not in installed]
    if missing:
        raise ValidationError(f"client_secrets.json に必須キー不足: {','.join(missing)}")


class YouTubeOAuthHandler:
    """YouTube Data API v3 OAuth 2.0 認証管理クラス"""

    # YouTube Full Access + Analytics + Reporting スコープ
    # yt-analytics-monetary.readonly は Reporting API v1 (#84) で
    # videoThumbnailImpressions / videoThumbnailImpressionsClickThroughRate を取得するため必須。
    SCOPES: ClassVar[list[str]] = [
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    ]

    # read-only skill（analytics-collect / benchmark / channel-status 等）用の
    # 最小権限スコープ。write 系（youtube / youtube.force-ssl）を含めない。
    # token 漏洩時の blast radius を読み取りに限定する（#1699）。
    READONLY_SCOPES: ClassVar[list[str]] = [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    ]

    # read-only token のファイル名。全 scope の token.json・stream 専用の
    # token_streaming.json（#135）と並ぶ第 3 の用途別 token（#1699）
    READONLY_TOKEN_FILENAME: ClassVar[str] = "token.readonly.json"

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
        self._channel_dir = channel_dir

        self.client_secrets_file, self._client_secrets_config = resolve_client_secrets_source(channel_dir)

        # scopes: 未指定時は SCOPES クラス属性（既存 callsite との後方互換）
        self._scopes = list(scopes) if scopes is not None else self.SCOPES

        # auth_dir は従来挙動を維持。未指定なら channel_dir/"auth"
        # ただし worktree でローカル token.json が無い場合は main 側 auth/ を
        # 読み書き対象にする（refresh 結果を main に集約し分岐を防ぐ。#1721）
        if auth_dir is None:
            auth_dir = channel_dir / "auth"
            if not (auth_dir / "token.json").exists():
                main_root = main_worktree_root(channel_dir)
                if main_root is not None:
                    auth_dir = main_root / "auth"
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

    @classmethod
    def readonly_token_path(cls) -> Path | None:
        """発行済み ``token.readonly.json`` の実体パスを返す（未発行なら None）。

        検索順は ``token.json`` の worktree フォールバック（#1721）と同じ:
        channel 側 ``auth/`` → main worktree 側 ``auth/``。
        handler を生成せずファイル存在だけで判定できるよう classmethod にしている
        （client_secrets 解決や 1Password 参照を発行チェックの副作用にしない）。
        """
        from youtube_automation.utils.config import channel_dir as _channel_dir

        channel = _channel_dir()
        local = channel / "auth" / cls.READONLY_TOKEN_FILENAME
        if local.exists():
            return local
        main_root = main_worktree_root(channel)
        if main_root is not None:
            candidate = main_root / "auth" / cls.READONLY_TOKEN_FILENAME
            if candidate.exists():
                return candidate
        return None

    @classmethod
    def create_readonly(cls) -> "YouTubeOAuthHandler":
        """read-only スコープ + ``token.readonly.json`` のハンドラーを生成する。

        未発行時の保存先は ``token.json`` と同じ規則で解決する
        （worktree にローカル token が無ければ main 側 ``auth/`` に集約。#1721）。
        """
        token_path = cls.readonly_token_path()
        if token_path is None:
            from youtube_automation.utils.config import channel_dir as _channel_dir

            channel = _channel_dir()
            auth_dir = channel / "auth"
            main_root = main_worktree_root(channel)
            if main_root is not None:
                auth_dir = main_root / "auth"
            token_path = auth_dir / cls.READONLY_TOKEN_FILENAME
        return cls(scopes=cls.READONLY_SCOPES, token_path=token_path)

    def _channel_label(self) -> str:
        """認証メッセージに埋め込むチャンネル識別ラベルを返す。

        config 読み込みに失敗しても認証自体は継続できるよう、
        ``ConfigError`` 時は auth ディレクトリの親ディレクトリ名へフォールバックする。
        """
        try:
            from youtube_automation.utils.config import load_config

            return load_config().meta.channel_short
        except ConfigError:
            return self.auth_dir.resolve().parent.name

    def _validate_client_secrets(self):
        """client_secrets.json の存在確認"""
        if self._client_secrets_config is not None:
            _validate_client_secrets_data(self._client_secrets_config)
            return
        if self.client_secrets_file.exists() and not self.client_secrets_file.is_file():
            raise ValidationError(f"client_secrets.json は通常ファイルである必要があります: {self.client_secrets_file}")
        if not self.client_secrets_file.is_file():
            searched = "\n".join(f"  - {p}" for p in client_secrets_file_candidates(self._channel_dir))
            raise FileNotFoundError(
                f"❌ client_secrets.json が見つかりません: {self.client_secrets_file}\n"
                f"探索したパス:\n{searched}\n"
                "設定手順:\n"
                "1. Google Cloud Console で YouTube Data API v3 を有効化\n"
                "2. Google Auth Platform > Branding でアプリ情報を保存\n"
                "3. Google Auth Platform > Audience > Test users に OAuth 認証でログインする Google アカウントを追加\n"
                "   (未追加だと初回認証が 403 access_denied で止まります)\n"
                "4. Google Auth Platform > Clients > Create client で Application type Desktop app を作成\n"
                "5. Clients > 対象 client > Client secrets > Add secret で secret を発行\n"
                "6. Download JSON を実行して Downloads に保存し、"
                "`uv run yt-doctor --fix-client-secrets` で "
                "<channel_dir>/auth/client_secrets.json へ自動移動\n"
                "   または CLIENT_SECRETS_DIR 環境変数を指定 / 1Password に CLIENT_SECRETS_JSON として登録"
            )
        try:
            data = json.loads(self.client_secrets_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise ValidationError(f"client_secrets.json 読み込み失敗: {e}") from e
        if not isinstance(data, dict):
            raise ValidationError("client_secrets.json は JSON object である必要があります")
        _validate_client_secrets_data(data)

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
            channel_label = self._channel_label()
            print(f"🌐 [{channel_label}] ブラウザで認証を実行します...")
            print("📝 注意: 初回認証時はブラウザが開き、Googleアカウントでのログインが必要です")

            try:
                if self._client_secrets_config is not None:
                    flow = InstalledAppFlow.from_client_config(self._client_secrets_config, self._scopes)
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_file), self._scopes)
                # authorization_prompt_message は run_local_server() 内で
                # ``.format(url=...)`` される。`{url}` placeholder を壊さないよう
                # ラベル側の brace は escape する（success_message は format されない）
                escaped_label = channel_label.replace("{", "{{").replace("}", "}}")
                self.credentials = flow.run_local_server(
                    port=0,
                    authorization_prompt_message=(
                        f"🔐 [{escaped_label}] チャンネルの OAuth 認証です。"
                        "ブラウザが開かない場合は以下の URL を開いてください"
                        "（URL 内 redirect_uri のポート番号がこのターミナルに対応するタブの目印です）: {url}"
                    ),
                    success_message=(
                        f"[{channel_label}] チャンネルの OAuth 認証が完了しました。"
                        "このタブを閉じてターミナルに戻ってください。"
                    ),
                )
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


def main(argv=None):
    """メイン関数 - スタンドアロン実行用（``yt-oauth``）

    Args:
        argv (list[str] | None): CLI 引数。None なら ``sys.argv[1:]``。
            テストから直接呼ぶ場合は ``main([])`` のように明示する
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="yt-oauth",
        description="YouTube OAuth 2.0 認証（token 発行・接続テスト）",
    )
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="read-only スコープの token.readonly.json を発行する（write scope を含まない。#1699）",
    )
    args = parser.parse_args(argv)

    mode_label = "read-only" if args.readonly else "full access"
    print(f"🎵 YouTube OAuth 2.0 認証テスト（{mode_label}）")
    print("=" * 60)

    auth_handler = None
    try:
        # OAuth ハンドラー初期化
        if args.readonly:
            auth_handler = YouTubeOAuthHandler.create_readonly()
        else:
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
    except (AuthError, ConfigError, ValidationError, YouTubeAPIError, OSError) as e:
        paths = []
        if auth_handler is not None:
            paths.extend([auth_handler.client_secrets_file, auth_handler.token_file])
        logger.error("CLI 実行失敗: %s", _redact(str(e), *paths))
        sys.exit(1)
    except Exception as e:
        # 想定外例外の最終 fallback。traceback は logger.exception が付与し、
        # _redact で token 値・絶対パスの leak を防ぐ。
        logger.exception("CLI 実行中に想定外のエラー: %s", _redact(str(e)))
        sys.exit(1)


if __name__ == "__main__":
    main()
