"""GeminiImageProvider の単体テスト。

`google.genai.Client` をモックし、現 `image_generator.generate_image()` の
振る舞いがリファクタ後も保たれていることを確認する回帰テスト。

検証する振る舞い:
1. aspect_ratio / image_size / model がそのまま Gemini API へ転送される
2. 参照画像があれば bytes Part として送信される
3. SAFETY / RECITATION 例外は即時失敗（リトライしない）
4. 一時的エラーは指数バックオフでリトライし、最終的に成功すれば True
5. 全リトライ失敗時は False を返す
6. 成功時は ImageGenerationResult.success=True と保存パスを返す
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.image_provider.base import ImageGenerationRequest
from youtube_automation.utils.image_provider.config import GeminiConfig
from youtube_automation.utils.image_provider.gemini import GeminiImageProvider

# ---------- フィクスチャ ----------


def _png_bytes() -> bytes:
    """1x1 のダミー PNG 画像バイナリ。"""
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (16, 16), color=(0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _fake_image_part(payload: bytes) -> MagicMock:
    """genai.Client が返す Part のスタブ（inline_data あり）。"""
    part = MagicMock()
    part.inline_data = MagicMock()
    part.inline_data.data = payload
    part.text = None
    return part


def _fake_text_part(text: str) -> MagicMock:
    """画像なしテキストレスポンス（Gemini が画像生成に失敗した場合）。"""
    part = MagicMock()
    part.inline_data = None
    part.text = text
    return part


def _fake_response(parts: list) -> MagicMock:
    response = MagicMock()
    response.parts = parts
    return response


@pytest.fixture
def gemini_config() -> GeminiConfig:
    return GeminiConfig(model="gemini-3.1-flash-image-preview", image_size="2K")


@pytest.fixture
def request_factory(tmp_path: Path):
    """ImageGenerationRequest を生成するファクトリ。tmp_path 配下に出力する。"""

    def _make(
        *,
        prompt: str = "a serene mountain at dawn",
        references: list[Path] | None = None,
        aspect_ratio: str = "16:9",
        image_size: str = "2K",
        output_name: str = "out.png",
    ) -> ImageGenerationRequest:
        return ImageGenerationRequest(
            prompt=prompt,
            output_path=tmp_path / output_name,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            references=list(references or []),
        )

    return _make


@pytest.fixture
def patched_genai_client():
    """`create_genai_client` を MagicMock に差し替えるコンテキストマネージャ。"""
    from contextlib import contextmanager

    @contextmanager
    def _ctx(response):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = response
        with patch(
            "youtube_automation.utils.image_provider.gemini.create_genai_client",
            return_value=mock_client,
        ):
            yield mock_client

    return _ctx


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """リトライバックオフを高速化（time.sleep を no-op に）。"""
    monkeypatch.setattr(
        "youtube_automation.utils.image_provider.gemini.time.sleep",
        lambda s: None,
    )


# ---------- Gemini API への引数転送 ----------


class TestForwardsRequestToGeminiApi:
    def test_aspect_ratio_and_image_size_are_forwarded(self, gemini_config, request_factory, patched_genai_client):
        # Given
        provider = GeminiImageProvider(gemini_config)
        req = request_factory(aspect_ratio="9:16", image_size="2K", output_name="out.png")
        response = _fake_response([_fake_image_part(_png_bytes())])

        # When
        with patched_genai_client(response) as client:
            result = provider.generate(req)

        # Then
        assert result.success is True
        kwargs = client.models.generate_content.call_args.kwargs
        assert kwargs["model"] == "gemini-3.1-flash-image-preview"
        # config 引数の中に aspect_ratio / image_size がセットされている
        cfg_arg = kwargs["config"]
        # GenerateContentConfig は属性アクセス可能
        assert getattr(cfg_arg.image_config, "aspect_ratio") == "9:16"
        assert getattr(cfg_arg.image_config, "image_size") == "2K"

    def test_does_not_validate_aspect_ratio_for_gemini(self, gemini_config, request_factory, patched_genai_client):
        """Gemini は branding/icon.png 用途で 1:1 等の任意比率を許容する。"""
        # Given
        provider = GeminiImageProvider(gemini_config)
        req = request_factory(aspect_ratio="1:1", image_size="2K")
        response = _fake_response([_fake_image_part(_png_bytes())])

        # When
        with patched_genai_client(response) as client:
            result = provider.generate(req)

        # Then: ConfigError にならず、API へそのまま渡る
        assert result.success is True
        kwargs = client.models.generate_content.call_args.kwargs
        assert kwargs["config"].image_config.aspect_ratio == "1:1"


class TestReferenceImagesForwarding:
    def test_no_reference_sends_only_prompt(self, gemini_config, request_factory, patched_genai_client):
        # Given
        provider = GeminiImageProvider(gemini_config)
        req = request_factory(references=[])
        response = _fake_response([_fake_image_part(_png_bytes())])

        # When
        with patched_genai_client(response) as client:
            provider.generate(req)

        # Then: contents にプロンプト文字列のみが含まれる
        contents = client.models.generate_content.call_args.kwargs["contents"]
        assert any(isinstance(c, str) for c in contents)

    def test_reference_image_is_sent_as_bytes_part(
        self, tmp_path, gemini_config, request_factory, patched_genai_client
    ):
        # Given
        ref_path = tmp_path / "ref.png"
        ref_path.write_bytes(_png_bytes())
        provider = GeminiImageProvider(gemini_config)
        req = request_factory(references=[ref_path])
        response = _fake_response([_fake_image_part(_png_bytes())])

        # When
        with patched_genai_client(response) as client:
            provider.generate(req)

        # Then: contents には参照画像が含まれる（bytes Part として）
        contents = client.models.generate_content.call_args.kwargs["contents"]
        # プロンプトと参照画像の両方が含まれていることを長さで確認
        assert len(contents) >= 2


# ---------- Variation Guard ----------


class TestVariationGuard:
    """variation_guard_enabled の ON/OFF でプロンプト先頭が変わることを検証する。"""

    def test_variation_guard_prepended_when_references_provided(self, tmp_path, request_factory, patched_genai_client):
        """参照画像あり + variation_guard_enabled=True → プロンプトに guard テキストが付く。"""
        # Given
        ref_path = tmp_path / "ref.png"
        ref_path.write_bytes(_png_bytes())
        config = GeminiConfig(model="gemini-3.1-flash-image-preview", variation_guard_enabled=True)
        provider = GeminiImageProvider(config)
        req = request_factory(prompt="a calm ocean sunset", references=[ref_path])
        response = _fake_response([_fake_image_part(_png_bytes())])

        # When
        with patched_genai_client(response) as client:
            provider.generate(req)

        # Then: 最後の contents 要素（プロンプト文字列）が "IMPORTANT:" で始まる
        contents = client.models.generate_content.call_args.kwargs["contents"]
        prompt_part = contents[-1]
        assert isinstance(prompt_part, str)
        assert prompt_part.startswith("IMPORTANT:")
        assert "a calm ocean sunset" in prompt_part

    def test_variation_guard_skipped_when_disabled(self, tmp_path, request_factory, patched_genai_client):
        """参照画像あり + variation_guard_enabled=False → プロンプトそのまま。"""
        # Given
        ref_path = tmp_path / "ref.png"
        ref_path.write_bytes(_png_bytes())
        config = GeminiConfig(model="gemini-3.1-flash-image-preview", variation_guard_enabled=False)
        provider = GeminiImageProvider(config)
        req = request_factory(prompt="a calm ocean sunset", references=[ref_path])
        response = _fake_response([_fake_image_part(_png_bytes())])

        # When
        with patched_genai_client(response) as client:
            provider.generate(req)

        # Then: プロンプトがそのまま（guard テキストなし）
        contents = client.models.generate_content.call_args.kwargs["contents"]
        prompt_part = contents[-1]
        assert isinstance(prompt_part, str)
        assert prompt_part == "a calm ocean sunset"

    def test_no_references_no_guard_regardless_of_config(self, request_factory, patched_genai_client):
        """参照画像なし → variation_guard_enabled の値にかかわらず guard は付かない。"""
        # Given
        config = GeminiConfig(model="gemini-3.1-flash-image-preview", variation_guard_enabled=True)
        provider = GeminiImageProvider(config)
        req = request_factory(prompt="a calm ocean sunset", references=[])
        response = _fake_response([_fake_image_part(_png_bytes())])

        # When
        with patched_genai_client(response) as client:
            provider.generate(req)

        # Then: プロンプトがそのまま
        contents = client.models.generate_content.call_args.kwargs["contents"]
        assert contents == ["a calm ocean sunset"]


# ---------- リトライ・エラーハンドリング ----------


class TestSafetyViolationSkipsRetry:
    def test_safety_exception_returns_failure_without_retry(self, gemini_config, request_factory):
        # Given: SAFETY 文字列を含む例外
        provider = GeminiImageProvider(gemini_config)
        req = request_factory()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("SAFETY policy violation")

        with patch(
            "youtube_automation.utils.image_provider.gemini.create_genai_client",
            return_value=mock_client,
        ):
            # When
            result = provider.generate(req)

        # Then: 1 回呼ばれただけで終了（リトライしない）
        assert result.success is False
        assert mock_client.models.generate_content.call_count == 1

    def test_recitation_exception_returns_failure_without_retry(self, gemini_config, request_factory):
        # Given
        provider = GeminiImageProvider(gemini_config)
        req = request_factory()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("RECITATION blocked")

        with patch(
            "youtube_automation.utils.image_provider.gemini.create_genai_client",
            return_value=mock_client,
        ):
            # When
            result = provider.generate(req)

        # Then
        assert result.success is False
        assert mock_client.models.generate_content.call_count == 1


class TestTransientErrorRetries:
    def test_retries_until_success(self, gemini_config, request_factory):
        # Given: 1 回目は瞬発エラー、2 回目で成功
        provider = GeminiImageProvider(gemini_config)
        req = request_factory()
        success_response = _fake_response([_fake_image_part(_png_bytes())])
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            RuntimeError("transient timeout"),
            success_response,
        ]

        with patch(
            "youtube_automation.utils.image_provider.gemini.create_genai_client",
            return_value=mock_client,
        ):
            # When
            result = provider.generate(req)

        # Then
        assert result.success is True
        assert mock_client.models.generate_content.call_count == 2

    def test_returns_failure_when_all_retries_exhausted(self, gemini_config, request_factory):
        # Given: 全試行失敗
        provider = GeminiImageProvider(gemini_config)
        req = request_factory()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("permanent error")

        with patch(
            "youtube_automation.utils.image_provider.gemini.create_genai_client",
            return_value=mock_client,
        ):
            from youtube_automation.utils.image_provider import RETRY_MAX

            # When
            result = provider.generate(req)

        # Then: RETRY_MAX 回呼ばれ、最終失敗
        assert result.success is False
        assert mock_client.models.generate_content.call_count == RETRY_MAX


class TestImageWithoutInlineDataRetries:
    def test_text_only_response_triggers_retry(self, gemini_config, request_factory):
        # Given: 1 回目は画像なしテキスト、2 回目で画像あり
        provider = GeminiImageProvider(gemini_config)
        req = request_factory()
        text_only = _fake_response([_fake_text_part("blocked content explanation")])
        success = _fake_response([_fake_image_part(_png_bytes())])
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [text_only, success]

        with patch(
            "youtube_automation.utils.image_provider.gemini.create_genai_client",
            return_value=mock_client,
        ):
            # When
            result = provider.generate(req)

        # Then
        assert result.success is True
        assert mock_client.models.generate_content.call_count == 2


# ---------- 結果型 ----------


class TestImageGenerationResult:
    def test_success_result_contains_saved_path(self, gemini_config, request_factory, patched_genai_client, tmp_path):
        # Given
        provider = GeminiImageProvider(gemini_config)
        req = request_factory(output_name="result.png")
        response = _fake_response([_fake_image_part(_png_bytes())])

        # When
        with patched_genai_client(response):
            result = provider.generate(req)

        # Then
        assert result.success is True
        assert result.saved_path is not None
        assert result.saved_path.exists()
        # 出力ディレクトリは tmp_path 配下
        assert result.saved_path.is_relative_to(tmp_path)

    def test_failure_result_has_no_saved_path(self, gemini_config, request_factory):
        # Given
        provider = GeminiImageProvider(gemini_config)
        req = request_factory()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("SAFETY")

        with patch(
            "youtube_automation.utils.image_provider.gemini.create_genai_client",
            return_value=mock_client,
        ):
            # When
            result = provider.generate(req)

        # Then
        assert result.success is False
        assert result.saved_path is None
