from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock
from urllib.request import urlopen

import pytest

from youtube_automation.commands.media import audio_studio
from youtube_automation.commands.media.audio_studio import (
    DEFAULT_HOST,
    AdjustmentSection,
    adjustment_sections,
    build_track_payload,
    create_server,
    read_adjustment_route,
    write_adjustment_route,
)
from youtube_automation.commands.suno.suno_audio_cleanup import CleanupConfig, cleanup_config_settings
from youtube_automation.domains.media.audio_adjustments import (
    master_settings_from_cleanup,
    replace_master_adjustments,
)
from youtube_automation.infrastructure.localserver.app import Request
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths


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


def test_adjustment_section_registry_and_put_handler_are_socket_free(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    document_path = CollectionPaths(collection).audio_adjustments_path
    written: list[object] = []

    def write(_path: Path, settings: object):
        written.append(settings)
        return MagicMock()

    section = AdjustmentSection("example", lambda document: document.master, write)
    request = Request(method="PUT", path="/api/example", query={}, headers={}, json={"settings": {"enabled": True}})

    write_adjustment_route(request, section=section, document_path=document_path, collection_dir=collection)

    assert written == [{"enabled": True}]
    assert set(adjustment_sections()) == {"tracks", "order", "master", "finalize"}


def test_adjustment_section_read_handler_is_socket_free(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    document_path = CollectionPaths(collection).audio_adjustments_path
    section = adjustment_sections()["master"]

    assert read_adjustment_route(section=section, document_path=document_path) is None


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


def test_adjustments_api_returns_defaults_and_saves_only_track_diff(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    audio = collection / "02-Individual-music" / "01 Track.mp3"
    audio.write_bytes(b"audio")
    defaults = cleanup_config_settings(CleanupConfig(enabled=True))
    server = create_server(
        collection,
        port=0,
        asset_root=_assets(tmp_path),
        duration_probe=lambda _path: 5.0,
        cleanup_defaults=defaults,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        track_id = next(iter(server.track_files))
        route = f"/api/tracks/{track_id}/adjustments"
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("GET", route)
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload == {"defaults": defaults, "settings": defaults, "overrides": {}}

        settings = dict(defaults)
        settings["eq"] = {**settings["eq"], "muddiness_gain_db": -4.0}
        body = json.dumps({"settings": settings})
        connection.request(
            "PUT",
            route,
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body.encode()))},
        )
        response = connection.getresponse()
        saved = json.loads(response.read())
        assert response.status == 200
        assert saved["overrides"] == {"eq": {"muddiness_gain_db": -4.0}}
        assert json.loads((collection / "20-documentation/audio-adjustments.json").read_text())["tracks"] == {
            "01 Track.mp3": {"eq": {"muddiness_gain_db": -4.0}}
        }
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_order_api_returns_default_and_saves_exact_order_seed_and_pins(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    music = collection / "02-Individual-music"
    (music / "02 Second.wav").write_bytes(b"second")
    (music / "01 First.mp3").write_bytes(b"first")
    server = create_server(collection, port=0, asset_root=_assets(tmp_path), duration_probe=lambda _path: 5.0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("GET", "/api/order")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {
            "order": ["01 First.mp3", "02 Second.wav"],
            "shuffle_seed": None,
            "pin_first": [],
            "saved": False,
        }

        payload = {
            "order": ["02 Second.wav", "01 First.mp3"],
            "shuffle_seed": 123,
            "pin_first": ["02 Second.wav"],
        }
        connection.request("PUT", "/api/order", body=json.dumps(payload))
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {**payload, "saved": True}
        saved = json.loads((collection / "20-documentation/audio-adjustments.json").read_text())
        assert {key: saved[key] for key in payload} == payload
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_order_api_rejects_file_set_mismatch(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    (collection / "02-Individual-music" / "01 First.mp3").write_bytes(b"first")
    server = create_server(collection, port=0, asset_root=_assets(tmp_path), duration_probe=lambda _path: 5.0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        payload = {"order": ["missing.mp3"], "shuffle_seed": None, "pin_first": []}
        connection.request("PUT", "/api/order", body=json.dumps(payload))
        response = connection.getresponse()
        assert response.status == 400
        assert "実ファイル" in json.loads(response.read())["error"]
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_master_api_serves_audio_saves_settings_and_applies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    master = collection / "01-master/master.mp3"
    master.write_bytes(b"0123456789")
    defaults = cleanup_config_settings(CleanupConfig(enabled=True))
    settings = master_settings_from_cleanup(defaults)
    settings["eq"] = {**settings["eq"], "muddiness_gain_db": -4.0}
    applied: list[Path] = []

    def fake_adjust(path: Path, *, quiet: bool) -> Path:
        assert quiet is True
        applied.append(path)
        master.write_bytes(b"adjusted")
        return master

    monkeypatch.setattr(audio_studio, "adjust_master", fake_adjust)
    server = create_server(
        collection,
        port=0,
        asset_root=_assets(tmp_path),
        duration_probe=lambda _path: 5.0,
        cleanup_defaults=defaults,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("GET", "/api/master/adjustments")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["available"] is True
        assert payload["settings"] == master_settings_from_cleanup(defaults)

        body = json.dumps({"settings": settings})
        connection.request("PUT", "/api/master/adjustments", body=body)
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["settings"] == settings

        connection.request("GET", "/api/master/audio", headers={"Range": "bytes=2-5"})
        response = connection.getresponse()
        assert response.status == 206
        assert response.read() == b"2345"

        connection.request("POST", "/api/master/apply")
        response = connection.getresponse()
        applied_payload = json.loads(response.read())
        assert response.status == 200
        assert applied_payload["applied"] is True
        assert applied == [collection]
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_master_api_reports_missing_master(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    defaults = cleanup_config_settings(CleanupConfig(enabled=True))
    server = create_server(
        collection,
        port=0,
        asset_root=_assets(tmp_path),
        duration_probe=lambda _path: 5.0,
        cleanup_defaults=defaults,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("GET", "/api/master/adjustments")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["available"] is False

        connection.request("GET", "/api/master/audio")
        response = connection.getresponse()
        assert response.status == 404
        response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_finalize_api_saves_applies_and_reapplies_master_adjustment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    (collection / "01-master/master.mp3").write_bytes(b"master")
    layer_dir = collection / "branding/rain_layers"
    layer_dir.mkdir(parents=True)
    (layer_dir / "rain_001.wav").write_bytes(b"rain")
    defaults = cleanup_config_settings(CleanupConfig(enabled=True))
    master_settings = master_settings_from_cleanup(defaults)
    replace_master_adjustments(CollectionPaths(collection).audio_adjustments_path, master_settings)
    monkeypatch.setattr(audio_studio, "load_skill_config", lambda *_args, **_kwargs: {})
    finalized: list[Path] = []
    adjusted: list[Path] = []
    monkeypatch.setattr(
        audio_studio,
        "finalize_master",
        lambda path, _channel, *, quiet: finalized.append(path) or 0,
    )
    monkeypatch.setattr(
        audio_studio,
        "adjust_master",
        lambda path, *, quiet: adjusted.append(path) or path / "01-master/master.mp3",
    )
    server = create_server(
        collection,
        port=0,
        asset_root=_assets(tmp_path),
        duration_probe=lambda _path: 5.0,
        cleanup_defaults=defaults,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("GET", "/api/finalize/adjustments")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["available"] is True
        assert payload["layers"] == ["rain_001.wav"]

        settings = payload["settings"]
        settings["ambient_layers"]["volume_db"] = -27.0
        body = json.dumps({"settings": settings})
        connection.request("PUT", "/api/finalize/adjustments", body=body)
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["settings"]["ambient_layers"]["volume_db"] == -27.0

        connection.request("POST", "/api/finalize/apply")
        response = connection.getresponse()
        applied = json.loads(response.read())
        assert response.status == 200
        assert applied["applied"] is True
        assert applied["master_reapplied"] is True
        assert finalized == [collection]
        assert adjusted == [collection]
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_finalize_api_disables_and_passes_through_without_layers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    (collection / "01-master/master.mp3").write_bytes(b"master")
    defaults = cleanup_config_settings(CleanupConfig(enabled=True))
    monkeypatch.setattr(audio_studio, "load_skill_config", lambda *_args, **_kwargs: {})
    finalize_spy = MagicMock()
    monkeypatch.setattr(audio_studio, "finalize_master", finalize_spy)
    server = create_server(
        collection,
        port=0,
        asset_root=_assets(tmp_path),
        duration_probe=lambda _path: 5.0,
        cleanup_defaults=defaults,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("POST", "/api/finalize/apply")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["available"] is False
        assert payload["applied"] is False
        assert payload["pass_through"] is True
        assert "pass-through" in payload["reason"]
        finalize_spy.assert_not_called()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_adjustments_api_rejects_unknown_track_and_invalid_settings(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    (collection / "02-Individual-music" / "track.mp3").write_bytes(b"audio")
    defaults = cleanup_config_settings(CleanupConfig(enabled=True))
    server = create_server(
        collection,
        port=0,
        asset_root=_assets(tmp_path),
        duration_probe=lambda _path: 5.0,
        cleanup_defaults=defaults,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        invalid_body = json.dumps({"settings": {"eq": {"muddiness_gain_db": "deep"}}})
        track_id = next(iter(server.track_files))
        connection.request("PUT", f"/api/tracks/{track_id}/adjustments", body=invalid_body)
        response = connection.getresponse()
        assert response.status == 400
        response.read()

        connection.request("GET", "/api/tracks/0000000000000000/adjustments")
        response = connection.getresponse()
        assert response.status == 404
        response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_adjustments_api_does_not_follow_documentation_directory_symlink(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    (collection / "02-Individual-music" / "track.mp3").write_bytes(b"audio")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (collection / "20-documentation").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink is unavailable")
    defaults = cleanup_config_settings(CleanupConfig(enabled=True))
    server = create_server(
        collection,
        port=0,
        asset_root=_assets(tmp_path),
        duration_probe=lambda _path: 5.0,
        cleanup_defaults=defaults,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        track_id = next(iter(server.track_files))
        body = json.dumps({"settings": defaults})
        connection = http.client.HTTPConnection(DEFAULT_HOST, server.server_port, timeout=2)
        connection.request("PUT", f"/api/tracks/{track_id}/adjustments", body=body)
        response = connection.getresponse()
        assert response.status == 400
        response.read()
        assert not (outside / "audio-adjustments.json").exists()
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
