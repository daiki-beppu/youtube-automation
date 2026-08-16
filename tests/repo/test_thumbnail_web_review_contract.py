from tests.helpers.paths import REPO_ROOT

SKILL = (REPO_ROOT / ".claude/skills/thumbnail/SKILL.md").read_text(encoding="utf-8")
REFERENCE = (REPO_ROOT / ".claude/skills/thumbnail/references/web-review.md").read_text(encoding="utf-8")


def test_manual_thumbnail_review_uses_product_neutral_cli_and_fixed_sidecars() -> None:
    assert "yt-thumbnail-review --collection <collection-path> --artifact thumbnail" in SKILL
    assert "--artifact main" in SKILL
    assert "--pattern <name>" in SKILL
    assert "直接 `cp` しない" in SKILL
    assert "<画像filename>.review.json" in REFERENCE
    assert '"image_sha256"' in REFERENCE
    assert '"thumbnail_check"' in REFERENCE
    assert '"comparison_qa"' in REFERENCE
    assert '"metadata"' in REFERENCE
    assert '"evidence"' in REFERENCE
    assert '"constraints"' in REFERENCE


def test_review_contract_keeps_auto_and_terminal_paths_explicit() -> None:
    assert "yt-thumbnail-auto-select --apply" in SKILL
    assert "--transport terminal" in SKILL
    assert "--candidate-id <ID>" in SKILL
    assert "tmp/reviews/thumbnail-selection.html" in REFERENCE
    assert "原寸と実幅320px" in REFERENCE
    assert "外部URL" in REFERENCE and "symlink" in REFERENCE
