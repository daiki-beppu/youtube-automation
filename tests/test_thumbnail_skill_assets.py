"""thumbnail skill の配布アセット内容を固定化するテスト。"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_thumbnail_skill() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "SKILL.md"
    return path.read_text(encoding="utf-8")


def _read_loop_video_skill() -> str:
    path = _repo_root() / ".claude" / "skills" / "loop-video" / "SKILL.md"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_default_config() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "config.default.yaml"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_diff_report() -> str:
    path = _repo_root() / "docs" / "skill-design" / "thumbnail-codex-imagegen-diff-report.md"
    return path.read_text(encoding="utf-8")


def _read_channel_new_thumbnail_template() -> str:
    path = (
        _repo_root()
        / ".claude"
        / "skills"
        / "channel-new"
        / "references"
        / "config-template"
        / "skills"
        / "thumbnail.yaml"
    )
    return path.read_text(encoding="utf-8")


def _read_codex_prompt_script() -> str:
    return _codex_prompt_script_path().read_text(encoding="utf-8")


def _codex_prompt_script_path() -> Path:
    return _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "codex-prompt.py"


def _thumbnail_archive_script_path() -> Path:
    return _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "archive-approved-thumbnail.py"


def _load_thumbnail_default_config() -> dict:
    return yaml.safe_load(_read_thumbnail_default_config()) or {}


def _load_channel_new_thumbnail_template() -> dict:
    return yaml.safe_load(_read_channel_new_thumbnail_template()) or {}


def _codex_prompt_template(config: dict) -> str:
    template = config["image_generation"]["codex"]["default_prompt_template"]
    assert isinstance(template, str)
    return template


def _slice_between(text: str, start_marker: str, end_marker: str) -> str:
    start_idx = text.find(start_marker)
    if start_idx == -1:
        raise AssertionError(f"{start_marker!r} が見つかりません")

    end_idx = text.find(end_marker, start_idx)
    if end_idx == -1:
        raise AssertionError(f"{end_marker!r} が見つかりません")

    return text[start_idx:end_idx]


def _collection_ideate_reference_validation_script() -> Path:
    return _repo_root() / ".claude" / "skills" / "collection-ideate" / "references" / "select-ttp-references.py"


def _collection_ideate_reference_history_script() -> Path:
    return (
        _repo_root() / ".claude" / "skills" / "collection-ideate" / "references" / "record-ttp-reference-assignments.py"
    )


def _run_collection_ideate_generation_block(
    tmp_path: Path,
    mode: str,
    references: list[Path],
    *,
    provider: str = "gemini",
) -> subprocess.CompletedProcess[str]:
    ideate_skill = (_repo_root() / ".claude" / "skills" / "collection-ideate" / "SKILL.md").read_text(encoding="utf-8")
    if mode == "parallel":
        section = _slice_between(
            ideate_skill,
            "**4-4: プロンプト構築 + 一括生成（parallel デフォルト）**",
            "### Phase 4 補足: sequential モード (opt-in)",
        )
        block = _slice_between(section, "# 順次実行。candidate_count", "```")
    else:
        section = _slice_between(
            ideate_skill,
            "**sequential 用 4-4 (選択 → 1 枚生成)**:",
            "**sequential 用 4-5 (1 枚承認)**:",
        )
        block = _slice_between(section, "# <x> は選択された企画", "```")
        block = re.sub(r'^REF_INDEX="<[^\n]+>"$', "REF_INDEX=0", block, count=1, flags=re.MULTILINE)

    block = block.replace("<dir>", "session").replace("<slug>", "preview").replace("<x>", "a")
    reference_values = " ".join(f'"{reference}"' for reference in references)
    script = f"CANDIDATE_COUNT={len(references)}\nREF_PATHS=({reference_values})\n{block}"

    history_dir = tmp_path / "collections" / "planning" / "_plan-previews" / "session"
    history_dir.mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == run && "$2" == python3 && "$3" == -c ]]; then\n'
        f"  printf '{provider}\\n'\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" == run && "$2" == python3 ]]; then\n'
        "  printf 'prompt\\n'\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" == run && "$2" == yt-generate-image ]]; then\n'
        '  for argument in "$@"; do\n'
        '    if [[ "$argument" == *.jpg ]]; then\n'
        '      printf \'%s\\n\' "$argument" >> "$INVOCATION_LOG"\n'
        '      [[ "$argument" == *fail* ]] && exit 23\n'
        "    fi\n"
        "  done\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    codex_image = tmp_path / ".claude" / "skills" / "thumbnail" / "references" / "codex-image.sh"
    codex_image.parent.mkdir(parents=True)
    codex_image.write_text(
        '#!/usr/bin/env bash\nfor argument in "$@"; do\n'
        '  if [[ "$argument" == *.jpg ]]; then\n'
        '    printf \'%s\\n\' "$argument" >> "$INVOCATION_LOG"\n'
        '    [[ "$argument" == *fail* ]] && exit 23\n'
        "  fi\n"
        "done\nexit 0\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    env["INVOCATION_LOG"] = str(tmp_path / "invocations.txt")
    return subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_codex_prompt_cli(tmp_path: Path, thumbnail_yaml: str, title: str) -> subprocess.CompletedProcess[str]:
    channel_dir = tmp_path / "channel"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "thumbnail.yaml").write_text(thumbnail_yaml, encoding="utf-8")

    env = os.environ.copy()
    env["CHANNEL_DIR"] = str(channel_dir)
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")

    return subprocess.run(
        [sys.executable, str(_codex_prompt_script_path()), title],
        cwd=_repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_thumbnail_skill_adds_ttp_preflight_checklist_before_two_phase_section() -> None:
    skill = _read_thumbnail_skill()

    checklist_idx = skill.find("#### TTP プリフライト・チェックリスト")
    recovery_idx = skill.find("#### 失敗時の対処")
    two_phase_idx = skill.find("### Two-Phase モード（従来方式・フォールバック）")

    assert recovery_idx != -1
    assert checklist_idx != -1
    assert two_phase_idx != -1
    assert recovery_idx < checklist_idx < two_phase_idx


def test_ttp_preflight_checklist_covers_required_operational_checks() -> None:
    skill = _read_thumbnail_skill()
    checklist_block = _slice_between(
        skill,
        "#### TTP プリフライト・チェックリスト",
        "### Two-Phase モード（従来方式・フォールバック）",
    )

    assert "reference_images.default" in checklist_block
    assert 'generation_mode: "single_step"' in checklist_block
    assert "diff_prompt_template" in checklist_block
    assert "image_generation.gemini.reference_images.stock.enabled" in checklist_block
    assert "--max-attempts" in checklist_block
    assert "参照不足" in checklist_block
    assert "--no-rotate" in checklist_block
    assert "/thumbnail-compare" in checklist_block
    assert "承認**前**" in checklist_block


def test_thumbnail_skill_isolates_private_repo_reference_as_operator_note() -> None:
    skill = _read_thumbnail_skill()
    rjn_lines = [line for line in skill.splitlines() if "daiki-beppu/rjn" in line]

    assert "実装事例として" not in skill
    assert rjn_lines == [
        "> **参考（オペレーター向け・実行時は無視してよい）**: `daiki-beppu/rjn` の "
        "`config/skills/thumbnail.yaml` が参考になる"
        "（jazzgak チャンネルの 5 サムネを `color_themes.<theme>.reference_image` で多軸切替）。"
        "private リポジトリのため下流リポジトリの実行者はアクセスできない。取得を試みないこと。"
    ]
    note = rjn_lines[0]
    assert note.startswith("> ")
    assert "実行時は無視" in note
    assert "取得を試みないこと" in note
    assert "color_themes.<theme>.reference_image" in note


def test_thumbnail_skill_documents_thumbnail_compare_and_alignment_check_roles() -> None:
    skill = _read_thumbnail_skill()
    quality_idx = skill.find("## 品質チェック")
    role_idx = skill.find("## 視認性検証と整合性監査の役割分担")
    prompt_idx = skill.find("## プロンプト保存")
    role_block = _slice_between(skill, "## 視認性検証と整合性監査の役割分担", "## プロンプト保存")

    assert quality_idx != -1
    assert role_idx != -1
    assert prompt_idx != -1
    assert quality_idx < role_idx < prompt_idx

    assert "/thumbnail-compare" in role_block
    assert "/alignment-check" in role_block
    assert "視認性検証" in role_block
    assert "整合性監査" in role_block
    assert "320px" in role_block
    assert "公開**後**" in role_block


def test_thumbnail_skill_documents_textless_first_deterministic_flow() -> None:
    """#1907: 標準フローは textless 背景を先に確定し yt-thumbnail-text で実フォント合成する。"""
    skill = _read_thumbnail_skill()

    standard_block = _slice_between(
        skill,
        "### 標準生成順序とファイル契約",
        "### thumbnail-text-profile 適用（#1907）",
    )
    single_step_block = _slice_between(
        skill,
        "### Single-Step / TTP モード",
        "### Two-Phase モード（従来方式・フォールバック）",
    )

    for required in (
        "textless 動画背景の生成 → `yt-thumbnail-text` による実フォント合成",
        "ベンチマーク先サムネを参照画像",
        "10-assets/thumbnail.jpg",
        "10-assets/main.png",
        "10-assets/main.jpg",
        "uv run yt-thumbnail-text",
        "--background <collection-path>/10-assets/main.png",
        "text_strip_clause",
        "uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json",
        "cp main-v1.png main.png",
        "cp thumbnail-v1.jpg thumbnail.jpg",
        "/thumbnail-compare",
        "config/skills/loop-video.yaml::enabled: true",
        "config/skills/loop-video.yaml::enabled: false",
        "静止画背景",
        "両者を同一画像で代用しない",
        "AI 焼き込み経路（fallback・非既定）",
    ):
        assert required in standard_block

    # textless 背景の確定が実フォント合成より先
    assert standard_block.find("cp main-v1.png main.png") < standard_block.find("uv run yt-thumbnail-text")
    # AI 焼き込みは運用者の明示選択のみ
    assert "運用者が明示的に選んだときだけ" in standard_block

    # AI 焼き込み経路（Single-Step 章）は fallback として従来契約のまま残す（#1901 の順序を維持）
    assert "AI 焼き込み経路（fallback・非既定）**の手順" in single_step_block
    for required in (
        "/thumbnail-compare",
        "cp thumbnail-v1.jpg thumbnail.jpg",
        "TEXTLESS_PROMPT=\"$(cat <<'PROMPT'",
        '--reference "${COLLECTION_PATH}/10-assets/thumbnail.jpg"',
        '--prompt "$TEXTLESS_PROMPT"',
        '--output "${COLLECTION_PATH}/10-assets/main-v1.png"',
        "uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json",
        "cp main-v1.png main.png",
        "テキストなし背景生成プロンプト",
        "テキスト付き生成プロンプト",
        "テキスト付き版の先行確定",
        "文字情報は `thumbnail.jpg` だけで扱う",
    ):
        assert required in single_step_block

    assert "承認済み `main.png/jpg` を参照画像にして" not in single_step_block
    assert "テキストなし版の先行確定" not in single_step_block


