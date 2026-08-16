"""Safe HTML view for fixed review candidates and loopback selection forms."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.review import SelectionManifest


def render_review_html(
    manifest: SelectionManifest,
    *,
    endpoint: str | None,
    media: Mapping[str, Path],
    compact_image_ids: frozenset[str] = frozenset(),
) -> str:
    """Render only manifest candidates; no free-form input or executable script."""
    if set(media) - {candidate.id for candidate in manifest.candidates}:
        raise DocumentRenderError("review mediaは候補allowlistに含まれる必要があります")
    if not compact_image_ids.issubset(media):
        raise DocumentRenderError("320px表示は画像候補allowlistに含まれる必要があります")
    action = endpoint or ""
    cards = "".join(
        _candidate_card(
            candidate.id,
            candidate.label,
            candidate.details,
            media.get(candidate.id),
            manifest,
            action,
            compact_image=candidate.id in compact_image_ids,
        )
        for candidate in manifest.candidates
    )
    package = "youtube_automation.domains.documents.resources"
    template = Template(files(package).joinpath("review.html").read_text(encoding="utf-8"))
    css = files(package).joinpath("base.css").read_text(encoding="utf-8").strip()
    csp_action = endpoint.rsplit("/select/", 1)[0] if endpoint is not None else "'none'"
    html = template.substitute(
        TITLE=escape(f"{manifest.artifact} review"),
        CONTENT=cards,
        CSS=css,
        FORM_ACTION=escape(csp_action, quote=True),
    )
    validate_review_html(
        html,
        manifest=manifest,
        endpoint=endpoint,
        media=media,
        compact_image_ids=compact_image_ids,
    )
    return html


def _candidate_card(
    candidate_id: str,
    label: str,
    details: tuple[tuple[str, str], ...],
    media_path: Path | None,
    manifest: SelectionManifest,
    action: str,
    *,
    compact_image: bool,
) -> str:
    preview = _preview(media_path, label, compact_image=compact_image) if media_path is not None else ""
    comparison = ""
    if details:
        rows = "".join(f"<dt>{escape(key)}</dt><dd>{escape(value)}</dd>" for key, value in details)
        comparison = f'<dl class="review-comparison">{rows}</dl>'
    form = ""
    if action:
        form = (
            f'<form method="post" action="{escape(action, quote=True)}">'
            f'<input type="hidden" name="artifact_digest" value="{manifest.artifact_digest}">'
            f'<button type="submit" name="candidate_id" value="{escape(candidate_id, quote=True)}">'
            "この候補を選ぶ</button></form>"
        )
    return (
        f'<section class="view-card" data-candidate-id="{escape(candidate_id, quote=True)}">'
        f"<h2>{escape(label)}</h2>{comparison}{preview}{form}</section>"
    )


def _preview(path: Path, label: str, *, compact_image: bool) -> str:
    uri = escape(path.resolve().as_uri(), quote=True)
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        original = f'<img src="{uri}" alt="{escape(label, quote=True)} 原寸" loading="lazy">'
        if not compact_image:
            return original
        compact = (
            f'<img class="review-320" src="{uri}" alt="{escape(label, quote=True)} 320px表示" '
            'width="320" loading="lazy">'
        )
        return (
            f'<div class="review-images"><figure><figcaption>原寸</figcaption>{original}</figure>'
            f"<figure><figcaption>320px表示</figcaption>{compact}</figure></div>"
        )
    if suffix in {".mp3", ".wav", ".flac", ".m4a", ".aac"}:
        return f'<audio src="{uri}" controls preload="metadata"></audio>'
    if suffix in {".mp4", ".mov", ".webm"}:
        return f'<video src="{uri}" controls preload="metadata"></video>'
    raise DocumentRenderError(f"review対象のmedia形式を表示できません: {path.name}")


class _ReviewHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_main = False
        self.csp: str | None = None
        self.actions: list[str] = []
        self.candidate_values: list[str] = []
        self.digest_values: list[str] = []
        self.media_uris: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "iframe", "object", "embed", "a"}:
            raise DocumentRenderError(f"review HTMLに禁止tagがあります: {tag}")
        if any(name.lower().startswith("on") for name in attributes):
            raise DocumentRenderError("review HTMLにevent handlerは指定できません")
        if tag == "main":
            self.has_main = True
        if tag == "meta" and attributes.get("http-equiv") == "Content-Security-Policy":
            self.csp = attributes.get("content")
        if tag == "form":
            if attributes.get("method") != "post" or set(attributes) != {"method", "action"}:
                raise DocumentRenderError("review formは固定POST契約だけを許可します")
            self.actions.append(attributes.get("action", ""))
        if tag == "input":
            if attributes.get("type") != "hidden" or attributes.get("name") != "artifact_digest":
                raise DocumentRenderError("review HTMLは自由入力を許可しません")
            self.digest_values.append(attributes.get("value", ""))
        if tag == "button":
            if attributes.get("type") != "submit" or attributes.get("name") != "candidate_id":
                raise DocumentRenderError("review buttonは候補ID送信だけを許可します")
            self.candidate_values.append(attributes.get("value", ""))
        if tag in {"img", "audio", "video"}:
            self.media_uris.append(attributes.get("src", ""))


def validate_review_html(
    html: str,
    *,
    manifest: SelectionManifest,
    endpoint: str | None,
    media: Mapping[str, Path],
    compact_image_ids: frozenset[str] = frozenset(),
) -> None:
    parser = _ReviewHTMLParser()
    parser.feed(html)
    parser.close()
    csp_action = endpoint.rsplit("/select/", 1)[0] if endpoint is not None else "'none'"
    expected_csp = (
        "default-src 'none'; img-src file:; media-src file:; style-src 'unsafe-inline'; "
        f"script-src 'none'; base-uri 'none'; form-action {csp_action}; frame-ancestors 'none'"
    )
    if not parser.has_main or parser.csp != expected_csp:
        raise DocumentRenderError("review HTMLのdocument/CSP境界が不正です")
    expected_ids = [candidate.id for candidate in manifest.candidates] if endpoint is not None else []
    if parser.candidate_values != expected_ids:
        raise DocumentRenderError("review HTMLの候補allowlistがmanifestと一致しません")
    if parser.actions != ([endpoint] * len(manifest.candidates) if endpoint is not None else []):
        raise DocumentRenderError("review HTMLのloopback endpointが一致しません")
    if parser.digest_values != ([manifest.artifact_digest] * len(manifest.candidates) if endpoint is not None else []):
        raise DocumentRenderError("review HTMLのartifact digestが一致しません")
    expected_media = [
        path.resolve().as_uri()
        for candidate in manifest.candidates
        if (path := media.get(candidate.id))
        for _ in range(2 if candidate.id in compact_image_ids else 1)
    ]
    if parser.media_uris != expected_media:
        raise DocumentRenderError("review HTMLのmedia allowlistが一致しません")
    if endpoint is not None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.path != f"/select/{manifest.token}"
            or parsed.query
            or parsed.fragment
        ):
            raise DocumentRenderError("review selection endpointは127.0.0.1 loopbackだけを許可します")


__all__ = ["render_review_html", "validate_review_html"]
