"""Register a validated unattended request and build its one-time launch URL."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.skill_config import load_skill_config

_DOWNLOAD_FORMATS = ("mp3", "m4a", "wav")


def _bounded_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigError(f"{field} は {minimum}..{maximum} の整数で指定してください")
    return value


def _loopback_base_url(value: str) -> str:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    is_loopback = hostname in {"localhost", "127.0.0.1"} or hostname.endswith(".localhost")
    if parsed.scheme != "http" or not is_loopback or parsed.username or parsed.password:
        raise ConfigError("--base-url は認証情報を含まない loopback http URL を指定してください")
    if not parsed.netloc:
        raise ConfigError("--base-url は host を含む URL で指定してください")
    path = parsed.path.rstrip("/")
    return urlunsplit(("http", parsed.netloc, path, "", ""))


def _default_request_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"scheduled-{timestamp}-{uuid.uuid4().hex[:8]}"


def build_unattended_request(
    *,
    base_url: str,
    collection_id: str,
    entry_indices: list[int] | None,
    download_format: str,
    max_entries: int,
    max_concurrent_generations: int,
    max_retries: int,
    request_id: str | None = None,
) -> dict[str, object]:
    collection_id = collection_id.strip()
    if not collection_id:
        raise ConfigError("--collection-id は空にできません")
    if download_format not in _DOWNLOAD_FORMATS:
        raise ConfigError(f"--download-format は {' / '.join(_DOWNLOAD_FORMATS)} から選んでください")
    normalized_indices: list[int] | None = None
    if entry_indices is not None:
        if not entry_indices:
            raise ConfigError("--entry-index は 1 件以上指定してください")
        normalized_indices = []
        seen: set[int] = set()
        for index in entry_indices:
            index = _bounded_integer(index, "--entry-index", 0, sys.maxsize)
            if index in seen:
                raise ConfigError(f"--entry-index {index} が重複しています")
            seen.add(index)
            normalized_indices.append(index)
    resolved_request_id = request_id.strip() if request_id else _default_request_id()
    if not resolved_request_id:
        raise ConfigError("--request-id は空にできません")
    request: dict[str, object] = {
        "version": 1,
        "requestId": resolved_request_id,
        "baseUrl": _loopback_base_url(base_url),
        "collectionId": collection_id,
        "downloadFormat": download_format,
        "limits": {
            "maxEntries": _bounded_integer(max_entries, "--max-entries", 1, 100),
            "maxConcurrentGenerations": _bounded_integer(
                max_concurrent_generations,
                "--max-concurrent-generations",
                1,
                10,
            ),
            "maxRetries": _bounded_integer(max_retries, "--max-retries", 0, 5),
        },
    }
    if normalized_indices is not None:
        request["entryIndices"] = normalized_indices
    return request


def build_unattended_launch_url(*, base_url: str, nonce: str) -> str:
    payload = json.dumps(
        {"version": 1, "baseUrl": _loopback_base_url(base_url), "nonce": nonce},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"https://suno.com/create#suno-helper-unattended={encoded}"


def register_unattended_request(base_url: str, request: dict[str, object]) -> str:
    url = f"{_loopback_base_url(base_url)}/unattended/requests"
    http_request = Request(
        url,
        data=json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(http_request, timeout=10) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ConfigError(f"unattended request を localhost server に登録できません: {exc}") from exc
    nonce = payload.get("nonce") if isinstance(payload, dict) else None
    if not isinstance(nonce, str) or not nonce:
        raise ConfigError("localhost server が有効な unattended nonce を返しませんでした")
    return nonce


def _parser(defaults: dict[str, object]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="suno-helper の定期実行 launch URL を生成する")
    parser.add_argument("--base-url", required=True, help="起動中の yt-collection-serve URL")
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--entry-index", type=int, action="append", dest="entry_indices")
    parser.add_argument("--download-format", choices=_DOWNLOAD_FORMATS, default=defaults["download_format"])
    parser.add_argument("--max-entries", type=int, default=defaults["max_entries"])
    parser.add_argument(
        "--max-concurrent-generations",
        type=int,
        default=defaults["max_concurrent_generations"],
    )
    parser.add_argument("--max-retries", type=int, default=defaults["max_retries"])
    parser.add_argument("--request-id", help="監査用 ID。省略時は UTC 時刻と乱数から生成")
    return parser


def _config_defaults() -> dict[str, object]:
    config = load_skill_config("suno-helper").get("unattended")
    if not isinstance(config, dict):
        raise ConfigError("suno-helper skill-config の unattended は object で指定してください")
    required = ("download_format", "max_entries", "max_concurrent_generations", "max_retries")
    missing = [key for key in required if key not in config]
    if missing:
        raise ConfigError(f"suno-helper skill-config に必須キーがありません: {', '.join(missing)}")
    return config


def main(argv: list[str] | None = None) -> int:
    args = _parser(_config_defaults()).parse_args(argv)
    request = build_unattended_request(
        base_url=args.base_url,
        collection_id=args.collection_id,
        entry_indices=args.entry_indices,
        download_format=args.download_format,
        max_entries=args.max_entries,
        max_concurrent_generations=args.max_concurrent_generations,
        max_retries=args.max_retries,
        request_id=args.request_id,
    )
    nonce = register_unattended_request(args.base_url, request)
    print(build_unattended_launch_url(base_url=args.base_url, nonce=nonce))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
