"""配布される skill / CLAUDE.md テンプレの参照が下流で解決できることを機械担保する。

issue #2567: PR #2566 で `.claude/CLAUDE.template.md` を 256 → 70 行へ再構成した際、
配布 skill 側から消えた節を指す参照が残り、下流チャンネルリポジトリで解決不能になった。
CI が通過したのはこの種の参照切れを検証する契約テストが無かったため。

規約は `docs/skill-design/skill-authoring-guidelines.md` の必須 3 点 3 番
「配布先で解決できる参照だけを書く」。同梱対象の判定は
`pyproject.toml::[tool.hatch.build.targets.wheel.force-include]` を正とする。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

_REPO_ROOT = REPO_ROOT
_SKILL_INVENTORY = SkillInventory(_REPO_ROOT)
_CLAUDE_TEMPLATE = _REPO_ROOT / ".claude" / "CLAUDE.template.md"
_RELEASE_SKILL = _SKILL_INVENTORY.skill_directory("automation-release") / "SKILL.md"
_RELEASE_CONTRACTS = _SKILL_INVENTORY.resolve_reference("automation-release", "references/release-contracts.md")
_CHANGELOG_PROMOTION = _SKILL_INVENTORY.resolve_reference("automation-release", "references/changelog-promotion.md")
_PREPARE_CHECKLIST = _SKILL_INVENTORY.resolve_reference("automation-release", "references/prepare-checklist.md")

# 配布ファイル内で走査する拡張子（prose / スクリプト双方に参照が現れうる）
_SCANNED_SUFFIXES = (".md", ".py", ".sh")

# `docs/...` 形式のリポジトリ内ドキュメント参照。相対 prefix (`../../`) は無視して末尾を拾う
_DOCS_REF = re.compile(r"docs/[A-Za-z0-9_/.-]+\.(?:md|html)")

# `CLAUDE.md §6` のような節番号参照。テンプレ再構成のたびに腐るため全面禁止する
_SECTION_REF = re.compile(r"CLAUDE\.md\s*§\s*\d+")

# ratchet: issue #2567 時点で既に存在した未解決参照。**新規追加は禁止**。
# 規約の適用方針「既存スキルの一括改修を本規約で要求しない」に従い現状を凍結し、
# 解消は issue #2568 で個別に行う。修正したらこの表から削除すること
# (test_known_unresolved_refs_are_still_present が stale entry を検出する)。
_KNOWN_UNRESOLVED: frozenset[tuple[str, str]] = frozenset()


def _wheel_included_paths() -> frozenset[str]:
    """`pyproject.toml` の wheel force-include に列挙された配布元パス。"""
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    return frozenset(force_include)


def _distributed_files() -> list[Path]:
    """wheel に同梱され `yt-skills sync` で下流へ配布されるテキストファイル。"""
    files = [
        path
        for skill_dir in _SKILL_INVENTORY.skill_directories()
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file() and path.suffix in _SCANNED_SUFFIXES
    ]
    files.append(_CLAUDE_TEMPLATE)
    return files


def _unresolvable_refs() -> set[tuple[str, str]]:
    """配布先で解決できない `docs/...` 参照を (参照元, 参照先) で返す。

    除外するもの:
    - force-include 済みの docs（`workflow-cheatsheet.md` / `features.md`）は下流にも届く
    - upstream に実体が無いパスは下流で生成される成果物（`docs/plans/` / `docs/channel/` 等）

    既知の限界: 2 番目の除外により、**upstream にも下流にも存在しないパス**（typo や
    削除済み doc への参照）は検出できない。下流生成物のパスと機械的に区別できないため。
    この網を広げるには「下流生成物パスの命名規約」を先に決める必要がある。
    """
    included = _wheel_included_paths()
    found: set[tuple[str, str]] = set()
    for path in _distributed_files():
        text = path.read_text(encoding="utf-8")
        for ref in _DOCS_REF.findall(text):
            if ref in included or not (_REPO_ROOT / ref).is_file():
                continue
            found.add((path.relative_to(_REPO_ROOT).as_posix(), ref))
    return found


def test_no_claude_md_section_number_references() -> None:
    """配布ファイルは `CLAUDE.md §N` 形式の節番号で参照してはならない。

    節番号はテンプレ再構成のたびに腐る（#2567 の実害）。参照したい内容があるなら
    節番号ではなく、配布される実ファイルへ直接リンクする。
    """
    offenders = [
        f"{path.relative_to(_REPO_ROOT).as_posix()}: {match}"
        for path in _distributed_files()
        for match in _SECTION_REF.findall(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "配布ファイルに CLAUDE.md の節番号参照が残っている（テンプレ再構成で腐る）:\n  " + "\n  ".join(offenders)
    )


def test_videoup_encoder_benchmark_contract_is_self_contained() -> None:
    """videoup の配布物だけで encoder 採用基準と安全な fallback を判断できる。"""
    skill = (_SKILL_INVENTORY.skill_directory("videoup") / "SKILL.md").read_text(encoding="utf-8")

    assert "median wall-clock が `libx264 medium` baseline より 20% 以上短い候補だけ" in skill
    assert "H.264 / yuv420p / profile / maxrate / bufsize / fps / AAC / duration" in skill
    assert (
        "VIDEOUP_BENCH_DURATION=60 VIDEOUP_BENCH_RUNS=3 "
        "bash .claude/skills/videoup/references/benchmark_overlay_encoders.sh"
    ) in skill
    assert "hardware encode は明示 opt-in" in skill
    assert "既定は引き続き `libx264`" in skill
    assert "1-frame 起動 probe 失敗時は `libx264` へ戻り" in skill
    assert "docs/benchmarks/videoup-overlay-encoder-2026-07-21.md" not in skill


def test_automation_release_routes_to_distributed_release_contracts() -> None:
    skill = _RELEASE_SKILL.read_text(encoding="utf-8")

    assert "references/release-contracts.md" in skill


def test_automation_release_auxiliary_references_route_to_release_contracts() -> None:
    promotion = _CHANGELOG_PROMOTION.read_text(encoding="utf-8")
    checklist = _PREPARE_CHECKLIST.read_text(encoding="utf-8")

    assert "release-contracts.md#python-migration-producer-contract" in promotion
    assert "release-contracts.md#python-migration-producer-contract" in checklist

    steps = tuple(promotion.index(f"### Step {number}:") for number in range(1, 4))
    assert steps == tuple(sorted(steps))
    for required in ("所要時間の目安", "local fix 衝突注意", "サマリ"):
        assert required in promotion
    for required in ("WARNING", "無くても abort はしない", "`AskUserQuestion`"):
        assert required in checklist


def test_python_release_migration_producer_contract_is_distributed() -> None:
    contract = _RELEASE_CONTRACTS.read_text(encoding="utf-8")

    for required in (
        "`[Unreleased]` 配下の `### Migration`",
        "所要時間の目安",
        "local fix 衝突注意",
        "サマリ",
        "warning",
        "`AskUserQuestion`",
        "無条件 abort しない",
    ):
        assert required in contract


def test_extension_release_distribution_contract_is_distributed() -> None:
    contract = _RELEASE_CONTRACTS.read_text(encoding="utf-8")

    for required in (
        "GitHub Release の zip",
        "suno-helper",
        "distrokid-helper",
        "community-helper",
        "統一 `ext-v*` tag 系列",
        "Python 本体 version と独立",
        "package version",
        "release asset 名",
    ):
        assert required in contract


def test_no_new_unresolvable_docs_references() -> None:
    """配布ファイルは wheel 非同梱の upstream docs を新たに参照してはならない。"""
    new_offenders = sorted(_unresolvable_refs() - _KNOWN_UNRESOLVED)
    assert new_offenders == [], (
        "下流チャンネルリポジトリで解決できない docs 参照が新規追加された。\n"
        "参照先を配布対象（同 skill の references/ / 他 skill の references/ / "
        "force-include 済み docs）へ移すこと:\n  " + "\n  ".join(f"{src} -> {dst}" for src, dst in new_offenders)
    )


def test_known_unresolved_refs_are_still_present() -> None:
    """解消済みの参照が allowlist に残り続けないようにする（ratchet の逆流防止）。"""
    stale = sorted(_KNOWN_UNRESOLVED - _unresolvable_refs())
    assert stale == [], (
        "allowlist に解消済みのエントリが残っている。_KNOWN_UNRESOLVED から削除すること:\n  "
        + "\n  ".join(f"{src} -> {dst}" for src, dst in stale)
    )


def test_workflow_cheatsheet_and_features_are_distributed() -> None:
    """allowlist の除外根拠（この 2 つは下流へ届く）が pyproject 側で維持されていること。"""
    included = _wheel_included_paths()
    for required in ("docs/workflow-cheatsheet.md", "docs/features.md", ".claude/CLAUDE.template.md"):
        assert required in included, (
            f"{required} が wheel force-include から外れている。"
            "配布 skill からの参照が下流で解決できなくなるため、外すなら参照側も同時に見直すこと"
        )
