"""`.claude/skills/suno/SKILL.md` が issue #692 の新フロー + fallback を記載するかを検証する。

issue #692 受け入れ基準: 「`.claude/skills/suno/SKILL.md` に新フローと fallback が記載されている」。

過去の iteration で SKILL.md が protected-path により未編集のまま REJECT が継続した
(family_tag: spec-noncompliance)。SKILL.md 本文はコード由来テストの対象外で、未反映でも
全テストが pass してしまうため、ドキュメント契約をこのテストで機械的に担保し再発を防ぐ。

検証する契約:
1. Chrome 拡張 + `yt-suno-serve` の自動投入フロー（Step 2.5）が記載されている。
2. 拡張が使えない／壊れたとき向けの手コピペ fallback 節が記載されている。
3. 自動投入が読む配信元 `suno-prompts.json` への言及がある。
"""

from __future__ import annotations

import re
from pathlib import Path

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "suno" / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_skill_md_exists() -> None:
    """Given リポジトリ
    When suno SKILL.md を探す
    Then ファイルが存在する。
    """
    assert SKILL_MD.exists(), f"{SKILL_MD} が存在しません"


def test_skill_md_documents_auto_inject_flow() -> None:
    """Given suno SKILL.md
    When 本文を読む
    Then Chrome 拡張 + `yt-suno-serve` の自動投入フロー（Step 2.5）が記載されている。
    """
    text = _read()
    for token in ("Step 2.5", "yt-suno-serve", "suno-helper", "連続実行"):
        assert token in text, f"SKILL.md に新フローの記載がない（`{token}` 不在）"


def test_skill_md_documents_serve_url_contract() -> None:
    """Given suno SKILL.md
    When 自動投入フローを読む
    Then 拡張が fetch する `suno-prompts.json` 配信元の言及がある。
    """
    text = _read()
    assert "suno-prompts.json" in text, "SKILL.md に配信元 `suno-prompts.json` の言及がない"
    assert "/prompts.json" in text, "SKILL.md に配信エンドポイント `/prompts.json` の言及がない"


def test_skill_md_documents_manual_fallback() -> None:
    """Given suno SKILL.md
    When 本文を読む
    Then 拡張が使えないときの手コピペ fallback 節が記載されている。
    """
    text = _read()
    assert "fallback" in text, "SKILL.md に fallback への言及がない"
    match = re.search(
        r"###\s*Step 2\.5 fallback\b.*?(?=^### |^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match, "SKILL.md に `### Step 2.5 fallback` 節が見つからない"
    fallback_section = match.group(0)
    assert "手コピペ" in fallback_section, "fallback 節に手コピペ手順の記載がない"
    assert "suno-prompts.md" in fallback_section, "fallback 節が手動投入元 `suno-prompts.md` を参照していない"
