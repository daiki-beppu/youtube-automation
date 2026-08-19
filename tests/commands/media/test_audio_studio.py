from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

from youtube_automation.commands.media.audio_studio import (
    DEFAULT_HOST,
    build_track_payload,
    create_server,
)


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "20260820-clm-night-drive-collection"
    (collection / "01-master").mkdir(parents=True)
    (collection / "02-Individual-music").mkdir()
    return collection


def _assets(tmp_path: Path) -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<title>Audio Studio</title><div id='root'></div>", encoding="utf-8")
    return assets


def test_build_track_payload_lists_supported_audio_in_name_order(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    music = collection / "02-Individual-music"
    (music / "02 Second.wav").write_bytes(b"second")
    (music / "01 First.mp3").write_bytes(b"first")
    (music / "notes.txt").write_text("ignored", encoding="utf-8")

    payload, files = build_track_payload(collection, duration_probe=lambda path: 61.5 if path.suffix == ".mp3" else 120)

    tracks = payload["tracks"]
    assert isinstance(tracks, list)
    assert [track["file_name"] for track in tracks] == ["01 First.mp3", "02 Second.wav"]
    assert tracks[0]["duration_seconds"] == 61.5
    assert tracks[0]["extension"] == "mp3"
    assert set(files) == {track["id"] for track in tracks}


def test_server_binds_loopback_and_serves_static_track_api_and_range_audio(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    audio = collection / "02-Individual-music" / "01 Track.mp3"
    audio.write_bytes(b"0123456789")
    server = create_server(collection, port=0, asset_root=_assets(tmp_path), duration_probe=lambda _path: 10.0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[0] == DEFAULT_HOST
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert b"Audio Studio" in response.read()

        connection.request("GET", "/api/tracks")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["collection_name"] == "night-drive-collection"
        assert payload["tracks"][0]["file_name"] == "01 Track.mp3"

        connection.request("GET", payload["tracks"][0]["audio_url"], headers={"Range": "bytes=2-5"})
        response = connection.getresponse()
        assert response.status == 206
        assert response.getheader("Content-Range") == "bytes 2-5/10"
        assert response.getheader("Accept-Ranges") == "bytes"
        assert response.read() == b"2345"
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_server_rejects_unknown_track_invalid_range_and_web_origin(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    (collection / "02-Individual-music" / "track.mp3").write_bytes(b"audio")
    server = create_server(collection, port=0, asset_root=_assets(tmp_path), duration_probe=lambda _path: 5.0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("GET", "/api/tracks/0000000000000000/audio")
        response = connection.getresponse()
        assert response.status == 404
        response.read()

        track_id = next(iter(server.track_files))
        connection.request("GET", f"/api/tracks/{track_id}/audio", headers={"Range": "bytes=99-100"})
        response = connection.getresponse()
        assert response.status == 416
        response.read()

        for foreign_origin in (
            "https://example.com",
            "https://suno.com",
            "https://distrokid.com",
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
        ):
            connection.request("GET", "/api/tracks", headers={"Origin": foreign_origin})
            response = connection.getresponse()
            assert response.status == 403
            assert response.getheader("Access-Control-Allow-Origin") is None
            response.read()

        same_origin = f"http://{DEFAULT_HOST}:{server.server_port}"
        connection.request("GET", "/api/tracks", headers={"Origin": same_origin})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") == same_origin
        response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_empty_collection_has_explicit_empty_track_list(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    payload, files = build_track_payload(collection, duration_probe=lambda _path: pytest.fail("no probe expected"))

    assert payload["tracks"] == []
    assert files == {}


def test_zero_byte_audio_has_zero_content_length(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    (collection / "02-Individual-music" / "empty.wav").touch()
    server = create_server(collection, port=0, asset_root=_assets(tmp_path), duration_probe=lambda _path: 0.0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        track_id = next(iter(server.track_files))
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("GET", f"/api/tracks/{track_id}/audio")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Length") == "0"
        assert response.read() == b""
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cli_stop_request_uses_audio_studio_lifecycle_files(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    with socket.socket() as probe:
        probe.bind((DEFAULT_HOST, 0))
        port = probe.getsockname()[1]
    command = [
        sys.executable,
        "-m",
        "youtube_automation.commands.media.audio_studio",
        str(collection),
        "--port",
        str(port),
        "--no-open",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://{DEFAULT_HOST}:{port}/api/tracks", timeout=0.5) as response:
                    assert response.status == 200
                    break
            except OSError:
                time.sleep(0.05)
        else:
            stdout, stderr = process.communicate(timeout=2)
            pytest.fail(f"audio studio did not start\nstdout={stdout}\nstderr={stderr}")

        stopped = subprocess.run([*command[:-1], "--stop"], capture_output=True, text=True, timeout=10)

        assert stopped.returncode == 0, stopped.stderr
        assert "Stopped audio studio" in stopped.stdout
        assert process.wait(timeout=5) == 0
        assert not (collection / f".audio-studio-{port}.pid").exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
