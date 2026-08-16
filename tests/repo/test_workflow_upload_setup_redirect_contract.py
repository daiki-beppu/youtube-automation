"""Workflow/upload opening routes owned by ``/setup --channel``."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from hashlib import sha256
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
TARGET_SKILLS = (
    "analytics",
    "automation-schedule",
    "automation",
    "video",
    "publish",
    "wf-auto",
    "wf-new",
    "wf-next",
    "wf-status",
    "wf-new-batch",
)
CONTEXTS = (
    "opening",
    "import",
    "regenerate",
    "push",
    "analysis",
    "direction",
    "shared-reference",
)
ROUTES = (
    "/channel-strategy --direction",
    "/setup --channel",
    "/setup --import",
    "/setup --regenerate",
    "/setup --push",
)


def _entry(skill: str, path: str, occurrence: str, context: str) -> tuple[str, str, str, str]:
    return skill, path, occurrence, context


# Every literal /channel-strategy --direction occurrence on main before #3986, classified by context.
INITIAL_OCCURRENCE_LEDGER = (
    _entry("analytics", "SKILL.md", "common-missing-config", "opening"),
    _entry("analytics", "references/analyze.md", "missing-config-new", "opening"),
    _entry("analytics", "references/analyze.md", "missing-config-existing", "import"),
    _entry("analytics", "references/collect.md", "missing-config-new", "opening"),
    _entry("analytics", "references/collect.md", "missing-config-existing", "import"),
    _entry("analytics", "references/report.md", "missing-config-new", "opening"),
    _entry("analytics", "references/report.md", "missing-config-existing", "import"),
    _entry("automation-schedule", "SKILL.md", "upstream-new-channel", "opening"),
    _entry(
        "automation-schedule",
        "references/detect_runtime.sh",
        "workflow-config-regeneration",
        "regenerate",
    ),
    _entry("automation", "references/update.md", "initial-save-commit", "push"),
    _entry("analytics", "references/status.md", "upstream-new-channel", "opening"),
    _entry("analytics", "references/status.md", "missing-config-new", "opening"),
    _entry("analytics", "references/status.md", "missing-config-existing", "import"),
    _entry("video", "references/describe.md", "missing-config-new", "opening"),
    _entry("video", "references/describe.md", "missing-config-existing", "import"),
    _entry("video", "references/describe.md", "config-generation-rules", "shared-reference"),
    _entry("publish", "references/upload.md", "missing-config-new", "opening"),
    _entry("publish", "references/upload.md", "missing-config-existing", "import"),
    _entry("wf-auto", "SKILL.md", "missing-config-new", "opening"),
    _entry("wf-auto", "SKILL.md", "load-config-existing", "import"),
    _entry("wf-new", "SKILL.md", "upstream-new-channel", "opening"),
    _entry("wf-new", "SKILL.md", "prerequisite-missing-config", "opening"),
    _entry("wf-new", "SKILL.md", "prerequisite-load-failure", "import"),
    _entry("wf-new", "SKILL.md", "hard-gate-missing-config", "opening"),
    _entry("wf-new", "SKILL.md", "hard-gate-load-failure", "import"),
    _entry("wf-next", "SKILL.md", "missing-config-new", "opening"),
    _entry("wf-next", "SKILL.md", "missing-config-existing", "import"),
    _entry("wf-status", "SKILL.md", "missing-config-new", "opening"),
    _entry("wf-status", "SKILL.md", "missing-config-existing", "import"),
    _entry("wf-new-batch", "SKILL.md", "upstream-new-channel", "opening"),
    _entry("wf-new-batch", "SKILL.md", "hard-gate-missing-config", "opening"),
)
INITIAL_CONTEXT_COUNTS = {
    "opening": 17,
    "import": 11,
    "regenerate": 1,
    "push": 1,
    "analysis": 0,
    "direction": 0,
    "shared-reference": 1,
}
MIXED_ROUTE_SPLITS = {
    ("analytics", "common-missing-config"),
    ("wf-auto", "missing-config-new"),
    ("wf-auto", "load-config-existing"),
    ("wf-new", "prerequisite-missing-config"),
    ("wf-new", "prerequisite-load-failure"),
    ("wf-new", "hard-gate-missing-config"),
    ("wf-new", "hard-gate-load-failure"),
    ("wf-new-batch", "hard-gate-missing-config"),
}


def _route(path: str, section: str, line: str) -> tuple[str, str, str]:
    return path, section, line


# Exact active Markdown records after #3986. Split records make opening/import
# ownership observable without allowing a single mixed route line.
EXPECTED_ACTIVE_ROUTES = (
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
    *(
        _route(f"analytics/references/{mode}.md", "## 前提", line)
        for mode in ("analyze", "collect", "flop")
        for line in (
            "- **新規チャンネル** → `/setup --channel` を案内",
            "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
        )
    ),
    _route(
        "analytics/references/flop.md",
        "### Phase 4: 検証の自律実行",
        "- `/audit --alignment`、`/channel-research --voice`、`/channel-strategy --persona`、"
        "`/channel-strategy --scene`、`/channel-strategy --direction` はスキルとして起動しない。"
        "これらは別成果物の保存または設定更新を完了条件に含むため、既存の検証済み "
        "`docs/plans/alignment-audit.json`、`docs/plans/viewer-voice-analysis.md`、"
        "`docs/channel/personas/persona-definition.md`、`docs/plans/viewing-scene-matrix.md` がある場合だけ "
        "read-only 入力として読む。alignment は HTML ではなく JSON だけを入力とする。"
        "必要な成果物がなければ、その仮説を理由付きの `未検証` とする",
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
    *(
        _route("analytics/references/report.md", "## 前提", line)
        for line in (
            "- **新規チャンネル** → `/setup --channel` を案内",
            "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
        )
    ),
    _route(
        "analytics/references/status.md",
        "## 前後工程",
        "- `前工程`: `/setup --channel`",
    ),
    *(
        _route("analytics/references/status.md", "## 前提", line)
        for line in (
            "- **新規チャンネル** → `/setup --channel` を案内",
            "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
        )
    ),
    *(
        _route("video/references/describe.md", "## 前提", line)
        for line in (
            "- **新規チャンネル** → `/setup --channel` を案内",
            "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
        )
    ),
    _route(
        "video/references/describe.md",
        "### 必須要素",
        "4. **ハッシュタグ**: `config/channel/content.json::descriptions.hashtags` が単一ソース"
        "（実装 `domains/metadata/service.py` は設定値をそのまま出力する。個数の目安は "
        "`/setup --regenerate` の config-generation-rules と同じ **5 個程度**）— YouTube は概要欄の最初の"
        "3ハッシュタグをタイトル下に表示するため、順序が重要",
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
    *(
        _route("publish/references/upload.md", "## 前提", line)
        for line in (
            "- **新規チャンネル** → `/setup --channel` を案内",
            "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
        )
    ),
    _route(
        "wf-new/SKILL.md",
        "## 前後工程",
        "- `前工程`: `/setup --channel`, `/setup`",
    ),
    _route(
        "wf-new/SKILL.md",
        "## 前提",
        "- `config/channel/` が存在しない場合は `/setup --channel` を案内して停止する",
    ),
    _route(
        "wf-new/SKILL.md",
        "## 前提",
        "- `config/channel/` が存在しても `load_config()` が失敗する場合は `/setup --import` を案内して停止する",
    ),
    _route(
        "wf-new/SKILL.md",
        "## Hard Gates",
        "   - 存在しない場合は `/setup --channel` を案内して停止する。",
    ),
    _route(
        "wf-new/SKILL.md",
        "## Hard Gates",
        "   - `load_config()` が失敗する場合は `/setup --import` を案内して停止する。",
    ),
    _route(
        "wf-new/references/auto.md",
        "## 実行手順",
        "1. `config/channel/` が無ければ `/setup --channel` を案内して停止する。",
    ),
    _route(
        "wf-new/references/auto.md",
        "## 実行手順",
        "   `load_config()` が失敗した場合は`/setup --import` を案内して停止する。"
        "state resolver または上記子 skill が無ければ `/automation --update`（本リポジトリ内では "
        "`yt-skills sync`）を案内して停止する。すべて満たすまで lease と子 skill を開始しない。",
    ),
    _route(
        "wf-new/references/batch.md",
        "## 前後工程",
        "- `前工程`: `/setup --channel`, `/setup`",
    ),
    _route(
        "wf-new/references/batch.md",
        "## Hard Gates",
        "   - `config/channel/` が存在しない場合は `/setup --channel` を案内して停止する。",
    ),
    _route(
        "wf-new/references/batch.md",
        "## Hard Gates",
        "   - `load_config()` が失敗する場合は `/setup --import` を案内して停止する。",
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
        "wf-new/references/schedule.md",
        "## 前後工程",
        "- `前工程`: `/setup --channel`, `/setup`",
    ),
    *(
        _route(f"{skill}/SKILL.md", "## 前提", line)
        for skill in ("wf-next", "wf-status")
        for line in (
            "- **新規チャンネル** → `/setup --channel` を案内",
            "- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内",
        )
    ),
)

MUTABLE_FILES = frozenset(
    path for path, _, _ in EXPECTED_ACTIVE_ROUTES if path != "automation/references/update.md"
) | {
    "analytics/references/analysis-json-validator.md",
    "analytics/config.default.yaml",
    "analytics/references/flop.md",
    "analytics/references/insights-entry.schema.json",
    "analytics/references/verification.py",
    "audit/references/audit-chain-manifest.json",
    "publish/SKILL.md",
    "publish/config.default.yaml",
    "publish/references/posting-checklist.md",
    "publish/references/community.md",
    "publish/references/clean.md",
    "publish/references/clean-scan.py",
    "publish/references/generate_batch.py",
    "publish/references/pinned.md",
    "publish/references/publish-chain-manifest.json",
    "publish/references/publish-chain-state.py",
    "publish/references/upload.md",
    "publish/references/scheduled-publish.md",
    "wf-new/references/phase-2c-artifact-contract.md",
    "wf-new/references/phase2.md",
    "wf-new/references/auto.md",
    "wf-new/references/batch.md",
    "wf-new/references/batch-ledger.py",
    "wf-new/references/schedule.md",
    "wf-new/references/detect_runtime.sh",
    "wf-new/references/run_scheduled.sh",
    "wf-new/references/run-sandwich.sh",
    "wf-new/references/run-github-actions.sh",
    "wf-new/references/github_actions_schedule.py",
    "wf-new/references/github-actions-oauth.md",
    "wf-new/references/schedule_backend.py",
    "wf-new/references/schedule_config.py",
    "wf-new/references/scheduler_job.sh",
    "wf-new/references/schema.md",
    "wf-new/references/validate-batch-manifest.py",
    "wf-new/references/wf-auto-state.py",
    "wf-next/references/master_audio_transition.py",
    "wf-new/references/collection-ideate.config.default.yaml",
    "wf-new/references/collection-plan-documents.md",
    "wf-new/references/collection-plan.schema.json",
    "music/references/music-prompt.schema.json",
    "music/references/music-prompt-documents.md",
    "wf-new/references/collection-lifecycle.md",
    "wf-new/references/freshness_action.py",
    "wf-new/references/generate_image.py",
    "wf-new/references/object-design-examples.md",
    "wf-new/references/planning-rules.md",
    "wf-new/references/preview-contract.md",
    "wf-new/references/preview-generation.md",
    "wf-new/references/record-ttp-reference-assignments.py",
    "wf-new/references/select-ttp-references.py",
    "wf-new/references/selection-handoff.md",
    "channel-research/SKILL.md",
    "channel-research/references/benchmark.md",
    "channel-research/references/channel-research-chain-manifest.json",
    "channel-research/references/channel-research-chain-state.py",
    "channel-research/references/channel-research-report.schema.json",
    "channel-research/references/market.md",
    "channel-research/references/market_research_contract.py",
    "channel-research/references/report-contract.md",
    "channel-research/references/structured-report.md",
    "channel-research/references/thumbnail.md",
    "channel-research/references/voice.md",
    "channel-strategy/SKILL.md",
    "channel-strategy/references/channel-strategy-chain-manifest.json",
    "channel-strategy/references/channel-strategy-chain-state.py",
    "channel-strategy/references/direction.md",
    "channel-strategy/references/persona.md",
    "channel-strategy/references/persona_flow.py",
    "channel-strategy/references/scene.md",
    "setup/references/channel-mode.md",
    "setup/references/setup-chain-manifest.json",
    "setup/references/setup-chain-state.py",
    "thumbnail/SKILL.md",
    "video/SKILL.md",
    "video/config.default.yaml",
    "video/references/describe.md",
    "video/references/generate.md",
    "video/references/master-video-review.md",
    "video/references/description-templates.md",
    "video/references/video-chain-manifest.json",
    "video/references/video-chain-state.py",
    "video/references/video-description-documents.md",
    "video/references/video-description.schema.json",
    "wf-new/references/freshness-rules.md",
    "wf-new/references/ideate.md",
    "wf-next/SKILL.md",
}
EXPECTED_ISSUE_3986_CHANGED_PATHS = frozenset(
    {
        ".claude/skills/analytics/SKILL.md",
        ".claude/skills/analytics/references/analyze.md",
        ".claude/skills/analytics/references/collect.md",
        ".claude/skills/analytics/references/report.md",
        ".claude/skills/automation-schedule/SKILL.md",
        ".claude/skills/channel-status/SKILL.md",
        ".claude/skills/video-description/SKILL.md",
        ".claude/skills/video-upload/SKILL.md",
        ".claude/skills/wf-auto/SKILL.md",
        ".claude/skills/wf-new-batch/SKILL.md",
        ".claude/skills/wf-new/SKILL.md",
        ".claude/skills/wf-next/SKILL.md",
        ".claude/skills/wf-status/SKILL.md",
        "CHANGELOG.md",
        "tests/conftest.py",
        "tests/repo/test_skill_docs_consistency.py",
        "tests/repo/test_workflow_upload_setup_redirect_contract.py",
    }
)
IMMUTABLE_TARGET_FILES_SHA256 = "58a9bec6e2a90aae5fd736da344cea0b6f3f452881f3b0e31cb7b145e174bfb6"
AUTOMATION_SCHEDULE_REGENERATE_SHA256 = "11d460f727fe50c41f00571b416a1486cb07d0b1548524bc650a7161c16f6c42"
AUTOMATION_UPDATE_PUSH_SHA256 = "ced3211760d9ff0abd20ec3cdc402501b424f48581ef3a618d51c0d9ee12840c"
ALLOWED_FENCED_ROUTES = {
    (
        "automation/references/update.md",
        "> /setup --import 直後の初回保存が未完了なら、まず初回 commit を作成してください。",
    )
}
RAW_HTML_STRIKE_TAG = re.compile(
    r"^<\s*(?P<closing>/)?\s*(?:s|del)\b[\s\S]*>$",
    re.IGNORECASE,
)


def _without_html_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    visible: list[str] = []
    cursor = 0
    while cursor < len(line):
        if in_comment:
            comment_end = line.find("-->", cursor)
            if comment_end == -1:
                return "".join(visible), True
            cursor = comment_end + len("-->")
            in_comment = False
            continue
        comment_start = line.find("<!--", cursor)
        if comment_start == -1:
            visible.append(line[cursor:])
            break
        visible.append(line[cursor:comment_start])
        cursor = comment_start + len("<!--")
        in_comment = True
    return "".join(visible), in_comment


def _advance_raw_html_strike_state(
    line: str,
    pending_tag: str | None,
    tag_quote: str | None,
    strike_depth: int,
) -> tuple[str | None, str | None, int, bool, bool]:
    """Consume visible Markdown as a raw HTML tag stream across line boundaries."""
    line_is_struck = strike_depth > 0
    route_is_inside_tag = False
    cursor = 0
    while cursor < len(line):
        if pending_tag is None:
            tag_start = line.find("<", cursor)
            if tag_start == -1:
                break
            pending_tag = "<"
            tag_quote = None
            cursor = tag_start + 1
            continue
        if line.startswith(ROUTES, cursor):
            route_is_inside_tag = True
        char = line[cursor]
        if char == "<":
            # Broken/generic tags must not swallow a later real HTML token.
            # Resynchronizing also fails closed for a nested token in a quote.
            pending_tag = "<"
            tag_quote = None
            cursor += 1
            continue
        pending_tag += char
        cursor += 1
        if tag_quote:
            if char == tag_quote:
                tag_quote = None
            continue
        if char in {'"', "'"}:
            tag_quote = char
            continue
        if char != ">":
            continue
        strike_tag = RAW_HTML_STRIKE_TAG.fullmatch(pending_tag)
        if strike_tag:
            line_is_struck = True
            if strike_tag.group("closing"):
                strike_depth = max(0, strike_depth - 1)
            else:
                strike_depth += 1
        pending_tag = None
        tag_quote = None
    if pending_tag is not None:
        pending_tag += "\n"
    return pending_tag, tag_quote, strike_depth, line_is_struck, route_is_inside_tag


def _active_route_records(overrides: dict[str, str] | None = None) -> tuple[tuple[str, str, str], ...]:
    records: list[tuple[str, str, str]] = []
    for skill in TARGET_SKILLS:
        for path in sorted((SKILLS_DIR / skill).rglob("*.md")):
            relative = path.relative_to(SKILLS_DIR).as_posix()
            text = (
                overrides.get(relative, path.read_text(encoding="utf-8"))
                if overrides
                else path.read_text(encoding="utf-8")
            )
            section = "frontmatter"
            in_fence = False
            in_comment = False
            strike_depth = 0
            pending_tag: str | None = None
            tag_quote: str | None = None
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(("```", "~~~")):
                    in_fence = not in_fence
                    continue
                original_has_route = any(route in line for route in ROUTES)
                if in_fence:
                    if original_has_route and (relative, line) not in ALLOWED_FENCED_ROUTES:
                        records.append((relative, "inactive", line))
                    continue
                visible_line, in_comment = _without_html_comments(line, in_comment)
                has_route = any(route in visible_line for route in ROUTES)
                if original_has_route and not has_route:
                    records.append((relative, "inactive", line))
                if has_route and "~~" in visible_line:
                    records.append((relative, "inactive", line))
                    continue
                (
                    pending_tag,
                    tag_quote,
                    strike_depth,
                    route_is_struck,
                    route_is_inside_tag,
                ) = _advance_raw_html_strike_state(visible_line, pending_tag, tag_quote, strike_depth)
                route_is_struck = route_is_struck or route_is_inside_tag
                if route_is_struck:
                    if has_route:
                        records.append((relative, "inactive", line))
                    continue
                if visible_line.startswith("##"):
                    section = visible_line
                if has_route:
                    records.append((relative, section, line))
    return tuple(records)


def _aggregate_hash(paths: list[Path]) -> str:
    records = []
    for path in sorted(paths):
        digest = sha256(path.read_bytes()).hexdigest()
        records.append(f"{digest}  {path.relative_to(REPO_ROOT).as_posix()}\n")
    return sha256("".join(records).encode()).hexdigest()


def _issue_3986_changed_paths() -> frozenset[str]:
    commit = subprocess.run(
        ["git", "log", "-n", "1", "--format=%H", "--fixed-strings", "--grep=(#3986)", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert commit, "the #3986 implementation commit must be reachable from HEAD"
    changed = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return frozenset(changed)


def _diff_scope_matches(changed_paths: frozenset[str]) -> bool:
    return changed_paths == EXPECTED_ISSUE_3986_CHANGED_PATHS


def test_initial_occurrences_have_a_complete_context_ledger() -> None:
    assert len(INITIAL_OCCURRENCE_LEDGER) == 31
    assert {entry[0] for entry in INITIAL_OCCURRENCE_LEDGER} == set(TARGET_SKILLS)
    assert {entry[3] for entry in INITIAL_OCCURRENCE_LEDGER} <= set(CONTEXTS)
    counts = Counter(entry[3] for entry in INITIAL_OCCURRENCE_LEDGER)
    assert {context: counts[context] for context in CONTEXTS} == INITIAL_CONTEXT_COUNTS
    ledger_ids = {(skill, occurrence) for skill, _, occurrence, _ in INITIAL_OCCURRENCE_LEDGER}
    assert MIXED_ROUTE_SPLITS <= ledger_ids


def test_active_markdown_routes_match_the_section_and_complete_line_contract() -> None:
    actual = _active_route_records()
    assert actual == EXPECTED_ACTIVE_ROUTES
    for _, _, line in actual:
        assert sum(route in line for route in ROUTES) == 1


def test_route_contract_rejects_inactive_swap_mixed_and_relocated_mutations() -> None:
    relative, _, opening = next(record for record in EXPECTED_ACTIVE_ROUTES if "/setup --channel" in record[2])
    source = (SKILLS_DIR / relative).read_text(encoding="utf-8")
    residual = next(line for path, _, line in EXPECTED_ACTIVE_ROUTES if path == relative and "/setup --import" in line)

    mutations = (
        source.replace(opening, f"~~{opening}~~", 1),
        source.replace(opening, f"<s>\n{opening}\n</s>", 1),
        source.replace(opening, f'<DEL class="muted">\n{opening}\n</DEL>', 1),
        source.replace(opening, f'<s data-reason="obsolete">{opening}</s>', 1),
        source.replace(opening, f"<DeL>{opening}</dEl>", 1),
        source.replace(opening, f'<!-- note --> <s data-reason="obsolete">\n{opening}\n</s>', 1),
        source.replace(opening, f'<DEL class="x"><!-- note -->\n{opening}\n</DEL>', 1),
        source.replace(opening, f"<s><!-- note\ncontinued -->\n{opening}\n</s>", 1),
        source.replace(opening, f'<!-- note\ncontinued --> <DEL class="x">\n{opening}\n</DEL>', 1),
        source.replace(opening, f'<s\n class="x">\n{opening}\n</s>', 1),
        source.replace(opening, f'<DEL\n data-x="y">\n{opening}\n</DEL>', 1),
        source.replace(opening, f'<s data-a="1"\n data-b="2">\n{opening}\n</s\n >', 1),
        source.replace(opening, f'<DeL data-x="y"\n>\n{opening}\n</dEl>', 1),
        source.replace(opening, f'<S<!-- note -->\n class="x">\n{opening}\n</S>', 1),
        source.replace(opening, f'<del data-note=">"\n class="x">\n{opening}\n</del>', 1),
        source.replace(opening, f"<notatag\n<s>\n{opening}\n</s>", 1),
        source.replace(opening, f'<div class="unterminated\n<s>\n{opening}\n</s>', 1),
        source.replace(opening, f'<notatag\n<DEL class="x">\n{opening}\n</DEL>', 1),
        source.replace(opening, f'<div data-note="\n{opening}\n">visible</div>', 1),
        source.replace(opening, f'<div data-note="before <s>\n{opening}\n</s>">', 1),
        source.replace(opening, opening.replace("/setup --channel", "/channel-strategy --direction"), 1),
        source.replace(opening, f"{opening} {residual}", 1),
        source.replace(opening + "\n", "", 1).replace(
            "## 設定読み込みゲート", f"## 設定読み込みゲート\n\n{opening}", 1
        ),
        source.replace(opening, f"<!-- {opening} -->", 1),
    )
    for mutated in mutations:
        assert _active_route_records({relative: mutated}) != EXPECTED_ACTIVE_ROUTES


def test_issue_3986_commit_has_exact_semantic_diff_scope() -> None:
    assert _diff_scope_matches(_issue_3986_changed_paths())


def test_diff_scope_contract_rejects_missing_target_and_unrelated_skill_mutations() -> None:
    missing_target = EXPECTED_ISSUE_3986_CHANGED_PATHS - {".claude/skills/wf-status/SKILL.md"}
    unrelated_skill = EXPECTED_ISSUE_3986_CHANGED_PATHS | {".claude/skills/masterup/SKILL.md"}
    assert not _diff_scope_matches(missing_target)
    assert not _diff_scope_matches(unrelated_skill)


def test_residual_target_assets_and_sections_remain_byte_identical() -> None:
    target_roots = {SKILLS_DIR / skill for skill in TARGET_SKILLS}
    immutable_target = [
        path
        for root in target_roots
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and "__pycache__" not in path.parts
        and path.relative_to(SKILLS_DIR).as_posix() not in MUTABLE_FILES
    ]
    assert _aggregate_hash(immutable_target) == IMMUTABLE_TARGET_FILES_SHA256
    assert (
        sha256((SKILLS_DIR / "wf-new/references/detect_runtime.sh").read_bytes()).hexdigest()
        == AUTOMATION_SCHEDULE_REGENERATE_SHA256
    )
    assert (
        sha256((SKILLS_DIR / "automation/references/update.md").read_bytes()).hexdigest()
        == AUTOMATION_UPDATE_PUSH_SHA256
    )
