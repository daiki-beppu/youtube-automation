"""google-genai Client 生成の抽象化ヘルパー (Vertex AI 専用)。

認証は ADC (Application Default Credentials) を前提とする。
事前に `scripts/gcp-bootstrap.sh` または `infra/terraform/gcp/` で
GCP プロジェクト / API 有効化 / ADC を整えたうえで使用する。

必要な環境変数:
- `GOOGLE_CLOUD_PROJECT` (必須)
- `GOOGLE_CLOUD_LOCATION` (任意、既定 `us-central1`)
"""

from __future__ import annotations

import os

from google import genai

from youtube_automation.utils.exceptions import ConfigError

_DEFAULT_LOCATION = "us-central1"


def create_genai_client() -> genai.Client:
    """Vertex AI モードで google-genai Client を初期化する。"""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", _DEFAULT_LOCATION)
    if not project:
        raise ConfigError(
            "GOOGLE_CLOUD_PROJECT が未設定です。`scripts/gcp-bootstrap.sh` または "
            "`infra/terraform/gcp/` で .env を書き出し、`gcloud auth application-default login` を実行してください"
        )
    return genai.Client(vertexai=True, project=project, location=location)
