"""collection-ideate / wf-new の codex サムネ生成導線に関する静的契約テスト。"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
_IDEATE_SKILL_MD = _SKILLS_DIR / "collection-ideate" / "SKILL.md"
_IDEATE_DEFAULT_CONFIG = _SKILLS_DIR / "collection-ideate" / "config.default.yaml"
_IDEATE_LIFECYCLE_MD = _SKILLS_DIR / "collection-ideate" / "references" / "collection-lifecycle.md"
_IDEATE_TTP_SELECTOR = _SKILLS_DIR / "collection-ideate" / "references" / "select-ttp-references.py"
_LYRIA_DEFAULT_CONFIG = _SKILLS_DIR / "lyria" / "config.default.yaml"
_LYRIA_SKILL_MD = _SKILLS_DIR / "lyria" / "SKILL.md"
_SHORT_THUMBNAIL_SKILL_MD = _SKILLS_DIR / "short-thumbnail" / "SKILL.md"
_THUMBNAIL_DIR = _SKILLS_DIR / "thumbnail"
_THUMBNAIL_SKILL_MD = _THUMBNAIL_DIR / "SKILL.md"
_THUMBNAIL_DEFAULT_CONFIG = _THUMBNAIL_DIR / "config.default.yaml"
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


def _thumbnail_standard_contract_block(text: str) -> str:
    match = re.search(r"### 標準生成順序とファイル契約(.*?)(?:### Single-Step / TTP モード|\Z)", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("thumbnail/SKILL.md に標準生成順序とファイル契約ブロックが見つかりません")
    return match.group(1)


def _thumbnail_single_step_block(text: str) -> str:
    match = re.search(r"### Single-Step / TTP モード(.*?)(?:### Two-Phase モード|\Z)", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("thumbnail/SKILL.md に Single-Step / TTP モードブロックが見つかりません")
    return match.group(1)


def _assert_codex_ttp_prompt_policy(block: str) -> None:
    assert ".claude/skills/thumbnail/references/codex-prompt.py" in block
    assert "default_prompt_template" in block
    assert "TTP thumbnail 先行" in block, "#1611/#1680: codex 分岐はテキスト付き thumbnail 先行フローを案内する"
    assert "TTP 背景先行" not in block, "#1680: textless 背景先行の旧コメントを残さない"
    assert "短い" in block or "短縮" in block or "短く" in block
    assert "サムネに焼くテキスト" in block, "#1680: {title} へ動画タイトル全文を渡さない注記が必要"
    assert "動画タイトル全文" in block


def test_thumbnail_standard_contract_is_textless_first_deterministic() -> None:
    """Given /thumbnail standard docs (#1907)
    Then textless main is approved first and thumbnail.jpg is composed via yt-thumbnail-text.
    """
    block = _thumbnail_standard_contract_block(_read(_THUMBNAIL_SKILL_MD))

    assert "textless 動画背景の生成 → `yt-thumbnail-text` による実フォント合成" in block
    assert "uv run yt-thumbnail-text" in block
    assert "テキスト付き最終サムネを `10-assets/thumbnail.jpg` として確定" in block
    assert "テキストなし `main.png/jpg`" in block
    assert block.find("cp main-v1.png main.png") < block.find("uv run yt-thumbnail-text")
    # 旧標準（テキスト付き先行）は明示 fallback としてだけ残る
    assert "AI 焼き込み経路（fallback・非既定）" in block
    assert "承認済み `main.png/jpg` を参照画像にして" not in block


def test_thumbnail_single_step_ttp_docs_are_thumbnail_first() -> None:
    """Given gemini single_step/TTP docs
    Then they generate thumbnail-v1 before regenerating main-v1.
    """
    block = _thumbnail_single_step_block(_read(_THUMBNAIL_SKILL_MD))

    assert "--output <collection-path>/10-assets/thumbnail-v1.jpg -y" in block
    assert "cp thumbnail-v1.jpg thumbnail.jpg" in block
    assert '--reference "${COLLECTION_PATH}/10-assets/thumbnail.jpg"' in block
    assert '--output "${COLLECTION_PATH}/10-assets/main-v1.png"' in block
    assert "cp main-v1.png main.png" in block
    assert "ベンチマーク参照からテキスト付き `thumbnail-v1.jpg/png` を生成" in block
    assert "承認済み `thumbnail.jpg` を参照して textless `main-v1.png/jpg` を再生成" in block
    assert "--output <collection-path>/10-assets/main-v1.png -y" not in block
    assert "テキストなし版の先行確定" not in block
    assert "承認済み `main.png/jpg` を参照してテキスト付き" not in block


def test_thumbnail_default_config_comments_match_thumbnail_first_single_step() -> None:
    """Given distributed thumbnail default config
    Then single_step comments do not describe initial textless generation.
    """
    config = _read(_THUMBNAIL_DEFAULT_CONFIG)

    assert "text-included thumbnail 候補を生成" in config
    assert "text-included thumbnail を先に確定" in config
    assert "承認済み thumbnail から textless main を後続再生成" in config
    assert "承認済み thumbnail から作る textless 再生成プロンプトには展開しない" in config
    assert "初回 textless 背景用" not in config


def test_thumbnail_skill_does_not_present_text_included_first_as_standard() -> None:
    """Given distributed thumbnail docs (#1907)
    Then text-included-first wording appears only as the explicit AI-bake fallback,
    never as the standard order.
    """
    skill = _read(_THUMBNAIL_SKILL_MD)

    assert "標準手順は、**textless 動画背景の生成" in skill
    assert "標準手順は、**テキスト付き YouTube サムネ" not in skill
    assert "テキスト付き YouTube サムネ → 承認済みサムネから textless 動画背景」の順で" in skill


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
    assert "for idx in $(seq 0 $((CANDIDATE_COUNT - 1)))" in block
    assert '"${REF_PATHS[$idx]}"' in block
    assert re.search(r"codex-image\.sh[^\n]*\"\$\{REF_PATHS\[@\]\}\"", block) is None, (
        f"全候補へ同じ参照配列を渡してはいけません:\n{block}"
    )
    assert "--require-reference" in block, f"TTP codex 呼び出しは参照必須フラグを明示してください:\n{block}"


def test_collection_ideate_parallel_validates_unique_single_channel_references() -> None:
    """Given collection-ideate Phase 4-4 parallel
    When TTP preview 参照を組み立てる
    Then duplicate / mixed channel は生成前 validation に合流する。
    """
    block = _phase_4_4_parallel_block(_read(_IDEATE_SKILL_MD))
    selector = _read(_IDEATE_TTP_SELECTOR)

    assert ".claude/skills/collection-ideate/references/select-ttp-references.py" in block
    assert "VALIDATED_REFS" in block
    assert "CANDIDATE_COUNT" in block
    assert "plan_ttp_reference_assignments" in selector
    assert 'benchmark_root=root / "data" / "thumbnail_compare" / "benchmark"' in selector
    assert "candidate_count = int(sys.argv[1])" in selector


def test_collection_ideate_api_parallel_uses_one_reference_per_candidate() -> None:
    """Given collection-ideate Phase 4-4 parallel の API provider 分岐
    When Gemini/OpenAI で preview を作る
    Then 候補ごとに別参照 1 枚を渡し、同じ REF_ARGS 全体を共有しない。
    """
    block = _phase_4_4_parallel_block(_read(_IDEATE_SKILL_MD))

    assert "for idx in $(seq 0 $((CANDIDATE_COUNT - 1)))" in block
    assert "yt-generate-image --ttp-strict-references" in block
    assert '--reference "${REF_PATHS[$idx]}"' in block
    assert "--max-attempts 1" in block
    assert 'yt-generate-image "${REF_ARGS[@]}"' not in block


def test_collection_ideate_sequential_uses_strict_single_reference_contract() -> None:
    """Given collection-ideate Phase 4-4 sequential
    When 選択済み 1 案を生成する
    Then codex/API とも選択 index の参照 1 枚だけを strict に使う。
    """
    block = _phase_4_4_sequential_block(_read(_IDEATE_SKILL_MD))

    assert "REF_INDEX" in block
    assert 'if [ "${#REF_PATHS[@]}" -le "$REF_INDEX" ]; then' in block
    assert "selected preview reference is missing" in block
    assert "codex-image.sh --require-reference" in block
    assert '"${REF_PATHS[$REF_INDEX]}"' in block
    assert "yt-generate-image --ttp-strict-references" in block
    assert '--reference "${REF_PATHS[$REF_INDEX]}"' in block
    assert "--max-attempts 1" in block


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
    Then parallel と同じ TTP thumbnail 先行 prompt template 契約を使う。
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
    assert "テキスト付き `10-assets/thumbnail.jpg` を先に生成・承認" in block, (
        "#1611/#1680: /thumbnail はテキスト付き thumbnail 先行フローを案内する"
    )
    assert "承認済み `thumbnail.jpg` からテキストなし `10-assets/main.png` または `main.jpg` を再生成" in block
    assert "承認済み背景からテキスト付き `10-assets/thumbnail.jpg`" not in block, (
        "#1680: textless 背景先行の旧記述を残さない"
    )
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
    assert "テキスト付き thumbnail を確定し、承認済み thumbnail から textless 背景を生成" in text
    assert "16:9 サムネ（動画背景用）" not in text
    assert "既存サムネ" not in text
    assert "textless 背景を先に生成" not in text


def test_collection_ideate_next_step_keeps_preview_out_of_main_background() -> None:
    """Given collection-ideate Next Step
    Then preview は企画参照であり main.png へ直接コピーしない。
    """
    block = _collection_ideate_next_step_block(_read(_IDEATE_SKILL_MD))

    assert "`main.png` にはコピーしない" in block
    assert "planning-preview.png" in block
    assert "`/thumbnail <theme>`" in block
    assert "テキスト付き `thumbnail.jpg` を先に確定" in block
    assert "承認済み `thumbnail.jpg` から textless `main.png/jpg` を別成果物として再生成・確定" in block
    assert "textless `main.png/jpg` を先に確定" not in block, "#1680: textless 背景先行の旧記述を残さない"
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

    assert "後段の `/thumbnail <theme>` がベンチマーク参照からテキスト付き `thumbnail.jpg` を先に生成・承認" in text
    assert "承認済み `thumbnail.jpg` から textless `main.png/jpg` を再生成" in text
    assert "textless `main.png/jpg` を先に生成・承認" not in text, "#1680: textless 背景先行の旧記述を残さない"
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
    assert lifecycle.find("textless `10-assets/main.png`") < lifecycle.find("テキスト付き `10-assets/thumbnail.jpg`")
    assert lifecycle.find("textless 動画背景作成") < lifecycle.find("サムネイル作成")
    assert "画像生成 → `10-assets/thumbnail.jpg`" not in lifecycle