def test_thumbnail_skill_applies_thumbnail_text_profile_with_default_fallback() -> None:
    """#1907: thumbnail-text-profile の 3 セクションを適用し、不在時はデフォルト値で続行する。"""
    skill = _read_thumbnail_skill()
    profile_block = _slice_between(
        skill,
        "### thumbnail-text-profile 適用（#1907）",
        "### 承認済みサムネイルのアーカイブ",
    )

    for required in (
        "docs/benchmarks/thumbnail-text-profile.md",
        "`schema_version: 1`",
        ".claude/skills/channel-research/SKILL.md",
        "## font_tendency",
        "## text_content_pattern",
        "## placement_tendency",
        "image_generation.gemini.thumbnail_text.overlay.font.title",
        "`overlay.layout.anchor` / `margin_x` / `margin_y`",
        "typeface_classification",
        "line_count_range",
        "languages",
        "character_count_range",
        "copy_pattern",
        "anchor_position",
        "日本語対応 .ttf/.otf/.ttc",
        "競合のチャンネル名・コレクション名・シリーズ名・コピー原文",
    ):
        assert required in profile_block

    # profile 不在は前提ガードにしない（現行デフォルト値で続行）
    assert "前提ガードではない" in profile_block
    assert "エラーで停止しない" in profile_block
    assert "unknown" in profile_block
    # フォントはローカル既存ファイルのみ（同梱・自動ダウンロードはスコープ外）
    assert "同梱・自動ダウンロードはしない" in profile_block
    # profile 不在かつフォント未設定でもローカル選定でフォント揺れを解消する
    assert "profile 不在でも `overlay.font.title` が未設定の場合" in profile_block
    # config への書き込みはユーザー承認つきの明示更新
    assert "承認を得てから書き込む" in profile_block


def test_thumbnail_archive_is_opt_in_and_wired_after_every_approval_path() -> None:
    config = _load_thumbnail_default_config()
    skill = _read_thumbnail_skill()
    archive_command = (
        "uv run python .claude/skills/thumbnail/references/archive-approved-thumbnail.py <collection-path>"
    )

    assert config["archive"] == {"enabled": False}
    assert "archive.enabled: false" in skill
    assert "assets/thumbnail-gallery/<collection-dir-name>.<ext>" in skill
    # 標準（決定的合成）/ codex / Single-Step / Two-Phase の確定直後 + アーカイブ節本文 = 5
    assert skill.count(archive_command) == 5

    approval_block = _slice_between(skill, "### 承認済みサムネイルのアーカイブ", "### Single-Step / TTP モード")
    for approval_path in ("手動承認", "codex", "Two-Phase", "フォント固定", "自動選択"):
        assert approval_path in approval_block
    assert "確定直後" in approval_block
    assert "既存の検証・承認順序を変えず" in approval_block

    opening_gate = "\n".join(skill.splitlines()[:60])
    assert "**Hard Gate**" in opening_gate
    assert "アーカイブ" in opening_gate
    assert "後工程へ進まず停止" in opening_gate

    codex_block = _slice_between(skill, "## codex 経由の生成", "## Channel Adaptation")
    standard_block = _slice_between(
        skill,
        "### 標準生成順序とファイル契約",
        "### thumbnail-text-profile 適用（#1907）",
    )
    single_step_block = _slice_between(
        skill,
        "### Single-Step / TTP モード",
        "### Two-Phase モード（従来方式・フォールバック）",
    )
    two_phase_block = _slice_between(
        skill,
        "### Two-Phase モード（従来方式・フォールバック）",
        "## フォント安定化",
    )
    auto_selection_block = _slice_between(skill, "## 自動選択", "## 品質チェック")

    for wired_block in (codex_block, standard_block, single_step_block, two_phase_block):
        assert wired_block.find("thumbnail.jpg") < wired_block.find(archive_command)
    assert "uv run yt-thumbnail-auto-select <collection-path> --apply" in auto_selection_block
    assert "--apply &&" not in auto_selection_block
    assert "候補生成後のユーザー承認を省略" in auto_selection_block
    assert auto_selection_block.find("--apply") < auto_selection_block.find("自動確定後も `/thumbnail-compare`")
    assert "内部で実行" in approval_block


