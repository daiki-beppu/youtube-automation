"""OpenAIImageProvider の単体テスト（gpt-image-2 用）。

`openai.OpenAI` クライアントをモックして以下を検証する:

1. `aspect_ratio` → OpenAI Images API の `size` 文字列マッピング
   - "16:9" → "1536x1024"
   - "9:16" → "1024x1536"
2. `model` / `quality` / `batch (n)` パラメータが API へ転送される
3. API キーは `secrets.get_secret("OPENAI_API_KEY")` 経由で取得される
4. 参照画像なし → `images.generate` エンドポイント
5. 参照画像あり → `images.edit` エンドポイント
6. 失敗時はリトライ、成功で True、全失敗で False
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.image_provider.base import ImageGenerationRequest
from youtube_automation.utils.image_provider.config import OpenAIConfig
from youtube_automation.utils.image_provider.openai import OpenAIImageProvider

# ---------- フィクスチャ ----------


def _png_bytes() -> bytes:
    """16x16 のダミー PNG バイナリ。"""
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (16, 16), color=(255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _fake_image_response(payload: bytes) -> MagicMock:
    """OpenAI Images API のスタブレスポンス。`data[0].b64_json` を持つ。"""
    item = MagicMock()
    item.b64_json = base64.b64encode(payload).decode("ascii")
    response = MagicMock()
    response.data = [item]
    return response


@pytest.fixture
def openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        model="gpt-image-2",
        quality="high",
        aspect_ratio="16:9",
        thinking="medium",
        batch=1,
    )


@pytest.fixture
def request_factory(tmp_path: Path):
    def _make(
        *,
        prompt: str = "a vivid sunset over the ocean",
        references: list[Path] | None = None,
        aspect_ratio: str = "16:9",
        image_size: str = "1536x1024",
        output_name: str = "out.jpg",
    ) -> ImageGenerationRequest:
        return ImageGenerationRequest(
            prompt=prompt,
            output_path=tmp_path / output_name,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            references=list(references or []),
        )

    return _make


@pytest.fixture(autouse=True)
def _stub_openai_api_key(monkeypatch):
    """secrets.get_secret("OPENAI_API_KEY") をスタブ。"""

    def _fake_get_secret(name: str) -> str:
        if name == "OPENAI_API_KEY":
            return "sk-test-fake-12345"
        raise KeyError(name)

    monkeypatch.setattr(
        "youtube_automation.utils.image_provider.openai.get_secret",
        _fake_get_secret,
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """リトライバックオフを高速化。"""
    monkeypatch.setattr(
        "youtube_automation.utils.image_provider.openai.time.sleep",
        lambda s: None,
    )


# ---------- aspect_ratio → size マッピング ----------


class TestAspectRatioToSizeMapping:
    @pytest.mark.parametrize(
        "ratio,expected_size",
        [
            ("16:9", "1536x1024"),
            ("9:16", "1024x1536"),
        ],
    )
    def test_aspect_ratio_maps_to_openai_size_string(self, request_factory, ratio: str, expected_size: str):
        # Given
        cfg = OpenAIConfig(
            model="gpt-image-2",
            quality="high",
            aspect_ratio=ratio,
            thinking="medium",
            batch=1,
        )
        provider = OpenAIImageProvider(cfg)
        req = request_factory(aspect_ratio=ratio, image_size=expected_size)

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.return_value = _fake_image_response(_png_bytes())
            mock_class.return_value = mock_client

            # When
            result = provider.generate(req)

        # Then
        assert result.success is True
        kwargs = mock_client.images.generate.call_args.kwargs
        assert kwargs["size"] == expected_size


# ---------- パラメータ転送 ----------


class TestParameterForwarding:
    def test_forwards_model_quality_and_batch(self, openai_config, request_factory):
        # Given
        provider = OpenAIImageProvider(openai_config)
        req = request_factory()

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.return_value = _fake_image_response(_png_bytes())
            mock_class.return_value = mock_client

            # When
            provider.generate(req)

        # Then
        kwargs = mock_client.images.generate.call_args.kwargs
        assert kwargs["model"] == "gpt-image-2"
        assert kwargs["quality"] == "high"
        assert kwargs["n"] == 1

    def test_batch_value_is_forwarded_as_n(self, request_factory):
        # Given: batch=4
        cfg = OpenAIConfig(
            model="gpt-image-2",
            quality="high",
            aspect_ratio="16:9",
            thinking="medium",
            batch=4,
        )
        provider = OpenAIImageProvider(cfg)
        # batch=4 でも 1 件分のレスポンスでテスト（複数取得は別 issue）
        req = request_factory()

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.return_value = _fake_image_response(_png_bytes())
            mock_class.return_value = mock_client

            # When
            provider.generate(req)

        # Then
        kwargs = mock_client.images.generate.call_args.kwargs
        assert kwargs["n"] == 4

    def test_prompt_is_forwarded_verbatim(self, openai_config, request_factory):
        # Given
        provider = OpenAIImageProvider(openai_config)
        req = request_factory(prompt="a vivid sunset over the ocean")

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.return_value = _fake_image_response(_png_bytes())
            mock_class.return_value = mock_client

            # When
            provider.generate(req)

        # Then
        kwargs = mock_client.images.generate.call_args.kwargs
        assert kwargs["prompt"] == "a vivid sunset over the ocean"


# ---------- API キー取得 ----------


class TestApiKeyAcquisition:
    def test_obtains_api_key_via_secrets_get_secret(self, openai_config, request_factory, monkeypatch):
        # Given: get_secret 呼び出しを記録
        calls: list[str] = []

        def _tracking(name: str) -> str:
            calls.append(name)
            return "sk-tracked-7890"

        monkeypatch.setattr(
            "youtube_automation.utils.image_provider.openai.get_secret",
            _tracking,
        )
        provider = OpenAIImageProvider(openai_config)
        req = request_factory()

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.return_value = _fake_image_response(_png_bytes())
            mock_class.return_value = mock_client

            # When
            provider.generate(req)

        # Then: OPENAI_API_KEY を要求し、その値で OpenAI クライアントを構築
        assert "OPENAI_API_KEY" in calls
        ctor_kwargs = mock_class.call_args.kwargs
        assert ctor_kwargs.get("api_key") == "sk-tracked-7890"


# ---------- エンドポイント分岐（参照画像の有無） ----------


class TestReferenceImageRouting:
    def test_no_reference_uses_images_generate(self, openai_config, request_factory):
        # Given
        provider = OpenAIImageProvider(openai_config)
        req = request_factory(references=[])

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.return_value = _fake_image_response(_png_bytes())
            mock_class.return_value = mock_client

            # When
            provider.generate(req)

        # Then
        mock_client.images.generate.assert_called_once()
        mock_client.images.edit.assert_not_called()

    def test_reference_image_uses_images_edit(self, tmp_path, openai_config, request_factory):
        # Given
        ref_path = tmp_path / "ref.png"
        ref_path.write_bytes(_png_bytes())
        provider = OpenAIImageProvider(openai_config)
        req = request_factory(references=[ref_path])

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.edit.return_value = _fake_image_response(_png_bytes())
            mock_class.return_value = mock_client

            # When
            provider.generate(req)

        # Then
        mock_client.images.edit.assert_called_once()
        mock_client.images.generate.assert_not_called()


# ---------- リトライ ----------


class TestRetryBehavior:
    def test_transient_failure_then_success(self, openai_config, request_factory):
        # Given: 1 回目は瞬発エラー、2 回目で成功
        provider = OpenAIImageProvider(openai_config)
        req = request_factory()

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.side_effect = [
                RuntimeError("transient 500"),
                _fake_image_response(_png_bytes()),
            ]
            mock_class.return_value = mock_client

            # When
            result = provider.generate(req)

        # Then
        assert result.success is True
        assert mock_client.images.generate.call_count == 2

    def test_all_retries_exhausted_returns_failure(self, openai_config, request_factory):
        # Given
        provider = OpenAIImageProvider(openai_config)
        req = request_factory()

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.side_effect = RuntimeError("permanent error")
            mock_class.return_value = mock_client

            from youtube_automation.utils.image_provider import RETRY_MAX

            # When
            result = provider.generate(req)

        # Then
        assert result.success is False
        assert mock_client.images.generate.call_count == RETRY_MAX


# ---------- 出力 ----------


class TestImageOutputPersistence:
    def test_saves_decoded_image_to_output_path(self, openai_config, request_factory, tmp_path):
        # Given
        provider = OpenAIImageProvider(openai_config)
        req = request_factory(output_name="generated.jpg")

        with patch("youtube_automation.utils.image_provider.openai.OpenAI") as mock_class:
            mock_client = MagicMock()
            mock_client.images.generate.return_value = _fake_image_response(_png_bytes())
            mock_class.return_value = mock_client

            # When
            result = provider.generate(req)

        # Then: 保存パスが存在し、サイズが 0 でない
        assert result.success is True
        assert result.saved_path is not None
        assert result.saved_path.exists()
        assert result.saved_path.stat().st_size > 0
        assert result.saved_path.is_relative_to(tmp_path)


# ---------- aspect_ratio バリデーションが Provider にも届く ----------


class TestProviderRejectsUnsupportedAspectRatio:
    """OpenAIConfig 構築時のバリデーションを通っていない不正値を Request に
    詰めた場合でも、Provider 側が防御する（Defense in depth ではなく、
    呼び出し元と境界の双方で同じ ConfigError を返す統一）。
    """

    def test_unsupported_request_aspect_ratio_raises_config_error(self, openai_config, request_factory):
        # Given: Request の aspect_ratio が "1:1"
        from youtube_automation.infrastructure.errors import ConfigError

        provider = OpenAIImageProvider(openai_config)
        req = request_factory(aspect_ratio="1:1", image_size="1024x1024")

        # When / Then
        with pytest.raises(ConfigError, match="aspect_ratio"):
            provider.generate(req)
