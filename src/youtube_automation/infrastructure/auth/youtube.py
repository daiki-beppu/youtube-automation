"""Canonical YouTube OAuth 2.0 authentication boundary.

YouTube OAuth 2.0 認証ハンドラー
YouTube Data API v3を使用した自動アップロードのための認証システム

Required setup:
1. GCP 層は上流 infra/terraform/gcp/README.md に従って構築
2. チャンネルルートで bash .claude/skills/setup/references/oauth-client-wizard.sh を実行し、
   auth/client_secrets.json を配置（Console 手順の正本は wizard）
"""

import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from requests import Session

from youtube_automation.core.errors import AuthError, ConfigError, YouTubeAPIError
from youtube_automation.core.redaction import redact_sensitive_data
from youtube_automation.infrastructure import secrets as secret_store
from youtube_automation.infrastructure.auth.client_secrets import (
    validate_desktop_client_config,
    validate_desktop_client_file,
)
from youtube_automation.infrastructure.auth.tokens import save_credentials
from youtube_automation.infrastructure.auth.tokens import token_path as resolve_token_path
from youtube_automation.infrastructure.vcs.worktree import main_worktree_root

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource


logger = logging.getLogger(__name__)

UPLOAD_REQUIRED_SCOPES = (
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
)
OAUTH_TOKEN_JSON_ENV = "YOUTUBE_OAUTH_TOKEN_JSON"


def build_youtube_service(credentials: Credentials):
    """Build the canonical YouTube Data API v3 service."""
    return build("youtube", "v3", credentials=credentials)


def client_secrets_file_candidates(channel_dir: Path) -> list[Path]:
    """ファイルとして配置された client_secrets.json の候補を検索順で返す。"""
    client_secrets_dir = os.environ.get("CLIENT_SECRETS_DIR")
    if client_secrets_dir:
        return [Path(client_secrets_dir) / "client_secrets.json"]
    candidates = [
        channel_dir / "auth" / "client_secrets.json",
        channel_dir / "automation" / "auth" / "client_secrets.json",
    ]
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
        from youtube_automation.core.channel_context import channel_dir as _channel_dir

        channel_dir = _channel_dir()

    kind, path = resolve_client_secrets_location(channel_dir)
    if kind in {"file", "invalid-file", "missing-file"}:
        return path, None

    try:
        return path, secret_store.get_client_secrets_config()
    except ConfigError:
        return path, None


def resolve_client_secrets_path(channel_dir: Path | None = None) -> Path:
    """後方互換のため client_secrets の表示用パスだけを返す。"""
    return resolve_client_secrets_source(channel_dir)[0]


def _run_browser_authorization(
    client_config: dict[str, object] | None,
    client_file: Path,
    scopes: list[str],
    channel_label: str,
) -> Credentials:
    """Run the Google browser flow using an already validated desktop client."""
    if client_config is not None:
        flow = InstalledAppFlow.from_client_config(client_config, scopes)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes)
    # authorization_prompt_message は run_local_server() 内で
    # ``.format(url=...)`` される。`{url}` placeholder を壊さないよう
    # ラベル側の brace は escape する（success_message は format されない）
    escaped_label = channel_label.replace("{", "{{").replace("}", "}}")
    return flow.run_local_server(
        port=0,
        authorization_prompt_message=(
            f"🔐 [{escaped_label}] チャンネルの OAuth 認証です。"
            "ブラウザが開かない場合は以下の URL を開いてください"
            "（URL 内 redirect_uri のポート番号がこのターミナルに対応するタブの目印です）: {url}"
        ),
        success_message=(
            f"[{channel_label}] チャンネルの OAuth 認証が完了しました。このタブを閉じてターミナルに戻ってください。"
        ),
    )


def _refresh_credentials(credentials: Credentials) -> None:
    """Refresh with a transport session bounded to this operation."""
    with Session() as session:
        credentials.refresh(Request(session=session))


def _connect_youtube_service(credentials: Credentials) -> "Resource":
    """Build the service and translate discovery HTTP failures at the SDK boundary."""
    try:
        service = build_youtube_service(credentials)
        print("✅ YouTube Data API サービス接続成功", file=sys.stderr)
        return service
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, "YouTube Data API サービス接続失敗") from e


