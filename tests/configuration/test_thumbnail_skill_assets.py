"""thumbnail skill の配布アセット内容を固定化するテスト。"""

import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageChops, ImageStat

from tests.helpers.paths import REPO_ROOT


def _repo_root() -> Path:
    return REPO_ROOT


def _read_thumbnail_skill() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "SKILL.md"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_compare_reference() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "compare.md"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_provider_guidance() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "provider-guidance.md"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_generation_workflows() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "generation-workflows.md"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_quality_and_operations() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "quality-and-operations.md"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_prompt_schema() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "prompt-schema.md"
    return path.read_text(encoding="utf-8")


def _read_loop_video_skill() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "loop.md"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_default_config() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "config.default.yaml"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_diff_report() -> str:
    path = _repo_root() / "docs" / "skill-design" / "thumbnail-codex-imagegen-diff-report.md"
    return path.read_text(encoding="utf-8")


def _read_setup_thumbnail_template() -> str:
    path = (
        _repo_root() / ".claude" / "skills" / "setup" / "references" / "config-template" / "skills" / "thumbnail.yaml"
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


def _load_setup_thumbnail_template() -> dict:
    return yaml.safe_load(_read_setup_thumbnail_template()) or {}


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
    return _repo_root() / ".claude" / "skills" / "wf-new" / "references" / "select-ttp-references.py"


def _collection_ideate_reference_history_script() -> Path:
    return _repo_root() / ".claude" / "skills" / "wf-new" / "references" / "record-ttp-reference-assignments.py"


def _run_collection_ideate_generation_block(
    tmp_path: Path,
    mode: str,
    references: list[Path],
    *,
    provider: str = "gemini",
) -> subprocess.CompletedProcess[str]:
    ideate_skill = (_repo_root() / ".claude" / "skills" / "wf-new" / "references" / "ideate.md").read_text(
        encoding="utf-8"
    )
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


def test_thumbnail_compare_is_disclosed_as_a_thumbnail_mode() -> None:
    root = _repo_root()
    skill = _read_thumbnail_skill()
    compare = _read_thumbnail_compare_reference()

    assert not (root / ".claude" / "skills" / "thumbnail-compare").exists()
    assert "| `--compare` | `references/compare.md` |" in skill
    assert "2 個以上の mode" in skill
    assert "`/channel-research --benchmark` を案内して停止" in compare
    assert "320px 縮小表示テスト" in compare

    compare_script = root / ".claude" / "skills" / "thumbnail" / "references" / "compare_thumbnails.py"
    assert compare_script.is_symlink()
    assert compare_script.resolve() == (
        root / "src" / "youtube_automation" / "commands" / "thumbnail" / "compare_thumbnails.py"
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
    assert "/thumbnail --compare" in checklist_block
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

    assert "/thumbnail --compare" in role_block
    assert "/audit --alignment" in role_block
    assert "視認性検証" in role_block
    assert "整合性監査" in role_block
    assert "320px" in role_block
    assert "公開**後**" in role_block


def test_thumbnail_skill_routes_provider_details_without_moving_runtime_gates() -> None:
    skill = _read_thumbnail_skill()
    provider_block = _slice_between(skill, "## プロバイダー切り替え", "## Channel Adaptation")

    assert "[provider/Codex 詳細](references/provider-guidance.md)" in provider_block
    assert provider_block.count("bash .claude/skills/thumbnail/references/codex-image.sh --require-reference") == 1
    assert provider_block.count("bash .claude/skills/thumbnail/references/codex-image-batch.sh") == 1
    for required in (
        "`image_generation.provider`",
        "`gemini`",
        "`openai`",
        "`codex`",
        "デフォルトは `gemini`",
        "codex 経路でも標準ファイル契約は同じ",
        "10-assets/thumbnail.jpg",
        "10-assets/main.png",
    ):
        assert required in provider_block

    assert "confirm_cost()" in skill
    assert "## 完了条件" in skill


def test_thumbnail_provider_guidance_owns_protocol_and_failure_details_once() -> None:
    skill = _read_thumbnail_skill()
    guidance = _read_thumbnail_provider_guidance()
    combined = skill + "\n" + guidance
    moved_details = (
        "旧 stdout プロトコル `generated image <id> <base64>`",
        "wrapper は JSONL を `jq` でフィルタ",
        "最終的に `<out>` の MD5 と一致したら",
        "`image_generation` tool 呼び出しを skip して path だけ echo",
        "reference を `<out>` に cp するだけで終わる",
    )

    for detail in moved_details:
        assert detail not in skill
        assert guidance.count(detail) == 1
        assert combined.count(detail) == 1


def test_thumbnail_skill_documents_ai_burn_in_default_and_deterministic_opt_in() -> None:
    """#3312: AI 焼き込みを既定に戻し、決定的合成は明示 opt-in とする。"""
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
        "yt-thumbnail-review --artifact main",
        "yt-thumbnail-review --artifact thumbnail",
        "/thumbnail --compare",
        "config/skills/loop-video.yaml::enabled: true",
        "/thumbnail --loop",
        "/video --generate",
        "静止画背景",
        "両者を同一画像で代用しない",
        "AI 焼き込み経路（既定）",
        "text_render.mode: deterministic",
    ):
        assert required in standard_block

    # deterministic 経路では textless 背景の確定が実フォント合成より先
    assert standard_block.find("yt-thumbnail-review --artifact main") < standard_block.find("uv run yt-thumbnail-text")
    # 既定は文字入り候補を先に生成し、決定的合成だけを明示 opt-in にする
    assert standard_block.find("AI 焼き込み経路（既定）") < standard_block.find(
        "決定的合成経路（`text_render.mode: deterministic`"
    )
    assert "未設定または `ai_burn_in` は既定" in standard_block

    # AI 焼き込み経路（Single-Step 章）が未設定 / ai_burn_in の標準手順
    assert "未設定 / `text_render.mode: ai_burn_in` の標準手順" in single_step_block
    for required in (
        "/thumbnail --compare",
        "yt-thumbnail-review --artifact thumbnail",
        "TEXTLESS_PROMPT=\"$(cat <<'PROMPT'",
        '--reference "${COLLECTION_PATH}/10-assets/thumbnail.jpg"',
        '--prompt "$TEXTLESS_PROMPT"',
        '--output "${COLLECTION_PATH}/10-assets/main-v1.png"',
        "uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json",
        "yt-thumbnail-review --artifact main",
        "テキストなし背景生成プロンプト",
        "テキスト付き生成プロンプト",
        "テキスト付き版の先行確定",
        "文字情報は `thumbnail.jpg` だけで扱う",
    ):
        assert required in single_step_block

    assert "承認済み `main.png/jpg` を参照画像にして" not in single_step_block
    assert "テキストなし版の先行確定" not in single_step_block


def test_thumbnail_skill_requires_manual_comparison_before_selecting_multiple_candidates() -> None:
    """#3622: 手動経路では全候補を比較し、選択された候補だけを確定する。"""
    skill = _read_thumbnail_skill()

    comparison_contract = _slice_between(
        skill,
        "#### 手動候補の比較選択 Hard Gate",
        "### Test & compare 用 A/B pattern（opt-in）",
    )
    for required in (
        "候補が 2 枚以上",
        "生成失敗",
        "yt-thumbnail-review --collection <collection-path> --artifact thumbnail",
        "--artifact main",
        "--pattern <name>",
        "原寸画像",
        "実幅320px表示",
        "candidate ID",
        "--transport terminal",
        "--candidate-id <ID>",
        "直接 `cp` しない",
        "成功候補が1枚",
        "auto_selection.enabled: true",
        "selection_only",
        "full",
        "別の `--reference-index`",
        "diff_prompt_template",
    ):
        assert required in comparison_contract

    assert comparison_contract.find("既存 `yt-thumbnail-check` と比較 QA") < comparison_contract.find(
        "yt-thumbnail-review --collection"
    )
    assert comparison_contract.find("共通selection broker") < comparison_contract.find(
        "atomic copy、archive、workflow-state owner"
    )

    standard_block = _slice_between(
        skill,
        "### 標準生成順序とファイル契約",
        "### Test & compare 用 A/B pattern（opt-in）",
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

    assert "背景候補は「手動候補の比較選択 Hard Gate」" in standard_block
    assert "テキスト付き候補は「手動候補の比較選択 Hard Gate」" in standard_block
    assert "4. テキスト付き候補は「手動候補の比較選択 Hard Gate」" in single_step_block
    assert "4. テキスト付き候補は「手動候補の比較選択 Hard Gate」" in two_phase_block


def _load_shared_main_module(name: str):
    script = _repo_root() / ".claude/skills/thumbnail/references/share_thumbnail_as_main.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_preview_finalizer_module(name: str):
    script = _repo_root() / ".claude/skills/thumbnail/references/finalize_planning_preview.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_finalize_planning_preview_preserves_visual_content(tmp_path: Path) -> None:
    module = _load_preview_finalizer_module("finalize_planning_preview")
    collection = tmp_path / "collection"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    preview = assets / "planning-preview.png"
    source = Image.new("RGB", (48, 32), "#17324d")
    for x in range(24, 48):
        for y in range(16, 32):
            source.putpixel((x, y), (220, 145, 38))
    source.save(preview, "PNG")

    result = module.finalize_planning_preview(collection)

    thumbnail = assets / "thumbnail.jpg"
    with Image.open(thumbnail) as converted:
        assert converted.format == "JPEG"
        assert converted.size == source.size
        difference = ImageStat.Stat(ImageChops.difference(source, converted.convert("RGB")))
    assert max(difference.mean) < 1.0
    assert result == {
        "status": "FINALIZED",
        "source": str(preview),
        "destination": str(thumbnail),
    }
    assert not list(assets.glob(".thumbnail-preview-*"))


def test_finalize_planning_preview_reports_missing_without_creating_thumbnail(tmp_path: Path) -> None:
    module = _load_preview_finalizer_module("finalize_planning_preview_missing")
    collection = tmp_path / "collection"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)

    result = module.finalize_planning_preview(collection)

    assert result == {
        "status": "MISSING",
        "source": str(assets / "planning-preview.png"),
    }
    assert not (assets / "thumbnail.jpg").exists()


def test_finalize_planning_preview_failure_preserves_existing_thumbnail(tmp_path: Path) -> None:
    module = _load_preview_finalizer_module("finalize_planning_preview_failure")
    collection = tmp_path / "collection"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    (assets / "planning-preview.png").write_bytes(b"not-an-image")
    thumbnail = assets / "thumbnail.jpg"
    thumbnail.write_bytes(b"existing-thumbnail")

    with pytest.raises(OSError):
        module.finalize_planning_preview(collection)

    assert thumbnail.read_bytes() == b"existing-thumbnail"
    assert not list(assets.glob(".thumbnail-preview-*"))


def test_finalize_planning_preview_rejects_broken_symlink(tmp_path: Path) -> None:
    module = _load_preview_finalizer_module("finalize_planning_preview_broken_symlink")
    collection = tmp_path / "collection"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    preview = assets / "planning-preview.png"
    preview.symlink_to(assets / "missing.png")
    thumbnail = assets / "thumbnail.jpg"
    thumbnail.write_bytes(b"existing-thumbnail")

    with pytest.raises(module.ValidationError, match="通常ファイル"):
        module.finalize_planning_preview(collection)

    assert thumbnail.read_bytes() == b"existing-thumbnail"
    assert not list(assets.glob(".thumbnail-preview-*"))


def test_finalize_planning_preview_permission_failure_preserves_existing_thumbnail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_preview_finalizer_module("finalize_planning_preview_permission")
    collection = tmp_path / "collection"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    Image.new("RGB", (8, 8), "navy").save(assets / "planning-preview.png", "PNG")
    thumbnail = assets / "thumbnail.jpg"
    thumbnail.write_bytes(b"existing-thumbnail")

    def deny_temporary_file(*_args, **_kwargs):
        raise PermissionError("injected permission failure")

    monkeypatch.setattr(module.tempfile, "mkstemp", deny_temporary_file)

    with pytest.raises(PermissionError, match="injected permission failure"):
        module.finalize_planning_preview(collection)

    assert thumbnail.read_bytes() == b"existing-thumbnail"


def test_thumbnail_textless_shared_main_default_and_contract() -> None:
    """Issue #2457: opt-in だけが thumbnail.jpg を main.jpg へ共用する。"""
    config = _read_thumbnail_default_config()
    skill = _read_thumbnail_skill()
    standard_block = _slice_between(
        skill,
        "### 標準生成順序とファイル契約",
        "### thumbnail-text-profile 適用（#1907）",
    )

    assert "textless:\n  enabled: true" in config
    for token in (
        "`textless.enabled: false`",
        "textless 候補の AI 生成、セルフチェック、プレビュー、承認をすべて省略",
        "share_thumbnail_as_main.py",
        "`status: SHARED`",
        "同一 SHA-256",
        "`main.png` 不在",
        "textless 生成プロンプトを捏造せず",
    ):
        assert token in standard_block
    assert "未設定または `true` では文字入りと文字なしを分離" in standard_block


def test_shared_main_contract_reaches_loop_video_and_videoup() -> None:
    """Issue #2458: opt-in の共有 main を動画背景 skill が正規入力として扱う。"""
    loop_video = _read_loop_video_skill()
    videoup = (_repo_root() / ".claude" / "skills" / "video" / "references" / "generate.md").read_text(encoding="utf-8")

    for text in (loop_video, videoup):
        assert "`thumbnail::textless.enabled: false`" in text
        assert "文字入り" in text
        assert "正規入力" in text
        assert "textless 再生成" in text
    assert "未設定または `true`" in loop_video
    assert "未設定または `true`" in videoup


def test_share_thumbnail_as_main_copies_atomically_and_removes_png(tmp_path: Path) -> None:
    module = _load_shared_main_module("share_thumbnail_as_main")
    collection = tmp_path / "collection"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    thumbnail = assets / "thumbnail.jpg"
    thumbnail.write_bytes(b"approved-thumbnail")
    (assets / "main.jpg").write_bytes(b"old-main")
    (assets / "main.png").write_bytes(b"conflict")

    result = module.share_thumbnail_as_main(collection, enabled=False)

    assert result["status"] == "SHARED"
    assert (assets / "main.jpg").read_bytes() == thumbnail.read_bytes()
    assert not (assets / "main.png").exists()
    assert not list(assets.glob(".main-shared-*"))


def test_share_thumbnail_as_main_true_is_noop(tmp_path: Path) -> None:
    module = _load_shared_main_module("share_thumbnail_as_main_noop")
    collection = tmp_path / "collection"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    (assets / "thumbnail.jpg").write_bytes(b"thumbnail")
    (assets / "main.png").write_bytes(b"textless")

    result = module.share_thumbnail_as_main(collection, enabled=True)

    assert result["status"] == "SKIP"
    assert (assets / "main.png").read_bytes() == b"textless"
    assert not (assets / "main.jpg").exists()


@pytest.mark.parametrize("failure_point", ["copy", "replace"])
def test_share_thumbnail_as_main_failure_preserves_existing_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    module = _load_shared_main_module(f"share_thumbnail_as_main_{failure_point}")
    collection = tmp_path / "collection"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    (assets / "thumbnail.jpg").write_bytes(b"approved-thumbnail")
    main = assets / "main.jpg"
    main.write_bytes(b"existing-main")
    before = hashlib.sha256(main.read_bytes()).hexdigest()

    def fail(*_args, **_kwargs):
        raise OSError(f"injected {failure_point} failure")

    if failure_point == "copy":
        monkeypatch.setattr(module.shutil, "copyfile", fail)
    else:
        monkeypatch.setattr(module.os, "replace", fail)

    with pytest.raises(OSError, match=f"injected {failure_point} failure"):
        module.share_thumbnail_as_main(collection, enabled=False)

    assert hashlib.sha256(main.read_bytes()).hexdigest() == before
    assert not list(assets.glob(".main-shared-*"))


def test_thumbnail_skill_applies_thumbnail_text_profile_with_default_fallback() -> None:
    """#1907: thumbnail-text-profile の 3 セクションを適用し、不在時はデフォルト値で続行する。"""
    skill = _read_thumbnail_skill()
    profile_block = _slice_between(
        skill,
        "### thumbnail-text-profile 適用（#1907）",
        "### 承認済みサムネイルのアーカイブ",
    )
    profile_details = _slice_between(
        _read_thumbnail_quality_and_operations(),
        "## thumbnail-text-profile 変換",
        "## 承認済みサムネイルのアーカイブ",
    )

    for required in (
        "docs/channel-research.json",
        "read_published_json_document",
        "`schema_version: 1`",
        ".claude/skills/channel-research/references/market.md",
    ):
        assert required in profile_block

    for required in (
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
        assert required in profile_details

    # profile 不在は前提ガードにしない（現行デフォルト値で続行）
    assert "前提ガードではない" in profile_block
    assert "エラーで停止しない" in profile_block
    assert "unknown" in profile_details
    # フォントはローカル既存ファイルのみ（同梱・自動ダウンロードはスコープ外）
    assert "同梱・自動ダウンロードはしない" in profile_details
    # profile 不在かつフォント未設定でもローカル選定でフォント揺れを解消する
    assert "profile 不在でも `overlay.font.title` が未設定なら" in profile_details
    # config への書き込みはユーザー承認つきの明示更新
    assert "承認を得てから" in profile_block


def test_thumbnail_archive_is_opt_in_and_wired_after_every_approval_path() -> None:
    config = _load_thumbnail_default_config()
    skill = _read_thumbnail_skill()
    archive_command = (
        "uv run python .claude/skills/thumbnail/references/archive-approved-thumbnail.py <collection-path>"
    )

    assert config["archive"] == {"enabled": False}
    assert "archive.enabled: false" in skill
    assert "assets/thumbnail-gallery/<collection-dir-name>.<ext>" in skill
    # Web reviewは同じarchive ownerをtransaction内で呼ぶ。文書上の旧互換/auto入口だけを保持する。
    assert skill.count(archive_command) == 2

    approval_block = _slice_between(skill, "### 承認済みサムネイルのアーカイブ", "### Single-Step / TTP モード")
    for approval_path in ("旧互換", "yt-thumbnail-review", "transaction", "自動選択"):
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

    assert codex_block.find("thumbnail.jpg") < codex_block.find(archive_command)
    for wired_block in (standard_block, single_step_block, two_phase_block):
        assert wired_block.find("thumbnail.jpg") < wired_block.find("yt-thumbnail-review --artifact thumbnail")
    assert "uv run yt-thumbnail-auto-select <collection-path> --apply" in auto_selection_block
    assert "--apply &&" not in auto_selection_block
    assert "候補生成後のユーザー承認を省略" in auto_selection_block
    assert auto_selection_block.find("--apply") < auto_selection_block.find("自動確定後も `/thumbnail --compare`")
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
    opening_gate = "\n".join(skill.splitlines()[:65])
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
    font_block = _slice_between(skill, "## フォント安定化", "## 自動選択")
    font_details = _slice_between(_read_thumbnail_quality_and_operations(), "## フォント運用", "## auto-selection")

    assert "typography_clause" in prompt_construction_block
    assert "text_strip_clause" in prompt_construction_block
    assert "テキスト付き `thumbnail-v*.jpg/png` 候補生成用" in font_details
    assert "`single_step.typography_clause` を opt-in で展開" in font_details
    assert "textless 再生成プロンプトには `${typography_clause}`" in font_details
    assert "初回 `diff_prompt_template` は textless" not in font_block + font_details


def test_thumbnail_skill_prompt_log_and_file_contract_cover_issue_1310_outputs() -> None:
    """#1310: prompt 保存とファイル命名が thumbnail/main/loop の役割を明示する。"""
    skill = _read_thumbnail_skill()
    prompt_block = _slice_between(
        _read_thumbnail_quality_and_operations(),
        "## プロンプト保存テンプレート",
        "## stock 退避と再利用",
    )
    naming_block = _slice_between(skill, "## ファイル命名ルール（上書き禁止）", "### クリーンアップ")

    for required in (
        "## Textless Background Prompt (main.png/main.jpg)",
        "## Text-Included Thumbnail Prompt (thumbnail.jpg)",
        "テキストなし背景を生成したプロンプト",
        "テキスト付きサムネを生成したプロンプト",
        "`10-assets/thumbnail-v1.jpg`",
        "`10-assets/thumbnail-v2.jpg`",
        "`10-assets/thumbnail-v3.jpg`",
        "`<参照画像 3>`",
        "| pattern | final output | variation |",
        "`10-assets/thumbnail-a.jpg`",
        "`<pattern a variation>`",
        "`10-assets/thumbnail-b.jpg`",
        "`<pattern b variation>`",
    ):
        assert required in prompt_block

    for required in (
        "`thumbnail.jpg` | YouTube アップロード用のテキスト付き最終サムネ",
        "`thumbnail-v{N}.jpg` / `thumbnail-v{N}.png` / `thumbnail-codex-v{N}.png` | テキスト付き候補",
        "`main.png` / `main.jpg` | 動画背景・`/thumbnail --loop` 入力用のテキストなし最終画像",
        "`main-v{N}.png` / `main-v{N}.jpg` | テキストなし背景候補",
        "`loop.mp4` | `loop-video` 有効チャンネルだけで生成する動画背景",
        "無効チャンネルでは作らない",
    ):
        assert required in naming_block


def test_thumbnail_skill_quality_check_separates_thumbnail_and_textless_main_qa() -> None:
    """#1310: 品質チェックは文字入り thumbnail と textless main を逆に扱わない。"""
    skill = _read_thumbnail_skill()
    qa_block = _slice_between(skill, "## 品質チェック", "## 視認性検証")
    qa_details = _slice_between(
        _read_thumbnail_quality_and_operations(),
        "## QA チェックリスト",
        "## プロンプト保存テンプレート",
    )

    for required in (
        "テキスト付き thumbnail 候補生成後",
        "ベンチマーク参照の構図",
        "/thumbnail --compare",
        "タイトル可読性",
        "`composition_rules.text_lines`",
        "`thumbnail_text.channel_name` が表示され",
        "`image_generation.gemini.style`",
        "`fixed_character` の外見",
        "`fixed_character.face`",
        "textless main 候補生成後",
        "承認済み `thumbnail.jpg` の構図",
        "タイトル文字、字幕、ロゴ、透かし、タイポグラフィ、チャンネル名が残っていない",
    ):
        assert required in qa_details

    assert "uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json" in qa_block
    assert "承認・確定しない" in qa_block
    assert qa_details.find("テキスト付き thumbnail 候補生成後") < qa_details.find("textless main 候補生成後")
    assert "承認済み `main.png/jpg` の構図" not in qa_block + qa_details

    combined = qa_block + qa_details
    assert "Phase 1 生成後" not in combined
    assert "Phase 2 生成後" not in combined
    assert "テキストが入っていないか" not in combined
    assert "single_step プレビューを最終 thumbnail に流用" not in combined


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
    assert "yt-thumbnail-review --artifact main" in two_phase_block
    assert "参照素材を `main.png/jpg` へコピーしない" in reference_phase_block
    assert "cp main-v1.png main.png" not in reference_phase_block
    assert "#### Phase 1: 背景候補生成（draft main）" not in two_phase_block
    assert "既に存在する場合は Phase 1 をスキップ" not in two_phase_block


def test_thumbnail_skill_ai_text_path_is_default_and_deterministic_is_opt_in() -> None:
    """#3312: フォント経路表も AI 既定 / deterministic opt-in とする。"""
    skill = _read_thumbnail_skill()
    font_block = _slice_between(skill, "## フォント安定化", "## 自動選択")
    font_details = _slice_between(
        _read_thumbnail_quality_and_operations(),
        "## フォント運用",
        "## auto-selection",
    )

    assert "**AI プロンプト経路**（`ai_burn_in`・**既定**）" in font_block
    assert "**決定的合成経路**（`deterministic`・opt-in）" in font_block

    assert "標準生成順序とファイル契約" in font_block
    assert "文字入りサムネを先に確定" in font_block
    assert "textless 背景の承認後に合成" in font_block
    assert "image_generation.gemini.thumbnail_text.overlay.font.title" in font_details
    assert "文字入り画像を `--background` に流用しない" in font_block
    assert "AI 経路へ無断で切り替えない" in font_block


def test_thumbnail_loop_mode_uses_textless_main_image_and_respects_disabled_channels() -> None:
    """#1310/#3832: --loop は文字入り thumbnail ではなく文字なし main を入力にする。"""
    skill = _read_loop_video_skill()
    prerequisites_block = _slice_between(skill, "### 前提条件", "### ステップ")
    steps_block = _slice_between(skill, "### ステップ", "### 構造化プロンプト（推奨）")

    for required in (
        "テキストなし `main.png/jpg`",
        "`thumbnail.jpg` は YouTube アップロード用のテキスト付きサムネイル",
        "`/thumbnail --loop` の入力には使わない",
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


def test_thumbnail_default_config_uses_ai_burn_in_text_render_mode() -> None:
    config = _load_thumbnail_default_config()

    assert config["text_render"] == {"mode": "ai_burn_in"}


@pytest.mark.parametrize("mode", ["ai_burn_in", "deterministic"])
def test_thumbnail_text_render_mode_accepts_supported_values(tmp_path, mode) -> None:
    from youtube_automation.configuration import skills as skill_config

    override_dir = tmp_path / "config" / "skills"
    override_dir.mkdir(parents=True)
    (override_dir / "thumbnail.yaml").write_text(f"text_render:\n  mode: {mode}\n", encoding="utf-8")

    merged = skill_config.load_skill_config("thumbnail", use_cache=False, channel_dir=tmp_path)

    assert merged["text_render"]["mode"] == mode


@pytest.mark.parametrize(
    "text_render_yaml",
    [
        "text_render: unsupported\n",
        "text_render:\n  mode: unsupported\n",
        "text_render:\n  mode: null\n",
    ],
)
def test_thumbnail_text_render_mode_rejects_invalid_values(tmp_path, text_render_yaml) -> None:
    from youtube_automation.configuration import skills as skill_config
    from youtube_automation.core.errors import ConfigError

    override_dir = tmp_path / "config" / "skills"
    override_dir.mkdir(parents=True)
    (override_dir / "thumbnail.yaml").write_text(text_render_yaml, encoding="utf-8")

    with pytest.raises(ConfigError, match=r"text_render\.mode.*ai_burn_in.*deterministic"):
        skill_config.load_skill_config("thumbnail", use_cache=False, channel_dir=tmp_path)


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
        "全 pattern の承認が揃うまでは `assets.thumbnail` を `true` にしない",
        "Test & compare",
        "公式 API はない",
    ):
        assert required in block

    prompt_block = _slice_between(
        _read_thumbnail_quality_and_operations(),
        "## プロンプト保存テンプレート",
        "## stock 退避と再利用",
    )
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


def test_thumbnail_prompt_schema_is_self_contained_experimental_contract() -> None:
    prompt_schema = _read_thumbnail_prompt_schema()

    for required in (
        "試験導入",
        "実本番のプロンプト構築フロー",
        "**未接続**",
        "issue #654",
        "再評価",
        "14 項目スキーマと skill-config キーの対応マッピング",
        "`PromptSchema` dataclass（frozen）",
        "`from_skill_config(skill_config: dict) -> PromptSchema`",
        "`render(schema: PromptSchema) -> str`",
        "段階移行パスと並存設計",
        "opt-in フェーズ",
        "default 切替",
        "legacy 撤去",
    ):
        assert required in prompt_schema

    assert "docs/skill-design/ADR-001-thumbnail-prompt-schema.md" not in prompt_schema
    assert "docs/skill-design/thumbnail-codex-imagegen-diff-report.md" not in prompt_schema


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
    ideate_skill = (_repo_root() / ".claude" / "skills" / "wf-new" / "references" / "ideate.md").read_text(
        encoding="utf-8"
    )

    assert "reference_images.dedup_recent_collections" in skill
    assert config["image_generation"]["gemini"]["reference_images"]["dedup_recent_collections"] == 5
    assert ".claude/skills/wf-new/references/select-ttp-references.py" in ideate_skill
    assert ".claude/skills/wf-new/references/record-ttp-reference-assignments.py" in ideate_skill


def test_collection_ideate_persists_only_the_adopted_reference_after_selection() -> None:
    ideate_skill = (_repo_root() / ".claude" / "skills" / "wf-new" / "references" / "ideate.md").read_text(
        encoding="utf-8"
    )
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


def test_collection_ideate_hands_adopted_preview_to_final_thumbnail_contract() -> None:
    ideate_dir = _repo_root() / ".claude" / "skills" / "wf-new" / "references"
    skill = (ideate_dir / "ideate.md").read_text(encoding="utf-8")
    config = (ideate_dir / "collection-ideate.config.default.yaml").read_text(encoding="utf-8")

    next_step = _slice_between(skill, "## Next Step", "### コスト拒否 / 生成失敗で企画参照画像が無い場合")

    assert "最終 `thumbnail.jpg` の正規入力" in next_step
    assert "最終 `thumbnail.jpg` の正規入力" in config
    assert "企画参照素材" not in next_step
    assert "企画参照素材" not in config
    assert "別の文字入り候補" not in next_step
    assert "`main.png` にはコピーしない" in next_step


def test_collection_ideate_routes_missing_preview_to_thumbnail_fallback() -> None:
    skill = (_repo_root() / ".claude" / "skills" / "wf-new" / "references" / "ideate.md").read_text(encoding="utf-8")

    no_image = _slice_between(
        skill,
        "### コスト拒否 / 生成失敗で企画参照画像が無い場合",
        "企画選択後:",
    )

    assert "`/thumbnail <theme>` フォールバック" in no_image
    assert "planning-preview.png コピーはスキップ" in no_image


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
    from youtube_automation.configuration import skills as skill_config

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
    prompting = (_repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "prompting.md").read_text(
        encoding="utf-8"
    )

    generation_workflows = _read_thumbnail_generation_workflows()

    assert "TTP 生成方針は provider によらず共通" in generation_workflows
    assert "TTP 方針は provider 共通" in prompting
    assert "チャンネル側 override" in prompting


def test_thumbnail_default_config_codex_template_matches_skill_md_block() -> None:
    """#1680: SKILL.md「既定テンプレート」ブロックと config.default.yaml を完全一致で機械担保する。"""
    config_template = _codex_prompt_template(_load_thumbnail_default_config())
    skill_template = _skill_md_codex_default_template()

    assert config_template == skill_template


def test_setup_thumbnail_template_includes_codex_ttp_upgrade_prompt() -> None:
    """#1300 / #1680: setup 再生成モードの thumbnail config も同じ Codex 既定文言を持つ。"""
    default_template = _codex_prompt_template(_load_thumbnail_default_config())
    setup_template = _codex_prompt_template(_load_setup_thumbnail_template())

    assert setup_template == default_template
    assert setup_template.count("{title}") == 1
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
        assert required in setup_template


def test_setup_thumbnail_template_includes_channel_branding_contract() -> None:
    template = _load_setup_thumbnail_template()
    reference_images = template["image_generation"]["gemini"]["reference_images"]

    assert reference_images["channel_branding"] == {
        "snapshot": "docs/channel/competitor-branding-snapshot.json",
        "icon_references": ["{{CHANNEL_BRANDING_ICON_REFERENCE}}"],
        "banner_references": ["{{CHANNEL_BRANDING_BANNER_REFERENCE}}"],
        "output_icon": "branding/icon.png",
        "output_banner": "branding/banner.png",
    }


def test_codex_prompt_helper_cli_renders_default_template(tmp_path: Path) -> None:
    """#1300 / #2586: default template と IP safety clause を title 付きで出力する。"""
    result = _run_codex_prompt_cli(
        tmp_path,
        "image_generation:\n  provider: codex\n",
        "Rain Study",
    )

    default_clause = _load_thumbnail_default_config()["image_generation"]["gemini"]["single_step"][
        "ip_safety_clause"
    ].strip()
    assert result.returncode == 0, result.stderr
    assert "TTP this reference thumbnail, then improve it into a stronger original thumbnail." in result.stdout
    assert "Use the title Rain Study." in result.stdout
    assert result.stdout.count(default_clause) == 1
    assert "Remove all text" not in result.stdout
    assert "{title}" not in result.stdout


def test_codex_prompt_helper_cli_appends_style_lock_clause(tmp_path: Path) -> None:
    """#2557: channel override の opt-in clause を Codex CLI 出力へ伝搬する。"""
    result = _run_codex_prompt_cli(
        tmp_path,
        """image_generation:
  provider: codex
  gemini:
    single_step:
      style_lock_clause: Keep the strong caricature treatment.
""",
        "Night Groove",
    )

    assert result.returncode == 0, result.stderr
    assert "Use the title Night Groove." in result.stdout
    assert "Additional thumbnail guidance:" in result.stdout
    assert "Keep the strong caricature treatment." in result.stdout


def test_codex_prompt_helper_cli_uses_channel_ip_safety_override_without_text_strip(tmp_path: Path) -> None:
    """#2586: channel の IP clause だけを初回の文字入り prompt へ一度展開する。"""
    result = _run_codex_prompt_cli(
        tmp_path,
        """image_generation:
  provider: codex
  gemini:
    single_step:
      ip_safety_clause: Channel-specific IP safety clause.
      text_strip_clause: Remove all text from the image.
""",
        "Rain Study",
    )

    default_clause = _load_thumbnail_default_config()["image_generation"]["gemini"]["single_step"][
        "ip_safety_clause"
    ].strip()
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("Use the title Rain Study.") == 1
    assert result.stdout.count("Channel-specific IP safety clause.") == 1
    assert default_clause not in result.stdout
    assert "Remove all text from the image." not in result.stdout


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
    prompt_section = _read_thumbnail_generation_workflows()

    assert "最小限のキーワード" in prompt_section
    assert "参照画像主導" in prompt_section
    assert "モード別差分" in prompt_section
    # 実際にプロバイダーへ渡る最終プロンプト例（既定 config の全文）
    assert "```text" in prompt_section
    assert "Use the title" in prompt_section
    assert "Do not reproduce any signature" in prompt_section
    # 既定 clause は ip_safety のみ。多重 clause の同時展開指示は解消済み
    assert "${ip_safety_clause}` の 1 つだけ" in prompt_section
    single_step_prompt_block = _slice_between(prompt_section, "## Single-Step / TTP 詳細", "## Two-Phase 詳細")
    assert "共通ガイダンス clause（`single_step.variation_clause` / `style_lock_clause`" not in single_step_prompt_block
    assert "opt-in clause" in single_step_prompt_block


def test_thumbnail_skill_routes_generation_details_without_moving_runtime_contract() -> None:
    skill = _read_thumbnail_skill()
    route = "[generation workflow 詳細](references/generation-workflows.md)"

    assert skill.index("## 生成モード判定") < skill.index(route) < skill.index("## ワークフロー")
    for mode in ("`single_step`", "`diff_from_reference`", "`two_phase`"):
        assert mode in _slice_between(skill, "## 生成モード判定", "## ワークフロー")
    # #2950 adds one canonical non-interactive background-session invocation.
    assert skill.count("uv run yt-generate-image") == 12
    assert skill.count("uv run yt-thumbnail-text") == 1
    assert skill.count("archive-approved-thumbnail.py") == 2
    assert '### Single-Step / TTP モード（`generation_mode: "single_step"`、デフォルト・推奨）' in skill
    assert "### Two-Phase モード（従来方式・フォールバック）" in skill
    assert "/thumbnail --compare" in skill
    assert "ユーザー承認" in skill
    assert "## 完了条件" in skill


def test_thumbnail_generation_workflows_owns_generation_details_once() -> None:
    skill = _read_thumbnail_skill()
    details = _read_thumbnail_generation_workflows()
    combined = skill + details
    moved_details = (
        '`path_base: "channel_dir"',
        "複数の clause を同時に積み上げない",
        "**最終プロンプト例（TTP / 既定 config でプロバイダーへ渡る全文）:**",
        "TTP 生成方針は provider によらず共通",
        "Two-Phase モードのテキストオーバーレイ・フォールバックプロンプト",
    )
    for detail in moved_details:
        assert detail not in skill
        assert details.count(detail) == 1
        assert combined.count(detail) == 1


def test_thumbnail_skill_routes_quality_details_without_moving_hard_gates() -> None:
    skill = _read_thumbnail_skill()
    route = "[quality / operations 詳細](references/quality-and-operations.md)"

    assert skill.index("## ワークフロー") < skill.index(route) < skill.index("## フォント安定化")
    assert skill.count("uv run yt-thumbnail-check") == 4
    assert skill.count("uv run yt-thumbnail-auto-select") == 3
    assert skill.count("archive-approved-thumbnail.py") == 2
    assert skill.count("uv run yt-stock-archive") == 1
    assert "## 完了条件" in skill
    assert "**Hard Gate**" in "\n".join(skill.splitlines()[:60])
    assert "/thumbnail --compare" in skill
    assert "ユーザー承認" in skill
    assert "assets.thumbnail = true" in skill
    assert "thumbnail.approved = true" not in skill


def test_thumbnail_quality_and_operations_owns_details_once() -> None:
    skill = _read_thumbnail_skill()
    details = _read_thumbnail_quality_and_operations()
    combined = skill + details
    moved_details = (
        "| `## font_tendency` |",
        "シンボリックリンクやコピー失敗は成功として扱わない",
        "brightness / contrast / saturation / dominant_hue / colorfulness",
        "**解剖学チェック（手・指）**",
        "# Thumbnail Prompts - <コレクション名>",
        "schema_version=1",
        "| Vertex AI rate | HTTP 429 |",
    )
    for detail in moved_details:
        assert detail not in skill
        assert details.count(detail) == 1
        assert combined.count(detail) == 1


def test_thumbnail_skill_quality_check_covers_hand_anatomy() -> None:
    """#570: 品質チェックに手・指の解剖学項目が含まれている。"""
    quality_block = _slice_between(
        _read_thumbnail_quality_and_operations(),
        "## QA チェックリスト",
        "## プロンプト保存テンプレート",
    )

    # issue #570 の修正要件 1: 手・指の解剖学チェック項目
    assert "解剖学" in quality_block
    assert "5 本指" in quality_block or "五本指" in quality_block
    assert "指の分離" in quality_block
