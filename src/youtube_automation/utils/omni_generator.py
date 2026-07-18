"""Gemini Omni Flash による画像→動画生成。

Developer API の Interactions API を使い、URI delivery の Files API state を
監視して生成動画を保存する。会話型編集は扱わず、各呼び出しは独立した一発生成。
"""

from __future__ import annotations

import base64
import mimetypes
import re
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import errors

from youtube_automation.utils.secrets import get_secret
from youtube_automation.utils.veo_generator import smooth_loop

DEFAULT_MODEL = "gemini-omni-flash-preview"
DEFAULT_POLL_INTERVAL_SEC = 5.0
DEFAULT_TIMEOUT_SEC = 600.0

_FILE_NAME_RE = re.compile(r"files/([^/:?]+)")
_FAILED_STATES = {"FAILED", "CANCELLED"}


def create_omni_client():
    """Gemini API key を解決して Developer API client を作る。

    ``get_secret`` が環境変数 → 1Password → ``ConfigError`` の共通契約を担う。
    """
    return genai.Client(api_key=get_secret("GEMINI_API_KEY"))


def _state_name(file_info) -> str:
    state = getattr(file_info, "state", "")
    return str(getattr(state, "name", state)).upper()


def _file_name(uri: str) -> str | None:
    match = _FILE_NAME_RE.search(uri)
    return f"files/{match.group(1)}" if match else None


def _wait_and_download(client, uri: str, *, timeout_sec: float, poll_interval_sec: float) -> bytes | None:
    name = _file_name(uri)
    if not name:
        print(f"  [ERROR]  Omni の出力 URI を解釈できません: {uri}")
        return None

    started = time.monotonic()
    while True:
        if time.monotonic() - started > timeout_sec:
            print(f"  [ERROR]  Omni 動画処理がタイムアウトしました ({timeout_sec:g}秒)")
            return None

        try:
            file_info = client.files.get(name=name)
        except (errors.APIError, httpx.HTTPError) as exc:
            print(f"  [ERROR]  Omni Files API の状態取得に失敗しました: {exc}")
            return None

        state = _state_name(file_info)
        if state == "ACTIVE":
            try:
                return client.files.download(file=uri)
            except (errors.APIError, httpx.HTTPError) as exc:
                print(f"  [ERROR]  Omni 動画のダウンロードに失敗しました: {exc}")
                return None
        if state in _FAILED_STATES:
            print(f"  [ERROR]  Omni 動画処理が失敗しました (state={state})")
            return None

        time.sleep(poll_interval_sec)


def generate_loop_video(
    client,
    image_path: Path,
    output_path: Path,
    model: str,
    prompt: str,
    *,
    aspect_ratio: str = "16:9",
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    compression: dict | None = None,
) -> bool:
    """Omni で画像から動画を生成し、ループ補正して ``output_path`` に保存する。"""
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")

    print(f"  [Submit] engine=omni / モデル={model}")
    print(f"  [Image]  {image_path.name}")
    print(f"  [Prompt] {prompt[:100]}...")
    try:
        interaction = client.interactions.create(
            model=model,
            input=[
                {"type": "image", "data": image_data, "mime_type": mime_type},
                {"type": "text", "text": prompt},
            ],
            generation_config={"video_config": {"task": "image_to_video"}},
            response_format={"type": "video", "delivery": "uri", "aspect_ratio": aspect_ratio},
            timeout=timeout_sec,
        )
    except (errors.APIError, httpx.HTTPError, TimeoutError) as exc:
        print(f"  [ERROR]  Omni Interactions API 呼び出しに失敗しました: {exc}")
        return False

    video = getattr(interaction, "output_video", None)
    if video is None:
        print("  [ERROR]  Omni の応答に動画がありません")
        return False

    data = getattr(video, "data", None)
    if data:
        try:
            video_bytes = base64.b64decode(data, validate=True)
        except (ValueError, TypeError) as exc:
            print(f"  [ERROR]  Omni の inline 動画データを復号できません: {exc}")
            return False
    else:
        uri = getattr(video, "uri", None)
        if not uri:
            print("  [ERROR]  Omni の応答に動画 data / uri がありません")
            return False
        video_bytes = _wait_and_download(
            client,
            uri,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
        )
        if not video_bytes:
            return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(video_bytes)
    print(f"  [Save]   保存完了 → {output_path.name}")

    crf = int(compression.get("crf", 22)) if compression and compression.get("enabled", True) else 18
    preset = str(compression.get("preset", "slow")) if compression and compression.get("enabled", True) else "slow"
    if not smooth_loop(output_path, crossfade_sec=0.5, trim_tail_sec=1.0, crf=crf, preset=preset):
        print("  [Warn]   Omni 動画のループ補正に失敗しました（生成済み動画は保持します）")
    return True