def test_thumbnail_skill_distributes_archive_script() -> None:
    assert _thumbnail_archive_script_path().is_file()


def test_thumbnail_skill_frontmatter_names_thumbnail_as_primary_output() -> None:
    """#1611: skill dispatch は main.png ではなく text-included thumbnail.jpg を主成果物として説明する。"""
    skill = _read_thumbnail_skill()
    frontmatter = skill.split("---\n", 2)[1]

    assert "YouTube サムネイル（thumbnail.jpg）" in frontmatter
    assert "textless main.png/jpg を先行生成して実フォント合成" in frontmatter
    assert "サムネイル（main.png）" not in frontmatter


def test_thumbnail_skill_documents_full_auto_selection_gate_contract() -> None:
    """#2167: full は 4 ゲートを省略し、selection_only の既存範囲を変えない。"""
    skill = _read_thumbnail_skill()
    opening_gate = "\n".join(skill.splitlines()[:60])
    auto_selection = _slice_between(skill, "## 自動選択", "## 品質チェック")

    for gate in ("テーマ確認", "生成可否", "textless 背景承認", "テキスト付き候補承認"):
        assert gate in opening_gate
    assert "mode: full" in opening_gate
    assert "残り 3 ゲートは従来どおり実行" in opening_gate

    assert "config のテーマ設定" in auto_selection
    assert "collection metadata" in auto_selection
    assert auto_selection.find("config のテーマ設定") < auto_selection.find("collection metadata")
    assert "workflow-state.json::theme" in auto_selection
    assert "生成 CLI に `-y`" in auto_selection
    assert "yt-thumbnail-auto-select <collection-path> --apply" in auto_selection
    assert "full モード失敗時の手動切替" in auto_selection
    assert "`selection_only` に変更" in auto_selection


def test_thumbnail_skill_initial_generation_examples_output_text_included_candidates() -> None:
    """#1310: 標準入口の初回生成例は main ではなく thumbnail 候補を出す。"""
    skill = _read_thumbnail_skill()
    mode_block = _slice_between(skill, "## 生成モード判定", "## ワークフロー")

    assert "--output <collection-path>/10-assets/thumbnail-v1.jpg -y" in mode_block
    assert "--output <collection-path>/10-assets/main-v1.png -y" not in mode_block


def test_thumbnail_skill_applies_typography_to_thumbnail_prompt_only() -> None:
    """#1901: single_step の書体指定は thumbnail 生成だけに使う。"""
    skill = _read_thumbnail_skill()
    prompt_construction_block = _slice_between(skill, "#### プロンプト構築", "#### 生成コマンド")
    font_block = _slice_between(skill, "## フォント安定化", "## 品質チェック")

    assert "typography_clause" in prompt_construction_block
    assert "text_strip_clause" in prompt_construction_block
    assert "テキスト付き `thumbnail-v*.jpg/png` 候補生成用" in font_block
    assert "`single_step.typography_clause` を展開" in font_block
    assert "textless 再生成プロンプトには、`${typography_clause}`" in font_block
    assert "初回 `diff_prompt_template` は textless" not in font_block


def test_thumbnail_skill_prompt_log_and_file_contract_cover_issue_1310_outputs() -> None:
    """#1310: prompt 保存とファイル命名が thumbnail/main/loop の役割を明示する。"""
    skill = _read_thumbnail_skill()
    prompt_block = _slice_between(skill, "## プロンプト保存", "## ファイル命名ルール（上書き禁止）")
    naming_block = _slice_between(skill, "## ファイル命名ルール（上書き禁止）", "### クリーンアップ")

    for required in (
        "## Textless Background Prompt (main.png/main.jpg)",
        "## Text-Included Thumbnail Prompt (thumbnail.jpg)",
        "テキストなし背景を生成したプロンプト",
        "テキスト付きサムネを生成したプロンプト",
        "`10-assets/thumbnail-v1.jpg`",
        "`10-assets/thumbnail-v2.jpg`",
    ):
        assert required in prompt_block

    for required in (
        "`thumbnail.jpg` | YouTube アップロード用のテキスト付き最終サムネ",
        "`thumbnail-v{N}.jpg` / `thumbnail-v{N}.png` / `thumbnail-codex-v{N}.png` | テキスト付き候補",
        "`main.png` / `main.jpg` | 動画背景・`/loop-video` 入力用のテキストなし最終画像",
        "`main-v{N}.png` / `main-v{N}.jpg` | テキストなし背景候補",
        "`loop.mp4` | `loop-video` 有効チャンネルだけで生成する動画背景",
        "無効チャンネルでは作らない",
    ):
        assert required in naming_block


def test_thumbnail_skill_quality_check_separates_thumbnail_and_textless_main_qa() -> None:
    """#1310: 品質チェックは文字入り thumbnail と textless main を逆に扱わない。"""
    skill = _read_thumbnail_skill()
    qa_block = _slice_between(skill, "## 品質チェック", "## 視認性検証")

    for required in (
        "テキスト付き thumbnail 候補生成後",
        "`thumbnail-v1.jpg` / `thumbnail-codex-v1.png`",
        "ベンチマーク参照の構図",
        "/thumbnail-compare",
        "タイトル可読性",
        "`thumbnail_text.channel_name` が表示されているか",
        "textless main 候補生成後",
        "`main-v1.png` / `main-v1.jpg`",
        "承認済み `thumbnail.jpg` の構図",
        "タイトル文字、字幕、ロゴ、透かし、タイポグラフィ、チャンネル名が残っていないか",
        "uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json",
    ):
        assert required in qa_block

    assert qa_block.find("テキスト付き thumbnail 候補生成後") < qa_block.find("textless main 候補生成後")
    assert "承認済み `main.png/jpg` の構図" not in qa_block

    assert "Phase 1 生成後" not in qa_block
    assert "Phase 2 生成後" not in qa_block
    assert "テキストが入っていないか" not in qa_block
    assert "single_step プレビューを最終 thumbnail に流用" not in qa_block


