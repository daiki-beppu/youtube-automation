"""OAuth client-secret resource helpers."""

from importlib.resources import files


def template_bytes() -> bytes:
    return (
        files("youtube_automation")
        .joinpath("infrastructure", "resources", "auth", "client_secrets.template.json")
        .read_bytes()
    )


def validate_desktop_client_config(data: dict[str, object]) -> None:
    """Validate the Google Desktop OAuth client configuration shape."""
    from youtube_automation.infrastructure.errors import ValidationError

    installed = data.get("installed")
    if not isinstance(installed, dict):
        raise ValidationError("Desktop app の client_secrets.json が必要です: installed セクションがありません")
    required_keys = ("client_id", "client_secret", "redirect_uris")
    missing = [key for key in required_keys if key not in installed]
    if missing:
        raise ValidationError(f"client_secrets.json に必須キー不足: {','.join(missing)}")
