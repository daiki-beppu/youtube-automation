"""collection-ideate / wf-new の codex サムネ生成導線に関する静的契約テスト。"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
_IDEATE_SKILL_MD = _SKILLS_DIR / "collection-ideate" / "SKILL.md"
_IDEATE_DEFAULT_CONFIG = _SKILLS_DIR / "collection-ideate" / "config.default.yaml"
_IDEATE_LIFECYCLE_MD = _SKILLS_DIR / "collection-ideate" / "references" / "collection-lifecycle.md"
_LYRIA_DEFAULT_CONFIG = _SKILLS_DIR / "lyria" / "config.default.yaml"
_LYRIA_SKILL_MD = _SKILLS_DIR / "lyria" / "SKILL.md"
_SHORT_THUMBNAIL_SKILL_MD = _SKILLS_DIR / "short-thumbnail" / "SKILL.md"
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


def _wf_new_sequence_block(text: str) -> str:
    match = re.search(r"### 実行シーケンス(.*?)(?:### Phase 1:|\Z)", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("wf-new/SKILL.md に実行シーケンスブロックが見つかりません")
    return match.group(1)


def _wf_new_phase_2e_block(text: str) -> str:
    match = re.search(
        r"#### 2e\. ループ動画生成(.*?)(?:#### 2f\.|\Z)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("wf-new/SKILL.md に Phase 2e ブロックが見つかりません")
    return match.group(1)


def _collection_ideate_next_step_block(text: str) -> str:
    match = re.search(r"^## Next Step(.*?)(?:^## |\Z)", text, flags=re.DOTALL | re.MULTILINE)
    if not match:
        raise AssertionError("collection-ideate/SKILL.md に Next Step ブロックが見つかりません")
    return match.group(1)


def _assert_codex_ttp_prompt_policy(block: str) -> None:
    assert ".claude/skills/thumbnail/references/codex-prompt.py" in block
    assert "default_prompt_template" in block
    assert "TTP 上位互換" in block
    assert "短い" in block or "短縮" in block or "短く" in block


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
    Then --reference ペアではなく候補ごとに REF_PATHS の 1 要素だけを位置引数として渡す。
    """
    block = _phase_4_4_parallel_block(_read(_IDEATE_SKILL_MD))

    assert "REF_PATHS" in block, f"codex 用の素の参照パス配列がありません:\n{block}"
    assert "REF_ARGS" in block, f"API provider 用の --reference 配列が消えています:\n{block}"
    assert "${REF_PATHS[0]}" in block
    assert "${REF_PATHS[1]}" in block
    assert "${REF_PATHS[2]}" in block
    assert '"${REF_PATHS[@]}"' not in block, f"全候補へ同じ参照配列を渡してはいけません:\n{block}"


def test_collection_ideate_codex_parallel_requires_short_prompt() -> None:
    """Given collection-ideate Phase 4-4 parallel の codex 分岐
    When codex-image.sh を呼ぶ
    Then 長文の本番プロンプトではなく短縮プロンプトを使う注意がある。
    """
    block = _phase_4_4_parallel_block(_read(_IDEATE_SKILL_MD))

    _assert_codex_ttp_prompt_policy(block)


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


def test_collection_ideate_codex_sequential_requires_short_prompt() -> None:
    """Given collection-ideate Phase 4-4 sequential の codex 分岐
    When codex-image.sh を呼ぶ
    Then parallel と同じ TTP 上位互換 prompt template 契約を使う。
    """
    block = _phase_4_4_sequential_block(_read(_IDEATE_SKILL_MD))

    _assert_codex_ttp_prompt_policy(block)


def test_wf_new_routes_codex_and_single_step_through_thumbnail_contract() -> None:
    """Given wf-new Phase 2c
    When image_generation.provider=codex
    Then preview を最終画像扱いせず /thumbnail で thumbnail と textless main を別成果物にする。
    """
    block = _wf_new_phase_2c_block(_read(_WF_NEW_SKILL_MD))

    assert "codex" in block
    assert "single_step" in block
    assert "`/thumbnail <theme>`" in block
    assert "テキスト付き `10-assets/thumbnail.jpg`" in block
    assert "テキストなし `10-assets/main.png` または `main.jpg`" in block
    assert "同一画像で代用しない" in block
    assert "旧運用は禁止" in block
    assert "cp <collection-path>/10-assets/main.png <collection-path>/10-assets/thumbnail.jpg" not in block


def test_wf_new_skips_loop_video_when_loop_video_disabled() -> None:
    """Given wf-new Phase 2e
    When loop-video.yaml::enabled=false
    Then /loop-video を呼ばず静止背景運用として prepared に進む。
    """
    block = _wf_new_phase_2e_block(_read(_WF_NEW_SKILL_MD))

    assert "config/skills/loop-video.yaml::enabled" in block
    assert "`enabled: false`" in block
    assert "`/loop-video` は呼ばず" in block
    assert "textless `main.png/jpg` の静止画背景運用" in block
    assert "`assets.loop_video = false` を維持" in block
    assert '`phase = "prepared"`' in block


