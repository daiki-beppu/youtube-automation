"""テンプレート文字列のプレースホルダ展開."""

from __future__ import annotations

from youtube_automation.utils.exceptions import ValidationError


class _SafeDict(dict):
    """`str.format_map` で未定義キーを例外に変換するための sentinel 用 dict."""

    def __missing__(self, key):  # type: ignore[override]
        raise KeyError(key)


def render_template(template: str, context: dict[str, str]) -> str:
    """`{video_title}` のようなプレースホルダを展開する.

    未定義のキーが含まれるテンプレートは `ValidationError` を送出。
    """
    try:
        return template.format_map(_SafeDict(context))
    except KeyError as e:
        raise ValidationError(
            f"コメントテンプレートに未定義のプレースホルダ {e.args[0]!r} が含まれます: {template!r}"
        ) from e
    except (IndexError, ValueError) as e:
        raise ValidationError(f"コメントテンプレートのフォーマットが不正です: {template!r} ({e})") from e
