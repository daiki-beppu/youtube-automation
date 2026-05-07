"""Issue #137: `.claude/skills/intro/references/generate_droplet_png.py` (C 節)。

雫 PNG ビルダーの純粋関数 `render_droplet` の振る舞いを Pillow 実呼びで検証。
config から渡された `color.droplet` が PNG ピクセルに反映される伝搬チェーンと、
親ディレクトリ自動作成、不正入力の検証も併せて担保する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from tests._skill_loader import load_skill_script
from youtube_automation.utils import skill_config
from youtube_automation.utils.config import reset as reset_config
from youtube_automation.utils.exceptions import ValidationError


@pytest.fixture(autouse=True)
def _reset_caches():
    skill_config.reset()
    reset_config()
    yield
    skill_config.reset()
    reset_config()


@pytest.fixture
def droplet_module():
    return load_skill_script("intro", "generate_droplet_png")


# ---------- C-1: 96x96 RGBA PNG が指定 color で出力される ----------


def test_render_droplet_writes_96x96_rgba_png_with_given_color(
    droplet_module, tmp_path: Path
) -> None:
    """Given 出力先 path と RGBA color tuple (#3A4A55)
    When render_droplet(out_path, color=(58, 74, 85, 255)) を呼ぶ
    Then 96x96 の RGBA PNG が出力され、塗り pixel が指定 color に一致する。
    """
    out_path = tmp_path / "droplet.png"
    color = (58, 74, 85, 255)  # #3A4A55

    droplet_module.render_droplet(out_path, color=color)

    assert out_path.exists()
    img = Image.open(out_path)
    assert img.mode == "RGBA"
    assert img.size == (96, 96)

    # 中央付近 (teardrop の bottom round 部分) が指定色である
    # 96x96 中央 (48, 60) — teardrop の下部 (丸い部分) を確実に外さない座標
    pixels = img.load()
    cx, cy = 48, 60
    sample = pixels[cx, cy]
    assert sample[:3] == color[:3], (
        f"中央付近 ({cx},{cy}) の RGB が指定色と異なる: {sample[:3]} != {color[:3]}"
    )
    assert sample[3] > 0, f"中央付近 ({cx},{cy}) のアルファが 0 (透明): {sample}"


# ---------- C-2: config 由来の色が main() 経由で反映される ----------


def test_main_derives_color_from_skill_config(
    droplet_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given channel config で `color.droplet` を上書き
    When main() を実行
    Then 出力 PNG に override した色が反映される。
    """
    # channel override の color.droplet に派手な赤を仕込み、main() がそれを採用するか確認
    import yaml

    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "intro.yaml"
    override.write_text(
        yaml.safe_dump({"color": {"droplet": "#FF0000"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    out_dir = tmp_path / "out"
    out_path = out_dir / "05_droplet.png"
    monkeypatch.setattr(droplet_module, "_resolve_output_path", lambda: out_path, raising=False)
    # `main()` が `--output` フラグでパス指定できる前提で argv を設定
    monkeypatch.setattr("sys.argv", ["generate_droplet_png", "--output", str(out_path)])

    rc = droplet_module.main()

    assert rc == 0
    assert out_path.exists()
    img = Image.open(out_path)
    pixels = img.load()
    sample = pixels[48, 60]
    assert sample[:3] == (255, 0, 0), (
        f"channel override した色が反映されていない: {sample[:3]} (expected (255,0,0))"
    )


# ---------- C-3: 親ディレクトリの自動作成 ----------


def test_render_droplet_creates_parent_dirs_when_missing(
    droplet_module, tmp_path: Path
) -> None:
    """Given 親ディレクトリが存在しない出力 path
    When render_droplet を呼ぶ
    Then mkdir(parents=True) で親が作られ、PNG が出力される。
    """
    nested = tmp_path / "deeply" / "nested" / "branding" / "intro_assets"
    out_path = nested / "05_droplet.png"
    assert not nested.exists()

    droplet_module.render_droplet(out_path, color=(58, 74, 85, 255))

    assert out_path.exists()


# ---------- C-4: 不正な color tuple は ValidationError ----------


def test_render_droplet_rejects_invalid_color_tuple_length(
    droplet_module, tmp_path: Path
) -> None:
    """Given color tuple が長さ 3 (RGBA でなく RGB)
    When render_droplet を呼ぶ
    Then ValidationError が出る (RGBA 必須の入力検証)。
    """
    out_path = tmp_path / "droplet.png"
    with pytest.raises(ValidationError):
        droplet_module.render_droplet(out_path, color=(58, 74, 85))  # type: ignore[arg-type]
