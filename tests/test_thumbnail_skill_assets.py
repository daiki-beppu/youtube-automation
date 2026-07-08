"""thumbnail skill の配布アセット内容を固定化するテスト。"""

import os
import subprocess
import sys
from pathlib import Path

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


def test_thumbnail_skill_documents_textless_background_to_text_included_flow() -> None:
    """#1502: /thumbnail は文字なし main 承認後に文字入り thumbnail を生成する。"""
    skill = _read_thumbnail_skill()

    standard_block = _slice_between(
        skill,
        "### 標準生成順序とファイル契約",
        "### Single-Step / TTP モード",
    )
    single_step_block = _slice_between(
        skill,
        "### Single-Step / TTP モード",
        "### Two-Phase モード（従来方式・フォールバック）",
    )

    for required in (
        "テキストなし動画背景 → テキスト付き YouTube サムネ",
        "ベンチマーク先サムネを参照画像",
        "10-assets/thumbnail.jpg",
        "10-assets/main.png",
        "10-assets/main.jpg",
        "承認済み `main.png/jpg` を参照画像",
        "/thumbnail-compare",
        "config/skills/loop-video.yaml::enabled: true",
        "config/skills/loop-video.yaml::enabled: false",
        "静止画背景",
        "両者を同一画像で代用しない",
    ):
        assert required in standard_block

    for required in (
        "/thumbnail-compare",
        "uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json",
        "cp main-v1.png main.png",
        "THUMBNAIL_PROMPT=\"$(cat <<'PROMPT'",
        '--reference "${COLLECTION_PATH}/10-assets/main.png"',
        '--prompt "$THUMBNAIL_PROMPT"',
        '--output "${COLLECTION_PATH}/10-assets/thumbnail-v1.jpg"',
        "cp thumbnail-v1.jpg thumbnail.jpg",
        "テキストなし背景生成プロンプト",
        "cp main-v1.png main.png",
        "テキスト付き生成プロンプト",
        "文字入り `thumbnail.jpg` をそのまま動画背景や `/loop-video` 入力にしない",
    ):
        assert required in single_step_block


def test_thumbnail_skill_frontmatter_names_thumbnail_as_primary_output() -> None:
    """#1611: skill dispatch は main.png ではなく text-included thumbnail.jpg を主成果物として説明する。"""
    skill = _read_thumbnail_skill()
    frontmatter = _slice_between(skill, "---", "---\n\n## Overview")

    assert "YouTube サムネイル（thumbnail.jpg）" in frontmatter
    assert "textless main.png/jpg を後続生成" in frontmatter
    assert "サムネイル（main.png）" not in frontmatter


def test_thumbnail_skill_initial_generation_examples_output_text_included_candidates() -> None:
    """#1310: 標準入口の初回生成例は main ではなく thumbnail 候補を出す。"""
    skill = _read_thumbnail_skill()
    mode_block = _slice_between(skill, "## 生成モード判定", "## ワークフロー")

    assert "--output <collection-path>/10-assets/thumbnail-v1.jpg -y" in mode_block
    assert "--output <collection-path>/10-assets/main-v1.png -y" not in mode_block


def test_thumbnail_skill_keeps_typography_out_of_initial_textless_prompt() -> None:
    """#1502: single_step 初回の textless 背景プロンプトへ title typography を混ぜない。"""
    skill = _read_thumbnail_skill()
    prompt_construction_block = _slice_between(skill, "#### プロンプト構築", "#### 生成コマンド")
    font_block = _slice_between(skill, "## フォント安定化", "## 品質チェック")

    assert "typography_clause" not in prompt_construction_block
    assert "Render the title text" not in prompt_construction_block
    assert "初回 `diff_prompt_template` は textless `main-v1.png/jpg` 背景生成専用" in font_block
    assert "`${typography_clause}` やタイトル文字の描画指示を入れない" in font_block
    assert "第2段のテキスト付き thumbnail prompt に `single_step.typography_clause` を展開" in font_block
    assert "diff_prompt_template` に `${typography_clause}` を展開" not in font_block


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
        "textless main 候補生成後",
        "`main-v1.png` / `main-v1.jpg`",
        "ベンチマーク参照の構図",
        "タイトル文字、字幕、ロゴ、透かし、タイポグラフィ、チャンネル名が残っていないか",
        "uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json",
        "テキスト付き thumbnail 候補生成後",
        "`thumbnail-v1.jpg` / `thumbnail-codex-v1.png`",
        "承認済み `main.png/jpg` の構図",
        "/thumbnail-compare",
        "タイトル可読性",
        "`thumbnail_text.channel_name` が表示されているか",
    ):
        assert required in qa_block

    assert qa_block.find("textless main 候補生成後") < qa_block.find("テキスト付き thumbnail 候補生成後")

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
    assert "textless 背景を先に承認" in two_phase_block
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


