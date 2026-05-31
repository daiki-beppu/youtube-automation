"""RuleEngine: キーワード / 正規表現 / NG ワード / provider 解決のテスト."""

from __future__ import annotations

from youtube_automation.utils.comments.rule_engine import RuleEngine
from youtube_automation.utils.config.comments import CommentRule


def _engine(rules, ng_words=None, default_language="ja", default_provider="codex"):
    return RuleEngine(
        rules=rules,
        default_language=default_language,
        ng_words=ng_words,
        default_provider=default_provider,
    )


def test_keyword_match_returns_provider_and_language():
    engine = _engine(
        rules=[CommentRule(name="greeting", keywords=["こんにちは"], language="ja")],
    )

    match = engine.evaluate("こんにちは、素敵な動画ですね")

    assert match is not None
    assert match.rule.name == "greeting"
    assert match.language == "ja"
    assert match.effective_provider == "codex"


def test_regex_pattern_match():
    engine = _engine(
        rules=[CommentRule(name="thanks", pattern=r"thank\s*you|thanks")],
    )

    assert engine.evaluate("Thank you for this!") is not None
    assert engine.evaluate("Thanks a lot") is not None
    assert engine.evaluate("素敵") is None


def test_priority_order_picks_highest():
    rules = [
        CommentRule(name="low", keywords=["fun"], priority=1),
        CommentRule(name="high", keywords=["fun"], priority=10),
    ]
    engine = _engine(rules=rules)

    match = engine.evaluate("so fun!")

    assert match is not None
    assert match.rule.name == "high"


def test_ng_words_skip_comment():
    engine = _engine(
        rules=[CommentRule(name="greeting", keywords=["hello"])],
        ng_words=["buy viagra"],
    )

    assert engine.evaluate("hello, buy viagra now") is None


def test_language_fallback_to_default():
    engine = _engine(
        rules=[CommentRule(name="greet", keywords=["hi"])],
        default_language="en",
    )

    match = engine.evaluate("hi!")

    assert match is not None
    assert match.language == "en"


def test_missing_template_no_longer_skips_matching_rule():
    engine = _engine(
        rules=[
            CommentRule(name="first", keywords=["fun"], language="ja", priority=10),
            CommentRule(name="second", keywords=["fun"], language="ja", priority=1),
        ],
    )

    match = engine.evaluate("so fun!")

    assert match is not None
    assert match.rule.name == "first"


def test_empty_text_returns_none():
    engine = _engine(rules=[CommentRule(name="g", keywords=["x"])])

    assert engine.evaluate("") is None


def test_case_insensitive_keyword():
    engine = _engine(rules=[CommentRule(name="g", keywords=["Hello"])])

    assert engine.evaluate("HELLO world") is not None


def test_rule_provider_overrides_global_provider():
    engine = _engine(
        rules=[CommentRule(name="gemini_rule", pattern=".+", provider="gemini")],
        default_provider="codex",
    )

    match = engine.evaluate("first!")

    assert match is not None
    assert match.rule.name == "gemini_rule"
    assert match.effective_provider == "gemini"


def test_default_provider_is_used_when_rule_has_no_override():
    engine = _engine(
        rules=[CommentRule(name="catch_all", pattern=".+")],
        default_provider="gemini",
    )

    match = engine.evaluate("some comment")

    assert match is not None
    assert match.rule.name == "catch_all"
    assert match.effective_provider == "gemini"


# ---------------------------------------------------------------------------
# scope: top_level / reply / any (#524)
# ---------------------------------------------------------------------------


def test_scope_default_is_any_and_matches_both():
    """scope 未指定はデフォルト 'any'。top-level / reply の両方に当たる（後方互換）。"""
    engine = _engine(rules=[CommentRule(name="g", keywords=["hi"])])

    assert engine.evaluate("hi there", is_reply=False) is not None
    assert engine.evaluate("hi there", is_reply=True) is not None


def test_scope_top_level_only_matches_top_level():
    engine = _engine(rules=[CommentRule(name="g", keywords=["hi"], scope="top_level")])

    assert engine.evaluate("hi there", is_reply=False) is not None
    assert engine.evaluate("hi there", is_reply=True) is None


def test_scope_reply_only_matches_reply():
    engine = _engine(rules=[CommentRule(name="g", keywords=["hi"], scope="reply")])

    assert engine.evaluate("hi there", is_reply=True) is not None
    assert engine.evaluate("hi there", is_reply=False) is None


def test_scope_falls_through_to_next_matching_rule():
    """scope 不一致のルールはスキップし、後続の当たるルールが採用される。"""
    rules = [
        CommentRule(name="reply_only", keywords=["hi"], scope="reply", priority=10),
        CommentRule(name="any_rule", keywords=["hi"], scope="any", priority=1),
    ]
    engine = _engine(rules=rules)

    # top-level コメントでは reply_only はスキップされ any_rule が採用される
    match = engine.evaluate("hi there", is_reply=False)
    assert match is not None
    assert match.rule.name == "any_rule"

    # reply では priority 最上位の reply_only が採用される
    match = engine.evaluate("hi there", is_reply=True)
    assert match is not None
    assert match.rule.name == "reply_only"


def test_evaluate_is_reply_defaults_to_false():
    """is_reply を省略すると top-level 扱い（既存呼び出しとの後方互換）。"""
    engine = _engine(rules=[CommentRule(name="g", keywords=["hi"], scope="top_level")])

    assert engine.evaluate("hi there") is not None
