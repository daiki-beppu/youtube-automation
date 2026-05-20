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


def _legacy_audio_data(outputs: object) -> str | None:
    """legacy `outputs` 配列から base64 エンコード済み audio data 文字列を抽出。

    型不正・キー欠落・非 audio mime は skip して次へ進む（例外を投げない）。
    """
    if not isinstance(outputs, list):
        return None
    for out in outputs:
        if not isinstance(out, dict) or out.get("type") != "audio":
            continue
        mime = out.get("mime_type", "")
        if not isinstance(mime, str) or not mime.startswith("audio/"):
            continue
        data = out.get("data")
        if isinstance(data, str):
            return data
    return None


def _audio_data_from_part(part: object) -> str | None:
    """新 schema `parts[*]` の 1 要素から base64 エンコード済み audio data 文字列を抽出。

    `inline_data` / `inlineData` および `mime_type` / `mimeType` の両表記を defensive に受ける。
    """
    if not isinstance(part, dict):
        return None
    inline = part.get("inline_data")
    if not isinstance(inline, dict):
        inline = part.get("inlineData")
    if not isinstance(inline, dict):
        return None
    mime = inline.get("mime_type") or inline.get("mimeType") or ""
    if not isinstance(mime, str) or not mime.startswith("audio/"):
        return None
    data = inline.get("data")
    return data if isinstance(data, str) else None


def _new_schema_audio_data(candidates: object) -> str | None:
    """新 schema `candidates[*].content.parts[*].inline_data` から audio data 文字列を抽出。"""
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            data = _audio_data_from_part(part)
            if data is not None:
                return data
    return None


def _extract_audio_bytes(body: dict) -> bytes | None:
    """Lyria レスポンスから audio bytes を抽出。legacy `outputs` と新 schema の両対応。

    走査順序は legacy → 新 schema 固定。両 schema に audio が同居する移行期レスポンスでは
    legacy を優先して既存挙動互換を保つ。型不正・キー欠落・非 audio mime は skip し、
    両 schema いずれにも audio が見つからなければ None。
    """
    encoded = _legacy_audio_data(body.get("outputs"))
    if encoded is None:
        encoded = _new_schema_audio_data(body.get("candidates"))
    return base64.b64decode(encoded) if encoded is not None else None


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
    audio = _extract_audio_bytes(body)
    if audio is not None:
        return audio

    print(f"\n[ERROR] Lyria レスポンスにオーディオデータがありません: {body}")
    return None
