"""Vertex AI Lyria 3 REST クライアント。

google-genai SDK 1.71.0 時点で Lyria 3 の `interactions` エンドポイントは未対応のため、
`requests` で直接叩く。認証は ADC (Application Default Credentials) 経由で access token を取得する。

エンドポイント:
    POST https://aiplatform.googleapis.com/v1beta1/projects/PROJECT/locations/global/interactions

公式ドキュメント: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/music/generate-music
"""

from __future__ import annotations

import base64
import functools
from pathlib import Path
from typing import Literal

import requests
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as AuthRequest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.google_cloud_project import resolve_project_id

_ENDPOINT = "https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/global/interactions"
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_TIMEOUT_SEC = 300

Intensity = Literal["low", "medium", "high"]
Mode = Literal["vocal", "instrumental"]

_INTENSITY_PHRASES: dict[str, str] = {
    "low": "mellow, low-energy",
    "medium": "balanced, moderate energy",
    "high": "driving, high-energy",
}

_MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _image_mime(path: Path) -> str:
    """画像パスの拡張子から MIME type を解決する。未対応形式は ConfigError。"""
    mime = _MIME_BY_EXT.get(path.suffix.lower())
    if mime is None:
        raise ConfigError(f"対応していない画像形式: {path.suffix} (対応: {sorted(_MIME_BY_EXT)})")
    return mime


@functools.lru_cache(maxsize=32)
def _encode_reference_image(path: Path) -> dict:
    """参照画像を Lyria 3 `input` 配列要素に変換する。不在・未対応形式は ConfigError。

    並列セグメント生成で同一画像が繰り返しエンコードされるのを避けるためキャッシュする。
    戻り値の dict は payload に append されるだけで mutate されない前提。
    """
    if not path.exists():
        raise ConfigError(f"参照画像が存在しません: {path}")
    return {
        "type": "image",
        "mime_type": _image_mime(path),
        "data": base64.b64encode(path.read_bytes()).decode(),
    }


def _compose_prompt(
    base_prompt: str,
    bpm: int | None,
    intensity: Intensity | None,
    mode: Mode | None,
    lyrics: str | None,
) -> str:
    """構造化パラメータを自然言語プロンプトに合成する。

    Lyria 3 interactions API は BPM / intensity / mode / lyrics を独立フィールドではなく
    プロンプトテキストに埋め込む仕様のため、ここで一括変換する。
    """
    head = f"{_INTENSITY_PHRASES[intensity]}, " if intensity is not None else ""
    prompt = f"{head}{base_prompt}"
    if bpm is not None:
        prompt = f"{prompt}, {bpm} BPM"
    if mode == "instrumental":
        prompt = f"{prompt}. Instrumental."
    elif mode == "vocal" and not lyrics:
        prompt = f"{prompt}. With vocals."
    if lyrics:
        sep = " " if prompt.endswith(".") else ". "
        prompt = f"{prompt}{sep}Lyrics: {lyrics}"
    return prompt


def _access_token() -> str:
    credentials, _ = google_auth_default(scopes=_SCOPES)
    credentials.refresh(AuthRequest())
    return credentials.token


def generate_music(
    prompt: str,
    model: str,
    reference_image: Path | None = None,
    bpm: int | None = None,
    intensity: Intensity | None = None,
    mode: Mode | None = None,
    lyrics: str | None = None,
) -> bytes | None:
    """Lyria 3 に prompt と追加パラメータを投げてオーディオバイト列 (MP3) を返す。失敗時は None。

    API 仕様上、構造化入力は `reference_image` のみ。`bpm` / `intensity` / `mode` / `lyrics` は
    プロンプトテキストに自然言語として合成される。
    """
    project = resolve_project_id()
    url = _ENDPOINT.format(project=project)
    composed = _compose_prompt(prompt, bpm, intensity, mode, lyrics)
    inputs: list[dict] = [{"type": "text", "text": composed}]
    if reference_image is not None:
        inputs.append(_encode_reference_image(reference_image))
    payload = {
        "model": model,
        "input": inputs,
    }
    headers = {
        "Authorization": f"Bearer {_access_token()}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SEC)
    except requests.RequestException as e:
        print(f"\n[ERROR] Lyria API 呼び出し失敗: {e}")
        return None

    if not response.ok:
        print(f"\n[ERROR] Lyria API {response.status_code}: {response.text}")
        return None

    body = response.json()
    for out in body.get("outputs", []):
        if out.get("type") == "audio" and out.get("mime_type", "").startswith("audio/"):
            return base64.b64decode(out["data"])

    print(f"\n[ERROR] Lyria レスポンスにオーディオデータがありません: {body}")
    return None
