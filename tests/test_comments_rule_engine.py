"""RuleEngine: キーワード / 正規表現 / NG ワード / テンプレート選択のテスト."""

from __future__ import annotations

from youtube_automation.utils.comments.rule_engine import RuleEngine
from youtube_automation.utils.config.comments import GENERATOR_TYPE_GEMINI, CommentRule


def _engine(rules, templates, ng_words=None, default_language="ja", default_generator_type="template"):
    return RuleEngine(
        rules=rules,
        templates=templates,
        default_language=default_language,
        ng_words=ng_words,
        default_generator_type=default_generator_type,
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
    assert match.effective_generator_type == "template"


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


# ─── AI ジェネレーター関連 ────────────────────────────────────────────────────


def test_ai_rule_matches_without_template():
    """generator="gemini" のルールはテンプレート未定義でもマッチする."""
    engine = _engine(
        rules=[CommentRule(name="ai_catch_all", pattern=".+", generator=GENERATOR_TYPE_GEMINI)],
        templates={},  # テンプレートなし
    )
    match = engine.evaluate("first!")
    assert match is not None
    assert match.rule.name == "ai_catch_all"
    assert match.template_text is None
    assert match.template_language is None
    assert match.effective_generator_type == GENERATOR_TYPE_GEMINI


def test_ai_rule_holds_template_for_fallback():
    """generator="gemini" かつテンプレートが存在する場合、fallback 用に保持する."""
    engine = _engine(
        rules=[
            CommentRule(
                name="ai_with_fallback",
                keywords=["nice"],
                generator=GENERATOR_TYPE_GEMINI,
                template_key="greet",
                language="ja",
            )
        ],
        templates={"ja": {"greet": "ありがとう！"}},
    )
    match = engine.evaluate("nice video")
    assert match is not None
    assert match.template_text == "ありがとう！"
    assert match.template_language == "ja"


def test_default_generator_type_gemini_matches_without_template():
    """global で gemini を設定した場合、テンプレート未定義ルールもマッチする."""
    engine = _engine(
        rules=[CommentRule(name="catch_all", pattern=".+")],
        templates={},
        default_generator_type=GENERATOR_TYPE_GEMINI,
    )
    match = engine.evaluate("some comment")
    assert match is not None
    assert match.rule.name == "catch_all"
    assert match.template_text is None
    assert match.effective_generator_type == GENERATOR_TYPE_GEMINI


def test_rule_generator_overrides_global_gemini_to_template():
    """global=gemini でも rule.generator='template' ならテンプレート必須."""
    engine = _engine(
        rules=[
            CommentRule(
                name="force_template",
                keywords=["hello"],
                generator="template",
                template_key="greet",
                language="ja",
            )
        ],
        templates={"ja": {"greet": "こんにちは！"}},
        default_generator_type=GENERATOR_TYPE_GEMINI,
    )
    match = engine.evaluate("hello there")
    assert match is not None
    assert match.template_text == "こんにちは！"


def test_rule_generator_template_skips_when_no_template():
    """rule.generator='template' でテンプレート未定義なら次のルールへ."""
    engine = _engine(
        rules=[
            CommentRule(name="no_tmpl", keywords=["hi"], generator="template", template_key="missing"),
            CommentRule(name="fallback", keywords=["hi"], generator=GENERATOR_TYPE_GEMINI),
        ],
        templates={},
        default_generator_type=GENERATOR_TYPE_GEMINI,
    )
    match = engine.evaluate("hi!")
    assert match is not None
    assert match.rule.name == "fallback"
