"""google-genai Client 生成の抽象化ヘルパー。

呼び出し側は `create_genai_client()` を使うことで、
Google AI Studio (API キー) と Vertex AI (ADC + GCP project) を
環境変数で切り替えられる。

- デフォルト: Google AI Studio (API キー = GEMINI_API_KEY)
- GOOGLE_GENAI_USE_VERTEXAI=true で Vertex AI に切替
  - 認証は ADC (Application Default Credentials)
  - GOOGLE_CLOUD_PROJECT と GOOGLE_CLOUD_LOCATION (default: us-central1) を参照

新規 GCP アカウント (2026/04~) では $300 無料クレジットが
Vertex AI 経由でのみ消費可能なため、該当ケースでは Vertex AI モードを推奨。
"""

from __future__ import annotations

import os

from google import genai

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.secrets import get_gemini_api_key

_TRUTHY = {"true", "1", "yes"}
_DEFAULT_LOCATION = "us-central1"


def _use_vertex() -> bool:
    return os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in _TRUTHY


def create_genai_client() -> genai.Client:
    """環境変数に応じて google-genai Client を初期化する。

    Returns:
        genai.Client: 初期化済みクライアント。呼び出し側は
            `client.models.generate_content(...)` など共通 API をそのまま使える。

    Raises:
        ConfigError: Vertex AI モードで GOOGLE_CLOUD_PROJECT が未設定の場合、
            または AI Studio モードで GEMINI_API_KEY が取得できない場合。
    """
    if _use_vertex():
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", _DEFAULT_LOCATION)
        if not project:
            raise ConfigError(
                "Vertex AI モード (GOOGLE_GENAI_USE_VERTEXAI=true) では "
                "GOOGLE_CLOUD_PROJECT が必須です。\n"
                "  → .env に GOOGLE_CLOUD_PROJECT=<gcp-project-id> を設定し、\n"
                "  → `gcloud auth application-default login` で ADC を準備してください"
            )
        return genai.Client(vertexai=True, project=project, location=location)

    return genai.Client(api_key=get_gemini_api_key())
