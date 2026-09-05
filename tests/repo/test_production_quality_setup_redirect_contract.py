"""Production/quality opening routes owned by ``/setup --channel``."""

from __future__ import annotations

import posixpath
import re
import subprocess
import tarfile
import unicodedata
import zipfile
from base64 import b64decode
from collections import Counter
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

pytestmark = pytest.mark.repo_contract

SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
TARGET_SKILLS = (
    "audit",
    "wf-new",
    "analytics",
    "publish",
    "short",
    "music",
    "thumbnail",
)
WF_NEW_IDEATION_MEMBERS = frozenset(
    {
        "references/collection-ideate.config.default.yaml",
        "references/collection-lifecycle.md",
        "references/freshness-rules.md",
        "references/freshness_action.py",
        "references/generate_image.py",
        "references/ideate.md",
        "references/object-design-examples.md",
        "references/planning-rules.md",
        "references/preview-contract.md",
        "references/preview-generation.md",
        "references/record-ttp-reference-assignments.py",
        "references/select-ttp-references.py",
        "references/selection-handoff.md",
    }
)
CONTEXTS = (
    "opening",
    "import",
    "regenerate",
    "analysis",
    "direction",
    "shared-reference",
)


def _entry(skill: str, path: str, occurrence: str, context: str) -> tuple[str, str, str, str]:
    return skill, path, occurrence, context


# Every literal /channel-strategy --direction occurrence on main before #3987, classified by context.
INITIAL_OCCURRENCE_LEDGER = (
    _entry("alignment-check", "SKILL.md", "missing-config-new", "opening"),
    _entry("alignment-check", "SKILL.md", "missing-config-existing", "import"),
    _entry("alignment-check", "SKILL.md", "cross-collection-direction", "direction"),
    _entry("collection-ideate", "SKILL.md", "desire-vocabulary", "shared-reference"),
    _entry("collection-ideate", "SKILL.md", "missing-config-new", "opening"),
    _entry("collection-ideate", "SKILL.md", "missing-config-existing", "import"),
    _entry("collection-ideate", "SKILL.md", "direction-record", "direction"),
    _entry("collection-ideate", "SKILL.md", "analysis-report", "analysis"),
    _entry("collection-ideate", "SKILL.md", "missing-direction-record", "direction"),
    _entry("collection-ideate", "references/freshness-rules.md", "desire-vocabulary", "shared-reference"),
    _entry("analytics", "SKILL.md", "missing-config-new", "opening"),
    _entry("analytics", "SKILL.md", "missing-config-existing", "import"),
    _entry("analytics", "SKILL.md", "read-only-input", "analysis"),
    _entry("analytics", "SKILL.md", "benchmark-input", "analysis"),
    _entry("analytics", "SKILL.md", "market-direction", "direction"),
    _entry("analytics", "SKILL.md", "whole-channel-direction", "direction"),
    _entry("thumbnail", "references/loop.md", "missing-config-new", "opening"),
    _entry("thumbnail", "references/loop.md", "missing-config-existing", "import"),
    _entry("lyria", "SKILL.md", "missing-config-new", "opening"),
    _entry("lyria", "SKILL.md", "missing-config-existing", "import"),
    _entry("lyria", "SKILL.md", "engine-direction", "direction"),
    _entry("lyria", "SKILL.md", "engine-regeneration", "regenerate"),
    _entry("metadata-audit", "SKILL.md", "missing-config-existing", "import"),
    _entry("playlist", "SKILL.md", "missing-playlists", "regenerate"),
    _entry("playlist", "SKILL.md", "playlist-definition", "regenerate"),
    _entry("short", "SKILL.md", "missing-config-existing", "import"),
    _entry("short-thumbnail", "SKILL.md", "missing-config-existing", "import"),
    _entry("music", "SKILL.md", "missing-config-new", "opening"),
    _entry("music", "SKILL.md", "missing-config-existing", "import"),
    _entry("thumbnail", "SKILL.md", "missing-config-new", "opening"),
    _entry("thumbnail", "SKILL.md", "missing-config-existing", "import"),
    _entry("thumbnail", "SKILL.md", "text-profile-analysis", "analysis"),
    _entry("thumbnail", "SKILL.md", "analysis-mode-reference", "shared-reference"),
    _entry("thumbnail", "config.default.yaml", "text-profile-analysis", "analysis"),
    _entry("thumbnail", "references/compare.md", "missing-config-existing", "import"),
    _entry("thumbnail", "references/compare.md", "missing-benchmark-direction", "direction"),
    _entry("value-loop-audit", "SKILL.md", "missing-config-new", "opening"),
    _entry("value-loop-audit", "SKILL.md", "missing-config-existing", "import"),
)
INITIAL_CONTEXT_COUNTS = {
    "opening": 8,
    "import": 12,
    "regenerate": 3,
    "analysis": 5,
    "direction": 7,
    "shared-reference": 3,
}


