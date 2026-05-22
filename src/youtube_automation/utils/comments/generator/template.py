"""既存テンプレート返信を wrap する generator."""

from __future__ import annotations

from youtube_automation.utils.comments.generator.base import GeneratedReply, ReplyContext
from youtube_automation.utils.comments.template import render_template
from youtube_automation.utils.exceptions import ValidationError


class TemplateGenerator:
    """`render_template` を generator 契約へ合わせる薄い adapter."""

    def generate(self, ctx: ReplyContext) -> GeneratedReply:
        if ctx.template_text is None:
            raise ValidationError("template generator requires template_text")
        return GeneratedReply(
            text=render_template(
                ctx.template_text,
                context={
                    "video_title": ctx.video_title,
                    "video_id": ctx.video_id,
                    "comment_author": ctx.comment_author,
                    "comment_text": ctx.comment_text,
                },
            ),
            prompt=None,
        )
