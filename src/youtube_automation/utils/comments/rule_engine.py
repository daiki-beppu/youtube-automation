"""コメント本文に対するルールマッチングとテンプレート選択."""

from __future__ import annotations

import re
from dataclasses import dataclass

from youtube_automation.utils.config.comments import CommentRule


@dataclass(frozen=True)
class RuleMatch:
    """ルールマッチ結果."""

    rule: CommentRule
    generator_name: str
    template_language: str | None
    template_text: str | None


class RuleEngine:
    """`CommentRule` のリストから `RuleMatch` を導出する.

    - `ng_words` のいずれかが本文に含まれるコメントは即除外（None を返す）
    - `rules` は priority 降順・定義順で評価し、最初に match したものを採用
    - マッチしたルールに対応するテンプレートを `templates[language][template_key]` から解決
      - language 未指定時は `default_language` を使う
      - テンプレート未定義時は None（= マッチ失敗扱い）
    """

    def __init__(
        self,
        rules: list[CommentRule],
        templates: dict[str, dict[str, str]],
        *,
        default_language: str,
        ng_words: list[str] | None = None,
        default_generator_name: str,
    ):
        self._rules = sorted(enumerate(rules), key=lambda iv: (-iv[1].priority, iv[0]))
        self._templates = templates
        self._default_language = default_language
        self._ng_words = [w.lower() for w in (ng_words or []) if w]
        self._pattern_cache: dict[str, re.Pattern[str]] = {}
        self._default_generator_name = default_generator_name

    def _compiled(self, pattern: str) -> re.Pattern[str]:
        if pattern not in self._pattern_cache:
            self._pattern_cache[pattern] = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        return self._pattern_cache[pattern]

    def _rule_matches(self, rule: CommentRule, text: str, lowered: str) -> bool:
        for kw in rule.keywords:
            if kw and kw.lower() in lowered:
                return True
        if rule.pattern and self._compiled(rule.pattern).search(text):
            return True
        return False

    def _resolve_template(self, rule: CommentRule) -> tuple[str, str] | None:
        language = rule.language or self._default_language
        bucket = self._templates.get(language)
        if not bucket:
            return None
        template_text = bucket.get(rule.template_key)
        if template_text is None:
            return None
        return language, template_text

    def evaluate(self, text: str) -> RuleMatch | None:
        if not text:
            return None
        lowered = text.lower()
        if any(word in lowered for word in self._ng_words):
            return None
        for _, rule in self._rules:
            if not self._rule_matches(rule, text, lowered):
                continue
            generator_name = rule.generator or self._default_generator_name
            if generator_name != "template":
                resolved = self._resolve_template(rule)
                if resolved is None:
                    template_language = None
                    template_text = None
                else:
                    template_language, template_text = resolved
                return RuleMatch(
                    rule=rule,
                    generator_name=generator_name,
                    template_language=template_language,
                    template_text=template_text,
                )
            resolved = self._resolve_template(rule)
            if resolved is None:
                continue
            language, template_text = resolved
            return RuleMatch(
                rule=rule,
                generator_name="template",
                template_language=language,
                template_text=template_text,
            )
        return None
