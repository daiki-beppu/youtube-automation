"""テンプレート文字列のプレースホルダ展開テスト."""

from __future__ import annotations

import pytest

from youtube_automation.utils.comments.template import render_template
from youtube_automation.utils.exceptions import ValidationError


def test_basic_placeholder_substitution():
    rendered = render_template(
        "{comment_author}さん、『{video_title}』をご覧いただきありがとうございます！",
        {"comment_author": "Alice", "video_title": "Study BGM"},
    )
    assert rendered == "Aliceさん、『Study BGM』をご覧いただきありがとうございます！"


def test_undefined_placeholder_raises():
    with pytest.raises(ValidationError, match="未定義のプレースホルダ"):
        render_template("hello {unknown}", {})


def test_malformed_template_raises():
    with pytest.raises(ValidationError):
        render_template("hello {", {})


def test_empty_context_ok_when_no_placeholder():
    assert render_template("static text", {}) == "static text"


def test_extra_context_keys_are_ignored():
    assert render_template("hi {name}", {"name": "Bob", "extra": "ignored"}) == "hi Bob"
