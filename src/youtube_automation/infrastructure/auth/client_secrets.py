"""OAuth client-secret resource helpers."""

import json
from importlib.resources import files
from pathlib import Path

from youtube_automation.core.errors import ValidationError


def template_bytes() -> bytes:
    return (
        files("youtube_automation")
        .joinpath("infrastructure", "resources", "auth", "client_secrets.template.json")
        .read_bytes()
    )


def validate_desktop_client_config(data: dict[str, object]) -> None:
    """Validate the Google Desktop OAuth client configuration shape."""
    installed = data.get("installed")
    if not isinstance(installed, dict):
        raise ValidationError("Desktop app の client_secrets.json が必要です: installed セクションがありません")
    required_keys = ("client_id", "client_secret", "redirect_uris")
    missing = [key for key in required_keys if key not in installed]
    if missing:
        raise ValidationError(f"client_secrets.json に必須キー不足: {','.join(missing)}")


def validate_desktop_client_file(path: Path) -> bool:
    """Validate a configured client file, returning False only when it is missing."""
    if path.exists() and not path.is_file():
        raise ValidationError(f"client_secrets.json は通常ファイルである必要があります: {path}")
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ValidationError(f"client_secrets.json 読み込み失敗: {error}") from error
    if not isinstance(data, dict):
        raise ValidationError("client_secrets.json は JSON object である必要があります")
    validate_desktop_client_config(data)
    return True
