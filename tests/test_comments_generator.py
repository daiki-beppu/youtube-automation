"""TemplateGenerator / GeminiGenerator の単体テスト."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.comments.generator import (
    GeminiGenerator,
    ReplyContext,
    TemplateGenerator,
)
from youtube_automation.utils.exceptions import GeneratorError, ValidationError

# create_genai_client はソースモジュールで patch する
_PATCH_GENAI_CLIENT = "youtube_automation.utils.genai_client.create_genai_client"


def _make_ctx(**overrides) -> ReplyContext:
    defaults = dict(
        video_id="v1",
        video_title="Rainy Night Jazz",
        comment_id="c1",
        comment_text="love this",
        comment_author="Alice",
        language="en",
        channel_persona="Warm lo-fi jazz host",
        max_length=280,
        parent_thread=None,
        dry_run=False,
    )
    defaults.update(overrides)
    return ReplyContext(**defaults)


def _make_mock_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    return resp


def _make_mock_client(response_text: str = "Reply") -> MagicMock:
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response(response_text)
    return mock_client


# ─── TemplateGenerator ──────────────────────────────────────────────────────


class TestTemplateGenerator:
    def test_renders_placeholders(self):
        gen = TemplateGenerator("Hi {comment_author}, thanks for watching {video_title}!")
        ctx = _make_ctx(comment_author="Bob", video_title="Jazz Night")
        result = gen.generate(ctx)
        assert result == "Hi Bob, thanks for watching Jazz Night!"

    def test_renders_video_id_placeholder(self):
        gen = TemplateGenerator("Video: {video_id}")
        ctx = _make_ctx(video_id="abc123")
        assert gen.generate(ctx) == "Video: abc123"

    def test_renders_comment_text_placeholder(self):
        gen = TemplateGenerator("You said: {comment_text}")
        ctx = _make_ctx(comment_text="nice vibes")
        assert gen.generate(ctx) == "You said: nice vibes"

    def test_undefined_placeholder_raises(self):
        gen = TemplateGenerator("Hello {unknown_key}!")
        with pytest.raises(ValidationError):
            gen.generate(_make_ctx())


# ─── GeminiGenerator ────────────────────────────────────────────────────────


class TestGeminiGenerator:
    def _make_gen(self, *, max_length: int = 280, requests_per_minute: int = 60, sleep_fn=None):
        return GeminiGenerator(
            model="gemini-2.5-flash",
            max_length=max_length,
            requests_per_minute=requests_per_minute,
            sleep_fn=sleep_fn or (lambda _: None),
        )

    def test_returns_generated_text(self):
        gen = self._make_gen()
        ctx = _make_ctx()

        with patch(_PATCH_GENAI_CLIENT, return_value=_make_mock_client("  Thanks for listening!  ")):
            result = gen.generate(ctx)

        assert result == "Thanks for listening!"

    def test_truncates_when_exceeds_max_length(self):
        gen = self._make_gen(max_length=10)
        ctx = _make_ctx()

        with patch(
            _PATCH_GENAI_CLIENT,
            return_value=_make_mock_client("This is a very long reply that exceeds max_length"),
        ):
            result = gen.generate(ctx)

        assert len(result) == 10
        assert result == "This is a "

    def test_does_not_truncate_when_within_max_length(self):
        gen = self._make_gen(max_length=100)
        ctx = _make_ctx()

        with patch(_PATCH_GENAI_CLIENT, return_value=_make_mock_client("Short reply")):
            result = gen.generate(ctx)

        assert result == "Short reply"

    def test_prompt_includes_persona_and_comment(self):
        gen = self._make_gen()
        ctx = _make_ctx(
            comment_text="so relaxing",
            comment_author="Bob",
            video_title="Midnight Jazz",
            channel_persona="Cozy lo-fi jazz host",
        )
        mock_client = _make_mock_client("Nice!")

        with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
            gen.generate(ctx)

        call_kwargs = mock_client.models.generate_content.call_args
        prompt = call_kwargs.kwargs["contents"][0]
        assert "Cozy lo-fi jazz host" in prompt
        assert "Bob" in prompt
        assert "so relaxing" in prompt
        assert "Midnight Jazz" in prompt

    def test_prompt_uses_ctx_channel_persona_not_constructor(self):
        """ctx.channel_persona がプロンプトに使われること（dead-data 再発防止）.

        GeminiGenerator のコンストラクタに channel_persona を持たせず、
        ctx に異なる persona を設定してもプロンプトに ctx 側の値が反映される。
        """
        gen = self._make_gen()
        ctx = _make_ctx(channel_persona="Unique persona for regression XYZ-123")
        mock_client = _make_mock_client("Reply")

        with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
            gen.generate(ctx)

        prompt = mock_client.models.generate_content.call_args.kwargs["contents"][0]
        assert "Unique persona for regression XYZ-123" in prompt

    def test_dry_run_logs_prompt_and_reply(self, caplog):
        import logging

        gen = self._make_gen()
        ctx = _make_ctx(dry_run=True)

        with patch(_PATCH_GENAI_CLIENT, return_value=_make_mock_client("Test reply")):
            with caplog.at_level(logging.INFO, logger="youtube_automation.utils.comments.generator"):
                result = gen.generate(ctx)

        assert result == "Test reply"
        log_messages = " ".join(caplog.messages)
        assert "[dry-run]" in log_messages
        assert "Gemini prompt" in log_messages
        assert "Gemini reply" in log_messages

    def test_rate_limit_sleeps_between_calls(self):
        sleep_calls: list[float] = []
        gen = GeminiGenerator(
            model="gemini-2.5-flash",
            max_length=280,
            requests_per_minute=60,  # 1秒間隔
            sleep_fn=sleep_calls.append,
        )
        ctx = _make_ctx()

        with (
            patch(_PATCH_GENAI_CLIENT, return_value=_make_mock_client()),
            patch("youtube_automation.utils.comments.generator.time.monotonic") as mock_monotonic,
        ):
            # 1回目: last_call_at が None なので sleep しない
            mock_monotonic.return_value = 0.0
            gen.generate(ctx)
            assert sleep_calls == []

            # 2回目: 0.3秒後の呼び出し → 0.7秒 sleep すべき
            mock_monotonic.return_value = 0.3
            gen.generate(ctx)
            assert len(sleep_calls) == 1
            assert abs(sleep_calls[0] - 0.7) < 0.01

    def test_no_rate_limit_when_requests_per_minute_zero(self):
        sleep_calls: list[float] = []
        gen = GeminiGenerator(
            model="gemini-2.5-flash",
            max_length=280,
            requests_per_minute=0,
            sleep_fn=sleep_calls.append,
        )
        ctx = _make_ctx()

        with patch(_PATCH_GENAI_CLIENT, return_value=_make_mock_client()):
            gen.generate(ctx)
            gen.generate(ctx)

        assert sleep_calls == []

    def test_api_exception_wrapped_as_generator_error(self):
        """外部 SDK の例外は GeneratorError に昇格される（境界変換）."""
        gen = self._make_gen()
        ctx = _make_ctx()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("API error")

        with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
            with pytest.raises(GeneratorError):
                gen.generate(ctx)

    def test_prompt_includes_language_hint_when_language_set(self):
        """ctx.language が指定されている場合、プロンプトに言語ヒントが含まれる."""
        gen = self._make_gen()
        ctx = _make_ctx(language="ja")
        mock_client = _make_mock_client("Nice!")

        with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
            gen.generate(ctx)

        prompt = mock_client.models.generate_content.call_args.kwargs["contents"][0]
        assert "ja" in prompt
        # language=None 時のフォールバック文言は使われない
        assert "Reply in the same language" not in prompt

    def test_prompt_uses_free_detection_when_language_is_none(self):
        """ctx.language が None のとき、LLM 自律推定フォールバック文言がプロンプトに含まれる."""
        gen = self._make_gen()
        ctx = _make_ctx(language=None)
        mock_client = _make_mock_client("Nice!")

        with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
            gen.generate(ctx)

        prompt = mock_client.models.generate_content.call_args.kwargs["contents"][0]
        assert "Reply in the same language" in prompt
