"""Compatibility facade for the downstream image-provider import path."""

import sys

from youtube_automation.infrastructure.media.image_provider import *  # noqa: F403
from youtube_automation.infrastructure.media.image_provider import (
    composition as composition,
)
from youtube_automation.infrastructure.media.image_provider import (
    config as config,
)
from youtube_automation.infrastructure.media.image_provider import (
    gemini as gemini,
)
from youtube_automation.infrastructure.media.image_provider import (
    openai as openai,
)
from youtube_automation.infrastructure.media.image_provider import (
    prompt_schema as prompt_schema,
)

# サブモジュールのエイリアスはこの __init__ に集約する（per-file shim は import 機構上実行されないため置かない）
sys.modules[f"{__name__}.composition"] = composition
sys.modules[f"{__name__}.config"] = config
sys.modules[f"{__name__}.gemini"] = gemini
sys.modules[f"{__name__}.openai"] = openai
sys.modules[f"{__name__}.prompt_schema"] = prompt_schema
