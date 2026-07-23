"""google-genai Client 生成の抽象化ヘルパー (Vertex AI 専用)。

認証は ADC (Application Default Credentials) を前提とする。
事前に `.claude/skills/channel-new/references/gcp-bootstrap.sh` または `infra/terraform/gcp/` で
GCP プロジェクト / API 有効化 / ADC を整えたうえで使用する。

環境変数:
- `GOOGLE_CLOUD_PROJECT` (任意) — 未設定なら ADC quota project から自動解決

Vertex AI はモデルごとにサポート region が異なる (2026-04 現在):
- `gemini-3.1-flash-image-preview` などの画像系: `global` のみ
- `veo-3.1-fast-generate-001` などの Veo 系: `us-central1` など region 指定

呼び出し側はモデル用途に合わせて `create_global_genai_client()` または
`create_veo_genai_client()` を使う。
"""

from __future__ import annotations

from google import genai

from youtube_automation.utils.google_cloud_project import resolve_project_id

GLOBAL_LOCATION = "global"
VEO_LOCATION = "us-central1"


def create_genai_client(*, location: str) -> genai.Client:
    """Vertex AI モードで google-genai Client を初期化する。

    Args:
        location: 利用モデルに対応する、呼び出し側で固定した region。
    """
    project = resolve_project_id()
    return genai.Client(vertexai=True, project=project, location=location)


def create_global_genai_client() -> genai.Client:
    """画像・Gemini・Lyria と同じ global endpoint を使う client を返す."""
    return create_genai_client(location=GLOBAL_LOCATION)


def create_veo_genai_client() -> genai.Client:
    """Veo 生成に対応する us-central1 endpoint の client を返す."""
    return create_genai_client(location=VEO_LOCATION)
