"""ImageProvider 抽象基底とリクエスト/レスポンス型。

Gemini / OpenAI の差を吸収するための薄い抽象化レイヤ。Provider 実装は
``generate(req)`` を実装し、`ImageGenerationResult` を返す。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

# 共通リトライ定数（Gemini / OpenAI で共有）
RETRY_MAX = 3
RETRY_BACKOFF: tuple[int, ...] = (10, 30, 60)


@dataclass(frozen=True)
class ImageGenerationRequest:
    """1 件分の画像生成リクエスト。

    Provider 中立の値のみを保持する（API 固有の `size` 文字列・`quality` 等は
    Provider 実装側で `aspect_ratio` から導出する）。

    Attributes:
        prompt: 生成プロンプト
        output_path: 出力先（拡張子 .png なら PNG ロスレス保存、.jpg なら JPEG）
        aspect_ratio: "16:9" / "9:16" / "1:1" など。OpenAI は 16:9/9:16 のみ受理
        image_size: Provider 固有の解像度ヒント（Gemini は "1K"/"2K"/"4K"、
            OpenAI は "1536x1024" 等の生 size 文字列）
        references: 参照画像パス（空なら参照なしモード）
        cost_per_image_usd: PRICING を上書きするカスタム単価（None なら自動算出）
    """

    prompt: str
    output_path: Path
    aspect_ratio: str
    image_size: str
    references: Sequence[Path] = field(default_factory=tuple)
    cost_per_image_usd: float | None = None


@dataclass(frozen=True)
class ImageGenerationResult:
    """画像生成の結果。

    Attributes:
        success: True なら保存成功
        saved_path: 保存先（拡張子変更が起きた場合は変更後のパス）。失敗時 None
    """

    success: bool
    saved_path: Path | None = None


@runtime_checkable
class ImageProvider(Protocol):
    """画像生成プロバイダーの最小契約。

    実装クラスは以下を備える:
    - ``name``: 識別子（"gemini" / "openai"）
    - ``pricing_model_id``: ``cost_tracker.PRICING`` のキーと一致するモデル ID
    - ``supported_aspect_ratios``: 許容するアスペクト比の列。空タプルは「制限なし」を意味する
    - ``generate(req)``: 1 枚生成して保存
    """

    name: str
    pricing_model_id: str
    supported_aspect_ratios: tuple[str, ...]

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult: ...
