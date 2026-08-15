"""OAuth credential loading, refresh, and persistence boundary."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


def token_path(auth_dir: Path, filename: str = "token.json") -> Path:
    """Return the explicitly selected token location for an auth directory."""
    return auth_dir / filename


@dataclass(frozen=True)
class OAuthCredentialState:
    credentials: Credentials | None = None
    refreshed: bool = False
    error: str | None = None
    reauthentication_required: bool = False


def load_credentials(path: Path, scopes: list[str] | None = None) -> Credentials:
    """Load authorized-user credentials from the selected token path."""
    if scopes is None:
        return Credentials.from_authorized_user_file(str(path))
    return Credentials.from_authorized_user_file(str(path), scopes)


def save_credentials(path: Path, credentials: Credentials) -> None:
    """Atomically persist credentials with mode ``0o600``."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(credentials.to_json())
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def load_refreshable_credentials(path: Path) -> OAuthCredentialState:
    """Load credentials and refresh an expired access token when possible."""
    try:
        credentials = load_credentials(path)
    except (OSError, ValueError) as error:
        return OAuthCredentialState(
            error=f"OAuth トークンが不正です: {error}",
            reauthentication_required=True,
        )

    refreshed = False
    if credentials.expired:
        if not credentials.refresh_token:
            return OAuthCredentialState(
                error="OAuth トークンが期限切れで、更新用トークンがありません",
                reauthentication_required=True,
            )
        try:
            credentials.refresh(Request())
        except RefreshError:
            return OAuthCredentialState(
                error="OAuth トークンの更新に失敗しました。更新用トークンが失効しています",
                reauthentication_required=True,
            )
        except TransportError as error:
            return OAuthCredentialState(error=f"OAuth トークン更新時の通信に失敗しました: {error}")
        try:
            save_credentials(path, credentials)
        except OSError as error:
            return OAuthCredentialState(error=f"更新した OAuth トークンの保存に失敗しました: {error}")
        refreshed = True

    if not credentials.valid:
        return OAuthCredentialState(
            error="OAuth トークンが利用できません",
            reauthentication_required=True,
        )
    return OAuthCredentialState(credentials=credentials, refreshed=refreshed)


__all__ = [
    "OAuthCredentialState",
    "load_credentials",
    "load_refreshable_credentials",
    "save_credentials",
    "token_path",
]
