"""端末向け文字列の可視化と、呼び出し側ごとの長さ制限。"""

import pytest

from youtube_automation.application.channel_readiness.checks import _format_external_display_value
from youtube_automation.core.display import format_terminal_text
from youtube_automation.domains.suno.playlist import format_display_text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("灯り café 🎵", "灯り café 🎵"),
        ("a\n\r\tb", "a\\n\\r\\tb"),
        ("\x1b[31m\x00", "\\x1b[31m\\x00"),
        ("\u202e\u200b", "\\u202e\\u200b"),
    ],
)
def test_control_characters_are_visible_without_escaping_printable_unicode(value: str, expected: str) -> None:
    assert format_terminal_text(value, max_length=200) == expected


@pytest.mark.parametrize("max_length", [3, 120, 200])
def test_truncation_happens_after_escaping(max_length: int) -> None:
    value = "\n" * max_length
    assert format_terminal_text(value, max_length=max_length) == ("\\n" * max_length)[: max_length - 3] + "..."


def test_callers_preserve_their_distinct_limits_and_object_conversion() -> None:
    assert _format_external_display_value(123) == "123"
    assert _format_external_display_value("x" * 121) == "x" * 117 + "..."
    assert format_display_text("x" * 200) == "x" * 200
    assert format_display_text("x" * 201) == "x" * 197 + "..."
