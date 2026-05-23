"""コメント本文に対するルールマッチングとテンプレート選択."""

from __future__ import annotations

import re
from dataclasses import dataclass

from youtube_automation.utils.config.comments import GENERATOR_TYPE_TEMPLATE, CommentRule


@dataclass(frozen=True)
class RuleMatch:
    """ルールマッチ結果.

    template_language / template_text は type="template" のルールでのみ設定される。
    AI ジェネレーター使用時は None だが、fallback_on_error="template" 設定があれば
    テンプレートが解決可能な場合に限り設定される。
    effective_generator_type は rule.generator または global default を解決した確定値。
    """

    rule: CommentRule
    template_language: str | None
    template_text: str | None
    effective_generator_type: str


class RuleEngine:
    """`CommentRule` のリストから `RuleMatch` を導出する.

    - `ng_words` のいずれかが本文に含まれるコメントは即除外（None を返す）
    - `rules` は priority 降順・定義順で評価し、最初に match したものを採用
    - `default_generator_type` が "template" のルールはテンプレート必須（未定義時はスキップ）
    - AI ジェネレータータイプのルールはテンプレート不要（あれば fallback 用に保持）
    """

    def __init__(
        self,
        rules: list[CommentRule],
        templates: dict[str, dict[str, str]],
        *,
        default_language: str,
        ng_words: list[str] | None = None,
        default_generator_type: str = GENERATOR_TYPE_TEMPLATE,
    ):
        self._rules = sorted(enumerate(rules), key=lambda iv: (-iv[1].priority, iv[0]))
        self._templates = templates
        self._default_language = default_language
        self._ng_words = [w.lower() for w in (ng_words or []) if w]
        self._default_generator_type = default_generator_type
        self._pattern_cache: dict[str, re.Pattern[str]] = {}

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

    def _effective_generator(self, rule: CommentRule) -> str:
        return rule.generator or self._default_generator_type

    def evaluate(self, text: str) -> RuleMatch | None:
        if not text:
            return None
        lowered = text.lower()
        if any(word in lowered for word in self._ng_words):
            return None
        for _, rule in self._rules:
            if not self._rule_matches(rule, text, lowered):
                continue
            effective = self._effective_generator(rule)
            if effective == GENERATOR_TYPE_TEMPLATE:
                # テンプレート必須。未解決なら次のルールへ
                resolved = self._resolve_template(rule)
                if resolved is None:
                    continue
                language, template_text = resolved
            else:
                # AI ジェネレーター。テンプレートは fallback 用に解決を試みるが必須ではない
                language, template_text = self._resolve_template(rule) or (None, None)
            return RuleMatch(
                rule=rule,
                template_language=language,
                template_text=template_text,
                effective_generator_type=effective,
            )
        return None