def test_thumbnail_skill_deterministic_text_path_keeps_textless_regeneration() -> None:
    """#1611: フォント固定経路でも承認済み thumbnail から textless main を後続生成する。"""
    skill = _read_thumbnail_skill()
    deterministic_block = _slice_between(
        skill,
        "### 決定的合成経路（yt-thumbnail-text）",
        "### フォント指定に失敗した場合",
    )

    assert "最初にテキスト付き `thumbnail-v*.jpg` を生成・承認して `thumbnail.jpg` を確定" in deterministic_block
    assert "承認済み `thumbnail.jpg` から textless `main-v*.png/jpg` を AI 再生成" in deterministic_block
    assert "cp main-v1.png main.png" in deterministic_block
    assert "フォント安定化だけを担う" in deterministic_block
    assert "旧順序には戻さず" in deterministic_block
    assert "承認済み thumbnail.jpg から textless 版を AI 再生成する」工程は不要" not in deterministic_block
    assert "背景がそのまま `main.png` になる" not in deterministic_block


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
    assert "variation_clause: |" in config
    assert "style_lock_clause: |" in config
    assert "text_strip_clause: |" in config
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
    assert 'diff_prompt_template: ""' in config


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

    assert "初回 textless 背景用の diff_prompt_template には展開しない" in config_text
    assert "diff_prompt_template に ${typography_clause} として展開する" not in config_text

    typography_clause = gemini_config["single_step"]["typography_clause"]
    assert "consistent {font_description} typeface" in typography_clause
    assert "Do not mix multiple typefaces" in typography_clause

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


def test_thumbnail_sample_prompts_are_short_ttp_diff_not_prompt_only_style() -> None:
    sample = (_repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "sample-prompts.md").read_text(
        encoding="utf-8"
    )

    assert "Single-Step / TTP の短い差分プロンプト" in sample
    assert "Create a stronger original textless background" in sample
    assert "Remove all text, typography, logos, signatures, watermarks" in sample
    assert "Do not add title text yet" in sample
    assert "内容改変なし・移動のみ" not in sample
    assert "プロンプトベースモード" not in sample
    assert "reference_images` がない場合" not in sample


def test_thumbnail_default_config_provides_codex_textless_background_prompt() -> None:
    """#1502: Codex 経路の既定プロンプトは TTP 背景先行型にする。"""
    template = _codex_prompt_template(_load_thumbnail_default_config())

    assert template.count("{title}") == 1
    for required in (
        "TTP this reference thumbnail into a stronger original textless background",
        "winning layout",
        "color mood",
        "Remove all text",
        "logos",
        "watermarks",
        "brand marks",
        "Do not add any title text yet",
    ):
        assert required in template


def test_channel_new_thumbnail_template_includes_codex_ttp_upgrade_prompt() -> None:
    """#1300: channel-new（再生成モード）で生成される thumbnail config も同じ Codex 既定文言を持つ。"""
    default_template = _codex_prompt_template(_load_thumbnail_default_config())
    channel_new_template = _codex_prompt_template(_load_channel_new_thumbnail_template())

    assert channel_new_template == default_template
    assert channel_new_template.count("{title}") == 1
    for required in (
        "TTP this reference thumbnail into a stronger original textless background",
        "winning layout",
        "color mood",
        "Remove all text",
        "logos",
        "watermarks",
        "brand marks",
        "Do not add any title text yet",
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
    assert "TTP this reference thumbnail into a stronger original textless background for Rain Study." in result.stdout
    assert "Do not add any title text yet" in result.stdout
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
    """#570: キャラ + 手構図向け anatomy-correctness clause が default config に同梱されている。"""
    config = _read_thumbnail_default_config()

    assert "anatomy_clause: |" in config
    # 解剖学品質ゲート core terms (issue #570 の修正要件 2)
    assert "five fingers" in config
    assert "fused" in config
    assert "extra" in config
    assert "melted" in config


def test_thumbnail_skill_quality_check_covers_hand_anatomy() -> None:
    """#570: 品質チェックに手・指の解剖学項目が含まれている。"""
    skill = _read_thumbnail_skill()
    quality_block = _slice_between(skill, "## 品質チェック", "## 視認性検証と整合性監査の役割分担")

    # issue #570 の修正要件 1: 手・指の解剖学チェック項目
    assert "解剖学" in quality_block
    assert "5 本指" in quality_block or "五本指" in quality_block
    assert "楽器" in quality_block
