"""collection-ideate / wf-new の codex サムネ生成導線に関する静的契約テスト。"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
_IDEATE_SKILL_MD = _SKILLS_DIR / "collection-ideate" / "SKILL.md"
_WF_NEW_SKILL_MD = _SKILLS_DIR / "wf-new" / "SKILL.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _phase_4_4_parallel_block(text: str) -> str:
    match = re.search(
        r"\*\*4-4: プロンプト構築 \+ 一括生成（parallel デフォルト）\*\*(.*?)(?:\*\*4-5:|\Z)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("collection-ideate/SKILL.md に parallel 4-4 ブロックが見つかりません")
    return match.group(1)


def _phase_4_4_sequential_block(text: str) -> str:
    match = re.search(
        r"\*\*sequential 用 4-4 \(選択 → 1 枚生成\)\*\*:(.*?)(?:\*\*sequential 用 4-5|\Z)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("collection-ideate/SKILL.md に sequential 4-4 ブロックが見つかりません")
    return match.group(1)


def _wf_new_phase_2c_block(text: str) -> str:
    match = re.search(
        r"#### 2c\. サムネイル確定 \+ 音楽素材生成(.*?)(?:#### 2d\.|\Z)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("wf-new/SKILL.md に Phase 2c ブロックが見つかりません")
    return match.group(1)


def test_collection_ideate_parallel_generation_branches_to_codex_image_script() -> None:
    """Given collection-ideate Phase 4-4 parallel
    When provider=codex が設定されている
    Then yt-generate-image ではなく codex-image.sh を呼ぶ分岐が文書化されている。
    """
    block = _phase_4_4_parallel_block(_read(_IDEATE_SKILL_MD))

    assert "cfg.provider" in block
    assert "codex" in block
    assert ".claude/skills/thumbnail/references/codex-image.sh" in block
    assert "yt-generate-image" in block, "gemini/openai の既存 API 経路も維持する必要があります"


def test_collection_ideate_codex_parallel_uses_reference_paths_as_positionals() -> None:
    """Given collection-ideate Phase 4-4 parallel の codex 分岐
    When 参照画像を渡す
    Then --reference ペアではなく REF_PATHS の位置引数として codex-image.sh へ渡す。
    """
    block = _phase_4_4_parallel_block(_read(_IDEATE_SKILL_MD))

    assert "REF_PATHS" in block, f"codex 用の素の参照パス配列がありません:\n{block}"
    assert "REF_ARGS" in block, f"API provider 用の --reference 配列が消えています:\n{block}"
    assert re.search(r"codex-image\.sh[^\n]*.*REF_PATHS", block, flags=re.DOTALL), (
        f"codex-image.sh 呼び出しに REF_PATHS が位置引数として渡されていません:\n{block}"
    )


def test_collection_ideate_codex_parallel_requires_short_prompt() -> None:
    """Given collection-ideate Phase 4-4 parallel の codex 分岐
    When codex-image.sh を呼ぶ
    Then 長文の本番プロンプトではなく短縮プロンプトを使う注意がある。
    """
    block = _phase_4_4_parallel_block(_read(_IDEATE_SKILL_MD))

    assert "短縮" in block or "短く" in block
    assert "prompt" in block or "プロンプト" in block


def test_collection_ideate_sequential_generation_branches_to_codex_image_script() -> None:
    """Given collection-ideate Phase 4-4 sequential
    When provider=codex が設定されている
    Then 選択 1 案生成でも codex-image.sh を呼ぶ分岐がある。
    """
    block = _phase_4_4_sequential_block(_read(_IDEATE_SKILL_MD))

    assert "cfg.provider" in block
    assert "codex" in block
    assert ".claude/skills/thumbnail/references/codex-image.sh" in block
    assert "yt-generate-image" in block


def test_wf_new_treats_codex_preview_as_finished_thumbnail() -> None:
    """Given wf-new Phase 2c
    When image_generation.provider=codex
    Then single_step と同様に main.png を thumbnail.jpg へコピーして /thumbnail 再生成を不要にする。
    """
    block = _wf_new_phase_2c_block(_read(_WF_NEW_SKILL_MD))

    assert "codex" in block
    assert "single_step" in block
    assert "cp <collection-path>/10-assets/main.png <collection-path>/10-assets/thumbnail.jpg" in block
    assert "/thumbnail" in block
