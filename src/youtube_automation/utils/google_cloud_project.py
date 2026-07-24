"""GCP project_id 解決ヘルパー。

`GOOGLE_CLOUD_PROJECT` 環境変数を必須にせず、未設定時は ADC
(`gcloud auth application-default login`) credentials の `quota_project_id` に
フォールバックする。env var が設定されていれば従来通り優先利用する。
"""

from __future__ import annotations

import os

from google.auth import default as google_auth_default
from google.auth.exceptions import DefaultCredentialsError

from youtube_automation.infrastructure.errors import ConfigError

_ENV_KEY = "GOOGLE_CLOUD_PROJECT"


def resolve_project_id(override: str | None = None) -> str:
    """GCP project_id を解決する。

    優先順位:
        1. `override` 引数（呼び出し側の明示指定）
        2. `os.environ["GOOGLE_CLOUD_PROJECT"]`
        3. `google.auth.default()` の戻り値 (`_, project_id`)
           — ADC credentials の `quota_project_id` がここに反映される

    いずれの経路でも取得できない場合は `ConfigError`。
    """
    if override:
        return override

    env_value = os.environ.get(_ENV_KEY)
    if env_value:
        return env_value

    try:
        _, adc_project = google_auth_default()
    except DefaultCredentialsError as exc:
        raise ConfigError(
            "GCP project_id を解決できません。"
            "`GOOGLE_CLOUD_PROJECT` を設定するか、"
            "`gcloud auth application-default login` で ADC を初期化してください"
        ) from exc

    if not adc_project:
        raise ConfigError(
            "ADC credentials に project_id が含まれていません。"
            "`gcloud auth application-default set-quota-project <PROJECT_ID>` で "
            "quota project を設定するか、`GOOGLE_CLOUD_PROJECT` 環境変数で明示してください"
        )

    return adc_project
