#!/usr/bin/env python3
"""yt-collection-serve: コレクション成果物をローカル HTTP で Chrome 拡張へ配信する.

issue #698: #692 の `yt-suno-serve` を一般化し、エンドポイントをサブパス分離する。

- `GET /suno/prompts.json` … suno-prompts.json 配列 JSON（#692 契約不変）
- `GET /distrokid/release.json` … profile + collection 動的データのマージ JSON
- `GET /distrokid/assets/<path>` … 曲・ジャケットファイルの binary 配信
- `GET /community/posts.json` … community-posts.json の投稿配列
- `GET /community/posts/<index>/image` … 投稿画像の binary 配信

起動中は port 別 PID ファイルを記録し、`--stop --port <PORT>` または HTTP request の
idle timeout（既定 60 分）で終了する。同一 port かつ同一構成の生存 server は再利用する。

`distrokid` が None または `enabled == False` のとき `/distrokid/*` は 404。
CORS はデフォルトで Chrome 拡張オリジン (`chrome-extension://...`) と helper サイト
web origin (`https://suno.com` / `https://distrokid.com` 系) を許可し、全ルートで
同一ポリシー。`--allow-origin` / `--allow-extension` 指定時はその値との完全一致のみに lock する。
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import http.client
import json
import math
import mimetypes
import os
import re
import secrets
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from youtube_automation import __version__
from youtube_automation.configuration import Distrokid, channel_dir, load_config
from youtube_automation.domains.distrokid.metadata import parse_album_metadata
from youtube_automation.domains.distrokid.release import (
    DISTROKID_ASSETS_PREFIX,
    DISTROKID_COLLECTION_ASSETS_PREFIX,
    DISTROKID_RELEASE_ROUTE,
    build_release_payload,
    kebab_to_title,
    resolve_asset_path,
)
from youtube_automation.domains.distrokid.specification import find_disc_entry, read_collection_spec
from youtube_automation.domains.suno.downloaded import (
    DownloadedArtifactError,
    DownloadedPayloadError,
    apply_downloaded_artifacts,
    count_audio_files,
    expected_download_count,
    parse_downloaded_payload,
    read_pattern_count,
)
from youtube_automation.domains.suno.prompts import read_suno_prompt_entries
from youtube_automation.scripts.collection_serve_discovery import (
    DISCOVERY_PORT,
    RegistryState,
    create_discovery_lifecycle,
    handle_registry_request,
)
from youtube_automation.scripts.suno_artifacts import (
    COLLECTIONS_ROUTE,
    DOCUMENTATION_DIRNAME,
    DOWNLOADED_ROUTE_SUFFIX,
    SUNO_PROMPTS_JSON_FILENAME,
    SUNO_PROMPTS_ROUTE,
    collection_downloaded_route,
)
from youtube_automation.utils.chrome_extensions import ChromeExtensionOrigin, resolve_unpacked_extension_origin
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ConfigError

DEFAULT_PORT = 7873
DEFAULT_IDLE_TIMEOUT_SECONDS = 60 * 60
VERSION_ROUTE = "/version"
SERVER_INFO_ROUTE = "/server-info"
_LIFECYCLE_ROUTE_PREFIX = "/.well-known/yt-collection-serve-lifecycle/"
MIN_EXTENSION_VERSION = "0.2.0"
_EXTENSION_ORIGIN_SCHEME = "chrome-extension://"
# overlay 化（#892/#895）で content script の fetch が page origin になったため、
# helper 拡張がホストされる web origin をデフォルト許可する（#896/#1710）。完全一致のみ。
_DEFAULT_ALLOWED_WEB_ORIGINS = frozenset(
    {
        "https://suno.com",
        "https://www.suno.com",
        "https://distrokid.com",
        "https://www.distrokid.com",
    }
)
# `collections/planning/` 配下で 1 コレクションを示すディレクトリ接尾辞。
_COLLECTION_DIR_SUFFIX = "-collection"

# DistroKid dir mode: リリース記録の出力先 JSON（`<root>/config/distrokid-releases.json`）（#934）。
_DISTROKID_RELEASES_OUTPUT_RELPATH = Path("config") / "distrokid-releases.json"
_DISTROKID_CAPTURE_ROOT_ENV = "DISTROKID_CAPTURE_ROOT"

# 30-distrokid サブディレクトリ名（#934）。コレクション配下のこのサブディレクトリが disc を含む。
_DISTROKID_DIRNAME = "30-distrokid"
_DISTROKID_METADATA_FILENAME = "metadata.md"

# dir mode: DistroKid collections 一覧 + releases POST のルート定数（#934）。
# distrokid-helper 拡張と対の契約（extensions/shared/constants.ts に追加予定）。
_DISTROKID_COLLECTIONS_ROUTE = "/distrokid/collections"
_DISTROKID_RELEASES_ROUTE = "/distrokid/releases"

# community-helper と対の公開 HTTP 契約。extensions/shared/constants.ts に同値を置く。
COMMUNITY_POSTS_ROUTE = "/community/posts.json"
COMMUNITY_IMAGE_ROUTE = "/community/posts"
_COMMUNITY_POSTS_RELPATH = Path("30-promo") / "community-posts.json"
_COMMUNITY_IMAGE_ROUTE_PATTERN = re.compile(r"^/community/posts/(?P<index>\d+)/image$")

# POST body upper bound for helper write endpoints. The expected payloads are
# small JSON objects/lists; larger bodies are rejected before reading from rfile.
_MAX_POST_BODY_BYTES = 1024 * 1024
_MAX_DOWNLOADED_POST_BODY_BYTES = 10 * 1024
_MAX_UNATTENDED_REQUEST_BODY_BYTES = 32 * 1024
_UNATTENDED_REQUESTS_ROUTE = "/unattended/requests"
_UNATTENDED_REQUEST_TTL_SECONDS = 5 * 60


class _ServerTerminationSignal(RuntimeError):
    """予期しない SIGTERM を未捕捉例外として記録可能にする。"""

    def __init__(self, signum: int) -> None:
        signal_name = signal.Signals(signum).name
        super().__init__(f"{signal_name} (signal {signum}) requested server termination")


class _IdleTimeout(RuntimeError):
    """HTTP request の無通信時間が上限に達したことを表す。"""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        super().__init__(f"no HTTP requests received for {seconds:g} seconds")


@dataclass(frozen=True)
class _LifecycleRecord:
    pid: int
    token: str
    configuration: str


class _IdleTrackingHTTPServer(ThreadingHTTPServer):
    """request の受付時刻を追跡し、serve loop から idle 終了する HTTP server。"""

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], seconds: float):
        self._idle_timeout_seconds = seconds
        self._last_request_at = time.monotonic()
        super().__init__(server_address, handler_class)

    def finish_request(self, request: object, client_address: tuple[str, int]) -> None:
        self._last_request_at = time.monotonic()
        super().finish_request(request, client_address)

    def service_actions(self) -> None:
        super().service_actions()
        if time.monotonic() - self._last_request_at >= self._idle_timeout_seconds:
            raise _IdleTimeout(self._idle_timeout_seconds)


def _hostname_slug(text: str) -> str:
    """チャンネル名を `*.localhost` 用の ASCII hostname label にする（#1352）。"""
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "youtube-automation"


def channel_hostname(channel_name: str) -> str:
    """チャンネル識別できるローカル hostname を返す。"""
    return f"{_hostname_slug(channel_name)}.localhost"


def build_server_info(channel_name: str, channel_short: str, port: int) -> dict[str, str | int]:
    """helper 拡張の接続先 selector に出す配信元情報（#1352）。"""
    hostname_source = (
        channel_short if channel_short and not re.search(r"[a-z0-9]", channel_name.lower()) else channel_name
    )
    hostname = channel_hostname(hostname_source)
    base_url = f"http://{hostname}:{port}"
    short = channel_short or channel_name
    return {
        "channel_name": channel_name,
        "channel_short": short,
        "hostname": hostname,
        "port": port,
        "base_url": base_url,
        "label": f"{channel_name} ({hostname}:{port})",
    }


def distrokid_releases_output_path(root: Path) -> Path:
    """DistroKid リリース記録 JSON の実体パス `<root>/config/distrokid-releases.json` を返す（#934）."""
    return root / _DISTROKID_RELEASES_OUTPUT_RELPATH