def _test_youtube_connection(get_service: Callable[[], "Resource"], token_file: Path, client_file: Path) -> bool:
    """Probe the authenticated channel and report connection failures with redaction."""
    try:
        service = get_service()
        # チャンネル情報取得でテスト
        response = service.channels().list(part="snippet,statistics", mine=True).execute()

        if response["items"]:
            channel = response["items"][0]
            channel_title = channel["snippet"]["title"]
            subscriber_count = channel["statistics"].get("subscriberCount", "N/A")
            print("✅ API接続テスト成功", file=sys.stderr)
            print(f"📺 チャンネル名: {channel_title}", file=sys.stderr)
            print(f"👥 登録者数: {subscriber_count}", file=sys.stderr)
            return True
        else:
            print("❌ チャンネル情報が取得できませんでした", file=sys.stderr)
            return False

    except (HttpError, AuthError, YouTubeAPIError, google.auth.exceptions.GoogleAuthError, OSError) as e:
        logger.error(
            "API 接続テスト失敗: %s",
            redact_sensitive_data(str(e), token_file, client_file),
        )
        return False


def _persist_oauth_credentials(token_file: Path, credentials: Credentials) -> None:
    """Persist credentials atomically and report filesystem errors as configuration failures."""
    try:
        save_credentials(token_file, credentials)
        print(f"💾 認証トークン保存完了: {token_file}", file=sys.stderr)
    except OSError as e:
        raise ConfigError(
            f"認証トークン保存失敗: {token_file} ({e})。親ディレクトリの書き込み権限と空き容量を確認してください。"
        ) from e


