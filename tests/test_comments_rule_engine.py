"""RuleEngine: キーワード / 正規表現 / NG ワード / テンプレート選択のテスト."""

from __future__ import annotations

from youtube_automation.utils.comments.rule_engine import RuleEngine
from youtube_automation.utils.config.comments import CommentRule


def _engine(rules, templates, ng_words=None, default_language="ja"):
    return RuleEngine(
        rules=rules,
        templates=templates,
        default_language=default_language,
        ng_words=ng_words,
    )


def test_keyword_match_returns_template():
    engine = _engine(
        rules=[CommentRule(name="greeting", keywords=["こんにちは"], template_key="greet", language="ja")],
        templates={"ja": {"greet": "どうも！"}},
    )
    match = engine.evaluate("こんにちは、素敵な動画ですね")
    assert match is not None
    assert match.rule.name == "greeting"
    assert match.template_text == "どうも！"
    assert match.template_language == "ja"


def test_regex_pattern_match():
    engine = _engine(
        rules=[CommentRule(name="thanks", pattern=r"thank\s*you|thanks", template_key="thx")],
        templates={"ja": {"thx": "ありがとうございます"}},
    )
    assert engine.evaluate("Thank you for this!") is not None
    assert engine.evaluate("Thanks a lot") is not None
    assert engine.evaluate("素敵") is None


def test_priority_order_picks_highest():
    rules = [
        CommentRule(name="low", keywords=["fun"], template_key="low", priority=1),
        CommentRule(name="high", keywords=["fun"], template_key="high", priority=10),
    ]
    engine = _engine(rules=rules, templates={"ja": {"low": "a", "high": "b"}})
    match = engine.evaluate("so fun!")
    assert match is not None
    assert match.rule.name == "high"


def test_ng_words_skip_comment():
    engine = _engine(
        rules=[CommentRule(name="greeting", keywords=["hello"], template_key="g")],
        templates={"ja": {"g": "hi"}},
        ng_words=["buy viagra"],
    )
    assert engine.evaluate("hello, buy viagra now") is None


def test_language_fallback_to_default():
    engine = _engine(
        rules=[CommentRule(name="greet", keywords=["hi"], template_key="g")],  # language 未指定
        templates={"en": {"g": "hi!"}},
        default_language="en",
    )
    match = engine.evaluate("hi!")
    assert match is not None
    assert match.template_language == "en"


def test_rule_skipped_when_template_missing():
    engine = _engine(
        rules=[
            CommentRule(name="first", keywords=["fun"], template_key="missing", language="ja", priority=10),
            CommentRule(name="second", keywords=["fun"], template_key="ok", language="ja", priority=1),
        ],
        templates={"ja": {"ok": "yes"}},
    )
    match = engine.evaluate("so fun!")
    assert match is not None
    # first はテンプレ未定義でスキップされ second が採用される
    assert match.rule.name == "second"


def test_empty_text_returns_none():
    engine = _engine(
        rules=[CommentRule(name="g", keywords=["x"], template_key="g")],
        templates={"ja": {"g": "x"}},
    )
    assert engine.evaluate("") is None


def test_case_insensitive_keyword():
    engine = _engine(
        rules=[CommentRule(name="g", keywords=["Hello"], template_key="g")],
        templates={"ja": {"g": "hi"}},
    )
    assert engine.evaluate("HELLO world") is not None
