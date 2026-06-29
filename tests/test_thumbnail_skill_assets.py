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


def _read_thumbnail_default_config() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "config.default.yaml"
    return path.read_text(encoding="utf-8")


def _read_channel_setup_thumbnail_template() -> str:
    path = (
        _repo_root()
        / ".claude"
        / "skills"
        / "channel-setup"
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


def _load_channel_setup_thumbnail_template() -> dict:
    return yaml.safe_load(_read_channel_setup_thumbnail_template()) or {}


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
    assert "/thumbnail-compare" in checklist_block
    assert "承認**前**" in checklist_block


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


def test_thumbnail_default_config_remains_ttp_aligned() -> None:
    config = _read_thumbnail_default_config()

    assert "generation_mode: single_step" in config
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
    assert "enabled: true" in config
    assert 'source_role: "thumbnail_candidate"' in config
    assert "fallback_when_empty: true" in config
    assert 'diff_prompt_template: ""' in config


def test_thumbnail_default_config_provides_codex_ttp_upgrade_prompt() -> None:
    """#1300: Codex 経路の既定プロンプトは短い TTP 上位互換型にする。"""
    template = _codex_prompt_template(_load_thumbnail_default_config())

    assert template.count("{title}") == 1
    for required in (
        "TTP this reference thumbnail",
        "winning layout",
        "more readable on mobile",
        "stronger face impact",
        "no logos",
        "no watermarks",
        "no broken hands",
        "Use the title {title}.",
    ):
        assert required in template


def test_channel_setup_thumbnail_template_includes_codex_ttp_upgrade_prompt() -> None:
    """#1300: channel-setup で生成される thumbnail config も同じ Codex 既定文言を持つ。"""
    default_template = _codex_prompt_template(_load_thumbnail_default_config())
    channel_setup_template = _codex_prompt_template(_load_channel_setup_thumbnail_template())

    assert channel_setup_template == default_template
    assert channel_setup_template.count("{title}") == 1
    for required in (
        "TTP this reference thumbnail",
        "winning layout",
        "more readable on mobile",
        "stronger face impact",
        "no logos",
        "no watermarks",
        "no broken hands",
        "Use the title {title}.",
    ):
        assert required in channel_setup_template


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
    assert "TTP this reference thumbnail" in result.stdout
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
