"""google-genai Client 生成の抽象化ヘルパー (Vertex AI 専用)。

認証は ADC (Application Default Credentials) を前提とする。
事前に `scripts/gcp-bootstrap.sh` または `infra/terraform/gcp/` で
GCP プロジェクト / API 有効化 / ADC を整えたうえで使用する。

必要な環境変数:
- `GOOGLE_CLOUD_PROJECT` (必須)
- `GOOGLE_CLOUD_LOCATION` (任意、既定 `us-central1`)

Vertex AI はモデルごとにサポート region が異なる (2026-04 現在):
- `gemini-3.1-flash-image-preview` などの画像系: `global` のみ
- `veo-3.1-fast-generate-001` などの Veo 系: `us-central1` など region 指定

呼び出し側はモデルに合わせて `create_genai_client(location="global")` のように
明示的に location を渡すこと。
"""

from __future__ import annotations

import os

from google import genai

from youtube_automation.utils.exceptions import ConfigError

_DEFAULT_LOCATION = "us-central1"


def create_genai_client(location: str | None = None) -> genai.Client:
    """Vertex AI モードで google-genai Client を初期化する。

    Args:
        location: 明示指定する region。None のときは `GOOGLE_CLOUD_LOCATION` 環境変数 →
            `_DEFAULT_LOCATION` の順でフォールバック。
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise ConfigError(
            "GOOGLE_CLOUD_PROJECT が未設定です。`scripts/gcp-bootstrap.sh` または "
            "`infra/terraform/gcp/` で .env を書き出し、`gcloud auth application-default login` を実行してください"
        )
    resolved_location = location or os.environ.get("GOOGLE_CLOUD_LOCATION", _DEFAULT_LOCATION)
    return genai.Client(vertexai=True, project=project, location=resolved_location)
