"""コメント本文に対するルールマッチングと provider 解決."""

from __future__ import annotations

import re
from dataclasses import dataclass

from youtube_automation.utils.config.comments import (
    PROVIDER_CODEX,
    SCOPE_REPLY,
    SCOPE_TOP_LEVEL,
    CommentRule,
)


@dataclass(frozen=True)
class RuleMatch:
    """ルールマッチ結果.

    effective_provider は rule.provider または global default を解決した確定値。
    """

    rule: CommentRule
    language: str
    effective_provider: str


class RuleEngine:
    """`CommentRule` のリストから `RuleMatch` を導出する.

    - `ng_words` のいずれかが本文に含まれるコメントは即除外（None を返す）
    - `rules` は priority 降順・定義順で評価し、最初に match したものを採用
    - provider は rule.provider があれば優先し、なければ default_provider を使う
    """

    def __init__(
        self,
        rules: list[CommentRule],
        *,
        default_language: str,
        ng_words: list[str] | None = None,
        default_provider: str = PROVIDER_CODEX,
    ):
        self._rules = sorted(enumerate(rules), key=lambda iv: (-iv[1].priority, iv[0]))
        self._default_language = default_language
        self._ng_words = [w.lower() for w in (ng_words or []) if w]
        self._default_provider = default_provider
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

    def _scope_matches(self, rule: CommentRule, is_reply: bool) -> bool:
        """rule.scope とコメント階層（top-level / reply）の突合 (#524)。

        `top_level` は top-level のみ、`reply` は reply のみ、`any` は両方に当たる。
        """
        if rule.scope == SCOPE_TOP_LEVEL:
            return not is_reply
        if rule.scope == SCOPE_REPLY:
            return is_reply
        return True  # SCOPE_ANY（後方互換のデフォルト）

    def _effective_provider(self, rule: CommentRule) -> str:
        return rule.provider or self._default_provider

    def evaluate(self, text: str, *, is_reply: bool = False) -> RuleMatch | None:
        """本文 `text` にマッチする最優先ルールを返す。

        Args:
            text: コメント本文
            is_reply: reply コメントなら True、top-level なら False。
                `FetchedComment.parent_id is not None` を渡す想定 (#524)
        """
        if not text:
            return None
        lowered = text.lower()
        if any(word in lowered for word in self._ng_words):
            return None
        for _, rule in self._rules:
            if not self._scope_matches(rule, is_reply):
                continue
            if not self._rule_matches(rule, text, lowered):
                continue
            return RuleMatch(
                rule=rule,
                language=rule.language or self._default_language,
                effective_provider=self._effective_provider(rule),
            )
        return None
