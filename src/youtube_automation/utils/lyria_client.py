"""Vertex AI Lyria 3 REST クライアント。

google-genai SDK 1.71.0 時点で Lyria 3 の `interactions` エンドポイントは未対応のため、
`requests` で直接叩く。認証は ADC (Application Default Credentials) 経由で access token を取得する。

エンドポイント:
    POST https://aiplatform.googleapis.com/v1beta1/projects/PROJECT/locations/global/interactions

公式ドキュメント: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/music/generate-music
"""

from __future__ import annotations

import base64
import os

import requests
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as AuthRequest

from youtube_automation.utils.exceptions import ConfigError

_ENDPOINT = "https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/global/interactions"
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_TIMEOUT_SEC = 300


def _access_token() -> str:
    credentials, _ = google_auth_default(scopes=_SCOPES)
    credentials.refresh(AuthRequest())
    return credentials.token


def generate_music(prompt: str, model: str) -> bytes | None:
    """Lyria 3 に prompt を投げてオーディオバイト列 (MP3) を返す。失敗時は None。"""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise ConfigError(
            "GOOGLE_CLOUD_PROJECT が未設定です。`scripts/gcp-bootstrap.sh` または "
            "`infra/terraform/gcp/` で .env を書き出し、`gcloud auth application-default login` を実行してください"
        )

    url = _ENDPOINT.format(project=project)
    payload = {
        "model": model,
        "input": [{"type": "text", "text": prompt}],
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
