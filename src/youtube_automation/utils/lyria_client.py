"""Vertex AI Lyria 3 REST クライアント。

google-genai SDK 1.71.0 時点で Lyria 3 の `interactions` エンドポイントは未対応のため、
`requests` で直接叩く。認証は ADC (Application Default Credentials) 経由で access token を取得する。

エンドポイント:
    POST https://aiplatform.googleapis.com/v1beta1/projects/PROJECT/locations/global/interactions

公式ドキュメント: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/music/generate-music

中断 (Ctrl+C) 時のオーディオ救済 (#481):
    Lyria は単一同期リクエストで billing が確定するため、Veo (async operation) と異なり
    「response を受信した時点で課金済み」になる。`requests.post` の戻り後に Ctrl+C を受けると
    支払い済みオーディオが失われるため、`generate_music()` は response 受信後の
    KeyboardInterrupt を捕捉し、bytes を `<CHANNEL_DIR>/tmp/lyria-recovered/<sha1>.mp3`
    へ退避してから中断を再送出する。`<sha1>` は MP3 bytes の内容ハッシュ（同一応答の
    再退避は冪等）。退避ファイルは手動で WAV 化して `02-Individual-music/` に置けば
    再課金なしで再利用できる（呼び出し側 `generate_lyria_master.py` が WAV 保存中の
    中断も同じ退避経路で救済する）。
"""

from __future__ import annotations

import base64
import functools
import hashlib
from pathlib import Path
from typing import Literal

import requests
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as AuthRequest

from youtube_automation.configuration import channel_dir
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.google_cloud_project import resolve_project_id

_ENDPOINT = "https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/global/interactions"
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_TIMEOUT_SEC = 300

# 支払い済みオーディオの退避先（<CHANNEL_DIR> からの相対サブパス）。
_RECOVERY_SUBDIR = ("tmp", "lyria-recovered")

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


def _audio_data_from_entries(entries: object) -> str | None:
    """`{"type": "audio", "mime_type": ..., "data": ...}` 形式の配列から audio data を抽出。

    legacy `outputs[*]` と新 schema `steps[*].content[*]` は audio 要素の形状が同一のため、
    両経路でこのヘルパーを共有する。型不正・キー欠落・非 audio mime は skip して次へ進む
    （例外を投げない）。
    """
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "audio":
            continue
        mime = entry.get("mime_type", "")
        if not isinstance(mime, str) or not mime.startswith("audio/"):
            continue
        data = entry.get("data")
        if isinstance(data, str):
            return data
    return None


def _new_schema_audio_data(steps: object) -> str | None:
    """新 schema `steps[*].content[*]` から base64 エンコード済み audio data 文字列を抽出。

    May 2026 breaking change で flat な `outputs` 配列が `steps` 配列へ置き換わる。各 step は
    `content` 配列を持ち、その要素形状は legacy `outputs` と同一（`type` / `mime_type` / `data`）。
    公式仕様: https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026
    型不正・キー欠落は skip して次へ進む（例外を投げない）。
    """
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        data = _audio_data_from_entries(step.get("content"))
        if data is not None:
            return data
    return None


def _extract_audio_bytes(body: dict) -> bytes | None:
    """Lyria レスポンスから audio bytes を抽出。legacy `outputs` と新 schema `steps` の両対応。

    走査順序は legacy → 新 schema 固定。両 schema に audio が同居する移行期レスポンスでは
    legacy を優先して既存挙動互換を保つ。型不正・キー欠落・非 audio mime は skip し、
    両 schema いずれにも audio が見つからなければ None。
    """
    # legacy `outputs` は audio 要素の flat list なので共通ヘルパーで直接抽出する。
    encoded = _audio_data_from_entries(body.get("outputs"))
    if encoded is None:
        encoded = _new_schema_audio_data(body.get("steps"))
    return base64.b64decode(encoded) if encoded is not None else None


def recovery_path(audio: bytes) -> Path:
    """退避先 `<CHANNEL_DIR>/tmp/lyria-recovered/<sha1>.mp3` を返す（#481）。

    `<sha1>` は MP3 bytes の内容ハッシュ。同一応答は同一パスになるため再退避は冪等。
    """
    digest = hashlib.sha1(audio).hexdigest()
    return channel_dir().joinpath(*_RECOVERY_SUBDIR) / f"{digest}.mp3"


def persist_recovered_audio(audio: bytes) -> Path:
    """支払い済みオーディオ bytes を退避ファイルに保存し、そのパスを返す（#481）。

    中断 (Ctrl+C) で課金済み応答が失われるのを防ぐための救済処理。呼び出し側
    （WAV 保存中の中断救済）からも利用される。
    """
    path = recovery_path(audio)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return path


def _recover_audio_on_interrupt(response: requests.Response) -> None:
    """response 受信後の中断時に audio bytes を再抽出して退避する（#481）。

    非ストリーミング `requests.post` では戻り時点で `response.content` が全受信済みのため、
    JSON パース中の Ctrl+C でも bytes を救済できる。退避先パスを画面に表示する。
    """
    try:
        audio = _extract_audio_bytes(response.json())
    except (ValueError, KeyboardInterrupt):
        # JSON 不正 / 退避中の二重 Ctrl+C は救済不能として扱う
        audio = None
    if audio is None:
        print("\n[Interrupt] Ctrl+C 検出。退避可能なオーディオデータがありませんでした。")
        return
    path = persist_recovered_audio(audio)
    print(
        f"\n[Recovered] 支払い済みオーディオを退避しました → {path}\n"
        "            手動で WAV 化して 02-Individual-music/ に置けば再課金なしで再利用できます。"
    )


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
    except KeyboardInterrupt:
        # API 処理中の中断。response 未受信のため bytes は手元になく救済不能。
        # billing は Lyria 側で確定し得るが、ここでは退避できないことを明示する。
        print("\n[Interrupt] Ctrl+C 検出（Lyria API 処理中）。response 未受信のため支払い済み応答を救済できません。")
        raise
    except requests.RequestException as e:
        print(f"\n[ERROR] Lyria API 呼び出し失敗: {e}")
        return None

    # response を受信した時点で billing は確定している。以降の Ctrl+C では
    # 支払い済みオーディオ bytes を退避してから中断を伝播する（#481）。
    try:
        if not response.ok:
            print(f"\n[ERROR] Lyria API {response.status_code}: {response.text}")
            return None

        body = response.json()
        audio = _extract_audio_bytes(body)
    except KeyboardInterrupt:
        _recover_audio_on_interrupt(response)
        raise

    if audio is not None:
        return audio

    print(f"\n[ERROR] Lyria レスポンスにオーディオデータがありません: {body}")
    return None