class YouTubeOAuthHandler:
    """YouTube Data API v3 OAuth 2.0 認証管理クラス"""

    # YouTube Full Access + Analytics + Reporting スコープ
    # yt-analytics-monetary.readonly は Reporting API v1 (#84) で
    # videoThumbnailImpressions / videoThumbnailImpressionsClickThroughRate を取得するため必須。
    SCOPES: ClassVar[list[str]] = [
        *UPLOAD_REQUIRED_SCOPES,
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    ]

    # read-only skill（analytics / benchmark / channel-status 等）用の
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

    def __init__(self, auth_dir=None, scopes=None, token_path=None, *, interactive: bool = True):
        """
        初期化

        Args:
            auth_dir (str): token.json を格納するチャンネル固有 auth ディレクトリのパス
            scopes (list[str] | None): OAuth scopes。未指定時はクラス属性 ``SCOPES``（既存挙動）
            token_path (str | Path | None): token ファイルパス。未指定時は ``<auth_dir>/token.json``。
                stream key 取得用に ``token_streaming.json`` を分離する用途で使用する（issue #135）
            interactive (bool): token を利用できない場合に browser OAuth を開始してよいか。
        """
        from youtube_automation.core.channel_context import channel_dir as _channel_dir

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
            self.token_file = resolve_token_path(self.auth_dir)
        self.credentials = None
        self._interactive = interactive
        self._ephemeral_credentials = False

    def _load_secret_credentials(self) -> Credentials | None:
        """Load an authorized-user token injected by the cloud secret boundary."""
        raw = os.environ.get(OAUTH_TOKEN_JSON_ENV)
        if raw is None:
            return None
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthError(f"{OAUTH_TOKEN_JSON_ENV} は有効な JSON object でなければなりません") from exc
        required = {"refresh_token", "token_uri", "client_id", "client_secret"}
        if not isinstance(document, dict) or any(
            not isinstance(document.get(key), str) or not document[key] for key in required
        ):
            raise AuthError(f"{OAUTH_TOKEN_JSON_ENV} に authorized-user OAuth fields が不足しています")
        try:
            credentials = Credentials.from_authorized_user_info(document, self._scopes)
        except ValueError as exc:
            raise AuthError(f"{OAUTH_TOKEN_JSON_ENV} を OAuth token として読み込めません") from exc
        self._ephemeral_credentials = True
        return credentials

    @classmethod
    def readonly_token_path(cls) -> Path | None:
        """発行済み ``token.readonly.json`` の実体パスを返す（未発行なら None）。

        検索順は ``token.json`` の worktree フォールバック（#1721）と同じ:
        channel 側 ``auth/`` → main worktree 側 ``auth/``。
        handler を生成せずファイル存在だけで判定できるよう classmethod にしている
        （client_secrets 解決や 1Password 参照を発行チェックの副作用にしない）。
        """
        from youtube_automation.core.channel_context import channel_dir as _channel_dir

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
    def create_readonly(cls, *, interactive: bool = True) -> "YouTubeOAuthHandler":
        """read-only スコープ + ``token.readonly.json`` のハンドラーを生成する。

        未発行時の保存先は ``token.json`` と同じ規則で解決する
        （worktree にローカル token が無ければ main 側 ``auth/`` に集約。#1721）。
        """
        resolved_token_path = cls.readonly_token_path()
        if resolved_token_path is None:
            from youtube_automation.core.channel_context import channel_dir as _channel_dir

            channel = _channel_dir()
            auth_dir = channel / "auth"
            main_root = main_worktree_root(channel)
            if main_root is not None:
                auth_dir = main_root / "auth"
            resolved_token_path = resolve_token_path(auth_dir, cls.READONLY_TOKEN_FILENAME)
        return cls(scopes=cls.READONLY_SCOPES, token_path=resolved_token_path, interactive=interactive)

    def _require_interactive_reauthentication(self) -> None:
        if self._interactive:
            return
        command = "uv run yt-oauth --readonly" if self._scopes == self.READONLY_SCOPES else "uv run yt-oauth"
        raise AuthError(
            "非対話実行では OAuth token を新規発行できません。"
            f"対話可能なターミナルで `{command}` を実行して token を発行してください。"
        )

    def _channel_label(self) -> str:
        """設定に依存しない認証ラベルとして auth ディレクトリの親名を返す。"""
        return self.auth_dir.resolve().parent.name

    def _validate_client_secrets(self):
        """client_secrets.json の存在確認"""
        if self._client_secrets_config is not None:
            validate_desktop_client_config(self._client_secrets_config)
            return
        if validate_desktop_client_file(self.client_secrets_file):
            return
        searched = "\n".join(f"  - {p}" for p in client_secrets_file_candidates(self._channel_dir))
        raise FileNotFoundError(
            f"❌ client_secrets.json が見つかりません: {self.client_secrets_file}\n"
            f"探索したパス:\n{searched}\n"
            "設定手順:\n"
            "1. チャンネルルートで "
            "`bash .claude/skills/setup/references/oauth-client-wizard.sh` を起動\n"
            "   (Console 手順の正本は wizard。完了すると "
            "<channel_dir>/auth/client_secrets.json が配置されます)\n"
            "2. または CLIENT_SECRETS_DIR 環境変数を指定 / 1Password に CLIENT_SECRETS_JSON として登録"
        )

    def authenticate(self, force_reauth=False):
        """
        OAuth 2.0 認証実行

        Args:
            force_reauth (bool): 強制再認証フラグ

        Returns:
            Credentials: Google OAuth 2.0 認証情報
        """
        print("🔐 YouTube Data API OAuth 2.0 認証開始...", file=sys.stderr)

        # cloud secret はファイルより優先し、refresh 後もディスクへ永続化しない。
        if not force_reauth:
            self.credentials = self._load_secret_credentials()

        # 既存トークンの読み込み
        if not force_reauth and self.credentials is None and self.token_file.exists():
            try:
                print("📁 既存トークンファイルを確認中...", file=sys.stderr)
                self.credentials = Credentials.from_authorized_user_file(str(self.token_file), self._scopes)
                print("✅ 既存トークン読み込み成功", file=sys.stderr)
            except (OSError, ValueError) as e:
                # 旧トークンが壊れているケースは新規認証へフォールスルーで recovery する
                logger.warning("既存トークン読み込み失敗: %s", redact_sensitive_data(str(e), self.token_file))
                self.credentials = None

        # トークンの有効性確認・更新
        if self.credentials:
            if self.credentials.expired and self.credentials.refresh_token:
                try:
                    print("🔄 トークンの更新中...", file=sys.stderr)
                    _refresh_credentials(self.credentials)
                    print("✅ トークン更新成功", file=sys.stderr)
                    if not self._ephemeral_credentials:
                        self._save_credentials()
                except google.auth.exceptions.GoogleAuthError as e:
                    # AuthError を raise すると新規認証へのフォールスルー recovery が壊れる。
                    # credentials=None に落として下の新規認証ブロックで recovery する。
                    logger.warning("token refresh 失敗: %s", redact_sensitive_data(str(e)))
                    if self._ephemeral_credentials:
                        raise AuthError("secret OAuth token の更新に失敗しました") from e
                    self.credentials = None

        # 新規認証が必要な場合
        if not self.credentials or not self.credentials.valid:
            self._authenticate_interactively()

        return self.credentials

    def _authenticate_interactively(self) -> None:
        """Run the permitted browser flow and persist its credentials with existing error redaction."""
        self._require_interactive_reauthentication()
        self._validate_client_secrets()
        channel_label = self._channel_label()
        print(f"🌐 [{channel_label}] ブラウザで認証を実行します...", file=sys.stderr)
        print(
            "📝 注意: 初回認証時はブラウザが開き、Googleアカウントでのログインが必要です",
            file=sys.stderr,
        )

        try:
            self.credentials = _run_browser_authorization(
                self._client_secrets_config, self.client_secrets_file, self._scopes, channel_label
            )
            print("✅ OAuth 2.0 認証成功", file=sys.stderr)
            self._save_credentials()
        except (ValueError, OSError, google.auth.exceptions.GoogleAuthError) as e:
            logger.error("OAuth 2.0 認証失敗: %s", redact_sensitive_data(str(e), self.client_secrets_file))
            raise AuthError("OAuth 2.0 認証に失敗しました") from e

    def refresh_existing_credentials(self) -> Credentials:
        """既存 refresh token だけを使い、ブラウザを開かず access token を更新する。"""
        credentials = self._load_secret_credentials()
        if credentials is None:
            if not self.token_file.is_file():
                raise AuthError(f"既存の OAuth token がありません: {self.token_file}")
            try:
                credentials = Credentials.from_authorized_user_file(str(self.token_file), self._scopes)
            except (OSError, ValueError) as exc:
                raise AuthError("既存の OAuth token を読み込めません") from exc
        if not credentials.refresh_token:
            raise AuthError("既存の OAuth token に refresh token がありません")
        try:
            _refresh_credentials(credentials)
        except google.auth.exceptions.GoogleAuthError as exc:
            logger.warning("token refresh 失敗: %s", redact_sensitive_data(str(exc)))
            raise AuthError("OAuth token の更新に失敗しました。refresh token が失効している可能性があります") from exc
        self.credentials = credentials
        if not self._ephemeral_credentials:
            self._save_credentials()
        return credentials

    def _save_credentials(self):
        """認証情報をファイルに atomic かつ 0o600 で保存する。

        同じディレクトリの一時ファイルを fsync してから置換するため、既存 token を
        部分書き込みで壊さず、プロセス umask に依存せず必ず 0o600 で保存する。
        書き込み失敗時は ``ConfigError`` として raise する（握りつぶし禁止 ―
        失敗を黙って成功扱いすると毎回ブラウザ認証が走る運用障害になる）。

        Raises:
            ConfigError: トークンファイルの書き込みに失敗した場合。
        """
        _persist_oauth_credentials(self.token_file, self.credentials)

    def get_youtube_service(self):
        """
        YouTube Data API サービスオブジェクト取得

        Returns:
            googleapiclient.discovery.Resource: YouTube API サービス
        """
        if not self.credentials:
            self.authenticate()

        return _connect_youtube_service(self.credentials)

    def test_connection(self):
        """
        API接続テスト

        Returns:
            bool: 接続成功可否
        """
        return _test_youtube_connection(self.get_youtube_service, self.token_file, self.client_secrets_file)
