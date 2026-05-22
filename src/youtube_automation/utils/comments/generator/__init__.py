"""コメント返信 generator の factory."""

from __future__ import annotations

from youtube_automation.utils.comments.generator.base import ReplyGenerator
from youtube_automation.utils.comments.generator.gemini import GeminiGenerator
from youtube_automation.utils.comments.generator.template import TemplateGenerator
from youtube_automation.utils.config.comments import Comments


def build_generators(config: Comments) -> dict[str, ReplyGenerator]:
    generators: dict[str, ReplyGenerator] = {
        "template": TemplateGenerator(),
    }
    needs_gemini = config.generator.type == "gemini" or any(rule.generator == "gemini" for rule in config.rules)
    if needs_gemini:
        generators["gemini"] = GeminiGenerator(
            model=config.generator.model,
            min_interval_sec=config.generator.min_interval_sec,
        )
    return generators
