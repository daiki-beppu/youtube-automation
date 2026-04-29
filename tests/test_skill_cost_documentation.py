"""skill ドキュメント上の画像生成コスト表記が cost_tracker.PRICING に追従しているかを検証する。

Issue #102: 画像生成コスト ($0.04/枚) のハードコーディング解消。
対象ファイル:
- .claude/skills/thumbnail/SKILL.md (ttp_swap モードのコスト記述)
- .claude/skills/ideate/SKILL.md (Phase 4-2 のコスト一括確認)
- .claude/skills/thumbnail/config.default.yaml (cost_per_image_usd コメント例)

ドキュメント変更のため、テストは
- 旧ハードコード値が残っていないこと（負の検証）
- cost_tracker.PRICING / estimate_cost を single source of truth として参照していること（正の検証）
の 2 観点で行う。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"

THUMBNAIL_SKILL_MD = _SKILLS_DIR / "thumbnail" / "SKILL.md"
THUMBNAIL_CONFIG_YAML = _SKILLS_DIR / "thumbnail" / "config.default.yaml"
IDEATE_SKILL_MD = _SKILLS_DIR / "ideate" / "SKILL.md"


# ---------- 共通ヘルパー ----------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ttp_swap_cost_section(text: str) -> str:
    """thumbnail/SKILL.md の ttp_swap モード「運用上の注意」配下、'**コスト**' の行を返す。

    別モード (single_step / two_phase 等) の説明と区別するため、'**コスト**' 行のみを取り出す。
    """
    for line in text.splitlines():
        if line.lstrip().startswith("- **コスト**"):
            return line
    raise AssertionError("thumbnail/SKILL.md に '**コスト**' の行が見つかりません")


def _phase_4_2_block(text: str) -> str:
    """ideate/SKILL.md の Phase 4-2 (コスト一括確認) ブロックを抽出する。"""
    match = re.search(
        r"\*\*4-2: コスト一括確認\*\*(.*?)(?:\n\*\*4-3:|\Z)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("ideate/SKILL.md に Phase 4-2 ブロックが見つかりません")
    return match.group(1)


def _config_yaml_gemini_image_block(text: str) -> str:
    """thumbnail/config.default.yaml の gemini_image セクション (cost_per_image_usd まで) を抽出。"""
    match = re.search(
        r"^gemini_image:.*?(?=^[a-z_]+:|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("thumbnail/config.default.yaml に gemini_image セクションが見つかりません")
    return match.group(0)


# ---------- skill ファイル存在確認（テスト基盤の sanity check） ----------


@pytest.mark.parametrize(
    "path",
    [THUMBNAIL_SKILL_MD, THUMBNAIL_CONFIG_YAML, IDEATE_SKILL_MD],
    ids=["thumbnail/SKILL.md", "thumbnail/config.default.yaml", "ideate/SKILL.md"],
)
def test_target_skill_files_exist(path: Path) -> None:
    """前提: 修正対象の skill ファイルが存在する。"""
    assert path.exists(), f"{path} が存在しません"


# ---------- thumbnail/SKILL.md (ttp_swap モードのコスト行) ----------


def test_thumbnail_skill_md_cost_line_drops_hardcoded_dollar_04() -> None:
    """Given thumbnail/SKILL.md ttp_swap '**コスト**' 行
    When 修正後のドキュメントを読む
    Then `$0.04〜$0.08` のハードコード値が消えている。
    """
    line = _ttp_swap_cost_section(_read(THUMBNAIL_SKILL_MD))
    assert "$0.04" not in line, f"`$0.04` ハードコードが残存: {line}"
    assert "$0.08" not in line, f"`$0.08` ハードコードが残存: {line}"


def test_thumbnail_skill_md_cost_line_references_cost_tracker_pricing() -> None:
    """Given thumbnail/SKILL.md ttp_swap '**コスト**' 行
    When 修正後のドキュメントを読む
    Then 単価の根拠として `cost_tracker.PRICING` が明記される。
    """
    line = _ttp_swap_cost_section(_read(THUMBNAIL_SKILL_MD))
    assert "cost_tracker.PRICING" in line, f"`cost_tracker.PRICING` 参照がない (single source of truth でない): {line}"


# ---------- ideate/SKILL.md Phase 4-2 (コスト一括確認) ----------


def test_ideate_phase_4_2_drops_static_cost_string() -> None:
    """Given ideate/SKILL.md Phase 4-2
    When 修正後のドキュメントを読む
    Then 静的な `3 枚 × $0.04 = $0.120` が削除されている。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "$0.04" not in block, f"`$0.04` 静的表記が残存:\n{block}"
    assert "$0.120" not in block, f"`$0.120` 静的合計が残存:\n{block}"
    assert "3 枚 × $0.04" not in block