def test_wf_new_sequence_table_allows_static_background_when_loop_video_disabled() -> None:
    """Given wf-new execution sequence
    Then loop-video disabled channels do not unconditionally run Veo.
    """
    block = _wf_new_sequence_block(_read(_WF_NEW_SKILL_MD))

    assert "`/loop-video` または静止背景運用" in block
    assert "`loop-video.enabled=true`" in block
    assert "`enabled=false` なら Veo を呼ばず" in block
    assert "textless `main.png/jpg` を静止背景として使う" in block
    assert "`10-assets/loop.mp4` または textless `10-assets/main.png/jpg`" in block
    old_unconditional_loop_row = (
        "| 7 | `/loop-video` | 承認済みテキストなし `main.png/jpg` から loop video を生成 | `10-assets/loop.mp4` |"
    )
    assert old_unconditional_loop_row not in block


def test_lyria_reference_image_uses_textless_main_wording() -> None:
    """Given lyria structured parameter docs
    Then main.png is not described as an upload thumbnail.
    """
    text = _read(_LYRIA_SKILL_MD)
    config = _read(_LYRIA_DEFAULT_CONFIG)

    assert "textless 動画背景 / ビジュアル参照画像 `10-assets/main.png`" in text
    assert "サムネイル `10-assets/main.png`" not in text
    assert "textless 動画背景 / ビジュアル参照画像を自動採用" in config
    assert "コレクションのサムネイルを参照画像として自動採用" not in config


def test_short_thumbnail_uses_textless_main_wording() -> None:
    """Given short-thumbnail docs
    Then main.png/main.jpg are reference visuals, not legacy thumbnails.
    """
    text = _read(_SHORT_THUMBNAIL_SKILL_MD)

    assert "16:9 textless 動画背景 / 参考ビジュアル" in text
    assert "既存の textless 動画背景 / 参考ビジュアル" in text
    assert "16:9 サムネ（動画背景用）" not in text
    assert "既存サムネ" not in text


def test_collection_ideate_next_step_keeps_preview_out_of_main_background() -> None:
    """Given collection-ideate Next Step
    Then preview は企画参照であり main.png へ直接コピーしない。
    """
    block = _collection_ideate_next_step_block(_read(_IDEATE_SKILL_MD))

    assert "`main.png` にはコピーしない" in block
    assert "planning-preview.png" in block
    assert "`/thumbnail <theme>`" in block
    assert "テキスト付き `thumbnail.jpg` と textless `main.png/jpg`" in block
    assert "`main.png` として動画背景に流用しない" in block
    assert (
        "cp collections/planning/_plan-previews/<session-dir>/plan-<x>-<slug>.png <collection-path>/10-assets/main.png"
        not in block
    )
    assert "Phase 2 からテキストオーバーレイのみ実行" not in block


def test_collection_ideate_cost_rejection_uses_new_thumbnail_contract() -> None:
    """Given collection-ideate cost rejection
    Then it does not route back to old main.png Phase 1 fallback.
    """
    text = _read(_IDEATE_SKILL_MD)

    assert "後段の `/thumbnail <theme>` がベンチマーク参照からテキスト付き `thumbnail.jpg` を生成" in text
    assert "承認済み `thumbnail.jpg` から textless `main.png/jpg` を再生成" in text
    assert "`planning-preview.png` は未生成のまま Next Step に進み" in text
    assert "`main.png` 不在を検出して Phase 1" not in text
    assert "プレビューが `/wf-new` Phase 2c でそのまま最終 thumbnail に流用" not in text


def test_collection_ideate_config_and_lifecycle_reference_new_thumbnail_contract() -> None:
    """Given distributed collection-ideate docs/config
    Then preview, upload thumbnail, and textless background roles are explicit.
    """
    config = _read(_IDEATE_DEFAULT_CONFIG)
    lifecycle = _read(_IDEATE_LIFECYCLE_MD)

    assert "採用 1 枚 planning-preview.png + 残り stock 退避" in config
    assert "planning-preview.png は企画参照素材" in config
    assert "最終 thumbnail.jpg と textless main.png/jpg は後段 /thumbnail で別生成" in config
    assert "採用 1 枚 main.png" not in config

    assert "thumbnail.jpg, textless main.png/jpg, planning-preview.png" in lifecycle
    assert "テキスト付き `10-assets/thumbnail.jpg`" in lifecycle
    assert "textless `10-assets/main.png` または `main.jpg`" in lifecycle
    assert "サムネイル作成（テキスト付き thumbnail.jpg）" in lifecycle
    assert "textless 動画背景作成（main.png または main.jpg）" in lifecycle
    assert "画像生成 → `10-assets/thumbnail.jpg`" not in lifecycle