def test_thumbnail_skill_cleanup_archives_png_candidates() -> None:
    """#1310: 承認後 cleanup は main/thumbnail の PNG 候補も stock 退避する。"""
    skill = _read_thumbnail_skill()
    cleanup_block = _slice_between(skill, "### クリーンアップ", "### `workflow-state.json` 更新")

    for required in (
        "10-assets/main-v*.png",
        "10-assets/main-v*.jpg",
        "10-assets/thumbnail-v*.jpg",
        "10-assets/thumbnail-v*.png",
        "10-assets/thumbnail-codex-v*.png",
    ):
        assert required in cleanup_block


def test_thumbnail_skill_two_phase_keeps_thumbnail_and_main_separate() -> None:
    """#1310: Two-Phase フォールバックでも thumbnail と textless main を別成果物にする。"""
    skill = _read_thumbnail_skill()
    two_phase_block = _slice_between(skill, "### Two-Phase モード", "## 品質チェック")
    reference_phase_block = _slice_between(
        two_phase_block,
        "#### Phase 1: 既存参照の選択（新規生成しない）",
        "#### Phase 2: テキストオーバーレイ（thumbnail.jpg）",
    )
    first_generation_idx = two_phase_block.find("生成: `uv run yt-generate-image")
    first_generation_output_idx = two_phase_block.find("--output", first_generation_idx)
    thumbnail_generation_idx = two_phase_block.find("--output 10-assets/thumbnail-v1.jpg -y")

    assert "旧チャンネル向けのフォールバック" in two_phase_block
    assert "テキスト付き `thumbnail.jpg` を先に承認" in two_phase_block
    assert "承認済み `thumbnail.jpg` から textless `main.png/jpg` を後続生成" in two_phase_block
    assert "`thumbnail.jpg`（テキスト付き YouTube サムネ）" in two_phase_block
    assert "`main.png/jpg`（テキストなし動画背景）" in two_phase_block
    assert "既存 `main.png/jpg`、`planning-preview.png`、または `reference_images`" in two_phase_block
    assert "ここでは `yt-generate-image` を実行せず" in two_phase_block
    assert "最終 `main.png/jpg` は Phase 3 で承認済み `thumbnail.jpg` から AI 再生成" in two_phase_block
    assert first_generation_idx != -1
    assert first_generation_output_idx == thumbnail_generation_idx
    assert "--reference <既存参照画像>" in two_phase_block
    assert "--output 10-assets/draft-background-v1.png -y" not in two_phase_block
    assert "--reference 10-assets/draft-background-v1.png" not in two_phase_block
    assert "#### Phase 3: 承認済み thumbnail から textless main を再生成" in two_phase_block
    assert "承認済み `thumbnail.jpg` を参照して textless `main-v1.png` を AI 再生成" in two_phase_block
    assert "cp main-v1.png main.png" in two_phase_block
    assert "参照素材を `main.png/jpg` へコピーしない" in reference_phase_block
    assert "cp main-v1.png main.png" not in reference_phase_block
    assert "#### Phase 1: 背景候補生成（draft main）" not in two_phase_block
    assert "既に存在する場合は Phase 1 をスキップ" not in two_phase_block


def test_thumbnail_skill_deterministic_text_path_is_standard_default() -> None:
    """#1907: 決定的合成経路が標準の既定で、textless 背景を先に確定してから合成する。"""
    skill = _read_thumbnail_skill()
    font_block = _slice_between(skill, "## フォント安定化", "## 自動選択")
    deterministic_block = _slice_between(
        skill,
        "### 決定的合成経路（yt-thumbnail-text・標準）",
        "### フォント指定に失敗した場合",
    )

    # 経路表の既定は決定的合成、AI プロンプト経路は fallback
    assert "**決定的合成経路**（`yt-thumbnail-text`・**既定**）" in font_block
    assert "**AI プロンプト経路**（fallback・非既定）" in font_block
    assert "**AI プロンプト経路**（既定）" not in font_block

    assert "既定テキスト描画経路（#1907）" in deterministic_block
    assert "「標準生成順序とファイル契約」に従う" in deterministic_block
    assert "「thumbnail-text-profile 適用」節に従う" in deterministic_block
    assert "決定的合成はテキスト描画だけを担う" in deterministic_block
    # 文字入り画像を背景に流用しない（過去コレクションの作り直しでも textless を先に用意する）
    assert (
        "承認済み `thumbnail.jpg` から textless `main-v*.png/jpg` を AI 再生成・承認してから合成する"
        in deterministic_block
    )
    assert "文字入り画像を `--background` に流用しない" in deterministic_block
    # 旧契約（テキスト付き先行）の手順は標準から撤去済み
    assert "最初にテキスト付き `thumbnail-v*.jpg` を生成・承認して" not in deterministic_block
    assert "標準 `/thumbnail` フローから自動分岐しない" not in deterministic_block


def test_loop_video_skill_uses_textless_main_image_and_respects_disabled_channels() -> None:
    """#1310: /loop-video は文字入り thumbnail ではなく文字なし main を入力にする。"""
    skill = _read_loop_video_skill()
    prerequisites_block = _slice_between(skill, "### 前提条件", "### ステップ")
    steps_block = _slice_between(skill, "### ステップ", "### 構造化プロンプト（推奨）")

    for required in (
        "テキストなし `main.png/jpg`",
        "`thumbnail.jpg` は YouTube アップロード用のテキスト付きサムネイル",
        "`/loop-video` の入力には使わない",
        "config/skills/loop-video.yaml::enabled: false",
        "テキストなし `main.png/jpg` を静止画背景として使う",
    ):
        assert required in skill

    assert "`10-assets/thumbnail.jpg` ではなく、テキストなし `main.png/jpg` を入力" in prerequisites_block
    assert "Veo を実行せず" in steps_block
    assert "文字入り `thumbnail.jpg` しか無い場合は `/thumbnail` に戻って textless 背景を生成・承認" in steps_block


def test_thumbnail_default_config_remains_ttp_aligned() -> None:
    config = _read_thumbnail_default_config()

    assert "generation_mode: single_step" in config
    assert "既存参照から text-included thumbnail を先に確定" in config
    assert "承認済み thumbnail から textless main を後続再生成" in config
    assert "背景 → テキストオーバーレイ" not in config
    assert "rotate: true" in config
    # #1702: opt-in clause は既定空文字（キーは後方互換のため残す）
    assert 'variation_clause: ""' in config
    assert 'style_lock_clause: ""' in config
    assert 'text_strip_clause: ""' in config
    # #569: TTP 参照画像の署名・透かし・ロゴが焼き込まれる IP / 版権リスク防止
    assert "ip_safety_clause: |" in config
    assert "signature" in config
    assert "watermark" in config
    assert "logo" in config
    assert "brand mark" in config
    assert "候補ごとにユニークな参照画像" in config
    assert "参照画像が候補数より少ない場合は再利用せずエラー" in config
    assert "enabled: false" in config
    assert 'source_role: "thumbnail_candidate"' in config
    assert "fallback_when_empty: true" in config
    # #2070: gemini 既定 diff_prompt_template は空文字ではなく TTP 既定テンプレートを持つ
    assert 'diff_prompt_template: ""' not in config
    assert "diff_prompt_template: |" in config


def test_thumbnail_default_config_disables_ab_test_by_default() -> None:
    config = _load_thumbnail_default_config()

    assert config["ab_test"] == {"enabled": False, "patterns": []}


