"""skill ドキュメント上の画像生成コスト表記が撤廃 (Issue #132) に揃っているか検証する。

Issue #132 で `cost_tracker.PRICING` / `estimate_cost` を撤廃したため、
それらを参照していた既存ドキュメントを以下のスタイルに反転する:

- 撤廃された API 名 (`cost_tracker.PRICING` / `estimate_cost`) を含まない
- 単価は `config/skills/thumbnail.yaml` の `image_generation.<provider>.cost_per_image_usd`
  で指定し、未指定なら GCP Cloud Console で実コスト確認、という説明を含む
- `collection-ideate` Phase 4-2 のワンライナーは `load_skill_config` + `cost_per_image_usd`
  直接参照 (`estimate_cost` 不使用)

対象ファイル:
- .claude/skills/thumbnail/SKILL.md (ttp_swap モードのコスト記述)
- .claude/skills/collection-ideate/SKILL.md (Phase 4-2 のコスト一括確認)
- .claude/skills/thumbnail/config.default.yaml (cost_per_image_usd コメント例)
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
IDEATE_SKILL_MD = _SKILLS_DIR / "collection-ideate" / "SKILL.md"


# ---------- 共通ヘルパー ----------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ttp_swap_cost_section(text: str) -> str:
    """thumbnail/SKILL.md の ttp_swap モード「運用上の注意」配下、'**コスト**' の行を返す。"""
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


def _config_yaml_image_generation_block(text: str) -> str:
    """thumbnail/config.default.yaml の image_generation セクションを抽出。"""
    match = re.search(
        r"^image_generation:.*?(?=^[a-z_]+:|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("thumbnail/config.default.yaml に image_generation セクションが見つかりません")
    return match.group(0)


# ---------- skill ファイル存在確認 ----------


@pytest.mark.parametrize(
    "path",
    [THUMBNAIL_SKILL_MD, THUMBNAIL_CONFIG_YAML, IDEATE_SKILL_MD],
    ids=["thumbnail/SKILL.md", "thumbnail/config.default.yaml", "collection-ideate/SKILL.md"],
)
def test_target_skill_files_exist(path: Path) -> None:
    """前提: 修正対象の skill ファイルが存在する。"""
    assert path.exists(), f"{path} が存在しません"


# ---------- thumbnail/SKILL.md (ttp_swap モードのコスト行) (Test #43) ----------


def test_thumbnail_skill_md_cost_line_drops_legacy_hardcoded_values() -> None:
    """Given thumbnail/SKILL.md ttp_swap '**コスト**' 行
    When 修正後のドキュメントを読む
    Then 旧ハードコード値 (`$0.04〜$0.08`) が消えている。
    """
    line = _ttp_swap_cost_section(_read(THUMBNAIL_SKILL_MD))
    assert "$0.04" not in line, f"`$0.04` ハードコードが残存: {line}"
    assert "$0.08" not in line, f"`$0.08` ハードコードが残存: {line}"


def test_thumbnail_skill_md_cost_line_drops_cost_tracker_pricing_reference() -> None:
    """Given thumbnail/SKILL.md ttp_swap '**コスト**' 行
    When 修正後のドキュメントを読む
    Then `cost_tracker.PRICING` 参照が削除されている (Issue #132 で撤廃済み)。
    """
    line = _ttp_swap_cost_section(_read(THUMBNAIL_SKILL_MD))
    assert "cost_tracker.PRICING" not in line, f"`cost_tracker.PRICING` 参照が残存 (Issue #132 で撤廃済み): {line}"


def test_thumbnail_skill_md_cost_line_points_to_gcp_or_skill_config() -> None:
    """Given thumbnail/SKILL.md ttp_swap '**コスト**' 行
    When 修正後のドキュメントを読む
    Then 単価ソースとして "GCP Cloud Console" もしくは
        skill-config の `cost_per_image_usd` を案内している。
    """
    line = _ttp_swap_cost_section(_read(THUMBNAIL_SKILL_MD))
    assert ("GCP Cloud Console" in line) or ("cost_per_image_usd" in line), (
        f"単価ソース (GCP Cloud Console / cost_per_image_usd) のいずれも案内されていない: {line}"
    )


# ---------- collection-ideate/SKILL.md Phase 4-2 (Test #44) ----------


def test_ideate_phase_4_2_drops_legacy_static_cost_string() -> None:
    """Given ideate/SKILL.md Phase 4-2
    When 修正後のドキュメントを読む
    Then 静的な `3 枚 × $0.04 = $0.120` が削除されている。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "$0.04" not in block, f"`$0.04` 静的表記が残存:\n{block}"
    assert "$0.120" not in block, f"`$0.120` 静的合計が残存:\n{block}"
    assert "3 枚 × $0.04" not in block


def test_ideate_phase_4_2_drops_estimate_cost_reference() -> None:
    """Given ideate/SKILL.md Phase 4-2 ワンライナー
    When 修正後のドキュメントを読む
    Then `cost_tracker.estimate_cost` / `estimate_cost` の参照が消えている
        (Issue #132 で API 自体が撤廃されたため)。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "estimate_cost" not in block, f"`estimate_cost` 参照が残存 (Issue #132 で撤廃済み):\n{block}"


def test_ideate_phase_4_2_still_loads_skill_config() -> None:
    """Given ideate/SKILL.md Phase 4-2 ワンライナー
    When 修正後のドキュメントを読む
    Then `load_skill_config` 経由で skill-config を取得する経路は維持される。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "load_skill_config" in block, (
        f"Phase 4-2 が `load_skill_config` を呼んでいない (skill-config 連動になっていない):\n{block}"
    )


def test_ideate_phase_4_2_references_cost_per_image_usd_key() -> None:
    """Given ideate/SKILL.md Phase 4-2 ワンライナー
    When 修正後のドキュメントを読む
    Then カスタム単価キー `cost_per_image_usd` を直接参照している
        (PRICING フォールバック撤廃後の唯一のソース)。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "cost_per_image_usd" in block, f"Phase 4-2 が `cost_per_image_usd` 直接参照になっていない:\n{block}"


def test_ideate_phase_4_2_keeps_user_reject_fallback_text() -> None:
    """Given ideate/SKILL.md Phase 4-2
    When 修正後のドキュメントを読む
    Then 「ユーザーが拒否した場合 → テキストのみで提示」のフォールバック説明は維持される。
    """
    block = _phase_4_2_block(_read(IDEATE_SKILL_MD))
    assert "ユーザーが拒否した場合" in block, f"ユーザー拒否時のフォールバック説明が削除されている:\n{block}"
    assert "テキストのみ" in block


# ---------- thumbnail/config.default.yaml (Test #45) ----------


def test_thumbnail_config_yaml_uses_image_generation_namespace() -> None:
    """Given thumbnail/config.default.yaml
    When ファイルを読む
    Then ルートキーが `image_generation:` に移行されている。
    """
    text = _read(THUMBNAIL_CONFIG_YAML)
    assert re.search(r"^image_generation:", text, flags=re.MULTILINE), "ルートキー `image_generation:` が見つかりません"


def test_thumbnail_config_yaml_drops_legacy_gemini_image_root_key() -> None:
    """Given thumbnail/config.default.yaml
    When ファイルを読む
    Then 旧ルートキー `gemini_image:` は削除されている。
    """
    text = _read(THUMBNAIL_CONFIG_YAML)
    assert not re.search(r"^gemini_image:", text, flags=re.MULTILINE), "旧ルートキー `gemini_image:` が残存"


def test_thumbnail_config_yaml_declares_provider_field() -> None:
    """Given image_generation ブロック
    When 内容を読む
    Then provider フィールドで gemini/openai を切り替え可能と明示されている。
    """
    block = _config_yaml_image_generation_block(_read(THUMBNAIL_CONFIG_YAML))
    assert re.search(r"\bprovider:\s*\w+", block), f"`provider:` キーが見当たりません:\n{block}"


def test_thumbnail_config_yaml_drops_hardcoded_004_example() -> None:
    """Given image_generation ブロック
    When コメントを読む
    Then `cost_per_image_usd: 0.04` という誤解を招く数値例が消えている。
    """
    block = _config_yaml_image_generation_block(_read(THUMBNAIL_CONFIG_YAML))
    assert "cost_per_image_usd: 0.04" not in block, f"`cost_per_image_usd: 0.04` の誤解を招く数値例が残存:\n{block}"
    assert "$0.04" not in block


def test_thumbnail_config_yaml_drops_cost_tracker_pricing_reference() -> None:
    """Given image_generation ブロック
    When コメントを読む
    Then `cost_tracker.PRICING` 参照コメントが消えている (Issue #132 で撤廃済み)。
    """
    block = _config_yaml_image_generation_block(_read(THUMBNAIL_CONFIG_YAML))
    assert "cost_tracker.PRICING" not in block, (
        f"`cost_tracker.PRICING` 参照コメントが残存 (Issue #132 で撤廃済み):\n{block}"
    )


def test_thumbnail_config_yaml_keeps_cost_per_image_usd_key_doc() -> None:
    """Given image_generation ブロック
    When コメントを読む
    Then カスタム単価キー `cost_per_image_usd` のドキュメント自体は残る
        (skill-config 経由の事前見積もり用 override 用途は維持)。
    """
    block = _config_yaml_image_generation_block(_read(THUMBNAIL_CONFIG_YAML))
    assert "cost_per_image_usd" in block, f"`cost_per_image_usd` キーの説明が消えている:\n{block}"


# ---------- 横断: 他 skill ドキュメントへの混入チェック ----------


def test_no_hardcoded_image_cost_in_other_skill_docs() -> None:
    """Given .claude/skills/ 配下の全 skill ドキュメント
    When 修正後の skill ツリー全体を走査する
    Then 画像生成コストの旧ハードコード `$0.04` / `$0.08` がどこにも残っていない。
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