def _section_identity(section: str, occurrence: int = 1) -> str:
    return f"{section} [occurrence {occurrence}]"


def _route(path: str, section: str, line: str) -> tuple[str, str, str]:
    return path, section, line


_RAW_EXPECTED_ACTIVE_ROUTES = (
    _route("audit/references/alignment.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "audit/references/alignment.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
    _route(
        "audit/references/alignment.md",
        "## Next Step",
        "| **横断的な方向性ズレ** | 複数コレクションで同じ不整合パターン | "
        "`/channel-strategy --direction`（方向性検討モード）でチャンネル全体の方向性を再検討 |",
    ),
    _route(
        "audit/references/metadata.md",
        "## 前提",
        "- `config/channel/` が存在すること（`load_config()` でロード可能）。存在しない場合は "
        "`/setup --import` を案内して停止する",
    ),
    _route(
        "audit/references/value-loop.md",
        "## Hard Gates",
        "  - 新規チャンネルでは `/setup --channel` を案内して停止する。",
    ),
    _route(
        "audit/references/value-loop.md",
        "## Hard Gates",
        "  - 既存チャンネルでは `/setup --import` を案内して停止する。",
    ),
    _route(
        "audit/references/video.md",
        "## 呼び出し側スキル",
        "- `/channel-strategy --direction`（方向性検討モード） — Step D1 の分析サマリーで "
        "`bgm_arc` 平均（intro / peak / outro 秒）を提示し、",
    ),
    _route("wf-new/references/ideate.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "wf-new/references/ideate.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
    _route(
        "wf-new/references/ideate.md",
        "#### Phase 1-1: チャンネル現状 + 戦略ドキュメント",
        "- `docs/channel/` 配下の方向性決定記録 — `/channel-strategy --direction`"
        "（方向性検討モード）Step D5 が保存する決定事項",
    ),
    _route(
        "wf-new/references/ideate.md",
        "#### Phase 1-1: チャンネル現状 + 戦略ドキュメント",
        "どちらも任意扱い。存在しない場合は warning を表示して進行する"
        "（方向性決定記録は `/channel-strategy --direction` の方向性検討モードで生成できる旨を案内）。",
    ),
    _route(
        "analytics/SKILL.md",
        "## 共通前提",
        "- **新規チャンネル（config 未作成）** → `/setup --channel` を案内して停止する",
    ),
    _route(
        "analytics/SKILL.md",
        "## 共通前提",
        "- **既存チャンネル（load_config() 失敗）** → `/setup --import` を案内して停止する",
    ),
    _route("analytics/references/analyze.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "analytics/references/analyze.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
    _route("analytics/references/collect.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "analytics/references/collect.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
    _route("analytics/references/flop.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "analytics/references/flop.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
    _route(
        "analytics/references/flop.md",
        "### Phase 4: 検証の自律実行",
        "- `/audit --alignment`、`/channel-research --voice`、`/channel-strategy --persona`、"
        "`/channel-strategy --scene`、"
        "`/channel-strategy --direction` はスキルとして起動しない。これらは別成果物の保存または設定更新を"
        "完了条件に含むため、検証済み成果物だけを read-only 入力として読む。",
    ),
    _route(
        "analytics/references/flop.md",
        "### Phase 4: 検証の自律実行",
        "- 差別化・市場性は `/channel-research --discover` や `/channel-strategy --direction` を起動せず、"
        "最新の既存 `data/benchmark_*.json` と `yt-theme-compare` の標準出力だけを使う。"
        "競合の追加、方向性決定、config 更新は行わない",
    ),
    _route(
        "analytics/references/flop.md",
        "## Next Step",
        "| テーマ自体の市場性不足 | `/channel-research --discover` → "
        "`/channel-strategy --direction`（方向性検討モード） |",
    ),
    _route(
        "analytics/references/flop.md",
        "## Next Step",
        "改善策の実行は本スキルの完了条件に含めない。必要なら "
        "`/channel-strategy --direction`（方向性検討モード）でチャンネル全体の方向性を見直す。",
    ),
    _route("analytics/references/report.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "analytics/references/report.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
    _route(
        "analytics/references/status.md",
        "## 前後工程",
        "- `前工程`: `/setup --channel`",
    ),
    _route("analytics/references/status.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "analytics/references/status.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
    _route(
        "publish/references/playlist.md",
        "## 前提",
        "`config/channel/playlists.json` が存在し、`playlists` セクションが定義されていること。"
        "未定義の場合は `/setup --regenerate` を案内する。",
    ),
    _route(
        "publish/references/playlist.md",
        "## Cross References",
        "- `/setup --regenerate` — `playlists.json` の初期定義",
    ),
    _route(
        "short/SKILL.md",
        "## 前提",
        "いずれか欠ける場合は早期に止めて該当 skill / config 更新を案内する"
        "（`/setup --import` / `/setup` / `/publish --upload`）。",
    ),
    _route(
        "short/references/thumbnail.md",
        "## 前提",
        "- `config/channel/` がロード可能（`load_config()`）。存在しない場合は `/setup --import` を案内して停止する",
    ),
    _route(
        "music/SKILL.md",
        "## 共通前提",
        "- **新規チャンネル** → `/setup --channel` を案内",
    ),
    _route(
        "music/SKILL.md",
        "## 共通前提",
        "- **既存チャンネル**（設定不整合）→ `/setup --import` を案内",
    ),
    _route(
        "music/references/generate.md",
        "## Lyria 前提",
        "- **`config/channel/` が無い新規チャンネル** → `/setup --channel` を案内",
    ),
    _route(
        "music/references/generate.md",
        "## Lyria 前提",
        "- **`config/channel/` が無い既存チャンネル** → `/setup --import` を案内",
    ),
    _route(
        "music/references/generate.md",
        "### 選択タイミング（どこで lyria が選ばれるか）",
        "1. **チャンネルのデフォルト** — `/channel-strategy --direction`（方向性検討モード）で "
        "`suno` / `lyria` を検討 → "
        "`/setup --regenerate` が `config/channel/youtube.json` の `music_engine` に書き込む",
    ),
    _route("thumbnail/SKILL.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "thumbnail/SKILL.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
    _route(
        "thumbnail/references/compare.md",
        "## 前提",
        "- `config/channel/` が存在すること（`load_config()` でロード可能）。存在しない場合は "
        "`/setup --import` を案内して停止する",
    ),
    _route(
        "thumbnail/references/compare.md",
        "## 前提",
        "- `config/channel/analytics.json::benchmark.channels` に承認済みベンチマークチャンネルが設定済みであること。"
        "未設定なら `/channel-strategy --direction` / `/channel-research --discover` を案内して停止する",
    ),
    _route("thumbnail/references/loop.md", "## 前提", "- **新規チャンネル** → `/setup --channel` を案内"),
    _route(
        "thumbnail/references/loop.md",
        "## 前提",
        "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
    ),
)

_ROUTES = (
    "/channel-strategy --direction",
    "/setup --channel",
    "/setup --import",
    "/setup --regenerate",
    "/setup --push",
)
_ROUTE_TOKEN = re.compile(r"/channel-\s*new|/setup\s+--(?:channel|import|regenerate|push)")
_TAG_NAME = re.compile(r"^<\s*(/?)\s*([A-Za-z][A-Za-z0-9:-]*)")
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_HEADING = re.compile(r"^(#{2,6})\s")
_NON_RENDERED_STYLE = re.compile(
    r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))"
    r"(?:\s*!important)?\s*(?:;|$)",
    re.IGNORECASE,
)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HTML_ROUTE_JOINER = re.compile(r"<!--.*?-->|</?[A-Za-z][^>]*>", re.DOTALL)
_REFERENCE_DEFINITION = re.compile(r"^[ ]{0,3}\[([^]]+)]\s*:\s*\S")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ROUTE_BYTE_PREFIXES = (b"/channel-", b"/setup")


@dataclass(frozen=True)
class _HtmlContainer:
    name: str = field()
    hard_hidden: bool = field()
    closed_details: bool = field()


class _StartTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parsed: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parsed.append((tag.lower(), {name.lower(): value for name, value in attrs}))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


@dataclass
class _MarkdownVisibility:
    in_comment: bool = False
    in_fence: bool = False
    markdown_struck: bool = False
    code_span_ticks: int | None = None
    tag_buffer: str | None = None
    tag_quote: str | None = None
    containers: list[_HtmlContainer] = field(default_factory=list)

    @property
    def hidden(self) -> bool:
        if any(container.hard_hidden for container in self.containers):
            return True
        for index, container in enumerate(self.containers):
            if container.closed_details and not any(
                descendant.name == "summary" for descendant in self.containers[index + 1 :]
            ):
                return True
        return False


def _start_tag(tag: str) -> tuple[str, dict[str, str | None]] | None:
    parser = _StartTagParser()
    parser.feed(tag)
    return parser.parsed[0] if parser.parsed else None


def _apply_html_tag(state: _MarkdownVisibility, tag: str) -> None:
    match = _TAG_NAME.match(tag)
    if not match:
        return
    closing, raw_name = match.groups()
    name = raw_name.lower()
    if closing:
        for index in range(len(state.containers) - 1, -1, -1):
            if state.containers[index].name == name:
                del state.containers[index:]
                return
        return
    if tag.rstrip().endswith("/>") or name in _VOID_TAGS:
        return
    parsed = _start_tag(tag)
    if parsed is None:
        return
    _, attrs = parsed
    style = _CSS_COMMENT.sub("", attrs.get("style") or "")
    hard_hidden = (
        name in {"s", "del", "template", "script", "style"}
        or "hidden" in attrs
        or (attrs.get("aria-hidden") or "").lower() == "true"
        or bool(_NON_RENDERED_STYLE.search(style))
    )
    state.containers.append(_HtmlContainer(name, hard_hidden, name == "details" and "open" not in attrs))


def _visible_markdown_line(line: str, state: _MarkdownVisibility) -> str:
    """Mask non-rendered Markdown/HTML while preserving character positions."""
    stripped = line.lstrip()
    if (
        state.tag_buffer is None
        and state.code_span_ticks is None
        and not state.in_comment
        and stripped.startswith(("```", "~~~"))
    ):
        state.in_fence = not state.in_fence
        return " " * len(line)
    if state.in_fence:
        return " " * len(line)

    visible = [" "] * len(line)
    index = 0
    while index < len(line):
        if state.code_span_ticks is not None:
            if line[index] == "`":
                end = index
                while end < len(line) and line[end] == "`":
                    end += 1
                ticks = end - index
                if not state.hidden and not state.markdown_struck:
                    visible[index:end] = line[index:end]
                if ticks == state.code_span_ticks:
                    state.code_span_ticks = None
                index = end
                continue
            if not state.hidden and not state.markdown_struck:
                visible[index] = line[index]
            index += 1
            continue
        if state.in_comment:
            end = line.find("-->", index)
            if end < 0:
                return "".join(visible)
            state.in_comment = False
            index = end + 3
            continue
        if state.tag_buffer is not None:
            char = line[index]
            state.tag_buffer += char
            if state.tag_quote:
                if char == state.tag_quote:
                    state.tag_quote = None
            elif char in {'"', "'"}:
                state.tag_quote = char
            elif char == ">":
                _apply_html_tag(state, state.tag_buffer)
                state.tag_buffer = None
            index += 1
            continue
        if line.startswith("<!--", index):
            state.in_comment = True
            index += 4
            continue
        if line[index] == "`":
            end = index
            while end < len(line) and line[end] == "`":
                end += 1
            if not state.hidden and not state.markdown_struck:
                visible[index:end] = line[index:end]
            state.code_span_ticks = end - index
            index = end
            continue
        if line.startswith("~~", index):
            state.markdown_struck = not state.markdown_struck
            index += 2
            continue
        if line[index] == "<" and index + 1 < len(line) and (line[index + 1].isalpha() or line[index + 1] in "/!"):
            state.tag_buffer = "<"
            index += 1
            continue
        if not state.markdown_struck and not state.hidden:
            visible[index] = line[index]
        index += 1
    if state.tag_buffer is not None:
        state.tag_buffer += "\n"
    return "".join(visible)


def _reference_label(label: str) -> str:
    return " ".join(label.split()).casefold()


def _is_punctuation(character: str) -> bool:
    return unicodedata.category(character).startswith("P")


def _delimiter_flanking(text: str, index: int) -> tuple[bool, bool]:
    previous = text[index - 1] if index else "\n"
    following = text[index + 1] if index + 1 < len(text) else "\n"
    left = not following.isspace() and (
        not _is_punctuation(following) or previous.isspace() or _is_punctuation(previous)
    )
    right = not previous.isspace() and (
        not _is_punctuation(previous) or following.isspace() or _is_punctuation(following)
    )
    return left, right


def _single_emphasis_end(text: str, index: int) -> int | None:
    delimiter = text[index]
    left, right = _delimiter_flanking(text, index)
    previous = text[index - 1] if index else "\n"
    if not left or (delimiter == "_" and right and not _is_punctuation(previous)):
        return None
    candidate = text.find(delimiter, index + 1)
    while candidate >= 0:
        adjacent_delimiter = (candidate > 0 and text[candidate - 1] == delimiter) or (
            candidate + 1 < len(text) and text[candidate + 1] == delimiter
        )
        if not adjacent_delimiter:
            close_left, close_right = _delimiter_flanking(text, candidate)
            following = text[candidate + 1] if candidate + 1 < len(text) else "\n"
            if close_right and (delimiter == "*" or not close_left or _is_punctuation(following)):
                return candidate
        candidate = text.find(delimiter, candidate + 1)
    return None


def _render_markdown_inline(text: str, references: frozenset[str]) -> str:
    rendered: list[str] = []
    code_ticks: int | None = None
    index = 0
    while index < len(text):
        if text[index] == "`":
            end = index
            while end < len(text) and text[end] == "`":
                end += 1
            ticks = end - index
            if code_ticks is None:
                code_ticks = ticks
            elif ticks == code_ticks:
                code_ticks = None
            else:
                rendered.extend(text[index:end])
            index = end
            continue
        if code_ticks is not None:
            rendered.append(text[index])
            index += 1
            continue
        if text.startswith(("**", "__"), index):
            index += 2
            continue
        if text[index] in "*_":
            emphasis_end = _single_emphasis_end(text, index)
            if emphasis_end is not None:
                rendered.append(_render_markdown_inline(text[index + 1 : emphasis_end], references))
                index = emphasis_end + 1
                continue
        if text[index] == "[":
            label_end = text.find("]", index + 1)
            destination_end = (
                text.find(")", label_end + 2) if label_end >= 0 and text[label_end : label_end + 2] == "](" else -1
            )
            if destination_end >= 0:
                rendered.append(_render_markdown_inline(text[index + 1 : label_end], references))
                index = destination_end + 1
                continue
            reference_end = (
                text.find("]", label_end + 2) if label_end >= 0 and text[label_end : label_end + 2] == "][" else -1
            )
            if reference_end >= 0:
                label = text[index + 1 : label_end]
                reference = text[label_end + 2 : reference_end] or label
                if _reference_label(reference) in references:
                    rendered.append(_render_markdown_inline(label, references))
                    index = reference_end + 1
                    continue
        rendered.append(text[index])
        index += 1
    return "".join(rendered)


def _normalized_route_syntax(text: str) -> str:
    return unescape(_HTML_ROUTE_JOINER.sub("", text))


def _tracked_target_members() -> dict[str, bytes]:
    roots = [f".claude/skills/{skill}" for skill in TARGET_SKILLS]
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *roots],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    members: dict[str, bytes] = {}
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = REPO_ROOT / raw_path.decode("utf-8")
        relative = path.relative_to(SKILLS_DIR).as_posix()
        if _is_target_member(relative):
            members[relative] = path.read_bytes()
    return members


def _is_target_member(relative: str) -> bool:
    skill, separator, child = relative.partition("/")
    if skill not in TARGET_SKILLS:
        return False
    if skill == "wf-new":
        return separator == "/" and child in WF_NEW_IDEATION_MEMBERS
    if skill == "publish":
        return separator == "/" and child == "references/playlist.md"
    return True


def _active_route_records(overrides: dict[str, str | bytes] | None = None) -> tuple[tuple[str, str, str], ...]:
    members = _tracked_target_members()
    if overrides:
        members.update(
            {path: value.encode("utf-8") if isinstance(value, str) else value for path, value in overrides.items()}
        )
    return _route_records_for_members(members)


def _is_genuine_binary(payload: bytes) -> bool:
    png = (
        payload.startswith(_PNG_SIGNATURE)
        and len(payload) >= 24
        and payload[12:16] == b"IHDR"
        and payload.endswith(b"IEND\xaeB`\x82")
    )
    jpeg = payload.startswith(b"\xff\xd8\xff") and payload.endswith(b"\xff\xd9")
    gif = payload.startswith((b"GIF87a", b"GIF89a")) and payload.endswith(b";")
    webp = (
        len(payload) >= 12
        and payload.startswith(b"RIFF")
        and payload[8:12] == b"WEBP"
        and int.from_bytes(payload[4:8], "little") == len(payload) - 8
    )
    return png or jpeg or gif or webp


def _contract_text(payload: bytes) -> str | None:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        if any(prefix in payload for prefix in _ROUTE_BYTE_PREFIXES) or not _is_genuine_binary(payload):
            raise
        return None


def _section_identities(visible_lines: list[str]) -> list[str]:
    headings: list[tuple[int, int, str, int]] = []
    counts: Counter[str] = Counter()
    for line_index, line in enumerate(visible_lines):
        match = _HEADING.match(line)
        if match is None:
            continue
        heading = line.rstrip()
        counts[heading] += 1
        headings.append((line_index, len(match.group(1)), heading, counts[heading]))

    identities = [_section_identity("frontmatter")] * len(visible_lines)
    for heading_index, (line_index, level, heading, occurrence) in enumerate(headings):
        previous = next(
            (candidate[2] for candidate in reversed(headings[:heading_index]) if candidate[1] <= level), "START"
        )
        following = next((candidate[2] for candidate in headings[heading_index + 1 :] if candidate[1] <= level), "END")
        identity = f"{_section_identity(heading, occurrence)} [between {previous} -> {following}]"
        next_line = headings[heading_index + 1][0] if heading_index + 1 < len(headings) else len(visible_lines)
        identities[line_index:next_line] = [identity] * (next_line - line_index)
    return identities


def _markdown_view(text: str) -> tuple[list[str], list[str], str]:
    state = _MarkdownVisibility()
    raw_lines = text.splitlines()
    visible_lines = [_visible_markdown_line(line, state) for line in raw_lines]
    unescaped_lines = [unescape(line) for line in visible_lines]
    definitions = [(_REFERENCE_DEFINITION.match(line), line) for line in unescaped_lines]
    references = frozenset(_reference_label(match.group(1)) for match, _ in definitions if match is not None)
    rendered = "\n".join(
        "" if match is not None else _render_markdown_inline(line, references) for match, line in definitions
    )
    return raw_lines, visible_lines, rendered


def _bind_expected_routes(raw_records: tuple[tuple[str, str, str], ...]) -> tuple[tuple[str, str, str], ...]:
    views: dict[str, tuple[list[str], list[str]]] = {}
    bound: list[tuple[str, str, str]] = []
    for relative, section, expected_line in raw_records:
        suffix = Path(relative).suffix
        if suffix != ".md":
            bound.append((relative, _section_identity(section), expected_line))
            continue
        if relative not in views:
            raw_lines, visible_lines, _ = _markdown_view((SKILLS_DIR / relative).read_text(encoding="utf-8"))
            views[relative] = raw_lines, _section_identities(visible_lines)
        raw_lines, identities = views[relative]
        candidates = [
            identity
            for line, identity in zip(raw_lines, identities, strict=True)
            if line == expected_line and identity.startswith(f"{_section_identity(section)} ")
        ]
        assert len(candidates) == 1, (relative, section, expected_line, candidates)
        bound.append((relative, candidates[0], expected_line))
    return tuple(bound)


def _route_records_for_members(members: dict[str, bytes]) -> tuple[tuple[str, str, str], ...]:
    records: list[tuple[str, str, str]] = []
    skill_order = {skill: index for index, skill in enumerate(TARGET_SKILLS)}
    ordered_members = sorted(
        members.items(),
        key=lambda item: (
            skill_order.get(item[0].split("/", 1)[0], len(skill_order)),
            item[0] != "wf-new/references/ideate.md",
            item[0],
        ),
    )
    for relative, payload in ordered_members:
        text = _contract_text(payload)
        if text is None:
            continue
        for token in _ROUTE_TOKEN.finditer(text):
            if token.group() not in _ROUTES:
                records.append((relative, "malformed-token", token.group()))

        suffix = Path(relative).suffix
        raw_lines = text.splitlines()
        if suffix == ".md":
            raw_lines, visible_lines, rendered = _markdown_view(text)
            section_identities = _section_identities(visible_lines)
        else:
            visible_lines = raw_lines
            rendered = unescape("\n".join(visible_lines))
            section = "yaml" if suffix in {".yaml", ".yml"} else "text"
            section_identities = [_section_identity(section)] * len(raw_lines)
        exact_visible_tokens: Counter[str] = Counter()
        for line, visible_line, section_identity in zip(raw_lines, visible_lines, section_identities, strict=True):
            raw_has_route = any(route in line for route in _ROUTES)
            has_route = any(route in visible_line for route in _ROUTES)
            if raw_has_route and not has_route:
                records.append((relative, "inactive", line))
            if has_route:
                records.append((relative, section_identity, line))
                exact_visible_tokens.update({token: visible_line.count(token) for token in _ROUTES})
        rendered_tokens = Counter(match.group() for match in _ROUTE_TOKEN.finditer(rendered))
        syntax_tokens = Counter(match.group() for match in _ROUTE_TOKEN.finditer(_normalized_route_syntax(text)))
        rendered_tokens |= syntax_tokens
        for token, count in rendered_tokens.items():
            if token not in _ROUTES or count > exact_visible_tokens[token]:
                records.append((relative, "rendered-token", token))
    return tuple(records)


EXPECTED_ACTIVE_ROUTES = _bind_expected_routes(_RAW_EXPECTED_ACTIVE_ROUTES)


def _run(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _archive_target_members(wheel: Path, sdist: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
    wheel_members: dict[str, bytes] = {}
    wheel_prefix = "youtube_automation/_skills/"
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if not name.startswith(wheel_prefix) or name.endswith("/"):
                continue
            relative = name.removeprefix(wheel_prefix)
            if _is_target_member(relative):
                wheel_members[relative] = archive.read(name)

    sdist_members: dict[str, bytes] = {}
    marker = "/.claude/skills/"
    with tarfile.open(sdist, "r:gz") as archive:

        def member_bytes(member: tarfile.TarInfo) -> bytes:
            if member.issym():
                target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
                return member_bytes(archive.getmember(target))
            if member.islnk():
                return member_bytes(archive.getmember(member.linkname))
            extracted = archive.extractfile(member)
            assert extracted is not None
            return extracted.read()

        for member in archive.getmembers():
            # hatch may encode duplicate payloads as tar link members.
            if not (member.isfile() or member.islnk() or member.issym()) or marker not in member.name:
                continue
            relative = member.name.split(marker, 1)[1]
            if not _is_target_member(relative):
                continue
            sdist_members[relative] = member_bytes(member)
    return wheel_members, sdist_members


def _tree_target_members(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for skill in TARGET_SKILLS
        for path in sorted((root / skill).rglob("*"))
        if path.is_file() and _is_target_member(path.relative_to(root).as_posix())
    }


def test_initial_occurrences_have_a_complete_context_ledger() -> None:
    historical_skills = {entry[0] for entry in INITIAL_OCCURRENCE_LEDGER}
    current_owners = {
        "alignment-check": "audit",
        "collection-ideate": "wf-new",
        "lyria": "music",
        "metadata-audit": "audit",
        "playlist": "publish",
        "short-thumbnail": "short",
        "value-loop-audit": "audit",
        "flop-analysis": "analytics",
    }
    assert {current_owners.get(skill, skill) for skill in historical_skills} == set(TARGET_SKILLS)
    assert {entry[3] for entry in INITIAL_OCCURRENCE_LEDGER} <= set(CONTEXTS)
    assert len({(skill, path, occurrence) for skill, path, occurrence, _ in INITIAL_OCCURRENCE_LEDGER}) == len(
        INITIAL_OCCURRENCE_LEDGER
    )
    counts = Counter(entry[3] for entry in INITIAL_OCCURRENCE_LEDGER)
    assert {context: counts[context] for context in CONTEXTS} == INITIAL_CONTEXT_COUNTS


def test_active_routes_match_the_section_and_complete_line_contract() -> None:
    assert _active_route_records() == EXPECTED_ACTIVE_ROUTES


def test_route_contract_rejects_inactive_swap_mixed_and_relocated_mutations() -> None:
    relative = "audit/references/alignment.md"
    source = (SKILLS_DIR / relative).read_text(encoding="utf-8")
    opening = "- **新規チャンネル** → `/setup --channel` を案内"
    existing = "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内"
    premise_block = source[source.index("## 前提\n") : source.index("## 実行フロー\n")]
    mutations = (
        source.replace(opening, f"~~{opening}~~", 1),
        source.replace(opening, f"~~\n{opening}\n~~", 1),
        source.replace(opening, f"<!-- {opening} -->", 1),
        source.replace(opening, f"<!--\n{opening}\n-->", 1),
        source.replace(opening, f"<s>\n{opening}\n</s>", 1),
        source.replace(opening, f'<DEL class="muted">\n{opening}\n</DEL>', 1),
        source.replace(opening, f'<s\n data-note=">">\n{opening}\n</s>', 1),
        source.replace(opening, f'<div data-route="\n{opening}\n">visible</div>', 1),
        source.replace(opening, f"<div hidden>\n{opening}\n</div>", 1),
        source.replace(opening, f'<div hidden="">\n{opening}\n</div>', 1),
        source.replace(opening, f'<div hidden="false">\n{opening}\n</div>', 1),
        source.replace(opening, f'<div hidden="anything">\n{opening}\n</div>', 1),
        source.replace(opening, f'<div style="display:none">\n{opening}\n</div>', 1),
        source.replace(opening, f'<div style="visibility:hidden">\n{opening}\n</div>', 1),
        source.replace(opening, f'<div style="display:/**/none">\n{opening}\n</div>', 1),
        source.replace(opening, f"<template>\n{opening}\n</template>", 1),
        source.replace(opening, f'<script type="text/plain">\n{opening}\n</script>', 1),
        source.replace(opening, f"<style>\n{opening}\n</style>", 1),
        source.replace(opening, f"<details><summary>why</summary>\n{opening}\n</details>", 1),
        source.replace(opening, f"<details hidden>\n{opening}\n</details>", 1),
        source.replace(opening, f"{opening} {existing}", 1),
        source.replace(opening, opening.replace("/setup --channel", "/channel-strategy --direction"), 1).replace(
            existing, existing.replace("/setup --import", "/setup --channel"), 1
        ),
        source.replace(opening + "\n", "", 1).replace("## Next Step", f"## Next Step\n\n{opening}", 1),
        source.replace(opening + "\n", "", 1).replace("## Next Step", f"## 前提\n\n{opening}\n\n## Next Step", 1),
        source.replace("`/setup --import`", "`/setup --\nimport`", 1),
        source.replace(premise_block, "", 1).replace("## Next Step", premise_block + "## Next Step", 1),
        source + "\nrendered split: `/channel-<!-- hidden -->new`\n",
        source + "\nrendered split: `/channel-<wbr>new`\n",
        source + "\nrendered entity: `/channel-&#110;ew`\n",
        source + "\nrendered setup: `/setup <!-- hidden -->--channel`\n",
        source + "\nrendered emphasis: /channel-**new**\n",
        source + "\nrendered setup emphasis: /setup **--channel**\n",
        source + "\nrendered link: /channel-[new](https://example.invalid)\n",
        source + "\nrendered single emphasis: /channel-*new*\n",
        source + "\nrendered setup single emphasis: /setup _--channel_\n",
        source + "\nrendered reference link: /channel-[new][route]\n\n[route]: https://example.invalid\n",
        source + "\nrendered collapsed reference link: /channel-[new][]\n\n[new]: https://example.invalid\n",
    )
    for mutated in mutations:
        assert _active_route_records({relative: mutated}) != EXPECTED_ACTIVE_ROUTES


def test_route_contract_rejects_arbitrary_extension_members(tmp_path: Path) -> None:
    relative = "audit/references/reintroduced.txt"
    reintroduced = tmp_path / relative
    reintroduced.parent.mkdir(parents=True)
    reintroduced.write_text("opening fallback: `/channel-strategy --direction`\n", encoding="utf-8")
    assert _active_route_records({relative: reintroduced.read_bytes()}) != EXPECTED_ACTIVE_ROUTES


def test_route_contract_allows_genuine_binary_without_route_tokens() -> None:
    png = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    assert _active_route_records({"audit/references/pixel.png": png}) == EXPECTED_ACTIVE_ROUTES


def test_route_contract_keeps_open_details_content_visible() -> None:
    relative = "audit/references/alignment.md"
    source = (SKILLS_DIR / relative).read_text(encoding="utf-8")
    opening = "- **新規チャンネル** → `/setup --channel` を案内"
    visible_details = source.replace(
        opening,
        f"<details open><summary>route details</summary>\n{opening}\n</details>",
        1,
    )
    assert _active_route_records({relative: visible_details}) == EXPECTED_ACTIVE_ROUTES


def test_inline_code_literals_do_not_change_markdown_or_html_visibility() -> None:
    relative = "audit/references/alignment.md"
    source = (SKILLS_DIR / relative).read_text(encoding="utf-8")
    opening = "- **新規チャンネル** → `/setup --channel` を案内"
    mutations = (
        source.replace(opening, f"`~~`\n{opening}", 1),
        source.replace(opening, f"`<div hidden>`\n{opening}", 1),
    )
    for mutated in mutations:
        assert _active_route_records({relative: mutated}) == EXPECTED_ACTIVE_ROUTES


def test_route_contract_allows_supported_distributed_binary_images() -> None:
    images = {
        "pixel.jpg": b64decode(
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDi6KKK+ZP3E//Z"
        ),
        "pixel.gif": b64decode("R0lGODdhAQABAIEAAP8AAAAAAAAAAAAAACwAAAAAAQABAAAIBAABBAQAOw=="),
        "pixel.webp": b64decode(
            "UklGRjwAAABXRUJQVlA4IDAAAADQAQCdASoBAAEAAUAmJaACdLoB+AADsAD+8ut//NgVzXPv9//S4P0uD9Lg/9KQAAA="
        ),
    }
    for filename, payload in images.items():
        assert _active_route_records({f"audit/references/{filename}": payload}) == EXPECTED_ACTIVE_ROUTES


def test_route_contract_fails_closed_for_undecodable_text_or_route_bearing_binary() -> None:
    text_like = b"opening fallback: \xff\n"
    route_bearing_png = b"\x89PNG\r\n\x1a\n/channel-strategy --direction\xff"
    with pytest.raises(UnicodeDecodeError):
        _active_route_records({"audit/references/broken.txt": text_like})
    with pytest.raises(UnicodeDecodeError):
        _active_route_records({"audit/references/route.png": route_bearing_png})


def test_source_wheel_sdist_and_installed_downstream_share_the_complete_route_contract(tmp_path: Path) -> None:
    source_members = _tracked_target_members()
    dist = tmp_path / "dist"
    built = _run("uv", "build", "--out-dir", dist, cwd=REPO_ROOT)
    assert built.returncode == 0, built.stdout + built.stderr
    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    wheel_members, sdist_members = _archive_target_members(wheel, sdist)

    # Exact path and byte equality proves arbitrary extensions cannot disappear
    # between the tracked source, wheel, and sdist before route parsing.
    assert wheel_members == source_members
    assert sdist_members == source_members
    assert _route_records_for_members(wheel_members) == EXPECTED_ACTIVE_ROUTES
    assert _route_records_for_members(sdist_members) == EXPECTED_ACTIVE_ROUTES

    venv = tmp_path / "venv"
    created = _run("uv", "venv", venv, cwd=REPO_ROOT)
    assert created.returncode == 0, created.stdout + created.stderr
    installed = _run("uv", "pip", "install", "--python", venv / "bin" / "python", wheel, cwd=REPO_ROOT)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    downstream = tmp_path / "downstream-skills"
    synced = _run(
        venv / "bin" / "yt-skills",
        "sync",
        "--asset",
        "skills",
        "--target",
        downstream,
        "--force",
        cwd=tmp_path,
    )
    assert synced.returncode == 0, synced.stdout + synced.stderr
    downstream_members = _tree_target_members(downstream)
    assert downstream_members == source_members
    assert _route_records_for_members(downstream_members) == EXPECTED_ACTIVE_ROUTES