def test_thumbnail_skill_documents_ab_test_outputs_prompts_and_approval_contract() -> None:
    skill = _read_thumbnail_skill()
    block = _slice_between(
        skill,
        "### Test & compare 用 A/B pattern（opt-in）",
        "### thumbnail-text-profile 適用（#1907）",
    )

    for required in (
        "`ab_test` 未設定または `enabled: false`",
        "1〜3 件",
        "`variation`",
        "`ConfigError`",
        "--ab-pattern <name>",
        "thumbnail-<name>.jpg",
        "先頭 pattern",
        "thumbnail.jpg",
        "A/B Test Pattern Prompts",
        "全 pattern の承認が揃うまでは `thumbnail.approved` を `true` にしない",
        "Test & compare",
        "公式 API はない",
    ):
        assert required in block

    prompt_block = _slice_between(skill, "## プロンプト保存", "## ファイル命名ルール（上書き禁止）")
    assert "## A/B Test Pattern Prompts" in prompt_block
    assert "Pattern a Final Prompt" in prompt_block
    assert "Pattern b Final Prompt" in prompt_block

    state_block = _slice_between(skill, "### `workflow-state.json` 更新", "## stock 退避と再利用")
    assert "全 pattern" in state_block
    assert "先頭 pattern と同一内容" in state_block


def test_thumbnail_design_report_uses_current_two_phase_contract() -> None:
    report = _read_thumbnail_diff_report()
    two_phase_section = _slice_between(report, "### 3-8. Two-Phase モード", "### 3-9. 視認性検証")

    assert "既存参照 → thumbnail → textless main" in two_phase_section
    assert "Phase 2 でテキスト付き `thumbnail.jpg` を確定" in two_phase_section
    assert "承認済み `thumbnail.jpg` から textless `main.png/jpg` を再生成" in two_phase_section
    assert "背景 → テキストオーバーレイ" not in two_phase_section
    assert "Phase 1 で背景（`main.png`）を生成" not in two_phase_section


def test_thumbnail_default_config_keeps_font_stabilization_contract() -> None:
    config_text = _read_thumbnail_default_config()
    config = _load_thumbnail_default_config()
    gemini_config = config["image_generation"]["gemini"]

    assert "承認済み thumbnail から作る textless 再生成プロンプトには展開しない" in config_text
    assert "diff_prompt_template に ${typography_clause} として展開する" not in config_text

    # #1702: typography_clause は既定空文字の opt-in。推奨文面はコメントとして残す
    assert gemini_config["single_step"]["typography_clause"] == ""
    assert "consistent {font_description} typeface" in config_text
    assert "Do not mix multiple typefaces" in config_text

    overlay = gemini_config["thumbnail_text"]["overlay"]
    assert overlay["font"]["title"] == ""
    assert overlay["font"]["channel_name"] == ""
    assert overlay["title"]["size"] == 96
    assert overlay["title"]["stroke_width"] == 4
    assert overlay["channel_name"]["size"] == 36
    assert overlay["layout"]["anchor"] == "bottom-center"
    assert overlay["layout"]["line_spacing"] == 1.15


def test_thumbnail_skill_requires_reference_per_ttp_attempt_and_drops_prompt_only_fallback() -> None:
    skill = _read_thumbnail_skill()

    assert "参照画像モード（必須）" in skill
    assert "同じベンチマークチャンネル内の別サムネイル画像" in skill
    assert "各 attempt は別参照画像" in skill
    assert "thumbnail-prompts.md" in skill
    assert "benchmark_channel" in skill
    assert "プロンプトベースモード" not in skill
    assert "参照画像なしでプロンプトのみで生成" not in skill


def test_ttp_reference_dedup_is_documented_and_collection_ideate_passes_it() -> None:
    skill = _read_thumbnail_skill()
    config = _load_thumbnail_default_config()
    ideate_skill = (_repo_root() / ".claude" / "skills" / "collection-ideate" / "SKILL.md").read_text(encoding="utf-8")

    assert "reference_images.dedup_recent_collections" in skill
    assert config["image_generation"]["gemini"]["reference_images"]["dedup_recent_collections"] == 5
    assert ".claude/skills/collection-ideate/references/select-ttp-references.py" in ideate_skill
    assert ".claude/skills/collection-ideate/references/record-ttp-reference-assignments.py" in ideate_skill


def test_collection_ideate_persists_only_the_adopted_reference_after_selection() -> None:
    ideate_skill = (_repo_root() / ".claude" / "skills" / "collection-ideate" / "SKILL.md").read_text(encoding="utf-8")
    parallel = _slice_between(
        ideate_skill,
        "**4-4: プロンプト構築 + 一括生成（parallel デフォルト）**",
        "### Phase 4 補足: sequential モード (opt-in)",
    )
    sequential = _slice_between(
        ideate_skill,
        "**sequential 用 4-4 (選択 → 1 枚生成)**:",
        "**sequential 用 4-5 (1 枚承認)**:",
    )
    next_step = _slice_between(ideate_skill, "## Next Step", "### parallel モード（デフォルト）")

    assert "REFERENCE_HISTORY_FILE" not in parallel
    assert "REFERENCE_HISTORY_FILE" not in sequential
    assert next_step.count("record-ttp-reference-assignments.py") == 1
    assert '"$COLLECTION_PATH" "${REF_PATHS[$REF_INDEX]}"' in next_step


def test_collection_ideate_parallel_generation_failure_continues_to_later_candidates(tmp_path: Path) -> None:
    references = [tmp_path / "fail.jpg", tmp_path / "success.jpg"]

    result = _run_collection_ideate_generation_block(tmp_path, "parallel", references)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "invocations.txt").read_text(encoding="utf-8").splitlines() == [
        str(references[0]),
        str(references[1]),
    ]


def test_collection_ideate_sequential_generation_failure_is_nonzero_and_records_nothing(tmp_path: Path) -> None:
    references = [tmp_path / "fail.jpg"]

    result = _run_collection_ideate_generation_block(tmp_path, "sequential", references)

    history_file = tmp_path / "collections" / "planning" / "_plan-previews" / "session" / "reference-assignments.txt"
    assert result.returncode != 0
    assert not history_file.exists()


@pytest.mark.parametrize("mode", ["parallel", "sequential"])
def test_collection_ideate_codex_generation_success_uses_selected_reference(tmp_path: Path, mode: str) -> None:
    references = [tmp_path / "success.jpg"]

    result = _run_collection_ideate_generation_block(tmp_path, mode, references, provider="codex")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "invocations.txt").read_text(encoding="utf-8").splitlines() == [str(references[0])]


@pytest.mark.parametrize("mode", ["parallel", "sequential"])
def test_collection_ideate_codex_generation_failure_is_nonzero_and_records_nothing(tmp_path: Path, mode: str) -> None:
    references = [tmp_path / "fail.jpg"]

    result = _run_collection_ideate_generation_block(tmp_path, mode, references, provider="codex")

    history_file = tmp_path / "collections" / "planning" / "_plan-previews" / "session" / "reference-assignments.txt"
    assert result.returncode != 0
    assert not history_file.exists() or history_file.read_text(encoding="utf-8") == ""