def _read_distrokid_releases(target: Path) -> dict:
    """既存 DistroKid リリース記録 JSON を dict で読む。不在・破損・非 dict は空 dict 扱い（#934）."""
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_json_write(target: Path, data: dict, *, prefix: str) -> None:
    """JSON dict を target へ atomic に書く。失敗時は中間 temp を残さない。"""
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=prefix, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, target)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def read_released_discs(root: Path) -> set[str]:
    """既存 `<root>/config/distrokid-releases.json` の `<collection_id>/<disc>` キー集合を返す（#934）.

    不在・破損は空集合（fail-loud せず「未配信」として扱う）。
    """
    return set(_read_distrokid_releases(distrokid_releases_output_path(root)).keys())


def write_distrokid_release(root: Path, collection_id: str, disc: str, album_title: str) -> None:
    """DistroKid リリース記録を `<root>/config/distrokid-releases.json` へ atomic 書き込みする（#934）.

    `<collection_id>/<disc>` をキーに `album_title` と `recorded_at`（ローカル時刻）を記録する。
    既存キーへの再書き込みは上書き（冪等）。`tempfile.mkstemp` → `os.replace` で atomic write。
    """
    target = distrokid_releases_output_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _read_distrokid_releases(target)

    key = f"{collection_id}/{disc}"
    # ローカルタイムゾーン付き ISO 8601 で記録する（後から人間が読める形式）。
    recorded_at = datetime.now().astimezone().isoformat()
    data[key] = {"album_title": album_title, "recorded_at": recorded_at}

    _atomic_json_write(target, data, prefix=".distrokid-releases-")


def find_distrokid_discs(collection_dir: Path) -> list[str]:
    """コレクション配下の `30-distrokid/<disc>/` を持つ disc 名一覧をソート済みで返す（#934）.

    disc ディレクトリは mp3 を 1 つ以上含む場合のみ列挙する。`30-distrokid/` 不在のコレクションは
    空リストを返す（例外は投げない）。
    """
    distrokid_dir = collection_dir / _DISTROKID_DIRNAME
    if not distrokid_dir.is_dir():
        return []
    discs = []
    for d in sorted(distrokid_dir.iterdir()):
        if d.is_dir() and any(d.glob("*.mp3")):
            discs.append(d.name)
    return discs


def _read_disc_album_title(collection_dir: Path, disc: str) -> str | None:
    """disc ディレクトリの album_title を読む（#941 spec 優先 / metadata.md フォールバック）.

    読み取り優先順位（#934 の fail-soft 方針を維持）:
    1. <collection>/30-distrokid/spec.json に disc のエントリがあり album_title が非空
       → spec の値を返す。
    2. spec 不在 / エントリ無し / spec 破損（ConfigError / OSError）
       → 従来の metadata.md fail-soft 読み。
    3. metadata.md も不在・エラー・album_title 空
       → None（呼び出し元の kebab_to_title フォールバックに任せる）。

    一覧表示用途なので例外を投げない（fail-soft）。
    release.json 組み立て時の fail-loud は `build_release_payload` 側で行う（#934）。
    """
    distrokid_dir = collection_dir / _DISTROKID_DIRNAME

    # spec.json 優先（#941）。破損 spec は fail-soft で metadata.md に降りる。
    try:
        spec = read_collection_spec(distrokid_dir)
        if spec is not None:
            entry = find_disc_entry(spec, disc)
            if entry is not None:
                album_title = entry.get("album_title")
                if album_title:
                    return str(album_title)
    except (ConfigError, OSError):
        # spec 破損・読み取りエラーは一覧表示なので fail-soft（metadata.md に降りる）。
        pass

    # metadata.md フォールバック（後方互換、従来の動作）。
    metadata_path = distrokid_dir / disc / _DISTROKID_METADATA_FILENAME
    if not metadata_path.is_file():
        return None
    try:
        meta = parse_album_metadata(metadata_path)
        return meta.get("album_title") or None
    except (ConfigError, OSError):
        # parse 失敗・読み取りエラーは一覧表示なので fail-soft（disc 名フォールバックに任せる）。
        return None


def build_distrokid_collections_index(
    root: Path,
    *,
    released_discs: set[str] | None = None,
) -> list[dict]:
    """collections_root 配下の DistroKid disc を列挙して JSON 配列用 dict リストを返す（#934）.

    - `collection_id`: コレクションディレクトリ名
    - `name`: CollectionPaths.collection_name（日付・channel 接頭辞を除去した表示名）
    - `disc`: disc ディレクトリ名（`<collection>/30-distrokid/<disc>/`）
    - `album_title`: metadata.md の album_title、不在なら `kebab_to_title(disc)` へフォールバック
    - `track_count`: disc 内の `*.mp3` 件数
    - `released`: `released_discs` に `"<collection_id>/<disc>"` が含まれるか。
      released_discs=None（capture root 未指定）時は全件 False（#934 要件）

    ソートは collection_id 昇順 → disc 昇順。
    """
    discs_set = released_discs if released_discs is not None else set()
    index: list[dict] = []
    for coll in find_collection_dirs(root):
        discs = find_distrokid_discs(coll)
        for disc in discs:
            disc_dir = coll / _DISTROKID_DIRNAME / disc
            track_count = len(list(disc_dir.glob("*.mp3")))
            album_title = _read_disc_album_title(coll, disc) or kebab_to_title(disc)
            key = f"{coll.name}/{disc}"
            index.append(
                {
                    "collection_id": coll.name,
                    "name": CollectionPaths(coll).collection_name,
                    "disc": disc,
                    "album_title": album_title,
                    "track_count": track_count,
                    "released": key in discs_set,
                }
            )
    return index


def resolve_prompts_path(path: Path) -> Path:
    """引数パスを suno-prompts.json の実体パスへ解決する.

    - ファイルパス → そのまま返す
    - ディレクトリ → `<dir>/20-documentation/suno-prompts.json`（存在すれば）
    - 不在 / json が見つからない → ConfigError（fail-loud、silent 続行しない）
    """
    if path.is_file():
        return path
    if path.is_dir():
        candidate = path / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
        if candidate.is_file():
            return candidate
        raise ConfigError(f"{SUNO_PROMPTS_JSON_FILENAME} not found under {path}")
    raise ConfigError(f"path does not exist: {path}")


def find_collection_dirs(root: Path) -> list[Path]:
    """`root` 直下の `*-collection` ディレクトリのみを名前昇順で返す（#816 dir mode）.

    `collections/planning/` 配下には `01-master` 等の非コレクションや雑多なファイルが
    混在しうるため、接尾辞 `-collection` を持つディレクトリだけをホワイトリスト採用する。
    `root` が存在しない / ディレクトリでない場合は空リスト。
    """
    if not root.is_dir():
        return []
    dirs = (p for p in root.iterdir() if p.is_dir() and p.name.endswith(_COLLECTION_DIR_SUFFIX))
    return sorted(dirs, key=lambda p: p.name)


