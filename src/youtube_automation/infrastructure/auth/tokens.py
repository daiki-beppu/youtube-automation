"""OAuth token path conventions."""

from pathlib import Path

from google.oauth2.credentials import Credentials


def token_path(auth_dir: Path, filename: str = "token.json") -> Path:
    """Return the explicitly selected token location for an auth directory."""
    return auth_dir / filename


def load_credentials(path: Path, scopes: list[str]) -> Credentials:
    """Load authorized-user credentials from the selected token path."""
    return Credentials.from_authorized_user_file(str(path), scopes)


def save_credentials(path: Path, credentials: Credentials) -> None:
    """Persist credentials with the token file's restrictive permission contract."""
    import os

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as token:
        token.write(credentials.to_json())
    os.chmod(path, 0o600)
