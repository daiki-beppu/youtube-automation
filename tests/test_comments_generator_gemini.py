"""GeminiGenerator の単体テスト."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from youtube_automation.utils.comments.generator.base import ReplyContext
from youtube_automation.utils.comments.generator.gemini import GeminiGenerator


def _reply_context(*, max_length: int = 280) -> ReplyContext:
    return ReplyContext(
        video_id="v1",
        video_title="Night Rain Jazz",
        comment_id="c1",
        comment_text="first!",
        comment_author="Alice",
        language=None,
        channel_persona="Rain Jazz Night host",
        max_length=max_length,
        parent_thread=None,
    )


def test_generate_returns_text_and_prompt(monkeypatch):
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(text="Warm reply from Gemini")
    monkeypatch.setattr(
        "youtube_automation.utils.comments.generator.gemini.create_genai_client",
        lambda location=None: mock_client,
    )

    generator = GeminiGenerator(model="gemini-2.5-flash", min_interval_sec=0.0)

    reply = generator.generate(_reply_context())

    assert reply.text == "Warm reply from Gemini"
    assert "Rain Jazz Night host" in reply.prompt
    assert "Night Rain Jazz" in reply.prompt
    assert "first!" in reply.prompt
    kwargs = mock_client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash"


def test_generate_retries_after_transient_error(monkeypatch):
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        RuntimeError("temporary timeout"),
        SimpleNamespace(text="Recovered reply"),
    ]
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "youtube_automation.utils.comments.generator.gemini.create_genai_client",
        lambda location=None: mock_client,
    )
    monkeypatch.setattr(
        "youtube_automation.utils.comments.generator.gemini.time.sleep",
        sleep_calls.append,
    )

    generator = GeminiGenerator(model="gemini-2.5-flash", min_interval_sec=0.0)

    reply = generator.generate(_reply_context())

    assert reply.text == "Recovered reply"
    assert mock_client.models.generate_content.call_count == 2
    assert sleep_calls


def test_generate_truncates_to_max_length_and_warns(monkeypatch, caplog):
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(text="ABCDEFGHIJKLMN")
    monkeypatch.setattr(
        "youtube_automation.utils.comments.generator.gemini.create_genai_client",
        lambda location=None: mock_client,
    )

    generator = GeminiGenerator(model="gemini-2.5-flash", min_interval_sec=0.0)

    with caplog.at_level("WARNING"):
        reply = generator.generate(_reply_context(max_length=10))

    assert reply.text == "ABCDEFGHIJ"
    assert any("max_length" in record.message for record in caplog.records)
