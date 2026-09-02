"""SKILL.md と公開 skill ページの動的生成契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _DEV_ONLY_SKILL_NAMES

SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"
FEATURES_PATH = REPO_ROOT / "docs" / "features.md"
SOURCE_PATH = REPO_ROOT / "site" / "skill-page-source.ts"


def _skill_names() -> set[str]:
    return {path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md")}


def _site_dev_only_skill_names() -> set[str]:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export const DEV_ONLY_SKILL_NAMES = new Set\(\[([\s\S]*?)\]\);",
        source,
    )
    assert match is not None
    return set(re.findall(r'"([a-z0-9-]+)"', match.group(1)))


def _catalog_names() -> list[str]:
    return re.findall(r"^\| /([a-z0-9-]+) \|", FEATURES_PATH.read_text(encoding="utf-8"), re.MULTILINE)


def _introduction_counts(features: str) -> list[int]:
    """冒頭（最初の `## ` 見出しより前）に書かれた skill 件数表記を全て拾う。"""
    introduction = features.split("## ", 1)[0]
    return [int(value) for value in re.findall(r"(\d+)\s*個", introduction)]


def test_skill_catalog_matches_all_distributed_skills() -> None:
    skill_names = _skill_names() - _DEV_ONLY_SKILL_NAMES
    catalog_names = _catalog_names()

    assert len(skill_names) == 19
    assert len(catalog_names) == len(set(catalog_names))
    assert set(catalog_names) == skill_names

    # 件数表記は無くてもよいが、書くなら実数と一致していること。
    features = FEATURES_PATH.read_text(encoding="utf-8")
    assert all(count == len(skill_names) for count in _introduction_counts(features))


def test_site_dev_only_skills_match_distribution_source_of_truth() -> None:
    assert _site_dev_only_skill_names() == _DEV_ONLY_SKILL_NAMES


def test_stale_skill_count_in_introduction_is_detected() -> None:
    """件数チェックが vacuous に成立しない（stale な件数を実際に検出できる）ことを固定する。"""
    stale = "# できることから skill を探す\n\nskill は全部で 40 個あります。\n\n## ワークフロー管理\n"

    assert _introduction_counts(stale) == [40]
    assert _introduction_counts(stale.replace("40 個", "22 個")) == [22]
    assert _introduction_counts("# 見出し\n\n個別の使い分けは別ページへ。\n\n## カテゴリ\n") == []
    assert _introduction_counts("# 見出し\n\n## カテゴリ\n\n全 40 個と書かれた本文\n") == []


def test_skill_catalog_keeps_exactly_nine_categories() -> None:
    features = FEATURES_PATH.read_text(encoding="utf-8")
    categories = re.findall(r"^## ([^\n]+)\n(?:(?!^## ).)*?^\| /", features, re.MULTILINE | re.DOTALL)

    assert categories == [
        "ワークフロー管理",
        "チャンネル立ち上げ",
        "オーディエンス・ポジショニング検証",
        "企画・コンテンツ生成",
        "公開・運用",
        "分析・振り返り",
        "ベンチマーク",
        "配信インフラ",
        "リポジトリメンテ",
    ]


def test_every_skill_has_stable_page_inputs() -> None:
    for skill_path in SKILLS_ROOT.glob("*/SKILL.md"):
        markdown = skill_path.read_text(encoding="utf-8")
        assert re.search(r"^name: [a-z0-9-]+$", markdown, re.MULTILINE), skill_path.parent.name
        assert re.search(r'^description: "(?:[^"\\]|\\.)*"$', markdown, re.MULTILINE), skill_path.parent.name
        assert "## 前後工程\n" in markdown, skill_path.parent.name


def test_site_build_owns_dynamic_skill_routes_without_python_runtime() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    config = (REPO_ROOT / "site/blume.config.ts").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github/workflows/site.yml").read_text(encoding="utf-8")

    assert 'resolve(repositoryRoot, ".claude/skills")' in source
    assert 'resolve(repositoryRoot, "docs/features.md")' in source
    assert 'slug: "/skills"' not in source  # index and pages share the same sourceEntry path
    assert '"/skills"' in source and "`/skills/${skill.name}`" in source
    assert "createSkillPageSource" in config
    assert '".claude/skills/**"' in workflow
    assert "python" not in source.lower()
