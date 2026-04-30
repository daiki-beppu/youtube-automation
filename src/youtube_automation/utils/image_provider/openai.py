"""OpenAI 画像生成プロバイダー（gpt-image-2 系）。

`openai` SDK の ``images.generate`` / ``images.edit`` を呼ぶ。
``aspect_ratio`` を OpenAI Images API の ``size`` 文字列にマップし、
API キーは `secrets.get_secret("OPENAI_API_KEY")` 経由で取得する。
"""

from __future__ import annotations

import base64
import contextlib
import io
import time
import warnings

from openai import OpenAI

from youtube_automation.utils import cost_tracker
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.base import (
    RETRY_BACKOFF,
    RETRY_MAX,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from youtube_automation.utils.image_provider.composition import log_image_cost, persist_image
from youtube_automation.utils.image_provider.config import (
    OPENAI_SUPPORTED_ASPECT_RATIOS,
    OpenAIConfig,
)
from youtube_automation.utils.secrets import get_secret

# OpenAI Images API が受け付ける size 文字列へのマッピング
_ASPECT_RATIO_TO_SIZE: dict[str, str] = {
    "16:9": "1536x1024",
    "9:16": "1024x1536",
}


class OpenAIImageProvider:
    """OpenAI Images API（gpt-image-2 系）で画像を 1 枚生成して保存する。"""

    name = "openai"
    supported_aspect_ratios: tuple[str, ...] = OPENAI_SUPPORTED_ASPECT_RATIOS

    def __init__(self, config: OpenAIConfig) -> None:
        self._config = config
        # `thinking` は config では受理するが、現在の openai-python SDK は
        # ``images.generate`` / ``images.edit`` に該当 kwarg を渡せない。
        # 設定が効いていると誤認させないため、明示値を持つ場合は警告する。
        # SDK が将来対応したらここを delete し generate() の kwargs に追加する。
        if config.thinking and config.thinking.lower() not in ("off", ""):
            warnings.warn(
                f"OpenAIConfig.thinking={config.thinking!r} は現在 openai-python SDK の "
                "images API に渡せず無視されます",
                stacklevel=2,
            )

    @property
    def pricing_model_id(self) -> str:
        return self._config.model

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
        """req に従って画像を生成して保存する。"""
        from PIL import Image as PILImage

        if req.aspect_ratio not in _ASPECT_RATIO_TO_SIZE:
            raise ConfigError(
                f"OpenAI image_generation の aspect_ratio={req.aspect_ratio!r} は未対応。"
                f"許容値: {tuple(_ASPECT_RATIO_TO_SIZE.keys())}"
            )

        api_key = get_secret("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        size = _ASPECT_RATIO_TO_SIZE[req.aspect_ratio]
        model = self._config.model
        quality = self._config.quality
        n = self._config.batch
        references = list(req.references)
        save_as_png = req.output_path.suffix.lower() == ".png"

        for attempt in range(RETRY_MAX):
            try:
                ref_label = ""
                if references:
                    names = ", ".join(r.name for r in references)
                    ref_label = f" + 参照画像={names}"
                print(f"  [Submit] モデル={model} size={size} quality={quality}{ref_label}")

                if references:
                    with contextlib.ExitStack() as stack:
                        image_files = [stack.enter_context(ref.open("rb")) for ref in references]
                        response = client.images.edit(
                            model=model,
                            image=image_files,
                            prompt=req.prompt,
                            size=size,
                            quality=quality,
                            n=n,
                        )
                else:
                    response = client.images.generate(
                        model=model,
                        prompt=req.prompt,
                        size=size,
                        quality=quality,
                        n=n,
                    )

                payload = _decode_first_image(response)
                if payload is None:
                    print("  [Retry]  画像なしレスポンス")
                else:
                    pil_image = PILImage.open(io.BytesIO(payload))
                    saved_path = persist_image(pil_image, req.output_path, save_as_png=save_as_png)
                    entry = log_image_cost(
                        model=model,
                        image_size=quality,  # OpenAI は quality で課金階層が決まる → PRICING の by_size key と一致
                        aspect_ratio=req.aspect_ratio,
                        output_file=saved_path,
                        cost_usd=req.cost_per_image_usd,
                        reference_count=len(references),
                    )
                    cost_tracker.print_last_report(entry)
                    return ImageGenerationResult(success=True, saved_path=saved_path)

            except ConfigError:
                # ConfigError は Fail Fast。リトライしない。
                raise
            except Exception as e:  # noqa: BLE001 - SDK 例外は文字列で分岐
                error_msg = str(e)
                print(f"  [Retry]  attempt {attempt + 1}/{RETRY_MAX}: {error_msg[:120]}")

            if attempt < RETRY_MAX - 1:
                backoff = RETRY_BACKOFF[attempt]
                print(f"  [Wait]   {backoff}秒待機...")
                time.sleep(backoff)

        return ImageGenerationResult(success=False, saved_path=None)


def _decode_first_image(response) -> bytes | None:
    """OpenAI Images API レスポンスから先頭画像の生バイト列を取り出す。"""
    data = getattr(response, "data", None) or []
    for item in data:
        b64 = getattr(item, "b64_json", None)
        if b64:
            return base64.b64decode(b64)
    return None