def test_collection_ideate_reference_validation_executes_override_and_cross_state_history(tmp_path: Path) -> None:
    channel_dir = tmp_path / "channel"
    refs = [
        channel_dir / "data" / "thumbnail_compare" / "benchmark" / "jazzgak" / f"ref-{index}.jpg" for index in range(3)
    ]
    for ref in refs:
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_bytes(b"jpg")

    config_dir = channel_dir / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "thumbnail.yaml").write_text(
        yaml.safe_dump({"image_generation": {"gemini": {"reference_images": {"dedup_recent_collections": 1}}}}),
        encoding="utf-8",
    )
    for collection, reference in (
        ("planning/20260101-old", refs[1]),
        ("live/20260712-new", refs[0]),
    ):
        prompt_log = channel_dir / "collections" / collection / "20-documentation" / "thumbnail-prompts.md"
        prompt_log.parent.mkdir(parents=True)
        prompt_log.write_text(
            "## Reference Assignments\n"
            "| attempt | output | reference_image | benchmark_channel |\n"
            "|---:|---|---|---|\n"
            f"| 1 | output | `{reference.relative_to(channel_dir)}` | jazzgak |\n",
            encoding="utf-8",
        )

    env = os.environ.copy()
    env["CHANNEL_DIR"] = str(channel_dir)
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, str(_collection_ideate_reference_validation_script()), "2"],
        cwd=_repo_root(),
        env=env,
        input="".join(f"{ref}\n" for ref in refs),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(refs[2]), str(refs[1])]


