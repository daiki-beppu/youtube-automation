"""Gemini 画像生成プロバイダー。

`google.genai` SDK でのリクエスト送信・参照画像の bytes Part 化・SAFETY/RECITATION
即時失敗・指数バックオフリトライ・PNG/JPEG 保存を担う。
"""

from __future__ import annotations

import io
import time

from youtube_automation.domains.media.image import (
    RETRY_BACKOFF,
    RETRY_MAX,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from youtube_automation.utils import cost_tracker
from youtube_automation.utils.genai_client import create_genai_client
from youtube_automation.utils.image_provider.composition import log_image_cost, persist_image
from youtube_automation.utils.image_provider.config import GeminiConfig


class GeminiImageProvider:
    """Gemini API（Vertex AI 経由）で画像を 1 枚生成して保存する。"""

    name = "gemini"
    # Gemini はアスペクト比を制限しない（branding/icon.png 用途で 1:1 等を許容）
    supported_aspect_ratios: tuple[str, ...] = ()

    def __init__(self, config: GeminiConfig) -> None:
        self._config = config

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
        """req に従って画像を生成して保存する。成功時は ImageGenerationResult.success=True。"""
        from google.genai import types
        from PIL import Image as PILImage

        client = create_genai_client(location="global")
        model = self._config.model
        image_size = req.image_size or self._config.image_size
        aspect_ratio = req.aspect_ratio
        references = list(req.references)

        if references:
            contents = []
            for ref in references:
                ref_bytes = ref.read_bytes()
                mime = "image/jpeg" if ref.suffix.lower() in (".jpg", ".jpeg") else "image/png"
                contents.append(types.Part.from_bytes(data=ref_bytes, mime_type=mime))
            if self._config.variation_guard_enabled:
                variation_guard = (
                    "IMPORTANT: The reference image(s) above are for style and composition guidance ONLY. "
                    "Create an ORIGINAL image inspired by the reference — do NOT reproduce, copy, or closely "
                    "replicate the reference. Change the subject, colors, specific elements, and details "
                    "while keeping the general mood and layout style. The output must be clearly distinct "
                    "from the reference.\n\n"
                )
                contents.append(variation_guard + req.prompt)
            else:
                contents.append(req.prompt)
        else:
            contents = [req.prompt]

        save_as_png = req.output_path.suffix.lower() == ".png"

        for attempt in range(RETRY_MAX):
            try:
                ref_label = ""
                if references:
                    names = ", ".join(r.name for r in references)
                    ref_label = f" + 参照画像={names}"
                print(f"  [Submit] モデル={model} 解像度={image_size}{ref_label}")
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                        image_config=types.ImageConfig(
                            aspect_ratio=aspect_ratio,
                            image_size=image_size,
                        ),
                    ),
                )

                for part in response.parts:
                    if part.inline_data is not None:
                        saved_path = persist_image(
                            PILImage.open(io.BytesIO(part.inline_data.data)),
                            req.output_path,
                            save_as_png=save_as_png,
                        )
                        entry = log_image_cost(
                            model=model,
                            image_size=image_size,
                            aspect_ratio=aspect_ratio,
                            output_file=saved_path,
                            reference_count=len(references),
                        )
                        cost_tracker.print_last_report(entry)
                        return ImageGenerationResult(success=True, saved_path=saved_path)

                # 画像なしレスポンス
                text_parts = [p.text for p in response.parts if p.text]
                error_msg = " ".join(text_parts) if text_parts else "no image in response"
                print(f"  [Retry]  画像なし: {error_msg[:120]}")

            except Exception as e:
                error_msg = str(e)
                if "SAFETY" in error_msg.upper() or "RECITATION" in error_msg.upper():
                    print(f"  [Skip]   コンテンツポリシー違反: {error_msg[:120]}")
                    return ImageGenerationResult(success=False, saved_path=None)
                print(f"  [Retry]  attempt {attempt + 1}/{RETRY_MAX}: {error_msg[:120]}")

            if attempt < RETRY_MAX - 1:
                backoff = RETRY_BACKOFF[attempt]
                print(f"  [Wait]   {backoff}秒待機...")
                time.sleep(backoff)

        return ImageGenerationResult(success=False, saved_path=None)
