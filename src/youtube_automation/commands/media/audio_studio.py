"""Loopback-only web studio for reviewing collection audio tracks."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import secrets
import time
import webbrowser
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import unquote, urlsplit

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.commands.suno.suno_audio_cleanup import (
    cleanup_config_settings,
    resolve_cleanup_config,
)
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.media.audio_adjustments import (
    merge_cleanup_settings,
    read_audio_adjustments,
    replace_track_cleanup_overrides,
)
from youtube_automation.domains.media.audio_formats import AUDIO_EXTS
from youtube_automation.infrastructure.file_lock import file_lock
from youtube_automation.infrastructure.localserver.cors import is_origin_allowed
from youtube_automation.infrastructure.localserver.lifecycle import (
    LifecycleRecord,
    consume_stop_request,
    pid_file_path,
    pid_is_running,
    process_exit_watcher,
    read_pid_file,
    remove_matching_record,
    remove_owned_pid_file,
    startup_lock_path,
    stop_request_path,
    write_pid_file,
)
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths, resolve_collection_dir
from youtube_automation.infrastructure.media.probe import probe_duration

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
SERVER_KIND = "audio-studio"
TRACKS_ROUTE = "/api/tracks"
_TRACK_AUDIO_PATTERN = re.compile(r"^/api/tracks/(?P<track_id>[a-f0-9]{16})/audio$")
_TRACK_ADJUSTMENTS_PATTERN = re.compile(r"^/api/tracks/(?P<track_id>[a-f0-9]{16})/adjustments$")
_RANGE_PATTERN = re.compile(r"^bytes=(?P<start>\d*)-(?P<end>\d*)$")
_MAX_JSON_BODY_BYTES = 64 * 1024


class _StopRequested(RuntimeError):
    pass


def _channel_dir_for_collection(collection_dir: Path) -> Path:
    for candidate in (collection_dir, *collection_dir.parents):
        if (candidate / "config/channel").is_dir():
            return candidate
    return collection_dir


def build_track_payload(
    collection_dir: Path,
    *,
    duration_probe: Callable[[Path], float | None] = probe_duration,
) -> tuple[dict[str, object], dict[str, Path]]:
    """Build the public track list and an allowlisted id-to-file map."""
    paths = CollectionPaths(collection_dir)
    tracks: list[dict[str, object]] = []
    track_files: dict[str, Path] = {}
    if paths.music_dir.is_dir():
        candidates = sorted(
            path
            for path in paths.music_dir.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in AUDIO_EXTS
        )
    else:
        candidates = []
    for path in candidates:
        track_id = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:16]
        duration = duration_probe(path)
        tracks.append(
            {
                "id": track_id,
                "file_name": path.name,
                "duration_seconds": duration if duration is not None else 0.0,
                "extension": path.suffix.lstrip(".").lower(),
                "audio_url": f"/api/tracks/{track_id}/audio",
            }
        )
        track_files[track_id] = path
    return {"collection_name": paths.collection_name, "tracks": tracks}, track_files


class AudioStudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        collection_dir: Path,
        asset_root: Traversable,
        track_payload: Mapping[str, object],
        track_files: Mapping[str, Path],
        cleanup_defaults: Mapping[str, object] | None = None,
        stop_path: Path | None = None,
    ) -> None:
        super().__init__(address, AudioStudioRequestHandler)
        self.collection_dir = collection_dir
        self.asset_root = asset_root
        self.track_payload = dict(track_payload)
        self.track_files = dict(track_files)
        self.cleanup_defaults = dict(cleanup_defaults) if cleanup_defaults is not None else None
        self.audio_adjustments_path = CollectionPaths(collection_dir).audio_adjustments_path
        self.stop_path = stop_path

    def service_actions(self) -> None:
        super().service_actions()
        if self.stop_path is not None and consume_stop_request(self.stop_path, os.getpid()):
            raise _StopRequested


class AudioStudioRequestHandler(BaseHTTPRequestHandler):
    server: AudioStudioServer

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _cors_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        expected_origin = f"http://{DEFAULT_HOST}:{self.server.server_port}"
        return origin is None or is_origin_allowed(origin, expected_origin)

    def _common_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin is not None and self._cors_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _json(self, status: HTTPStatus, payload: Mapping[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._common_headers()
        self.end_headers()
        self.wfile.write(body)

    def _resource(self, relative_path: str) -> Traversable | None:
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            return None
        resource = self.server.asset_root
        for part in pure_path.parts:
            resource = resource.joinpath(part)
        return resource

    def _static(self, path: str) -> None:
        relative_path = unquote(path).lstrip("/") or "index.html"
        resource = self._resource(relative_path)
        if resource is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "asset not found"})
            return
        if not resource.is_file():
            resource = self._resource("index.html")
        if resource is None or not resource.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "audio studio build asset not found"})
            return
        body = resource.read_bytes()
        content_type, _ = mimetypes.guess_type(str(resource))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self._common_headers()
        self.end_headers()
        self.wfile.write(body)

    def _audio(self, path: Path) -> None:
        size = path.stat().st_size
        byte_range = _parse_range(self.headers.get("Range"), size)
        if byte_range is False:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()
            return
        start, end = byte_range if byte_range is not None else (0, max(0, size - 1))
        length = max(0, end - start + 1) if byte_range is not None else size
        status = HTTPStatus.PARTIAL_CONTENT if byte_range is not None else HTTPStatus.OK
        content_type, _ = mimetypes.guess_type(path.name)
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if byte_range is not None:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._common_headers()
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining > 0:
                chunk = stream.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _defaults(self) -> dict[str, object]:
        if self.server.cleanup_defaults is None:
            config = resolve_cleanup_config(
                load_skill_config(
                    "masterup",
                    channel_dir=_channel_dir_for_collection(self.server.collection_dir),
                )
            )
            self.server.cleanup_defaults = cleanup_config_settings(config)
        return dict(self.server.cleanup_defaults)

    def _adjustments_payload(self, track: Path) -> dict[str, object]:
        defaults = self._defaults()
        document = read_audio_adjustments(self.server.audio_adjustments_path)
        overrides = document.tracks.get(track.name, {})
        return {
            "defaults": defaults,
            "settings": merge_cleanup_settings(defaults, overrides),
            "overrides": overrides,
        }

    def _read_json_body(self) -> Mapping[str, object]:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as error:
            raise ValidationError("Content-Length が不正です") from error
        if length <= 0 or length > _MAX_JSON_BODY_BYTES:
            raise ValidationError(f"JSON body は 1..{_MAX_JSON_BODY_BYTES} bytes で指定してください")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(f"JSON body が不正です: {error}") from error
        if not isinstance(payload, Mapping):
            raise ValidationError("JSON body は object である必要があります")
        return payload

    def _put_adjustments(self, track: Path) -> None:
        payload = self._read_json_body()
        if set(payload) != {"settings"}:
            raise ValidationError("JSON body は settings だけを含む必要があります")
        collection_root = self.server.collection_dir.resolve()
        if not self.server.audio_adjustments_path.parent.resolve().is_relative_to(collection_root):
            raise ValidationError("audio-adjustments.json の保存先が collection 外を指しています")
        defaults = self._defaults()
        with file_lock(self.server.audio_adjustments_path):
            document = replace_track_cleanup_overrides(
                self.server.audio_adjustments_path,
                track.name,
                payload["settings"],
                defaults,
            )
        overrides = document.tracks.get(track.name, {})
        self._json(
            HTTPStatus.OK,
            {
                "defaults": defaults,
                "settings": merge_cleanup_settings(defaults, overrides),
                "overrides": overrides,
            },
        )

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/api/") and not self._cors_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return
        if path == TRACKS_ROUTE:
            self._json(HTTPStatus.OK, self.server.track_payload)
            return
        match = _TRACK_AUDIO_PATTERN.fullmatch(path)
        if match is not None:
            track = self.server.track_files.get(match.group("track_id"))
            if track is None or not track.is_file() or track.is_symlink():
                self._json(HTTPStatus.NOT_FOUND, {"error": "track not found"})
                return
            self._audio(track)
            return
        adjustment_match = _TRACK_ADJUSTMENTS_PATTERN.fullmatch(path)
        if adjustment_match is not None:
            track = self.server.track_files.get(adjustment_match.group("track_id"))
            if track is None or not track.is_file() or track.is_symlink():
                self._json(HTTPStatus.NOT_FOUND, {"error": "track not found"})
                return
            try:
                self._json(HTTPStatus.OK, self._adjustments_payload(track))
            except ValidationError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except ConfigError as error:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})
            return
        if path.startswith("/api/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "API path not found"})
            return
        self._static(path)

    def do_PUT(self) -> None:
        path = urlsplit(self.path).path
        if not self._cors_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return
        match = _TRACK_ADJUSTMENTS_PATTERN.fullmatch(path)
        if match is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "API path not found"})
            return
        track = self.server.track_files.get(match.group("track_id"))
        if track is None or not track.is_file() or track.is_symlink():
            self._json(HTTPStatus.NOT_FOUND, {"error": "track not found"})
            return
        try:
            self._put_adjustments(track)
        except ValidationError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except ConfigError as error:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def do_OPTIONS(self) -> None:
        if not self._cors_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.send_header("Content-Length", "0")
        self._common_headers()
        self.end_headers()


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None | bool:
    if header is None:
        return None
    match = _RANGE_PATTERN.fullmatch(header.strip())
    if match is None or size <= 0:
        return False
    start_text = match.group("start")
    end_text = match.group("end")
    if not start_text and not end_text:
        return False
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            return False
        return max(0, size - suffix_length), size - 1
    start = int(start_text)
    end = min(int(end_text), size - 1) if end_text else size - 1
    if start >= size or end < start:
        return False
    return start, end


def create_server(
    collection_dir: Path,
    *,
    port: int = DEFAULT_PORT,
    asset_root: Traversable | None = None,
    stop_path: Path | None = None,
    duration_probe: Callable[[Path], float | None] = probe_duration,
    cleanup_defaults: Mapping[str, object] | None = None,
) -> AudioStudioServer:
    payload, track_files = build_track_payload(collection_dir, duration_probe=duration_probe)
    resolved_assets = asset_root or files("youtube_automation").joinpath("audio_studio_dist")
    return AudioStudioServer(
        (DEFAULT_HOST, port),
        collection_dir=collection_dir,
        asset_root=resolved_assets,
        track_payload=payload,
        track_files=track_files,
        cleanup_defaults=cleanup_defaults,
        stop_path=stop_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="コレクション音源を loopback Audio Studio で確認します")
    parser.add_argument("collection", nargs="?", help="コレクション path（省略時は CWD）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"配信 port（default: {DEFAULT_PORT}）")
    parser.add_argument("--stop", action="store_true", help="同じ collection / port の server を停止します")
    parser.add_argument("--no-open", action="store_true", help="起動後に browser を開きません")
    return parser


def _stop_server(collection_dir: Path, port: int) -> None:
    pid_path = pid_file_path(collection_dir, port, server_kind=SERVER_KIND)
    stop_path = stop_request_path(collection_dir, port, server_kind=SERVER_KIND)
    record = read_pid_file(pid_path)
    if record is None:
        print(f"No audio studio PID file for port {port}.")
        return
    if not pid_is_running(record.pid):
        remove_owned_pid_file(pid_path, record.pid)
        print(f"Removed stale audio studio PID file for port {port}.")
        return
    request = LifecycleRecord(record.pid, secrets.token_hex(16), record.configuration)
    remove_matching_record(stop_path, read_pid_file(stop_path) or request)
    write_pid_file(stop_path, request)
    with process_exit_watcher(record.pid) as wait_for_exit:
        if wait_for_exit is not None:
            stopped = wait_for_exit(5.0)
        else:
            deadline = time.monotonic() + 5.0
            while pid_is_running(record.pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            stopped = not pid_is_running(record.pid)
    if not stopped:
        remove_matching_record(stop_path, request)
        raise ConfigError(f"audio studio PID {record.pid} did not stop within 5 seconds")
    remove_matching_record(stop_path, request)
    remove_owned_pid_file(pid_path, record.pid)
    print(f"Stopped audio studio on port {port} (PID {record.pid}).")


def run(args: argparse.Namespace) -> int:
    if not 0 <= args.port <= 65535:
        raise ConfigError("--port は 0..65535 で指定してください")
    collection_dir = resolve_collection_dir(cast(str | None, args.collection))
    if args.stop:
        if args.port == 0:
            raise ConfigError("--stop では --port 0 を指定できません")
        _stop_server(collection_dir, args.port)
        return 0

    server = create_server(collection_dir, port=args.port)
    port = server.server_port
    pid_path = pid_file_path(collection_dir, port, server_kind=SERVER_KIND)
    stop_path = stop_request_path(collection_dir, port, server_kind=SERVER_KIND)
    lock_path = startup_lock_path(collection_dir, port, server_kind=SERVER_KIND)
    configuration = hashlib.sha256(str(collection_dir.resolve()).encode("utf-8")).hexdigest()
    record = LifecycleRecord(os.getpid(), secrets.token_hex(16), configuration)
    with file_lock(lock_path):
        existing = read_pid_file(pid_path)
        if existing is not None and pid_is_running(existing.pid):
            server.server_close()
            raise ConfigError(f"audio studio on port {port} is already running (PID {existing.pid})")
        if existing is not None:
            remove_owned_pid_file(pid_path, existing.pid)
        stop_path.unlink(missing_ok=True)
        write_pid_file(pid_path, record)
    server.stop_path = stop_path
    url = f"http://{DEFAULT_HOST}:{port}/"
    print(f"audio studio: {url}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.1)
    except (KeyboardInterrupt, _StopRequested):
        pass
    finally:
        server.server_close()
        remove_owned_pid_file(pid_path, record.pid)
        stop_path.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="audio studio error")


if __name__ == "__main__":
    raise SystemExit(main())