def test_collection_ideate_persists_assignments_for_the_next_run(tmp_path: Path) -> None:
    channel_dir = tmp_path / "channel"
    refs = [
        channel_dir / "data" / "thumbnail_compare" / "benchmark" / "jazzgak" / f"ref-{index}.jpg" for index in range(3)
    ]
    for ref in refs:
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_bytes(b"jpg")

    env = os.environ.copy()
    env["CHANNEL_DIR"] = str(channel_dir)
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    validation_script = _collection_ideate_reference_validation_script()
    first = subprocess.run(
        [sys.executable, str(validation_script), "1"],
        cwd=_repo_root(),
        env=env,
        input="".join(f"{ref}\n" for ref in refs),
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout.splitlines() == [str(refs[0])]

    collection_dir = channel_dir / "collections" / "planning" / "20260713-first"
    prompt_log = collection_dir / "20-documentation" / "thumbnail-prompts.md"
    prompt_log.parent.mkdir(parents=True)
    prompt_log.write_text(
        "## Reference Assignments\n"
        "| attempt | output | reference_image | benchmark_channel |\n"
        "|---:|---|---|---|\n"
        f"| 1 | thumbnail | `{refs[2].relative_to(channel_dir)}` | jazzgak |\n"
        "\n## Prompt Details\nexisting thumbnail prompt\n",
        encoding="utf-8",
    )
    persisted = subprocess.run(
        [
            sys.executable,
            str(_collection_ideate_reference_history_script()),
            str(collection_dir),
            first.stdout.strip(),
        ],
        cwd=_repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert persisted.returncode == 0, persisted.stderr
    prompt_text = prompt_log.read_text(encoding="utf-8")
    assert prompt_text.count("## Reference Assignments") == 2
    assert f"`{refs[0].relative_to(channel_dir)}`" in prompt_text

    second = subprocess.run(
        [sys.executable, str(validation_script), "1"],
        cwd=_repo_root(),
        env=env,
        input="".join(f"{ref}\n" for ref in refs),
        text=True,
        capture_output=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert second.stdout.splitlines() == [str(refs[1])]


def test_collection_ideate_sequential_records_only_generated_reference_and_preserves_unused_order(
    tmp_path: Path,
) -> None:
    channel_dir = tmp_path / "channel"
    refs = [
        channel_dir / "data" / "thumbnail_compare" / "benchmark" / "jazzgak" / f"ref-{index}.jpg" for index in range(4)
    ]
    for ref in refs:
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_bytes(b"jpg")

    env = os.environ.copy()
    env["CHANNEL_DIR"] = str(channel_dir)
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    validation_script = _collection_ideate_reference_validation_script()
    selected = subprocess.run(
        [sys.executable, str(validation_script), "3"],
        cwd=_repo_root(),
        env=env,
        input="".join(f"{ref}\n" for ref in refs),
        text=True,
        capture_output=True,
        check=False,
    )
    assert selected.returncode == 0, selected.stderr
    selected_refs = selected.stdout.splitlines()
    assert selected_refs == [str(ref) for ref in refs[:3]]

    ref_index = 1
    collection_dir = channel_dir / "collections" / "planning" / "20260713-first"
    persisted = subprocess.run(
        [
            sys.executable,
            str(_collection_ideate_reference_history_script()),
            str(collection_dir),
            selected_refs[ref_index],
        ],
        cwd=_repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert persisted.returncode == 0, persisted.stderr
    prompt_log = (collection_dir / "20-documentation" / "thumbnail-prompts.md").read_text(encoding="utf-8")
    assert f"`{refs[1].relative_to(channel_dir)}`" in prompt_log
    assert f"`{refs[0].relative_to(channel_dir)}`" not in prompt_log
    assert f"`{refs[2].relative_to(channel_dir)}`" not in prompt_log

    next_selection = subprocess.run(
        [sys.executable, str(validation_script), "3"],
        cwd=_repo_root(),
        env=env,
        input="".join(f"{ref}\n" for ref in refs),
        text=True,
        capture_output=True,
        check=False,
    )
    assert next_selection.returncode == 0, next_selection.stderr
    assert next_selection.stdout.splitlines() == [str(refs[0]), str(refs[2]), str(refs[3])]


def test_collection_ideate_cycles_entire_pool_before_reuse(tmp_path: Path) -> None:
    channel_dir = tmp_path / "channel"
    refs = [
        channel_dir / "data" / "thumbnail_compare" / "benchmark" / "jazzgak" / f"ref-{index}.jpg" for index in range(5)
    ]
    for ref in refs:
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_bytes(b"jpg")

    env = os.environ.copy()
    env["CHANNEL_DIR"] = str(channel_dir)
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    validation_script = _collection_ideate_reference_validation_script()
    history_script = _collection_ideate_reference_history_script()
    selected: list[str] = []
    planned: list[list[str]] = []

    for index in range(len(refs)):
        validation = subprocess.run(
            [sys.executable, str(validation_script), "3"],
            cwd=_repo_root(),
            env=env,
            input="".join(f"{ref}\n" for ref in refs),
            text=True,
            capture_output=True,
            check=False,
        )
        assert validation.returncode == 0, validation.stderr
        planned_references = validation.stdout.splitlines()
        planned.append(planned_references)
        generated = _run_collection_ideate_generation_block(
            tmp_path / f"preview-{index}",
            "parallel",
            [Path(reference) for reference in planned_references],
        )
        assert generated.returncode == 0, generated.stderr
        invocation_log = tmp_path / f"preview-{index}" / "invocations.txt"
        assert invocation_log.read_text(encoding="utf-8").splitlines() == planned_references

        selected_reference = planned_references[0]
        selected.append(selected_reference)
        persisted = subprocess.run(
            [
                sys.executable,
                str(history_script),
                str(channel_dir / "collections" / "planning" / f"2026071{index}-collection"),
                selected_reference,
            ],
            cwd=_repo_root(),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert persisted.returncode == 0, persisted.stderr

    assert selected == [str(ref) for ref in refs]
    assert planned == [
        [str(refs[0]), str(refs[1]), str(refs[2])],
        [str(refs[1]), str(refs[2]), str(refs[3])],
        [str(refs[2]), str(refs[3]), str(refs[4])],
        [str(refs[3]), str(refs[4]), str(refs[0])],
        [str(refs[4]), str(refs[0]), str(refs[1])],
    ]

    after_cycle = subprocess.run(
        [sys.executable, str(validation_script), "3"],
        cwd=_repo_root(),
        env=env,
        input="".join(f"{ref}\n" for ref in refs),
        text=True,
        capture_output=True,
        check=False,
    )
    assert after_cycle.returncode == 0, after_cycle.stderr
    assert after_cycle.stdout.splitlines()[0] == str(refs[0])


def test_collection_ideate_reference_history_failure_is_nonzero(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "channel" / "blocked"
    blocked_parent.parent.mkdir(parents=True)
    blocked_parent.write_text("not a directory", encoding="utf-8")
    collection_dir = blocked_parent / "20260713-collection"
    env = os.environ.copy()
    env["CHANNEL_DIR"] = str(tmp_path / "channel")
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            str(_collection_ideate_reference_history_script()),
            str(collection_dir),
            str(tmp_path / "reference.jpg"),
        ],
        cwd=_repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "参照画像履歴を保存できません" in result.stderr


def test_thumbnail_sample_prompts_are_short_ttp_diff_not_prompt_only_style() -> None:
    sample = (_repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "sample-prompts.md").read_text(
        encoding="utf-8"
    )

    assert "Single-Step / TTP の短い差分プロンプト" in sample
    assert "Create a stronger original YouTube thumbnail" in sample
    assert "Render the title text clearly for mobile readability" in sample
    assert "Do not reproduce logos, signatures, watermarks, brand marks, or broken hands" in sample
    assert "textless 背景を先に生成" not in sample
    assert "Do not add title text yet" not in sample
    assert "内容改変なし・移動のみ" not in sample
    assert "プロンプトベースモード" not in sample
    assert "reference_images` がない場合" not in sample


def _skill_md_codex_default_template() -> str:
    """thumbnail/SKILL.md の「既定テンプレート:」直後の ```text fenced block を抽出する。"""
    skill = _read_thumbnail_skill()
    match = re.search(r"既定テンプレート:\n\n```text\n(.*?)```\n", skill, flags=re.DOTALL)
    assert match is not None, "thumbnail/SKILL.md に「既定テンプレート」の ```text ブロックが見つかりません"
    return match.group(1)


def test_thumbnail_default_config_provides_codex_thumbnail_first_prompt() -> None:
    """#1680: Codex 経路の既定プロンプトは #1611 のテキスト付き thumbnail 先行型にする。"""
    template = _codex_prompt_template(_load_thumbnail_default_config())

    assert template.count("{title}") == 1
    for required in (
        "TTP this reference thumbnail, then improve it into a stronger original thumbnail",
        "winning layout",
        "typography feel",
        "color mood",
        "more readable on mobile",
        "no logos",
        "no watermarks",
        "no broken hands",
        "Use the title {title}.",
    ):
        assert required in template
    for forbidden in (
        "textless background",
        "Remove all text",
        "Do not add any title text yet",
    ):
        assert forbidden not in template


def _gemini_diff_prompt_template(config: dict) -> str:
    template = config["image_generation"]["gemini"]["diff_prompt_template"]
    assert isinstance(template, str)
    return template


def _codex_policy_lines(template: str) -> list[str]:
    """codex 既定テンプレートから title 行を除いた TTP 方針行（winning layout 維持・最小改善）を返す。"""
    policy = [line for line in template.strip().splitlines() if line and "{title}" not in line]
    assert policy, "codex 既定テンプレートから方針行を抽出できません"
    return policy


def test_thumbnail_default_config_gemini_diff_template_syncs_codex_ttp_policy() -> None:
    """#2070: gemini 既定 diff_prompt_template は codex 既定テンプレート（SSOT）と同じ TTP 方針行を持つ。"""
    config = _load_thumbnail_default_config()
    codex_template = _codex_prompt_template(config)
    gemini_template = _gemini_diff_prompt_template(config)

    for policy_line in _codex_policy_lines(codex_template):
        assert policy_line in gemini_template

    # title は codex の {title} 意味論と同じく「サムネに焼くテキスト」を行単位で渡す
    assert gemini_template.count("{title_line1}") == 1
    assert gemini_template.count("{title_line2}") == 1
    # TTP モード常時挿入必須の ip_safety_clause (#569) を既定で展開対象にする
    assert "${ip_safety_clause}" in gemini_template
    for forbidden in (
        "textless background",
        "Remove all text",
        "Do not add any title text yet",
    ):
        assert forbidden not in gemini_template


def test_thumbnail_gemini_diff_template_channel_override_takes_priority(tmp_path, monkeypatch) -> None:
    """#2070: channel 側 diff_prompt_template は deep-merge のスカラ置換で既定値より常に優先される。"""
    from youtube_automation.utils import skill_config

    override_dir = tmp_path / "config" / "skills"
    override_dir.mkdir(parents=True)
    (override_dir / "thumbnail.yaml").write_text(
        'image_generation:\n  gemini:\n    diff_prompt_template: "channel custom prompt {title_line1}"\n',
        encoding="utf-8",
    )

    merged = skill_config.load_skill_config("thumbnail", use_cache=False, channel_dir=tmp_path)

    assert merged["image_generation"]["gemini"]["diff_prompt_template"] == "channel custom prompt {title_line1}"
    # dict 部分は default が残る (deep-merge 検証)
    assert "ip_safety_clause" in merged["image_generation"]["gemini"]["single_step"]


def test_thumbnail_docs_state_provider_agnostic_ttp_policy() -> None:
    """#2070: SKILL.md / prompting.md が provider 差なく同じ TTP 方針を明示する。"""
    skill = _read_thumbnail_skill()
    prompting = (_repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "prompting.md").read_text(
        encoding="utf-8"
    )

    assert "TTP 生成方針は provider によらず共通" in skill
    assert "TTP 方針は provider 共通" in prompting
    assert "チャンネル側 override" in prompting
    # #2071: gemini_cli 経路も同じ diff_prompt_template と構築手順を共有することを明示
    assert "`provider: gemini_cli`" in skill
    assert "同じ `diff_prompt_template` とこの構築手順を共有" in skill


def test_thumbnail_default_config_codex_template_matches_skill_md_block() -> None:
    """#1680: SKILL.md「既定テンプレート」ブロックと config.default.yaml を完全一致で機械担保する。"""
    config_template = _codex_prompt_template(_load_thumbnail_default_config())
    skill_template = _skill_md_codex_default_template()

    assert config_template == skill_template


def test_channel_new_thumbnail_template_includes_codex_ttp_upgrade_prompt() -> None:
    """#1300 / #1680: channel-new（再生成モード）で生成される thumbnail config も同じ Codex 既定文言を持つ。"""
    default_template = _codex_prompt_template(_load_thumbnail_default_config())
    channel_new_template = _codex_prompt_template(_load_channel_new_thumbnail_template())

    assert channel_new_template == default_template
    assert channel_new_template.count("{title}") == 1
    for required in (
        "TTP this reference thumbnail, then improve it into a stronger original thumbnail",
        "winning layout",
        "typography feel",
        "color mood",
        "more readable on mobile",
        "no logos",
        "no watermarks",
        "no broken hands",
        "Use the title {title}.",
    ):
        assert required in channel_new_template


def test_channel_new_thumbnail_template_includes_channel_branding_contract() -> None:
    template = _load_channel_new_thumbnail_template()
    reference_images = template["image_generation"]["gemini"]["reference_images"]

    assert reference_images["channel_branding"] == {
        "snapshot": "docs/channel/competitor-branding-snapshot.json",
        "icon_references": ["{{CHANNEL_BRANDING_ICON_REFERENCE}}"],
        "banner_references": ["{{CHANNEL_BRANDING_BANNER_REFERENCE}}"],
        "output_icon": "branding/icon.png",
        "output_banner": "branding/banner.png",
    }


def test_thumbnail_skill_includes_codex_prompt_helper_script() -> None:
    """#1300: collection-ideate から共有する Codex prompt helper を同梱する。"""
    script = _read_codex_prompt_script()

    assert "from youtube_automation.utils.image_provider.config import build_codex_prompt" in script
    assert 'load_skill_config("thumbnail")' in script
    assert 'parser.add_argument("title"' in script


def test_codex_prompt_helper_cli_renders_default_template(tmp_path: Path) -> None:
    """#1300: provider=codex の最小 override で default template を title 差し替えして出力する。"""
    result = _run_codex_prompt_cli(
        tmp_path,
        "image_generation:\n  provider: codex\n",
        "Rain Study",
    )

    assert result.returncode == 0, result.stderr
    assert "TTP this reference thumbnail, then improve it into a stronger original thumbnail." in result.stdout
    assert "Use the title Rain Study." in result.stdout
    assert "{title}" not in result.stdout


def test_codex_prompt_helper_cli_rejects_non_codex_provider(tmp_path: Path) -> None:
    """#1300: codex 以外の provider では prompt helper を失敗させる。"""
    result = _run_codex_prompt_cli(
        tmp_path,
        "image_generation:\n  provider: gemini\n",
        "Rain Study",
    )

    assert result.returncode != 0
    assert "provider=codex" in result.stderr


def test_codex_prompt_helper_cli_rejects_empty_title(tmp_path: Path) -> None:
    """#1300: 空 title は title 差し替え入口で失敗させる。"""
    result = _run_codex_prompt_cli(
        tmp_path,
        "image_generation:\n  provider: codex\n",
        "",
    )

    assert result.returncode != 0
    assert "title" in result.stderr


def test_codex_prompt_helper_cli_rejects_invalid_template(tmp_path: Path) -> None:
    """#1300: `{title}` を含まない override template は失敗させる。"""
    result = _run_codex_prompt_cli(
        tmp_path,
        "image_generation:\n  provider: codex\n  codex:\n    default_prompt_template: No placeholder.\n",
        "Rain Study",
    )

    assert result.returncode != 0
    assert "default_prompt_template" in result.stderr


def test_thumbnail_default_config_provides_anatomy_clause() -> None:
    """#570 / #1702: anatomy clause は opt-in（既定空文字）だが推奨文面はコメントで同梱する。"""
    config_text = _read_thumbnail_default_config()
    config = _load_thumbnail_default_config()

    assert config["image_generation"]["gemini"]["single_step"]["anatomy_clause"] == ""
    # 解剖学品質ゲート core terms (issue #570 の修正要件 2) は推奨文面コメントとして残す
    assert "five fingers" in config_text
    assert "fused" in config_text
    assert "extra" in config_text
    assert "melted" in config_text


def test_thumbnail_default_config_injects_only_ip_safety_clause_by_default() -> None:
    """#1702: 既定で注入される clause は ip_safety_clause の 1 つだけに集約する。"""
    config = _load_thumbnail_default_config()
    single_step = config["image_generation"]["gemini"]["single_step"]

    clause_keys = [key for key in single_step if key.endswith("_clause")]
    non_empty = [key for key in clause_keys if single_step[key]]
    assert non_empty == ["ip_safety_clause"]

    template = _gemini_diff_prompt_template(config)
    assert re.findall(r"\$\{(\w+)\}", template) == ["ip_safety_clause"]


def test_thumbnail_default_config_slims_composition_rules_and_thumbnail_text() -> None:
    """#1702: composition_rules は text_lines のみ、thumbnail_text は text_overlay_prompt を単一入口にする。"""
    config_text = _read_thumbnail_default_config()
    config = _load_thumbnail_default_config()
    gemini = config["image_generation"]["gemini"]

    assert gemini["composition_rules"] == {"text_lines": "タイトルは 2 行以内"}
    assert set(gemini["thumbnail_text"]) == {"channel_name", "font", "text_overlay_prompt", "overlay"}
    # 段階的廃止方針（deprecated キーと移行ガイド）が明記されている
    assert "deprecated" in config_text
    assert "DeprecationWarning" in config_text
    assert "移行ガイド" in config_text


def test_thumbnail_skill_prompt_section_is_single_source_with_final_prompt_example() -> None:
    """#1702: プロンプト指示解説は 1 セクション + モード別差分に集約し、最終プロンプト例を 1 例掲載する。"""
    skill = _read_thumbnail_skill()
    prompt_section = _slice_between(skill, "## プロンプト構築", "## ワークフロー")

    assert "最小限のキーワード" in prompt_section
    assert "参照画像主導" in prompt_section
    assert "モード別差分" in prompt_section
    # 実際にプロバイダーへ渡る最終プロンプト例（既定 config の全文）
    assert "```text" in prompt_section
    assert "Use the title" in prompt_section
    assert "Do not reproduce any signature" in prompt_section
    # 既定 clause は ip_safety のみ。多重 clause の同時展開指示は解消済み
    assert "${ip_safety_clause}` の 1 つだけ" in prompt_section
    single_step_prompt_block = _slice_between(skill, "#### プロンプト構築", "#### 生成コマンド")
    assert "共通ガイダンス clause（`single_step.variation_clause` / `style_lock_clause`" not in single_step_prompt_block
    assert "opt-in clause" in single_step_prompt_block


def test_thumbnail_skill_quality_check_covers_hand_anatomy() -> None:
    """#570: 品質チェックに手・指の解剖学項目が含まれている。"""
    skill = _read_thumbnail_skill()
    quality_block = _slice_between(skill, "## 品質チェック", "## 視認性検証と整合性監査の役割分担")

    # issue #570 の修正要件 1: 手・指の解剖学チェック項目
    assert "解剖学" in quality_block
    assert "5 本指" in quality_block or "五本指" in quality_block
    assert "楽器" in quality_block
