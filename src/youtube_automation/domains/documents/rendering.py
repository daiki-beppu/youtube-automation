"""検証済み JSON と schema annotation から自己完結 HTML を生成する。"""

from __future__ import annotations

import json
from html import escape
from html.parser import HTMLParser
from importlib.resources import files
from string import Template
from typing import Mapping, Sequence
from urllib.parse import unquote, urlsplit

from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.schema_registry import (
    RepositorySchema,
    load_repository_schema,
    validate_repository_document,
)

_CSP = (
    "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; "
    "script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
_PRESENTATIONS = frozenset({"card", "cards", "details", "table", "media"})
_MEDIA_TYPES = frozenset({"image", "audio", "video", "link"})


def render_repository_document(schema: RepositorySchema, document: object) -> str:
    """registry 所有 schema で検証してから HTML を生成する。"""
    validate_repository_document(schema, document)
    return render_schema_document(document, load_repository_schema(schema))


def render_schema_document(document: object, schema: Mapping[str, object]) -> str:
    """検証済み文書を schema annotation と ``x-view`` に従って描画する。

    この低水準関数は schema をコンパイルしない。保存・CLI 入口は必ず
    :func:`render_repository_document` を使い、固定 registry で先に検証する。
    """
    title = _annotation(schema, "title", "Structured document")
    description = _annotation(schema, "description", "")
    content = _render_root(document, schema, schema)
    embedded = _embedded_json(document)
    package = "youtube_automation.domains.documents.resources"
    template = files(package).joinpath("base.html").read_text(encoding="utf-8")
    css = files(package).joinpath("base.css").read_text(encoding="utf-8").strip()
    description_html = f'<p class="document-description">{escape(description)}</p>' if description else ""
    html = Template(template).substitute(
        TITLE=escape(title),
        DESCRIPTION=description_html,
        CONTENT=content,
        DATA=embedded,
        CSS=css,
    )
    validate_generated_html(html)
    return html


def _render_root(document: object, schema: Mapping[str, object], root_schema: Mapping[str, object]) -> str:
    if not isinstance(document, dict):
        return _card("Value", "", _render_value(document, schema, root_schema))
    properties = schema.get("properties")
    property_schemas = properties if isinstance(properties, dict) else {}
    sections: list[tuple[int, int, str]] = []
    navigation: list[tuple[int, int, str, str]] = []
    known_properties: set[str] = set()
    for index, (name, property_schema) in enumerate(property_schemas.items()):
        if name not in document or not isinstance(property_schema, dict):
            continue
        known_properties.add(name)
        view = _view(property_schema)
        order = view.get("order", index)
        if isinstance(order, bool) or not isinstance(order, int):
            raise DocumentRenderError(f"x-view.order は integer で指定してください: {name}")
        heading = _annotation(property_schema, "title", name)
        description = _annotation(property_schema, "description", "")
        section_id = f"section-{_html_id(name)}"
        rendered = _render_section(
            heading, description, document[name], property_schema, root_schema, section_id=section_id
        )
        sections.append((order, index, rendered))
        navigation.append((order, index, section_id, heading))
    for offset, name in enumerate(sorted(set(document) - known_properties), start=len(property_schemas)):
        fallback_schema = {
            "title": name,
            "x-view": {"presentation": "details"},
        }
        rendered = _render_section(name, "", document[name], fallback_schema, root_schema)
        sections.append((10_000, offset, rendered))
    if not sections:
        return _card(_annotation(schema, "title", "Value"), "", _render_value(document, schema, root_schema))
    nav_items = "".join(
        f'<li><a href="#{escape(section_id, quote=True)}">{escape(heading)}</a></li>'
        for _, _, section_id, heading in sorted(navigation)
    )
    navigation_html = (
        '<nav class="review-nav" aria-label="文書内ナビゲーション">'
        '<p><strong>目次</strong> · 検索はブラウザの Ctrl/⌘+F を使用</p>'
        f"<ol>{nav_items}</ol></nav>"
    )
    # ナビゲーションは CSS order で先頭表示する。本文を先に置くことで、支援技術と
    # テキスト抽出では承認対象の本文を目次の重複ラベルより先に読める。
    return "".join(rendered for _, _, rendered in sorted(sections)) + navigation_html


def _render_section(
    heading: str,
    description: str,
    value: object,
    schema: Mapping[str, object],
    root_schema: Mapping[str, object],
    *,
    section_id: str | None = None,
) -> str:
    view = _view(schema)
    _validate_review_view(view)
    presentation = _presentation(view, value)
    modifiers = _review_classes(view)
    rendered_schema = _without_review_flags(schema) if view.get("collapsed") is True else schema
    if presentation == "table":
        rendered = _render_table(heading, description, value, rendered_schema, root_schema, modifiers=modifiers)
    elif presentation == "cards":
        rendered = _render_cards(heading, description, value, rendered_schema, root_schema, modifiers=modifiers)
    elif presentation == "details":
        content = _render_value(value, _without_presentation(schema), root_schema)
        rendered = _details(heading, description, content, modifiers=modifiers)
    elif presentation == "media":
        rendered = _render_media(heading, description, value, view, modifiers=modifiers)
    else:
        content = _render_value(value, rendered_schema, root_schema)
        rendered = _card(heading, description, content, modifiers=modifiers)
    if view.get("collapsed") is True and presentation != "details":
        rendered = _details(heading, description, rendered, modifiers=modifiers)
    if section_id is not None:
        rendered = f'<span class="section-anchor" id="{section_id}"></span>{rendered}'
    return rendered


def _html_id(value: str) -> str:
    """Schema property name を安全な fragment identifier にする。"""
    return "".join(character if character.isalnum() or character in "-_" else "-" for character in value)


def _view(schema: Mapping[str, object]) -> dict[str, object]:
    value = schema.get("x-view")
    return value if isinstance(value, dict) else {}


def _presentation(view: Mapping[str, object], value: object) -> str:
    candidate = view.get("presentation", view.get("type", view.get("layout")))
    if candidate is None:
        return "table" if isinstance(value, list) and all(isinstance(item, dict) for item in value) else "card"
    if not isinstance(candidate, str) or candidate not in _PRESENTATIONS:
        raise DocumentRenderError("x-view.presentation は card/cards/details/table/media のいずれかにしてください")
    return candidate


def _annotation(schema: Mapping[str, object], key: str, fallback: str) -> str:
    value = schema.get(key)
    return value if isinstance(value, str) and value else fallback


def _card(heading: str, description: str, content: str, *, modifiers: str = "") -> str:
    description_html = f'<p class="view-description">{escape(description)}</p>' if description else ""
    classes = f"view-card{modifiers}"
    return f'<section class="{classes}"><h2>{escape(heading)}</h2>{description_html}{content}</section>'


def _details(heading: str, description: str, content: str, *, modifiers: str = "") -> str:
    description_html = f'<p class="view-description">{escape(description)}</p>' if description else ""
    return (
        f'<details class="view-details{modifiers}"><summary>{escape(heading)}</summary>'
        f'<div class="view-details-content">{description_html}{content}</div></details>'
    )


def _without_presentation(schema: Mapping[str, object]) -> Mapping[str, object]:
    view = dict(_view(schema))
    for key in ("presentation", "type", "layout"):
        view.pop(key, None)
    rendered_schema = dict(schema)
    if view:
        rendered_schema["x-view"] = view
    else:
        rendered_schema.pop("x-view", None)
    return rendered_schema


def _without_review_flags(schema: Mapping[str, object]) -> Mapping[str, object]:
    view = dict(_view(schema))
    view.pop("collapsed", None)
    rendered_schema = dict(schema)
    rendered_schema["x-view"] = view
    return rendered_schema


def _validate_review_view(view: Mapping[str, object]) -> None:
    for key in ("summary", "collapsed", "copyable", "diff"):
        value = view.get(key)
        if value is not None and not isinstance(value, bool):
            raise DocumentRenderError(f"x-view.{key} は boolean で指定してください")
    priority = view.get("priority")
    if priority is not None and priority not in {"critical", "high", "normal", "low"}:
        raise DocumentRenderError("x-view.priority は critical/high/normal/low のいずれかにしてください")


def _review_classes(view: Mapping[str, object]) -> str:
    classes: list[str] = []
    if view.get("summary") is True:
        classes.append("view-summary")
    priority = view.get("priority")
    if isinstance(priority, str):
        classes.append(f"view-priority-{priority}")
    return "" if not classes else " " + " ".join(classes)


def _resolve_local_reference(schema: Mapping[str, object], root_schema: Mapping[str, object]) -> Mapping[str, object]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise DocumentRenderError("表示用 schema の $ref は local JSON Pointer だけを使用できます")
    current: object = root_schema
    for encoded_token in reference[2:].split("/"):
        token = unquote(encoded_token).replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or token not in current:
            raise DocumentRenderError("表示用 schema の local $ref を解決できません")
        current = current[token]
    if not isinstance(current, Mapping):
        raise DocumentRenderError("表示用 schema の local $ref は object を参照する必要があります")
    return current


def _ordered_properties(
    schema: Mapping[str, object], root_schema: Mapping[str, object]
) -> list[tuple[str, Mapping[str, object]]]:
    schema = _resolve_local_reference(schema, root_schema)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    ordered: list[tuple[int, int, str, Mapping[str, object]]] = []
    for index, (name, child) in enumerate(properties.items()):
        if not isinstance(child, dict):
            continue
        order = _view(child).get("order", index)
        if isinstance(order, bool) or not isinstance(order, int):
            raise DocumentRenderError(f"x-view.order は integer で指定してください: {name}")
        ordered.append((order, index, name, child))
    return [(name, child) for _, _, name, child in sorted(ordered)]


def _render_value(value: object, schema: Mapping[str, object], root_schema: Mapping[str, object]) -> str:
    schema = _resolve_local_reference(schema, root_schema)
    view = _view(schema)
    _validate_review_view(view)
    if view.get("collapsed") is True:
        return _details("詳細を表示", "", _render_value(value, _without_review_flags(schema), root_schema))
    presentation = _presentation(view, value)
    if presentation == "media":
        return _render_media(_annotation(schema, "title", "Media"), "", value, view)
    if presentation == "details":
        return _details("詳細を表示", "", _render_value(value, _without_presentation(schema), root_schema))
    if isinstance(value, dict):
        children = _ordered_properties(schema, root_schema)
        known = {name for name, _ in children}
        children.extend((name, {}) for name in sorted(value) if name not in known)
        rows = "".join(
            f"<dt>{escape(_annotation(child_schema, 'title', name))}</dt>"
            f"<dd>{_render_value(value[name], child_schema, root_schema)}</dd>"
            for name, child_schema in children
            if name in value
        )
        return f"<dl>{rows}</dl>" if rows else '<p class="empty">No values</p>'
    if isinstance(value, list):
        item_schema = schema.get("items")
        child_schema = item_schema if isinstance(item_schema, dict) else {}
        items = "".join(f"<li>{_render_value(item, child_schema, root_schema)}</li>" for item in value)
        return f"<ul>{items}</ul>" if items else '<p class="empty">No items</p>'
    if value is None:
        return '<span class="empty">None</span>'
    if isinstance(value, bool):
        return "true" if value else "false"
    rendered = escape(str(value))
    if view.get("copyable") is True:
        diff_class = " view-diff" if view.get("diff") is True else ""
        return (
            f'<div class="copyable-content{diff_class}" tabindex="0" '
            'aria-label="コピー対象。選択してコピー" title="選択してコピー">'
            f"{rendered}</div>"
        )
    if view.get("diff") is True:
        return f'<div class="view-diff">{rendered}</div>'
    return rendered


def _render_table(
    heading: str,
    description: str,
    value: object,
    schema: Mapping[str, object],
    root_schema: Mapping[str, object],
    *,
    modifiers: str = "",
) -> str:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise DocumentRenderError(f"table 表示には object の array が必要です: {heading}")
    schema = _resolve_local_reference(schema, root_schema)
    items = schema.get("items")
    item_schema = items if isinstance(items, dict) else {}
    columns = _ordered_properties(item_schema, root_schema)
    known = {name for name, _ in columns}
    additional_names = sorted({name for row in value for name in row if name not in known})
    columns.extend((name, {}) for name in additional_names)
    header = "".join(f"<th>{escape(_annotation(child, 'title', name))}</th>" for name, child in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{_render_value(row.get(name), child, root_schema)}</td>" for name, child in columns)
        + "</tr>"
        for row in value
    )
    if not body:
        body = f'<tr><td class="empty" colspan="{max(1, len(columns))}">No rows</td></tr>'
    description_html = f'<p class="view-description">{escape(description)}</p>' if description else ""
    return (
        f'<section class="view-table-section{modifiers}"><h2>{escape(heading)}</h2>{description_html}'
        f'<div class="table-scroll"><table class="view-table"><thead><tr>{header}</tr></thead>'
        f"<tbody>{body}</tbody></table></div></section>"
    )


def _render_cards(
    heading: str,
    description: str,
    value: object,
    schema: Mapping[str, object],
    root_schema: Mapping[str, object],
    *,
    modifiers: str = "",
) -> str:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DocumentRenderError(f"cards 表示には object の array が必要です: {heading}")
    schema = _resolve_local_reference(schema, root_schema)
    item_schema_value = schema.get("items")
    item_schema = item_schema_value if isinstance(item_schema_value, dict) else {}
    labels = [str(item.get("title") or item.get("name") or f"Entry {index}") for index, item in enumerate(value, 1)]
    flow = "".join(f'<li><a href="#track-{index}">{escape(label)}</a></li>' for index, label in enumerate(labels, 1))
    cards = "".join(
        f'<article class="entry-card" id="track-{index}"><h3>{escape(label)}</h3>'
        f"{_render_value(item, item_schema, root_schema)}</article>"
        for index, (label, item) in enumerate(zip(labels, value, strict=True), 1)
    )
    description_html = f'<p class="view-description">{escape(description)}</p>' if description else ""
    return (
        f'<section class="view-cards-section{modifiers}"><h2>{escape(heading)}</h2>{description_html}'
        f'<ol class="card-flow">{flow}</ol><div class="entry-card-grid">{cards}</div></section>'
    )


def _render_media(
    heading: str,
    description: str,
    value: object,
    view: Mapping[str, object],
    *,
    modifiers: str = "",
) -> str:
    media_type = view.get("mediaType", view.get("media-type", "link"))
    if not isinstance(media_type, str) or media_type not in _MEDIA_TYPES:
        raise DocumentRenderError("x-view.mediaType は image/audio/video/link のいずれかにしてください")
    references: Sequence[object] = value if isinstance(value, list) else [value]
    prefix = view.get("pathPrefix", "")
    if prefix not in {"", "../"}:
        raise DocumentRenderError("x-view.pathPrefixは空または../だけを許可します")
    rendered: list[str] = []
    for reference in references:
        if not isinstance(reference, str) or not _is_local_asset(reference):
            raise DocumentRenderError(f"media は local asset reference だけを使用できます: {heading}")
        safe_reference = escape(f"{prefix}{reference}", quote=True)
        if media_type == "image":
            rendered.append(f'<img src="{safe_reference}" alt="{escape(heading, quote=True)}" loading="lazy">')
        elif media_type == "audio":
            rendered.append(f'<audio src="{safe_reference}" controls preload="metadata"></audio>')
        elif media_type == "video":
            rendered.append(f'<video src="{safe_reference}" controls preload="metadata"></video>')
        else:
            rendered.append(f'<a href="{safe_reference}">{escape(reference)}</a>')
    description_html = f'<p class="view-description">{escape(description)}</p>' if description else ""
    return (
        f'<section class="view-media{modifiers}"><h2>{escape(heading)}</h2>'
        f'{description_html}{"".join(rendered)}</section>'
    )


def _is_local_asset(reference: str, *, allow_plan_preview: bool = False) -> bool:
    if not reference or "\\" in reference or any(ord(character) < 32 for character in reference):
        return False
    parsed = urlsplit(reference)
    segments = unquote(parsed.path).split("/")
    if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
        return False
    if ".." not in segments:
        return True
    return allow_plan_preview and segments[:2] == ["..", "10-assets"] and segments.count("..") == 1


def _embedded_json(document: object) -> str:
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        serialized.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


class _GeneratedHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_doctype = False
        self.has_main = False
        self.has_csp = False
        self.data_script_count = 0
        self.in_data_script = False
        self.embedded_parts: list[str] = []
        self.in_style = False
        self.style_parts: list[str] = []

    def handle_decl(self, declaration: str) -> None:
        if declaration.lower() == "doctype html":
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"base", "embed", "form", "iframe", "object", "link"}:
            raise DocumentRenderError(f"生成 HTML に禁止 tag があります: {tag}")
        if any(name.lower().startswith("on") for name in attributes):
            raise DocumentRenderError("生成 HTML に event handler attribute があります")
        for attribute in ("src", "href", "poster"):
            reference = attributes.get(attribute)
            if reference is not None and not _is_local_asset(reference, allow_plan_preview=True):
                raise DocumentRenderError("生成 HTML に external asset reference があります")
        if "srcset" in attributes:
            raise DocumentRenderError("生成 HTML に srcset reference があります")
        if tag == "main":
            self.has_main = True
        if tag == "meta" and attributes.get("http-equiv", "").lower() == "content-security-policy":
            self.has_csp = attributes.get("content") == _CSP
        if tag == "script":
            if attributes != {"id": "document-data", "type": "application/json"}:
                raise DocumentRenderError("生成 HTML に executable script があります")
            self.data_script_count += 1
            self.in_data_script = True
        if tag == "style":
            self.in_style = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_data_script = False
        if tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        if self.in_data_script:
            self.embedded_parts.append(data)
        if self.in_style:
            self.style_parts.append(data)


def validate_generated_html(html: str) -> None:
    """自己完結・CSP・埋込 JSON の安全境界を再検証する。"""
    parser = _GeneratedHTMLParser()
    try:
        parser.feed(html)
        parser.close()
        embedded = "".join(parser.embedded_parts)
        json.loads(embedded)
    except (DocumentRenderError, json.JSONDecodeError) as error:
        if isinstance(error, DocumentRenderError):
            raise
        raise DocumentRenderError("生成 HTML の embedded JSON が不正です") from error
    styles = "".join(parser.style_parts).lower()
    if "@import" in styles or "url(" in styles:
        raise DocumentRenderError("生成 HTML の CSS に external resource 参照があります")
    if not parser.has_doctype or not parser.has_main or not parser.has_csp or parser.data_script_count != 1:
        raise DocumentRenderError("生成 HTML の document/CSP/data 境界が不正です")
