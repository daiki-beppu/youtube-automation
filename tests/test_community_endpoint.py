"""community-helper 向け collection-serve HTTP 契約（#1710）。"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.scripts import collection_serve as collection_serve_module
from youtube_automation.scripts.collection_serve import create_server, main

_COMMUNITY_POSTS_ROUTE = "/community/posts.json"
_COMMUNITY_IMAGE_ROUTE = "/community/posts"
_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
_STUDIO_ORIGIN = "https://studio.youtube.com"


@pytest.fixture
def serve_community(tmp_path):
    started = []

    def _start(posts: list[dict], *, image: tuple[str, bytes] | None = None) -> str:
        collection = tmp_path / "collections" / "planning" / "20260718-community-collection"
        promo = collection / "30-promo"
        promo.mkdir(parents=True)
        (promo / "community-posts.json").write_text(
            json.dumps({"posts": posts}, ensure_ascii=False),
            encoding="utf-8",
        )
        if image is not None:
            image_path = tmp_path / image[0]
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(image[1])

        server = create_server(
            0,
            None,
            prompts_path=None,
            collection_dir=collection,
            community_asset_root=tmp_path,
            distrokid=None,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        return f"http://localhost:{server.server_address[1]}"

    yield _start

    for server, thread in started:
        server.shutdown()
        thread.join(timeout=5)


def test_get_community_posts_returns_post_array(serve_community):
    posts = [
        {
            "text": "公開のお知らせ",
            "scheduled_at": "2026-07-19T18:00:00+09:00",
            "image_path": None,
            "visibility": "public",
        }
    ]
    base = serve_community(posts)

    with urllib.request.urlopen(f"{base}{_COMMUNITY_POSTS_ROUTE}") as response:
        assert response.status == 200
        assert response.headers.get_content_type() == "application/json"
        assert json.loads(response.read().decode("utf-8")) == posts


def test_community_only_server_returns_404_for_suno_route(serve_community):
    base = serve_community([])

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}/suno/prompts.json")

    assert exc_info.value.code == 404


@pytest.mark.parametrize(
    ("relative_path", "content_type"),
    [
        ("collections/planning/20260718-community-collection/main.png", "image/png"),
        ("collections/planning/20260718-community-collection/main.jpg", "image/jpeg"),
    ],
)
def test_get_community_image_returns_binary_with_detected_content_type(
    serve_community, relative_path: str, content_type: str
):
    image = b"image-binary"
    base = serve_community(
        [{"text": "post", "scheduled_at": "2026-07-19T18:00:00+09:00", "image_path": relative_path}],
        image=(relative_path, image),
    )

    with urllib.request.urlopen(f"{base}{_COMMUNITY_IMAGE_ROUTE}/0/image") as response:
        assert response.status == 200
        assert response.headers.get_content_type() == content_type
        assert response.read() == image


def test_get_community_image_returns_404_when_image_path_is_null(serve_community):
    base = serve_community([{"text": "post", "scheduled_at": "2026-07-19T18:00:00+09:00", "image_path": None}])

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}{_COMMUNITY_IMAGE_ROUTE}/0/image")

    assert exc_info.value.code == 404


def test_get_community_image_rejects_path_outside_channel_root(serve_community, tmp_path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"secret")
    base = serve_community(
        [{"text": "post", "scheduled_at": "2026-07-19T18:00:00+09:00", "image_path": "../outside.png"}]
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}{_COMMUNITY_IMAGE_ROUTE}/0/image")

    assert exc_info.value.code == 404


def test_get_community_image_rejects_channel_file_outside_collection(serve_community, tmp_path):
    secret = tmp_path / "auth" / "token.png"
    secret.parent.mkdir()
    secret.write_bytes(b"secret")
    base = serve_community(
        [{"text": "post", "scheduled_at": "2026-07-19T18:00:00+09:00", "image_path": "auth/token.png"}]
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}{_COMMUNITY_IMAGE_ROUTE}/0/image")

    assert exc_info.value.code == 404


def test_get_community_image_rejects_non_image_file(serve_community):
    relative_path = "collections/planning/20260718-community-collection/secret.json"
    base = serve_community(
        [{"text": "post", "scheduled_at": "2026-07-19T18:00:00+09:00", "image_path": relative_path}],
        image=(relative_path, b'{"token": "secret"}'),
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}{_COMMUNITY_IMAGE_ROUTE}/0/image")

    assert exc_info.value.code == 404


@pytest.mark.parametrize("origin", [_EXTENSION_ORIGIN, _STUDIO_ORIGIN])
def test_community_routes_allow_required_cors_origins(serve_community, origin: str):
    base = serve_community([])
    request = urllib.request.Request(f"{base}{_COMMUNITY_POSTS_ROUTE}", headers={"Origin": origin})

    with urllib.request.urlopen(request) as response:
        assert response.headers.get("Access-Control-Allow-Origin") == origin


def test_studio_origin_can_read_public_version_for_extension_preflight(serve_community):
    base = serve_community([])
    request = urllib.request.Request(f"{base}/version", headers={"Origin": _STUDIO_ORIGIN})

    with urllib.request.urlopen(request) as response:
        assert response.headers.get("Access-Control-Allow-Origin") == _STUDIO_ORIGIN


def test_studio_origin_is_not_allowed_to_read_other_non_community_routes(serve_community):
    base = serve_community([])
    request = urllib.request.Request(f"{base}/suno/prompts.json", headers={"Origin": _STUDIO_ORIGIN})

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request)

    assert exc_info.value.code == 404
    assert exc_info.value.headers.get("Access-Control-Allow-Origin") is None


def test_shared_route_constants_match_server_contract():
    constants = (Path(__file__).parents[1] / "extensions/shared/constants.ts").read_text(encoding="utf-8")

    assert 'export const COMMUNITY_POSTS_ROUTE = "/community/posts.json"' in constants
    assert 'export const COMMUNITY_IMAGE_ROUTE = "/community/posts"' in constants


def test_dir_mode_does_not_expose_initial_scope_community_routes(tmp_path):
    collection = tmp_path / "20260718-community-collection"
    (collection / "30-promo").mkdir(parents=True)
    (collection / "30-promo/community-posts.json").write_text('{"posts": []}', encoding="utf-8")
    server = create_server(
        0,
        None,
        prompts_path=None,
        collection_dir=None,
        collections_root=tmp_path,
        distrokid=None,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://localhost:{server.server_address[1]}"
    try:
        for route in (_COMMUNITY_POSTS_ROUTE, f"{_COMMUNITY_IMAGE_ROUTE}/0/image"):
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"{base}{route}")
            assert exc_info.value.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_main_accepts_community_only_collection(tmp_path, monkeypatch):
    collection = tmp_path / "collections" / "planning" / "20260718-community-collection"
    (collection / "30-promo").mkdir(parents=True)
    (collection / "30-promo/community-posts.json").write_text('{"posts": []}', encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeServer:
        server_address = ("localhost", 0)

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            pass

    class FakeDiscoveryLifecycle:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    def fake_create_server(port: int, allow_origin: str | None, **kwargs: object) -> FakeServer:
        captured.update(kwargs)
        return FakeServer()

    config = SimpleNamespace(
        distrokid=SimpleNamespace(enabled=False),
        meta=SimpleNamespace(channel_name="Test", channel_short="T"),
    )
    monkeypatch.setattr(collection_serve_module, "load_config", lambda: config)
    monkeypatch.setattr(collection_serve_module, "channel_dir", lambda: tmp_path)
    monkeypatch.setattr(collection_serve_module, "create_server", fake_create_server)
    monkeypatch.setattr(
        collection_serve_module,
        "create_discovery_lifecycle",
        lambda _server_info: FakeDiscoveryLifecycle(),
    )
    monkeypatch.setattr(sys, "argv", ["yt-collection-serve", str(collection), "--port", "0"])

    main()

    assert captured["prompts_path"] is None
    assert captured["collection_dir"] == collection
    assert captured["community_asset_root"] == tmp_path
