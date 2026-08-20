"""Safe, self-contained renderer for the read-only workflow status snapshot."""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from importlib.resources import files
from string import Template

from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.workflow_status import CollectionStatusView, WorkflowStatusSnapshot

_RESOURCE_PACKAGE = "youtube_automation.domains.documents.resources"
_FILTERS = ("all", "planning", "live", "complete")


def render_workflow_status(snapshot: WorkflowStatusSnapshot) -> str:
    template = Template(files(_RESOURCE_PACKAGE).joinpath("workflow_status.html").read_text(encoding="utf-8"))
    css = files(_RESOURCE_PACKAGE).joinpath("workflow_status.css").read_text(encoding="utf-8")
    filters = (
        "".join(
            f'<input class="filter-control" type="radio" name="status-filter" id="filter-{status}"'
            f"{' checked' if status == 'all' else ''}>"
            for status in _FILTERS
        )
        + '<nav class="filters" aria-label="表示フィルター">'
        + "".join(
            f'<label for="filter-{status}"><span class="filter-selected" aria-hidden="true">'
            f"選択中 · </span>{label}</label>"
            for status, label in zip(_FILTERS, ("すべて", "企画中", "公開工程", "完了"), strict=True)
        )
        + "</nav>"
    )
    if snapshot.collections:
        ordered = sorted(snapshot.collections, key=lambda item: not _needs_attention(item))
        collections = "".join(_render_collection(item) for item in ordered)
    else:
        collections = '<p class="empty">コレクションはありません</p>'
    html = template.substitute(
        css=css,
        generated_at=escape(snapshot.generated_at.isoformat()),
        filters=filters,
        collections=collections,
    )
    validate_workflow_status_html(html)
    return html


def _render_collection(item: CollectionStatusView) -> str:
    attention_items: list[str] = []
    if item.stale:
        attention_items.append(f"停滞: {escape(item.stalled_for)}（最終更新 {escape(item.updated_at)}）")
    attention_items.extend(f"警告: {escape(warning)}" for warning in item.warnings)
    attention_items.extend(
        f"{escape(artifact.label)}: {_status_label(artifact.status)} — {escape(artifact.detail)}"
        for artifact in item.artifacts
        if artifact.status != "complete"
    )
    attention = ""
    if attention_items:
        attention = (
            '<section class="attention" aria-label="要対応"><h3>要対応</h3><ul>'
            + "".join(f"<li>{message}</li>" for message in attention_items)
            + "</ul></section>"
        )
    artifacts = "".join(
        "<tr>"
        f'<th scope="row">{escape(artifact.label)}</th>'
        f'<td><span class="artifact {artifact.status}">{_status_label(artifact.status)}</span></td>'
        f"<td>{escape(artifact.detail)}</td>"
        "</tr>"
        for artifact in item.artifacts
    )
    return (
        f'<article class="collection-card" data-status="{item.status}" data-slug="{escape(item.slug, quote=True)}" '
        f'data-attention="{str(bool(attention_items)).lower()}">'
        f'<header><p class="status">{_collection_label(item.status)} · phase {escape(item.phase)}</p>'
        f"<h2>{escape(item.name)}</h2></header>{attention}"
        '<dl class="summary">'
        f"<div><dt>phase</dt><dd>{escape(item.phase)}</dd></div>"
        f"<div><dt>blocker</dt><dd>{escape(item.blocker)}</dd></div>"
        f"<div><dt>next action</dt><dd>{escape(item.next_action)}</dd></div>"
        f"<div><dt>更新</dt><dd>{escape(item.updated_at)} / {escape(item.stalled_for)}</dd></div>"
        "</dl>"
        '<div class="table-scroll"><table><caption>成果物の詳細</caption>'
        "<thead><tr><th>項目</th><th>状態</th><th>根拠</th></tr></thead>"
        f"<tbody>{artifacts}</tbody></table></div></article>"
    )


def _needs_attention(item: CollectionStatusView) -> bool:
    return item.stale or bool(item.warnings) or any(artifact.status != "complete" for artifact in item.artifacts)


def _status_label(status: str) -> str:
    return {"complete": "完了", "missing": "未生成", "inconsistent": "不整合"}[status]


def _collection_label(status: str) -> str:
    return {"planning": "企画中", "live": "公開工程", "complete": "完了"}[status]


class _SnapshotHTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_main = False
        self.has_csp = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "form", "button", "a", "iframe", "object", "embed"}:
            raise DocumentRenderError(f"workflow status HTML に禁止要素があります: {tag}")
        if any(name.lower().startswith("on") for name in attributes):
            raise DocumentRenderError("workflow status HTML に event handler は指定できません")
        if any(name in attributes for name in ("href", "src", "action")):
            raise DocumentRenderError("workflow status HTML に外部参照やactionは指定できません")
        if tag == "main":
            self.has_main = True
        if tag == "meta" and attributes.get("http-equiv") == "Content-Security-Policy":
            self.has_csp = True
        if tag == "input" and attributes.get("type") != "radio":
            raise DocumentRenderError("workflow status HTML の入力は表示filterのradioだけ許可されます")


def validate_workflow_status_html(html: str) -> None:
    """Reject active content and missing structural safety markers."""
    parser = _SnapshotHTMLValidator()
    try:
        parser.feed(html)
        parser.close()
    except (DocumentRenderError, ValueError) as exc:
        if isinstance(exc, DocumentRenderError):
            raise
        raise DocumentRenderError("workflow status HTML を解析できません") from exc
    if not parser.has_main or not parser.has_csp:
        raise DocumentRenderError("workflow status HTML に main またはCSPがありません")


__all__ = ["render_workflow_status", "validate_workflow_status_html"]
