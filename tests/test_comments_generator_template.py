"""TemplateGenerator の単体テスト."""

from __future__ import annotations

from youtube_automation.utils.comments.generator.base import GeneratedReply, ReplyContext
from youtube_automation.utils.comments.generator.template import TemplateGenerator


def test_template_generator_renders_context_fields_from_template_text():
    generator = TemplateGenerator()
    ctx = ReplyContext(
        video_id="v1",
        video_title="Night Rain Jazz",
        comment_id="c1",
        comment_text="first!",
        comment_author="Alice",
        language="ja",
        channel_persona="Rain Jazz Night host",
        max_length=280,
        parent_thread=None,
        template_text="{comment_author}さん、{video_title} へようこそ。『{comment_text}』ありがとう！",
    )

    reply = generator.generate(ctx)

    assert reply == GeneratedReply(
        text="Aliceさん、Night Rain Jazz へようこそ。『first!』ありがとう！",
        prompt=None,
    )