def test_ideate_phase_4_2_uses_dynamic_estimate_cost() -> None:
    """Given ideate/SKILL.md Phase 4-2
    When 修正後のドキュメントを読む
    Then `cost_tracker.estimate_cost` を呼ぶ動的算出ワンライナーが含まれる。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "estimate_cost" in block, f"Phase 4-2 が `estimate_cost` を呼んでいない (動的算出になっていない):\n{block}"


def test_ideate_phase_4_2_loads_skill_config_for_overrides() -> None:
    """Given ideate/SKILL.md Phase 4-2 ワンライナー
    When 修正後のドキュメントを読む
    Then `load_skill_config` 経由でチャンネル側の設定（candidate_count / model 等）を取得する。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "load_skill_config" in block, (
        f"Phase 4-2 が `load_skill_config` を呼んでいない (skill-config 連動になっていない):\n{block}"
    )


def test_ideate_phase_4_2_respects_custom_cost_per_image_usd() -> None:
    """Given ideate/SKILL.md Phase 4-2 ワンライナー
    When 修正後のドキュメントを読む
    Then カスタム単価 `cost_per_image_usd` を優先する分岐が含まれる
        (generate_image.py:90-94 の挙動と一致させるため)。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "cost_per_image_usd" in block, f"Phase 4-2 がカスタム単価 `cost_per_image_usd` 優先になっていない:\n{block}"


def test_ideate_phase_4_2_keeps_user_reject_fallback_text() -> None:
    """Given ideate/SKILL.md Phase 4-2
    When 修正後のドキュメントを読む
    Then 「ユーザーが拒否した場合 → テキストのみで提示」のフォールバック説明は維持される
        (実装ガイドラインで明示的に維持指示あり)。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "ユーザーが拒否した場合" in block, f"ユーザー拒否時のフォールバック説明が削除されている:\n{block}"
    assert "テキストのみ" in block


# ---------- thumbnail/config.default.yaml (cost_per_image_usd コメント) ----------


def test_thumbnail_config_yaml_drops_hardcoded_004_example() -> None:
    """Given thumbnail/config.default.yaml の gemini_image ブロック
    When 修正後のコメントを読む
    Then `cost_per_image_usd: 0.04` という誤解を招く数値例が消えている。
    """
    block = _config_yaml_gemini_image_block(_read(THUMBNAIL_CONFIG_YAML))
    assert "cost_per_image_usd: 0.04" not in block, f"`cost_per_image_usd: 0.04` の誤解を招く数値例が残存:\n{block}"
    # 念のため 単独の $0.04 系表記も拒否
    assert "$0.04" not in block


def test_thumbnail_config_yaml_keeps_pricing_auto_calc_comment() -> None:
    """Given thumbnail/config.default.yaml の gemini_image ブロック
    When 修正後のコメントを読む
    Then 「PRICING から自動算出」の既存コメントは維持される
        (Issue 補足で「自動算出が正」と明示されているため)。
    """
    block = _config_yaml_gemini_image_block(_read(THUMBNAIL_CONFIG_YAML))
    assert "cost_tracker.PRICING" in block, f"`cost_tracker.PRICING` 参照コメントが消えている:\n{block}"


def test_thumbnail_config_yaml_keeps_cost_per_image_usd_key_doc() -> None:
    """Given thumbnail/config.default.yaml の gemini_image ブロック
    When 修正後のコメントを読む
    Then カスタム単価キー `cost_per_image_usd` のドキュメント自体は残る
        (キーの存在意義の説明が必要なため)。
    """
    block = _config_yaml_gemini_image_block(_read(THUMBNAIL_CONFIG_YAML))
    assert "cost_per_image_usd" in block, f"`cost_per_image_usd` キーの説明が消えている:\n{block}"


# ---------- 横断: 他 skill ドキュメントへの混入チェック ----------


def test_no_hardcoded_image_cost_in_other_skill_docs() -> None:
    """Given .claude/skills/ 配下の全 skill ドキュメント
    When 修正後の skill ツリー全体を走査する
    Then 画像生成コストの旧ハードコード `$0.04` / `$0.08` がどこにも残っていない
        (修正対象 3 ファイル含む)。
    """
    offenders: list[str] = []
    for path in _SKILLS_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".md", ".yaml", ".yml"}:
            continue
        text = _read(path)
        for needle in ("$0.04", "$0.08", "cost_per_image_usd: 0.04"):
            if needle in text:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}: {needle!r}")
    assert offenders == [], "skill ドキュメントに旧ハードコード値が残存:\n  " + "\n  ".join(offenders)