def _is_live_complete_collection(root: Path, collection_id: str) -> bool:
    """planning の対応する live collection が完了済みなら True を返す（#2331）。

    Suno の dir mode を ``collections/planning`` で配信する場合だけ sibling の
    ``collections/live/<collection_id>/workflow-state.json`` を参照する。状態ファイルが
    不在・破損・非 object の場合は fail-open とし、planning 側を従来どおり表示する。
    """
    if root.name != "planning" or root.parent.name != "collections":
        return False
    workflow_state = root.parent / "live" / collection_id / "workflow-state.json"
    if not workflow_state.is_file():
        return False
    try:
        data = json.loads(workflow_state.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and data.get("phase") == "complete"


def _find_suno_collection_dirs(root: Path) -> list[Path]:
    """Suno に提示可能な planning collection だけを返す（#2331）。"""
    return [coll for coll in find_collection_dirs(root) if not _is_live_complete_collection(root, coll.name)]


def _determine_status(
    has_prompts: bool,
    pattern_count: int | None,
    downloaded_count: int,
    explicit_expected: int | None = None,
) -> str:
    """collection の status を判定する（#1216）.

    - ``needs_prompts``: suno-prompts.json が無い
    - ``downloaded``: prompts が有り、02-Individual-music/ の音声ファイル数 >= pattern_count * 2
    - ``ready``: prompts が有り、ダウンロード未完了
    """
    if not has_prompts:
        return "needs_prompts"
    expected_count = expected_download_count(pattern_count, explicit_expected)
    if expected_count is not None and downloaded_count >= expected_count:
        return "downloaded"
    return "ready"


def _read_music_downloaded_flag(coll_dir: Path) -> bool:
    """workflow-state.json の assets.music_downloaded を読む（#1913 部分完了の貫通契約）."""
    ws_path = CollectionPaths(coll_dir).workflow_state_path
    if not ws_path.is_file():
        return False
    try:
        data = json.loads(ws_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    assets = data.get("assets")
    if not isinstance(assets, dict):
        return False
    return assets.get("music_downloaded") is True


def _read_music_expected_file_count(coll_dir: Path) -> int | None:
    """workflow-state.json から full playlist download の期待ファイル数を読む."""
    ws_path = CollectionPaths(coll_dir).workflow_state_path
    if not ws_path.is_file():
        return None
    try:
        data = json.loads(ws_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    planning = data.get("planning")
    if not isinstance(planning, dict):
        return None
    music = planning.get("music")
    if not isinstance(music, dict):
        return None
    expected = music.get("expected_file_count")
    if isinstance(expected, int) and not isinstance(expected, bool) and expected > 0:
        return expected
    return None


def _read_music_suno_playlist_url(coll_dir: Path) -> str | None:
    """workflow-state.json から保存済み Suno playlist URL を読む."""
    ws_path = CollectionPaths(coll_dir).workflow_state_path
    if not ws_path.is_file():
        return None
    try:
        data = json.loads(ws_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    planning = data.get("planning")
    if not isinstance(planning, dict):
        return None
    music = planning.get("music")
    if not isinstance(music, dict):
        return None
    url = music.get("suno_playlist_url")
    if isinstance(url, str) and url:
        return url
    return None


def _read_workflow_theme(coll_dir: Path) -> str | None:
    """workflow-state.json から collection theme slug を読む。"""
    ws_path = CollectionPaths(coll_dir).workflow_state_path
    if not ws_path.is_file():
        return None
    try:
        data = json.loads(ws_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    theme = data.get("theme")
    return theme if isinstance(theme, str) and theme else None


def _theme_from_collection_dir(coll_dir: Path) -> str:
    """collection dir 由来の theme slug を返す。

    workflow-state.json の theme は人間向け表示名の場合があるため、collection id の
    suffix slug として検証できる値だけを `/collections` の theme 契約に使う。
    """
    workflow_theme = _read_workflow_theme(coll_dir)
    if workflow_theme and _channel_from_collection_id(coll_dir.name, workflow_theme) is not None:
        return workflow_theme
    fallback = CollectionPaths(coll_dir).collection_name
    return fallback[: -len(_COLLECTION_DIR_SUFFIX)] if fallback.endswith(_COLLECTION_DIR_SUFFIX) else fallback


def _channel_from_collection_id(collection_id: str, theme: str) -> str | None:
    """`<date>-<channel>-<theme>-collection` から channel を抽出する。"""
    stripped = (
        collection_id[: -len(_COLLECTION_DIR_SUFFIX)]
        if collection_id.endswith(_COLLECTION_DIR_SUFFIX)
        else collection_id
    )
    suffix = f"-{theme}"
    if not theme or not stripped.endswith(suffix):
        return None
    date_plus_channel = stripped[: -len(suffix)]
    parts = date_plus_channel.split("-")
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    channel = "-".join(parts[1:])
    return channel or None


def build_collections_index(root: Path) -> list[dict]:
    """各 collection を index entry に写像する（#816 dir mode / #1216 BREAKING）.

    - id   = ディレクトリ名（拡張から個別 fetch する際のホワイトリスト key）
    - name = ``CollectionPaths.collection_name``（日付＋チャンネル接頭辞を除去した表示名）
    - status = ``needs_prompts`` | ``ready`` | ``downloaded``（ファイルシステムから動的判定）
    - pattern_count = json があれば entries 数、無ければ None
    - downloaded_count = ``02-Individual-music/`` 内の音声ファイル数

    #1216 BREAKING: mapped_slugs を廃止。mapped / has_prompts / playlist_name を廃止。
    """
    index: list[dict] = []
    for coll in _find_suno_collection_dirs(root):
        prompts_path = coll / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
        has_prompts = prompts_path.is_file()
        pattern_count = read_pattern_count(coll, prompt_entries_reader=read_suno_prompt_entries)
        music_dir = CollectionPaths(coll).music_dir
        downloaded_count = count_audio_files(music_dir)
        expected_file_count = _read_music_expected_file_count(coll)
        expected_count = expected_download_count(pattern_count, expected_file_count)
        suno_playlist_url = _read_music_suno_playlist_url(coll)
        music_downloaded = _read_music_downloaded_flag(coll)
        status = _determine_status(has_prompts, pattern_count, downloaded_count, expected_file_count)
        # 部分完了を受理済み（assets.music_downloaded=true）の collection はファイル数が
        # 期待数未満でも downloaded として扱い、拡張が再ダウンロードを提示しないようにする（#1913）
        if status == "ready" and music_downloaded:
            status = "downloaded"
        theme = _theme_from_collection_dir(coll)
        channel = _channel_from_collection_id(coll.name, theme)
        entry = {
            "id": coll.name,
            "name": theme,
            "status": status,
            "pattern_count": pattern_count,
            "downloaded_count": downloaded_count,
            "theme": theme,
        }
        if channel is not None:
            entry["channel"] = channel
        if expected_count is not None:
            entry["expected_file_count"] = expected_count
        if music_downloaded:
            entry["music_downloaded"] = True
        if suno_playlist_url is not None:
            entry["suno_playlist_url"] = suno_playlist_url
        index.append(entry)
    return index


def resolve_collection_prompts_path(root: Path, cid: str) -> Path | None:
    """`cid` が既知の collection dir 名のとき docs json パスを返す（#816 dir mode）.

    未知 id / パストラバーサル文字列は `find_collection_dirs` のホワイトリストに
    一致せず None を返す（fail-loud でなく 404 化できる形）。json の実在判定は
    呼び出し側に委ねる（has_prompts=False の collection も dir 自体は既知）。
    """
    known = {coll.name for coll in _find_suno_collection_dirs(root)}
    if cid not in known:
        return None
    return root / cid / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME


def _resolve_single_mode_prompts_path(path: Path) -> Path | None:
    """Suno または community の成果物を持つ single collection を受理する。"""
    try:
        return resolve_prompts_path(path)
    except ConfigError:
        if path.is_dir() and (path / _COMMUNITY_POSTS_RELPATH).is_file():
            return None
        raise


def _read_community_posts(collection_dir: Path) -> list[dict] | None:
    """community-draft の envelope を外部 API の CommunityPost[] に正規化する。"""
    posts_path = collection_dir / _COMMUNITY_POSTS_RELPATH
    if not posts_path.is_file():
        return None
    try:
        payload = json.loads(posts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"community-posts.json を読み込めません: {posts_path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("posts"), list):
        raise ConfigError(f"community-posts.json::posts は配列でなければなりません: {posts_path}")
    posts = payload["posts"]
    if not all(isinstance(post, dict) for post in posts):
        raise ConfigError(f"community-posts.json::posts[] は object でなければなりません: {posts_path}")
    return posts


def _resolve_community_image(
    collection_dir: Path,
    community_asset_root: Path,
    index: int,
) -> Path | None:
    """投稿 index の画像を channel root 内だけに解決する。画像なし・不在は None。"""
    posts = _read_community_posts(collection_dir)
    if posts is None or index >= len(posts):
        return None
    image_path = posts[index].get("image_path")
    if image_path is None:
        return None
    if not isinstance(image_path, str) or not image_path:
        raise ConfigError("community-posts.json::posts[].image_path は string または null でなければなりません")
    root = community_asset_root.resolve()
    collection_root = collection_dir.resolve()
    resolved = (root / image_path).resolve()
    try:
        resolved.relative_to(root)
        resolved.relative_to(collection_root)
    except ValueError:
        return None
    content_type = mimetypes.guess_type(resolved.name)[0]
    return resolved if resolved.is_file() and content_type is not None and content_type.startswith("image/") else None


def is_origin_allowed(origin: str | None, allow_origin: str | None) -> bool:
    """CORS 判定.

    allow_origin=None なら `chrome-extension://` scheme と helper サイト web origin
    （suno.com / distrokid.com、完全一致）を許可する（#896）。
    allow_origin 指定時はその値との完全一致のみ許可する（lock 維持）。
    """
    if not origin:
        return False
    if allow_origin is not None:
        return origin == allow_origin
    if origin.startswith(_EXTENSION_ORIGIN_SCHEME):
        return True
    return origin in _DEFAULT_ALLOWED_WEB_ORIGINS


def _is_read_origin_allowed(origin: str | None, allow_origin: str | None, _path: str) -> bool:
    """Read-only GET/OPTIONS CORS 判定.

    `--allow-origin` 指定時は read-only も exact lock に従う。Suno overlay から
    必要な read API は background script が extension origin で取得する。YouTube の
    page origin には localhost の下書きや画像を公開しない。
    """
    return is_origin_allowed(origin, allow_origin)


def _is_locked_extension_request(raw_origin: str | None, allow_origin: str | None) -> bool:
    """Token/mutating endpoints require an explicit extension lock.

    Chrome MV3 background fetches can omit the Origin header. Web-page CORS
    fetches include an Origin, so keep rejecting non-matching explicit origins.
    """
    if allow_origin is None or not allow_origin.startswith(_EXTENSION_ORIGIN_SCHEME):
        return False
    return raw_origin is None or raw_origin == allow_origin


def build_version_payload() -> dict[str, str]:
    """拡張の互換確認用 version payload を返す（#1023）."""
    return {
        "version": __version__.split("+", 1)[0],
        "min_extension_version": MIN_EXTENSION_VERSION,
    }


def _decode_collection_id_path_segment(cid: str) -> str:
    return urllib.parse.unquote(cid)


def _encode_collection_id_path_segment(cid: str) -> str:
    return urllib.parse.quote(cid, safe="")


def _lifecycle_root(path: Path) -> Path:
    """起動 path から PID ファイルを置く collections/planning 相当を返す。"""
    if path.is_file():
        collection = path.parent.parent
    else:
        collection = path
    if collection.name.endswith(_COLLECTION_DIR_SUFFIX):
        return collection.parent
    return collection


def _pid_file_path(root: Path, port: int) -> Path:
    return root / f".collection-serve-{port}.pid"


def _stop_request_path(root: Path, port: int) -> Path:
    return root / f".collection-serve-{port}.stop"


def _lifecycle_stop_path(record: _LifecycleRecord, attempt_token: str) -> str:
    return f"{_LIFECYCLE_ROUTE_PREFIX}{record.token}/stop/{attempt_token}"


def _startup_lock_path(root: Path, port: int) -> Path:
    return root / f".collection-serve-{port}.lock"


@contextlib.contextmanager
def _startup_lock(path: Path):
    """同じ lifecycle record に対する check→bind→publish を直列化する。"""
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_pid_file(path: Path) -> _LifecycleRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"PID file を読み取れません: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"PID file が不正です: {path}")
    pid = payload.get("pid")
    token = payload.get("token")
    configuration = payload.get("configuration")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(token, str)
        or not token
        or not isinstance(configuration, str)
        or not configuration
    ):
        raise ConfigError(f"PID file が不正です: {path}")
    return _LifecycleRecord(pid=pid, token=token, configuration=configuration)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # kill(pid, 0) also succeeds for an exited child until its parent reaps it.
    # A zombie has completed server/discovery cleanup and no longer executes.
    try:
        status = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return True
    return not (status.returncode == 0 and status.stdout.lstrip().startswith("Z"))


@contextlib.contextmanager
def _process_exit_watcher(pid: int):
    """元の process instance の終了を待つ callable を返す。"""
    pidfd_open = getattr(os, "pidfd_open", None)
    if callable(pidfd_open):
        try:
            descriptor = pidfd_open(pid)
        except OSError:
            pass
        else:
            try:
                yield lambda timeout: bool(select.select([descriptor], [], [], timeout)[0])
            finally:
                os.close(descriptor)
            return

    if hasattr(select, "kqueue") and hasattr(select, "KQ_NOTE_EXIT"):
        queue = select.kqueue()
        try:
            event = select.kevent(
                pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                fflags=select.KQ_NOTE_EXIT,
            )
            queue.control([event], 0, 0)
        except OSError:
            queue.close()
        else:
            try:
                yield lambda timeout: bool(queue.control(None, 1, timeout))
            finally:
                queue.close()
            return

    yield None


def _server_process_id(port: int, record: _LifecycleRecord, expected_configuration: str | None = None) -> int | None:
    connection = http.client.HTTPConnection("localhost", port, timeout=0.5)
    try:
        connection.request("GET", f"{_LIFECYCLE_ROUTE_PREFIX}{record.token}")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        process_id = payload.get("process_id") if isinstance(payload, dict) else None
        configuration = payload.get("configuration") if isinstance(payload, dict) else None
        required_configuration = expected_configuration or record.configuration
        return (
            process_id
            if response.status == 200
            and isinstance(process_id, int)
            and process_id == record.pid
            and configuration == record.configuration
            and configuration == required_configuration
            else None
        )
    except (ConnectionError, OSError, UnicodeDecodeError, json.JSONDecodeError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def _request_server_stop(port: int, record: _LifecycleRecord, attempt_token: str) -> bool:
    """Token で識別した server owner 自身へ停止要求を渡す。"""
    connection = http.client.HTTPConnection("localhost", port, timeout=0.5)
    try:
        connection.request("POST", _lifecycle_stop_path(record, attempt_token))
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        process_id = payload.get("process_id") if isinstance(payload, dict) else None
        configuration = payload.get("configuration") if isinstance(payload, dict) else None
        return response.status == 200 and process_id == record.pid and configuration == record.configuration
    except (ConnectionError, OSError, UnicodeDecodeError, json.JSONDecodeError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def _remove_owned_pid_file(path: Path, pid: int) -> None:
    try:
        record = _read_pid_file(path)
        if record is not None and record.pid == pid:
            path.unlink()
    except FileNotFoundError:
        return


def _remove_matching_record(path: Path, expected: _LifecycleRecord) -> None:
    try:
        if _read_pid_file(path) == expected:
            path.unlink()
    except FileNotFoundError:
        return


def _consume_stop_request(path: Path, pid: int) -> bool:
    try:
        request = _read_pid_file(path)
    except ConfigError:
        return False
    if request is None or request.pid != pid:
        return False
    path.unlink(missing_ok=True)
    return True


def _existing_server_pid(path: Path, port: int, expected_configuration: str) -> int | None:
    try:
        record = _read_pid_file(path)
    except ConfigError:
        path.unlink(missing_ok=True)
        return None
    if record is None:
        return None
    if not _pid_is_running(record.pid):
        _remove_owned_pid_file(path, record.pid)
        return None
    server_pid = _server_process_id(port, record, expected_configuration)
    if server_pid is not None:
        return server_pid
    running_server_pid = _server_process_id(port, record)
    if running_server_pid is not None:
        raise ConfigError(
            f"collection server on port {port} is running with a different configuration; use another port"
        )
    raise ConfigError(
        f"collection server PID {record.pid} is running, but its identity on port {port} could not be verified"
    )


def _write_pid_file(path: Path, record: _LifecycleRecord) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(
                {"pid": record.pid, "token": record.token, "configuration": record.configuration},
                stream,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise ConfigError(f"PID file already exists: {path}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _configuration_fingerprint(
    *,
    path: Path,
    mode: str,
    allow_origin: str | None,
    capture_root: Path | None,
    distrokid_source: str | None,
    idle_timeout_seconds: float,
) -> str:
    payload = json.dumps(
        {
            "path": str(path.resolve()),
            "mode": mode,
            "allow_origin": allow_origin,
            "capture_root": str(capture_root.resolve()) if capture_root is not None else None,
            "distrokid_source": distrokid_source,
            "idle_timeout_seconds": idle_timeout_seconds,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stop_server(port: int) -> None:
    lifecycle_root = channel_dir() / "collections" / "planning"
    pid_path = _pid_file_path(lifecycle_root, port)
    stop_request_path = _stop_request_path(lifecycle_root, port)
    record = _read_pid_file(pid_path)
    if record is None:
        print(f"No collection server PID file for port {port}.")
        return
    pid = record.pid
    if not _pid_is_running(pid):
        _remove_owned_pid_file(pid_path, record.pid)
        print(f"Removed stale collection server PID file for port {port}.")
        return
    with _process_exit_watcher(pid) as wait_for_exit:
        stop_request_path.unlink(missing_ok=True)
        stop_request = _LifecycleRecord(pid=pid, token=uuid.uuid4().hex, configuration=record.configuration)
        _write_pid_file(stop_request_path, stop_request)
        stop_accepted = _request_server_stop(port, record, stop_request.token)
        if not stop_accepted:
            try:
                active_request = _read_pid_file(stop_request_path)
            except ConfigError:
                active_request = stop_request
            # The owner consumes this exact marker before self-signalling. Its
            # disappearance therefore proves acceptance even if the HTTP response
            # is cut off by process shutdown.
            stop_accepted = active_request is None
        if not stop_accepted:
            _remove_matching_record(stop_request_path, stop_request)
            if not _pid_is_running(pid):
                _remove_owned_pid_file(pid_path, pid)
                print(f"Removed stale collection server PID file for port {port}.")
                return
            raise ConfigError(
                f"collection server PID {pid} is running, but its identity on port {port} could not be verified"
            )
        if wait_for_exit is not None:
            stopped = wait_for_exit(5.0)
        else:
            deadline = time.monotonic() + 5.0
            while _pid_is_running(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            stopped = not _pid_is_running(pid)
    if not stopped:
        _remove_matching_record(stop_request_path, stop_request)
        raise ConfigError(f"collection server PID {pid} did not stop within 5 seconds")
    _remove_matching_record(stop_request_path, stop_request)
    _remove_owned_pid_file(pid_path, pid)
    print(f"Stopped collection server on port {port} (PID {pid}).")


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def create_server(
    port: int,
    allow_origin: str | None,
    *,
    server_info: dict[str, str | int] | None = None,
    prompts_path: Path | None,
    collection_dir: Path | None,
    distrokid: Distrokid | None,
    community_asset_root: Path | None = None,
    collections_root: Path | None = None,
    distrokid_source: str | None = None,
    capture_root: Path | None = None,
    discovery_registry_state: RegistryState | None = None,
    idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
    lifecycle_record: _LifecycleRecord | None = None,
    lifecycle_root: Path | None = None,
) -> ThreadingHTTPServer:
    """サブパス分離した GET / POST / CORS preflight を返すサーバーを生成する.

    `collections_root` 指定時は **dir mode**（`/collections` 系を配信し
    単一ファイル mode の `/suno/prompts.json` は配信しない）。既定 None は
    単一ファイル mode（`/suno/prompts.json` + `/distrokid/*`）。

    `capture_root` 指定時のみ DistroKid release capture の POST を有効化する。
    None なら capture 系 POST は 404。

    distrokid が None または `enabled == False` のとき `/distrokid/*` は 404。
    """
    dir_mode = collections_root is not None
    distrokid_enabled = distrokid is not None and distrokid.enabled
    serve_token = str(uuid.uuid4())
    unattended_requests: dict[str, tuple[float, dict[str, object]]] = {}
    unattended_requests_lock = threading.Lock()
    resolved_server_info = (
        server_info if server_info is not None else build_server_info("YouTube Automation", "YA", port)
    )
    resolved_community_asset_root = community_asset_root if community_asset_root is not None else collection_dir

    class _Handler(BaseHTTPRequestHandler):
        def _allowed_origin(self) -> str | None:
            headers = getattr(self, "headers", None)
            if headers is None:
                return None
            origin = headers.get("Origin")
            if self.command in {"GET", "HEAD", "OPTIONS"}:
                return origin if _is_read_origin_allowed(origin, allow_origin, self.path) else None
            return origin if is_origin_allowed(origin, allow_origin) else None

        def _send_cors(self, origin: str | None) -> None:
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send_bytes(self, body: bytes, content_type: str) -> None:
            origin = self._allowed_origin()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self._send_cors(origin)
            self.end_headers()
            self.wfile.write(body)

        def _send_json_error(self, status: int, message: str) -> None:
            # send_error は CORS ヘッダを付けず HTML を返すため、拡張へ届けるエラーは
            # JSON + CORS で返す（#944）。message に改行を含む ConfigError も安全に運べる。
            origin = self._allowed_origin()
            body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors(origin)
            self.end_headers()
            can_write_body = self.command != "HEAD" and status >= 200 and status not in (204, 205, 304)
            if can_write_body:
                self.wfile.write(body)

        def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
            if (
                code == 501
                and discovery_registry_state is not None
                and handle_registry_request(self, discovery_registry_state)
            ):
                return
            resolved_message = message
            if resolved_message is None:
                resolved_message = self.responses.get(code, ("???", "???"))[0]
            self._send_json_error(code, resolved_message)

        def do_OPTIONS(self) -> None:
            if discovery_registry_state is not None and handle_registry_request(self, discovery_registry_state):
                return
            origin = self._allowed_origin()
            self.send_response(204)
            self._send_cors(origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Serve-Token")
            self.end_headers()

        def _handle_downloaded_post(self, cid: str) -> None:
            """POST /collections/<id>/downloaded を処理する（dir mode only、#1216/#1217）。"""
            assert collections_root is not None
            raw_origin = self.headers.get("Origin")
            if not _is_locked_extension_request(raw_origin, allow_origin):
                self.send_error(403, "Forbidden")
                return
            req_token = self.headers.get("X-Serve-Token")
            if req_token != serve_token:
                self.send_error(403, "Forbidden")
                return

            cid = _decode_collection_id_path_segment(cid)
            if ".." in cid:
                self.send_error(404, "Not Found")
                return
            known_ids = {coll.name for coll in find_collection_dirs(collections_root)}
            if cid not in known_ids:
                self.send_error(404, "Not Found")
                return

            raw = self._read_limited_post_body(max_bytes=_MAX_DOWNLOADED_POST_BODY_BYTES)
            if raw is None:
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_error(400, "Bad Request")
                return
            try:
                downloaded = parse_downloaded_payload(payload)
            except DownloadedPayloadError:
                self.send_error(400, "Bad Request")
                return

            coll_dir = collections_root / cid
            try:
                placed_count_for_response = apply_downloaded_artifacts(
                    coll_dir,
                    downloaded,
                    prompt_entries_reader=read_suno_prompt_entries,
                    atomic_json_write=_atomic_json_write,
                )
            except DownloadedPayloadError:
                self.send_error(400, "Bad Request")
                return
            except DownloadedArtifactError as exc:
                self._send_json_error(500, str(exc))
                return
            resp: dict = {"ok": True, "collection_id": cid, "placed_count": placed_count_for_response}
            # 部分完了（Suno が期待数未満しか生成しないケース）は 500 にせず warning で返す（#1913）
            expected_count = expected_download_count(
                read_pattern_count(
                    coll_dir,
                    prompt_entries_reader=read_suno_prompt_entries,
                    default=0,
                ),
                downloaded.expected_file_count,
            )
            if (
                downloaded.download_path
                and expected_count is not None
                and 0 < placed_count_for_response < expected_count
            ):
                missing = expected_count - placed_count_for_response
                resp["warning"] = (
                    f"placed {placed_count_for_response} files, expected {expected_count} ({missing} missing)"
                )
            resp_body = json.dumps(resp).encode("utf-8")
            self._send_bytes(resp_body, "application/json; charset=utf-8")

        def _read_limited_post_body(self, *, max_bytes: int = _MAX_POST_BODY_BYTES) -> bytes | None:
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                self.send_error(400, "Bad Request")
                return None
            if length < 0:
                self.send_error(400, "Bad Request")
                return None
            if length > max_bytes:
                self.send_error(413, "Payload Too Large")
                return None
            return self.rfile.read(length) if length else b""

        def do_POST(self) -> None:
            # GET と異なり POST は route ごとに書き込み可否を明示的に判定する。
            lifecycle_stop_prefix = (
                f"{_LIFECYCLE_ROUTE_PREFIX}{lifecycle_record.token}/stop/" if lifecycle_record is not None else None
            )
            if (
                lifecycle_record is not None
                and lifecycle_stop_prefix is not None
                and self.path.startswith(lifecycle_stop_prefix)
            ):
                if lifecycle_root is None:
                    self.send_error(404, "Not Found")
                    return
                marker_path = _stop_request_path(lifecycle_root, self.server.server_address[1])
                try:
                    marker = _read_pid_file(marker_path)
                except ConfigError:
                    marker = None
                marker_matches_owner = (
                    marker is not None
                    and marker.pid == lifecycle_record.pid
                    and marker.configuration == lifecycle_record.configuration
                )
                if not marker_matches_owner or self.path != _lifecycle_stop_path(lifecycle_record, marker.token):
                    self.send_error(409, "Stop request is no longer active")
                    return
                body = json.dumps(
                    {"process_id": lifecycle_record.pid, "configuration": lifecycle_record.configuration}
                ).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                self.wfile.flush()
                os.kill(os.getpid(), signal.SIGTERM)
                return
            if discovery_registry_state is not None and handle_registry_request(self, discovery_registry_state):
                return

            # Local scheduler only: register the paid-operation request outside the
            # browser, then expose only a short-lived nonce in the Suno URL. Browser
            # requests always carry Origin, so rejecting it here prevents a Suno page
            # from minting its own unattended command.
            if dir_mode and self.path == _UNATTENDED_REQUESTS_ROUTE:
                if self.headers.get("Origin") is not None:
                    self.send_error(403, "Forbidden")
                    return
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    self.send_error(415, "Unsupported Media Type")
                    return
                raw = self._read_limited_post_body(max_bytes=_MAX_UNATTENDED_REQUEST_BODY_BYTES)
                if raw is None:
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.send_error(400, "Bad Request")
                    return
                if not isinstance(payload, dict):
                    self.send_error(400, "Bad Request")
                    return
                nonce = secrets.token_urlsafe(32)
                expires_at = time.monotonic() + _UNATTENDED_REQUEST_TTL_SECONDS
                with unattended_requests_lock:
                    unattended_requests[nonce] = (expires_at, payload)
                body = json.dumps({"nonce": nonce, "expires_in": _UNATTENDED_REQUEST_TTL_SECONDS}).encode()
                self._send_bytes(body, "application/json; charset=utf-8")
                return

            consume_prefix = f"{_UNATTENDED_REQUESTS_ROUTE}/"
            if dir_mode and self.path.startswith(consume_prefix) and self.path.endswith("/consume"):
                raw_origin = self.headers.get("Origin")
                if not _is_locked_extension_request(raw_origin, allow_origin):
                    self.send_error(403, "Forbidden")
                    return
                if self.headers.get("X-Serve-Token") != serve_token:
                    self.send_error(403, "Forbidden")
                    return
                nonce = self.path[len(consume_prefix) : -len("/consume")]
                if not nonce or "/" in nonce or urllib.parse.quote(nonce, safe="") != nonce:
                    self.send_error(404, "Not Found")
                    return
                with unattended_requests_lock:
                    record = unattended_requests.pop(nonce, None)
                if record is None:
                    self.send_error(404, "Unattended request not found or already consumed")
                    return
                expires_at, payload = record
                if expires_at < time.monotonic():
                    self.send_error(410, "Unattended request expired")
                    return
                self._send_bytes(json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return

            # POST /distrokid/releases: capture 有効時のみ（#934）。
            if self.path == _DISTROKID_RELEASES_ROUTE:
                if not distrokid_enabled or capture_root is None:
                    # distrokid disabled / capture root 未指定時は endpoint 自体を出さない。
                    self.send_error(404, "Not Found")
                    return
                # 書き込み境界（#1360）: /downloaded と同じく extension lock + serve token 必須。
                # MV3 background fetch は Origin を省略しうるため _is_locked_extension_request で
                # 「Origin 無し or 完全一致」を許可し、本人性は X-Serve-Token で担保する。
                raw_origin = self.headers.get("Origin")
                if not _is_locked_extension_request(raw_origin, allow_origin):
                    self.send_error(403, "Forbidden")
                    return
                req_token = self.headers.get("X-Serve-Token")
                if req_token != serve_token:
                    self.send_error(403, "Forbidden")
                    return
                raw = self._read_limited_post_body()
                if raw is None:
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.send_error(400, "Bad Request")
                    return
                if not isinstance(payload, dict):
                    self.send_error(400, "Bad Request")
                    return
                coll_id = payload.get("collection_id")
                disc = payload.get("disc")
                album_title = payload.get("album_title")
                if (
                    not isinstance(coll_id, str)
                    or not coll_id
                    or not isinstance(disc, str)
                    or not disc
                    or not isinstance(album_title, str)
                    or not album_title
                ):
                    # 必須フィールド欠落・非 string は 400（#934）。
                    self.send_error(400, "Bad Request")
                    return
                if collections_root is not None:
                    known_collections = {coll.name: coll for coll in find_collection_dirs(collections_root)}
                    coll_dir = known_collections.get(coll_id)
                    if coll_dir is None:
                        self.send_error(400, "Bad Request")
                        return
                    if disc not in find_distrokid_discs(coll_dir):
                        self.send_error(400, "Bad Request")
                        return
                write_distrokid_release(capture_root, coll_id, disc, album_title)
                resp_body = json.dumps(
                    {"recorded": True, "path": str(distrokid_releases_output_path(capture_root))}
                ).encode("utf-8")
                self._send_bytes(resp_body, "application/json; charset=utf-8")
                return

            # POST /collections/<id>/downloaded: dir mode のみ（#1216）。
            downloaded_prefix = f"{COLLECTIONS_ROUTE}/"
            if dir_mode and self.path.startswith(downloaded_prefix) and self.path.endswith(DOWNLOADED_ROUTE_SUFFIX):
                cid = self.path[len(downloaded_prefix) : -len(DOWNLOADED_ROUTE_SUFFIX)]
                decoded_cid = _decode_collection_id_path_segment(cid)
                if self.path != collection_downloaded_route(decoded_cid):
                    self.send_error(404, "Not Found")
                    return
                self._handle_downloaded_post(cid)
                return

            # その他のパスは 404。POST は定義済みルートのみハンドルする。
            self.send_error(404, "Not Found")

        def do_GET(self) -> None:
            if discovery_registry_state is not None and handle_registry_request(self, discovery_registry_state):
                return
            if self.path == VERSION_ROUTE:
                body = json.dumps(build_version_payload()).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            if self.path == SERVER_INFO_ROUTE:
                body = json.dumps(resolved_server_info, ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            if lifecycle_record is not None and self.path == f"{_LIFECYCLE_ROUTE_PREFIX}{lifecycle_record.token}":
                body = json.dumps({"process_id": os.getpid(), "configuration": lifecycle_record.configuration}).encode(
                    "utf-8"
                )
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            if self.path == "/auth/token":
                raw_origin = self.headers.get("Origin")
                if not _is_locked_extension_request(raw_origin, allow_origin):
                    self.send_error(403, "Forbidden")
                    return
                body = json.dumps({"token": serve_token}).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            if dir_mode:
                self._serve_dir_mode()
                return
            if self.path == COMMUNITY_POSTS_ROUTE:
                assert collection_dir is not None
                try:
                    posts = _read_community_posts(collection_dir)
                except ConfigError as exc:
                    self._send_json_error(500, str(exc))
                    return
                if posts is None:
                    self.send_error(404, "Not Found")
                    return
                body = json.dumps(posts, ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            community_image_match = _COMMUNITY_IMAGE_ROUTE_PATTERN.fullmatch(self.path)
            if community_image_match is not None:
                assert collection_dir is not None
                assert resolved_community_asset_root is not None
                try:
                    image = _resolve_community_image(
                        collection_dir,
                        resolved_community_asset_root,
                        int(community_image_match.group("index")),
                    )
                except ConfigError as exc:
                    self._send_json_error(500, str(exc))
                    return
                if image is None:
                    self.send_error(404, "Not Found")
                    return
                content_type = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
                self._send_bytes(image.read_bytes(), content_type)
                return
            if self.path == SUNO_PROMPTS_ROUTE:
                if prompts_path is None:
                    self.send_error(404, "Not Found")
                    return
                self._send_bytes(prompts_path.read_bytes(), "application/json; charset=utf-8")
                return
            if self.path == DISTROKID_RELEASE_ROUTE:
                self._serve_distrokid_release()
                return
            if self.path.startswith(DISTROKID_ASSETS_PREFIX):
                self._serve_distrokid_asset()
                return
            if self.path == COLLECTIONS_ROUTE:
                self._send_json_error(404, "Not Found")
                return
            self.send_error(404, "Not Found")

        def do_DELETE(self) -> None:
            if discovery_registry_state is not None and handle_registry_request(self, discovery_registry_state):
                return
            self.send_error(501, f"Unsupported method ({self.command!r})")

        def _serve_dir_mode(self) -> None:
            if self.path == COLLECTIONS_ROUTE:
                index = build_collections_index(collections_root)
                body = json.dumps(index).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            coll_prefix = f"{COLLECTIONS_ROUTE}/"
            if self.path.startswith(coll_prefix) and self.path.endswith(SUNO_PROMPTS_ROUTE):
                cid = _decode_collection_id_path_segment(self.path[len(coll_prefix) : -len(SUNO_PROMPTS_ROUTE)])
                resolved = resolve_collection_prompts_path(collections_root, cid)
                if resolved is None or not resolved.is_file():
                    self._send_json_error(404, "Not Found")
                    return
                self._send_bytes(resolved.read_bytes(), "application/json; charset=utf-8")
                return

            if self.path == SUNO_PROMPTS_ROUTE:
                self._send_json_error(404, "Not Found")
                return

            # --- dir mode DistroKid エンドポイント群（#934）---

            # GET /distrokid/collections: disc 一覧
            if self.path == _DISTROKID_COLLECTIONS_ROUTE:
                self._serve_distrokid_dir_collections()
                return

            # GET /collections/<id>/distrokid/<disc>/release.json: collection-scoped release payload
            # GET /collections/<id>/distrokid/assets/<rel>: collection-scoped アセット
            if self.path.startswith(coll_prefix):
                self._serve_distrokid_collection_routes(self.path[len(coll_prefix) :])
                return

            self.send_error(404, "Not Found")

        def _serve_distrokid_dir_collections(self) -> None:
            """GET /distrokid/collections を処理する（#934）."""
            # capture root が指定されている場合のみ released 判定を行う（gating は #893 と同方針）。
            released = read_released_discs(capture_root) if capture_root is not None else None
            index = build_distrokid_collections_index(collections_root, released_discs=released)
            body = json.dumps(index).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8")

        def _serve_distrokid_collection_routes(self, rest: str) -> None:
            """GET /collections/<id>/distrokid/... を処理する（#934）.

            `rest` は `/collections/` を除いた残り（例: `<id>/distrokid/<disc>/release.json`）。
            """
            # collection_id を最初のスラッシュで分割し、残りをサブパスとして処理する。
            parts = rest.split("/", 1)
            if len(parts) != 2:
                self.send_error(404, "Not Found")
                return
            raw_coll_id, sub = parts
            coll_id = _decode_collection_id_path_segment(raw_coll_id)

            # トラバーサル防御: find_collection_dirs のホワイトリストで弾く（#934）。
            known_ids = {coll.name for coll in find_collection_dirs(collections_root)}
            if coll_id not in known_ids:
                self.send_error(404, "Not Found")
                return

            coll_dir = collections_root / coll_id

            # `/distrokid/assets/<rel>` → collection-scoped アセット配信
            distrokid_assets_infix = "distrokid/assets/"
            if sub.startswith(distrokid_assets_infix):
                relpath = urllib.parse.unquote(sub[len(distrokid_assets_infix) :])
                # コレクションルートからの相対パスで resolve（30-distrokid 配下も含む）
                resolved = resolve_asset_path(coll_dir, relpath)
                if resolved is None:
                    self.send_error(404, "Not Found")
                    return
                content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
                self._send_bytes(resolved.read_bytes(), content_type)
                return

            # `/distrokid/<disc>/release.json` → collection-scoped release payload
            distrokid_prefix = "distrokid/"
            release_suffix = "/release.json"
            if sub.startswith(distrokid_prefix) and sub.endswith(release_suffix):
                disc = sub[len(distrokid_prefix) : -len(release_suffix)]
                # disc にスラッシュを含む場合はトラバーサルのおそれがある（#934）。
                if not disc or "/" in disc:
                    self.send_error(404, "Not Found")
                    return
                # disc 実在確認: find_distrokid_discs のホワイトリストで弾く（#934）。
                known_discs = find_distrokid_discs(coll_dir)
                if disc not in known_discs:
                    self.send_error(404, "Not Found")
                    return
                if not distrokid_enabled:
                    self.send_error(404, "Not Found")
                    return
                # asset_path を collection-scoped 形式にするための prefix を組み立てる（#934）。
                encoded_coll_id = _encode_collection_id_path_segment(coll_id)
                coll_assets_prefix = f"{COLLECTIONS_ROUTE}/{encoded_coll_id}{DISTROKID_COLLECTION_ASSETS_PREFIX}"
                distrokid_source = f"{_DISTROKID_DIRNAME}/{disc}"
                try:
                    payload = build_release_payload(
                        coll_dir,
                        distrokid,
                        distrokid_source=distrokid_source,
                        assets_prefix=coll_assets_prefix,
                    )
                except ConfigError as exc:
                    # 破損 spec.json 等の fail-loud は handler 落ち（接続切断）ではなく
                    # 500 + メッセージで拡張へ届ける（#944）。配信停止の意図は維持する。
                    self._send_json_error(500, str(exc))
                    return
                body = json.dumps(payload).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return

            self.send_error(404, "Not Found")

        def _serve_distrokid_release(self) -> None:
            if not distrokid_enabled:
                self.send_error(404, "Not Found")
                return
            try:
                payload = build_release_payload(collection_dir, distrokid, distrokid_source=distrokid_source)
            except ConfigError as exc:
                # 単一 mode も同様: 破損 spec / metadata.md 不在の fail-loud を 500 で返す（#944）。
                self._send_json_error(500, str(exc))
                return
            body = json.dumps(payload).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8")

        def _serve_distrokid_asset(self) -> None:
            if not distrokid_enabled:
                self.send_error(404, "Not Found")
                return
            relpath = urllib.parse.unquote(self.path[len(DISTROKID_ASSETS_PREFIX) :])
            resolved = resolve_asset_path(collection_dir, relpath)
            if resolved is None:
                self.send_error(404, "Not Found")
                return
            content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
            self._send_bytes(resolved.read_bytes(), content_type)

        def log_message(self, *args) -> None:  # サーバーログを抑制
            pass

    server = _IdleTrackingHTTPServer(("localhost", port), _Handler, idle_timeout_seconds)
    if server_info is None:
        resolved_server_info.update(build_server_info("YouTube Automation", "YA", server.server_address[1]))
    return server


def _resolve_distrokid_capture_root(root_arg: str | None) -> Path | None:
    """CLI 引数 + env fallback から DistroKid release capture root を解決する."""
    root = root_arg if root_arg is not None else os.environ.get(_DISTROKID_CAPTURE_ROOT_ENV)
    return Path(root).expanduser() if root is not None else None


def _resolve_allow_origin(
    allow_origin: str | None, allow_extension: str | None
) -> tuple[str | None, ChromeExtensionOrigin | None]:
    if allow_extension is None:
        return allow_origin, None
    detected = resolve_unpacked_extension_origin(allow_extension)
    return detected.origin, detected


def main() -> None:
    # nohup / file redirect 下でも extension 検出結果を起動直後に診断できるよう、
    # block buffering を行バッファへ切り替える。pytest の StringIO 等は reconfigure
    # を持たないため、その場合はそのまま使う。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(
        description=(
            "Serve collection artifacts over localhost HTTP for the suno-helper / distrokid-helper / "
            "community-helper Chrome extensions (subpaths: /suno/*, /distrokid/*, /community/*)."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="collection dir or suno-prompts.json path",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="stop the server recorded for --port and remove its PID file",
    )
    parser.add_argument(
        "--idle-timeout",
        type=_positive_float,
        default=DEFAULT_IDLE_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=f"stop after this many seconds without an HTTP request (default: {DEFAULT_IDLE_TIMEOUT_SECONDS})",
    )
    allow_origin_group = parser.add_mutually_exclusive_group()
    allow_origin_group.add_argument(
        "--allow-origin",
        default=None,
        help=(
            "lock CORS to a single origin via exact match. POST /collections/<id>/downloaded, "
            f"POST {_DISTROKID_RELEASES_ROUTE} and GET /auth/token require an explicit "
            "chrome-extension://<EXTENSION_ID> lock. "
            "Default allows chrome-extension scheme plus suno.com / distrokid.com helper origins "
            "for read-only routes only."
        ),
    )
    allow_origin_group.add_argument(
        "--allow-extension",
        default=None,
        help=(
            "detect an unpacked Chrome extension by directory name from macOS Chrome profiles "
            "and lock CORS to chrome-extension://<detected-id>. Use --allow-origin as manual fallback."
        ),
    )
    parser.add_argument(
        "--distrokid-source",
        default=None,
        help=(
            "submit a 30-distrokid disc dir as one album, e.g. "
            "'30-distrokid/disc1-coding-focus-vol1' (default: 02-Individual-music/)"
        ),
    )
    parser.add_argument(
        "--distrokid-capture-root",
        default=None,
        help=(
            "downstream channel repo root for DistroKid release capture writes; enables POST "
            f"{_DISTROKID_RELEASES_ROUTE} (env fallback: {_DISTROKID_CAPTURE_ROOT_ENV})"
        ),
    )
    args = parser.parse_args()

    if args.stop:
        if args.path is not None:
            parser.error("path cannot be used with --stop")
        _stop_server(args.port)
        return
    if args.path is None:
        parser.error("the following arguments are required: path")

    capture_root = _resolve_distrokid_capture_root(args.distrokid_capture_root)
    allow_origin, detected_extension = _resolve_allow_origin(args.allow_origin, args.allow_extension)
    embedded_registry_state = RegistryState() if args.port == DISCOVERY_PORT else None

    # path が `*-collection/` を並べたディレクトリなら dir mode（#816）。
    collection_dirs = find_collection_dirs(args.path)
    lifecycle_root = _lifecycle_root(args.path)
    lifecycle_configuration = _configuration_fingerprint(
        path=args.path,
        mode="dir" if collection_dirs else "single",
        allow_origin=allow_origin,
        capture_root=capture_root,
        distrokid_source=args.distrokid_source,
        idle_timeout_seconds=args.idle_timeout,
    )
    requested_pid_path = _pid_file_path(lifecycle_root, args.port)
    lifecycle_record = _LifecycleRecord(
        pid=os.getpid(),
        token=uuid.uuid4().hex,
        configuration=lifecycle_configuration,
    )

    if collection_dirs:
        # dir mode でも distrokid エンドポイントを有効化するため load_config() を試みる（#934）。
        # distrokid 設定が無いチャンネルでは None のままにして 404 にフォールバックする。
        try:
            config = load_config()
            distrokid_cfg = config.distrokid
            channel_name = config.meta.channel_name
            channel_short = config.meta.channel_short
        except ConfigError:
            distrokid_cfg = None
            channel_name = "YouTube Automation"
            channel_short = "YA"
        distrokid_capture_active = distrokid_cfg is not None and distrokid_cfg.enabled
    else:
        # community-draft だけを使う collection は suno-prompts.json を持たなくても起動可能。
        prompts_path = _resolve_single_mode_prompts_path(args.path)
        # collection dir: dir 引数はそのまま、json ファイル引数なら <collection>/20-documentation/x.json から 2 階層上。
        collection_dir = args.path if args.path.is_dir() else args.path.parent.parent
        config = load_config()
        distrokid = config.distrokid
        channel_name = config.meta.channel_name
        channel_short = config.meta.channel_short

        distrokid_capture_active = distrokid.enabled

    server_info = build_server_info(channel_name, channel_short, args.port)
    lock = _startup_lock(_startup_lock_path(lifecycle_root, args.port)) if args.port != 0 else contextlib.nullcontext()
    with lock:
        if args.port != 0:
            existing_pid = _existing_server_pid(requested_pid_path, args.port, lifecycle_configuration)
            if existing_pid is not None:
                print(f"Reusing collection server on port {args.port} (PID {existing_pid}).")
                return
        if collection_dirs:
            server = create_server(
                args.port,
                allow_origin,
                server_info=server_info,
                prompts_path=None,
                collection_dir=None,
                distrokid=distrokid_cfg,
                collections_root=args.path,
                capture_root=capture_root,
                discovery_registry_state=embedded_registry_state,
                idle_timeout_seconds=args.idle_timeout,
                lifecycle_record=lifecycle_record,
                lifecycle_root=lifecycle_root,
            )
        else:
            server = create_server(
                args.port,
                allow_origin,
                server_info=server_info,
                prompts_path=prompts_path,
                collection_dir=collection_dir,
                community_asset_root=channel_dir(),
                distrokid=distrokid,
                distrokid_source=args.distrokid_source,
                capture_root=capture_root,
                discovery_registry_state=embedded_registry_state,
                idle_timeout_seconds=args.idle_timeout,
                lifecycle_record=lifecycle_record,
                lifecycle_root=lifecycle_root,
            )
        port = server.server_address[1]
        pid = lifecycle_record.pid
        pid_path = _pid_file_path(lifecycle_root, port)
        stop_request_path = _stop_request_path(lifecycle_root, port)
        stop_request_path.unlink(missing_ok=True)
        cleanup_managed = False
        previous_sigterm_handler = signal.SIG_DFL

        def handle_sigterm(signum: int, _frame: object) -> None:
            explicit_stop = _consume_stop_request(stop_request_path, pid)
            if explicit_stop:
                signal.signal(signal.SIGTERM, previous_sigterm_handler)
                server.server_close()
                _remove_owned_pid_file(pid_path, pid)
                _remove_owned_pid_file(stop_request_path, pid)
                raise SystemExit(0)
            if not cleanup_managed:
                signal.signal(signal.SIGTERM, previous_sigterm_handler)
                server.server_close()
                _remove_owned_pid_file(pid_path, pid)
                _remove_owned_pid_file(stop_request_path, pid)
            raise _ServerTerminationSignal(signum)

        previous_sigterm_handler = signal.signal(signal.SIGTERM, handle_sigterm)
        try:
            _write_pid_file(pid_path, lifecycle_record)
        except (ConfigError, OSError):
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
            server.server_close()
            raise

    server_info.update(build_server_info(channel_name, channel_short, port))
    canonical_url = str(server_info["base_url"])
    if collection_dirs:
        print(f"Serving {len(collection_dirs)} collections from {args.path} at {canonical_url}{COLLECTIONS_ROUTE}")
        print(f"  legacy URL: http://localhost:{port}{COLLECTIONS_ROUTE}")
        print(f"  selector label: {server_info['label']}")
        if distrokid_cfg is not None and distrokid_cfg.enabled:
            print(
                f"  distrokid dir mode enabled: {_DISTROKID_COLLECTIONS_ROUTE}, "
                f"{COLLECTIONS_ROUTE}/<id>/distrokid/<disc>/release.json"
            )
    else:
        print(f"Serving {collection_dir} at {canonical_url}")
        if prompts_path is not None:
            print(f"  suno endpoint: {SUNO_PROMPTS_ROUTE}")
        print(f"  community endpoints: {COMMUNITY_POSTS_ROUTE}, {COMMUNITY_IMAGE_ROUTE}/<index>/image")
        print(f"  legacy URL: http://localhost:{port}{SUNO_PROMPTS_ROUTE}")
        print(f"  selector label: {server_info['label']}")
        if distrokid.enabled:
            print(f"  distrokid endpoints enabled: {DISTROKID_RELEASE_ROUTE}, {DISTROKID_ASSETS_PREFIX}<path>")
    if capture_root is not None and distrokid_capture_active:
        print(
            f"  distrokid releases enabled: POST {_DISTROKID_RELEASES_ROUTE} "
            f"-> {distrokid_releases_output_path(capture_root)}"
        )
    if detected_extension is not None:
        print(
            f"  detected extension: {detected_extension.name} -> "
            f"{detected_extension.extension_id} ({detected_extension.origin})"
        )
    if allow_origin is not None and allow_origin.startswith(_EXTENSION_ORIGIN_SCHEME):
        print(f"  serve token: GET {canonical_url}/auth/token")
    else:
        print(
            "  serve token: disabled until --allow-origin chrome-extension://<EXTENSION_ID> "
            "or --allow-extension <name> is set for /auth/token, "
            f"/downloaded and {_DISTROKID_RELEASES_ROUTE}"
        )
    print("Press Ctrl-C to stop.")

    discovery_lifecycle = None
    interrupted = False
    cleanup_managed = True
    try:
        if embedded_registry_state is None:
            discovery_lifecycle = create_discovery_lifecycle(server_info)
        else:
            discovery_lifecycle = create_discovery_lifecycle(
                server_info, embedded_registry_state=embedded_registry_state
            )
        discovery_lifecycle.start()
        server.serve_forever()
    except KeyboardInterrupt:
        interrupted = True
        print("\nStopped.")
    except _IdleTimeout as error:
        print(f"Idle timeout reached: {error}. Stopping.")
    finally:
        cleanup_error: RuntimeError | ValueError | None = None
        try:
            if discovery_lifecycle is not None:
                discovery_lifecycle.stop()
        except OSError as error:
            print(f"Warning: discovery cleanup failed: {error}")
        except (RuntimeError, ValueError) as error:
            cleanup_error = error
            print(f"Warning: discovery cleanup failed: {error}")
        finally:
            try:
                signal.signal(signal.SIGTERM, previous_sigterm_handler)
            finally:
                try:
                    server.server_close()
                finally:
                    try:
                        _remove_owned_pid_file(pid_path, pid)
                    finally:
                        _remove_owned_pid_file(stop_request_path, pid)
        if cleanup_error is not None and not interrupted and sys.exc_info()[0] is None:
            raise cleanup_error


if __name__ == "__main__":
    main()
