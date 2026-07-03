"""thumbnail_text (決定的フォント合成, #1332) のユニットテスト"""

from __future__ import annotations

from pathlib import Path

import pytest
from matplotlib import font_manager
from PIL import Image

from youtube_automation.utils import config as config_mod
from youtube_automation.utils import skill_config
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.thumbnail_text import (
    OverlaySpec,
    TextStyle,
    compose_thumbnail_text,
    overlay_spec_from_overlay_config,
    resolve_font_path,
)


@pytest.fixture(autouse=True)
def reset_skill_config_cache():
    config_mod.reset()
    skill_config.reset()
    yield
    config_mod.reset()
    skill_config.reset()


@pytest.fixture(scope="module")
def test_font() -> Path:
    """テスト用の実フォント (matplotlib 同梱の DejaVuSans)"""
    return Path(font_manager.findfont("DejaVu Sans"))


@pytest.fixture
def background(tmp_path: Path) -> Path:
    path = tmp_path / "main.png"
    Image.new("RGB", (1280, 720), color="#123456").save(path)
    return path


def _overlay_config_dict(font_path: Path, **overlay_extra) -> dict:
    overlay = {"font": {"title": str(font_path)}}
    overlay.update(overlay_extra)
    return overlay


def _skill_config_dict(font_path: Path, **overlay_extra) -> dict:
    overlay = _overlay_config_dict(font_path, **overlay_extra)
    return {"image_generation": {"gemini": {"thumbnail_text": {"overlay": overlay}}}}


class TestResolveFontPath:
    def test_missing_raises_with_guidance(self, tmp_path: Path):
        """未設定なら理由と代替手順つきの ConfigError (#1332 受け入れ条件)"""
        with pytest.raises(ConfigError) as exc_info:
            resolve_font_path(
                "",
                channel_root=tmp_path,
                key="image_generation.gemini.thumbnail_text.overlay.font.title",
            )
        message = str(exc_info.value)
        assert "フォント指定が未設定です" in message
        assert "対処:" in message
        assert "config/skills/thumbnail.yaml" in message
        assert "image_generation.gemini.thumbnail_text.overlay.font.title" in message

    def test_nonexistent_raises_with_guidance(self, tmp_path: Path):
        with pytest.raises(ConfigError) as exc_info:
            resolve_font_path("assets/fonts/nope.ttf", channel_root=tmp_path, key="overlay.font.title")
        message = str(exc_info.value)
        assert "フォントファイルが見つかりません" in message
        assert "対処:" in message

    def test_relative_path_resolved_from_channel_root(self, tmp_path: Path, test_font: Path):
        fonts_dir = tmp_path / "assets" / "fonts"
        fonts_dir.mkdir(parents=True)
        target = fonts_dir / "font.ttf"
        target.write_bytes(test_font.read_bytes())

        resolved = resolve_font_path("assets/fonts/font.ttf", channel_root=tmp_path, key="overlay.font.title")
        assert resolved == target

    def test_absolute_path_used_as_is(self, tmp_path: Path, test_font: Path):
        resolved = resolve_font_path(str(test_font), channel_root=tmp_path, key="overlay.font.title")
        assert resolved == test_font


class TestOverlaySpecFromOverlayConfig:
    def test_defaults_applied(self, tmp_path: Path, test_font: Path):
        spec = overlay_spec_from_overlay_config(
            _overlay_config_dict(test_font),
            channel_root=tmp_path,
            with_channel_name=False,
        )
        assert spec.title_style.font_path == test_font
        assert spec.title_style.size == 96
        assert spec.title_style.stroke_width == 4
        assert spec.channel_name_style is None
        assert spec.anchor == "bottom-center"

    def test_channel_name_font_inherits_title(self, tmp_path: Path, test_font: Path):
        spec = overlay_spec_from_overlay_config(
            _overlay_config_dict(test_font),
            channel_root=tmp_path,
            with_channel_name=True,
        )
        assert spec.channel_name_style is not None
        assert spec.channel_name_style.font_path == test_font
        assert spec.channel_name_style.size == 36

    @pytest.mark.parametrize(
        ("font_cfg_factory", "with_channel_name", "message"),
        [
            (lambda _test_font: {"title": True}, False, "font.title"),
            (lambda test_font: {"title": str(test_font), "channel_name": ["bad"]}, True, "font.channel_name"),
        ],
    )
    def test_font_paths_must_be_strings(
        self,
        tmp_path: Path,
        test_font: Path,
        font_cfg_factory,
        with_channel_name: bool,
        message: str,
    ):
        cfg = {"font": font_cfg_factory(test_font)}
        with pytest.raises(ConfigError, match=message):
            overlay_spec_from_overlay_config(cfg, channel_root=tmp_path, with_channel_name=with_channel_name)

    def test_invalid_anchor_raises(self, tmp_path: Path, test_font: Path):
        cfg = _overlay_config_dict(test_font, layout={"anchor": "middle"})
        with pytest.raises(ConfigError, match="anchor"):
            overlay_spec_from_overlay_config(cfg, channel_root=tmp_path, with_channel_name=False)

    def test_invalid_color_raises(self, tmp_path: Path, test_font: Path):
        cfg = _overlay_config_dict(test_font, title={"color": "not-a-color"})
        with pytest.raises(ConfigError, match="色指定が不正"):
            overlay_spec_from_overlay_config(cfg, channel_root=tmp_path, with_channel_name=False)

    @pytest.mark.parametrize(
        ("cfg", "message"),
        [
            ([], "thumbnail_text.overlay"),
            (None, "thumbnail_text.overlay"),
        ],
    )
    def test_non_mapping_overlay_root_raises_config_error(self, tmp_path: Path, cfg, message: str):
        with pytest.raises(ConfigError, match=message):
            overlay_spec_from_overlay_config(cfg, channel_root=tmp_path, with_channel_name=False)

    @pytest.mark.parametrize("section", ["font", "title", "layout"])
    @pytest.mark.parametrize("bad_value", [None, [], "bad"])
    def test_non_mapping_overlay_sections_raise_config_error(
        self,
        tmp_path: Path,
        test_font: Path,
        section: str,
        bad_value,
    ):
        cfg = _overlay_config_dict(test_font, **{section: bad_value})
        with pytest.raises(ConfigError, match=rf"thumbnail_text\.overlay\.{section}"):
            overlay_spec_from_overlay_config(cfg, channel_root=tmp_path, with_channel_name=False)

    @pytest.mark.parametrize("bad_value", [None, [], "bad"])
    def test_non_mapping_channel_name_section_always_raises(self, tmp_path: Path, test_font: Path, bad_value):
        cfg = _overlay_config_dict(test_font, channel_name=bad_value)
        with pytest.raises(ConfigError, match=r"thumbnail_text\.overlay\.channel_name"):
            overlay_spec_from_overlay_config(cfg, channel_root=tmp_path, with_channel_name=False)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("size", True, "整数を指定してください"),
            ("size", 0, "1 以上"),
            ("size", 1.5, "整数を指定してください"),
            ("size", float("inf"), "有限の整数"),
            ("size", float("nan"), "有限の整数"),
            ("stroke_width", -1, "0 以上"),
            ("line_spacing", False, "数値を指定してください"),
            ("line_spacing", 0, "正の数"),
            ("line_spacing", "nan", "有限の数値"),
        ],
    )
    def test_invalid_numeric_values_raise_config_error(
        self,
        tmp_path: Path,
        test_font: Path,
        field: str,
        value,
        message: str,
    ):
        if field == "line_spacing":
            cfg = _overlay_config_dict(test_font, layout={field: value})
        else:
            cfg = _overlay_config_dict(test_font, title={field: value})
        with pytest.raises(ConfigError, match=message):
            overlay_spec_from_overlay_config(cfg, channel_root=tmp_path, with_channel_name=False)


class TestThumbnailTextConfigAdapter:
    @pytest.mark.parametrize(
        ("cfg", "key"),
        [
            ([], "thumbnail skill-config"),
            ({"image_generation": []}, "image_generation"),
            ({"image_generation": {"gemini": []}}, "image_generation.gemini"),
            (
                {"image_generation": {"gemini": {"thumbnail_text": []}}},
                "image_generation.gemini.thumbnail_text",
            ),
            (
                {"image_generation": {"gemini": {"thumbnail_text": {"overlay": []}}}},
                "image_generation.gemini.thumbnail_text.overlay",
            ),
            (
                {"image_generation": {"gemini": {"thumbnail_text": {"overlay": None}}}},
                "image_generation.gemini.thumbnail_text.overlay",
            ),
        ],
    )
    def test_non_mapping_skill_config_sections_raise_config_error(self, cfg, key: str):
        from youtube_automation.scripts.thumbnail_text import _overlay_config_from_skill_config

        with pytest.raises(ConfigError, match=key):
            _overlay_config_from_skill_config(cfg)


class TestComposeThumbnailText:
    def _spec(self, test_font: Path, *, with_channel: bool = False) -> OverlaySpec:
        style = TextStyle(
            font_path=test_font,
            size=96,
            color="#FFFFFF",
            stroke_width=4,
            stroke_color="#000000",
        )
        channel_style = (
            TextStyle(
                font_path=test_font,
                size=36,
                color="#FFFFFF",
                stroke_width=0,
                stroke_color="#000000",
            )
            if with_channel
            else None
        )
        return OverlaySpec(
            title_style=style,
            channel_name_style=channel_style,
            anchor="bottom-center",
            margin_x=64,
            margin_y=48,
            line_spacing=1.15,
            gap=24,
        )

    def test_output_created_and_differs_from_background(self, tmp_path: Path, background: Path, test_font: Path):
        output = tmp_path / "thumbnail-v1.jpg"
        result = compose_thumbnail_text(
            background=background,
            output=output,
            spec=self._spec(test_font),
            title_lines=["Relaxing Jazz", "Night Lounge"],
        )
        assert result == output
        assert output.is_file()
        composed = Image.open(output).convert("RGB")
        original = Image.open(background).convert("RGB")
        assert composed.size == original.size
        assert composed.tobytes() != original.tobytes()

    def test_deterministic_output(self, tmp_path: Path, background: Path, test_font: Path):
        """同一の背景・テキスト・設定なら同一バイト列 (#1332 受け入れ条件)"""
        out1 = tmp_path / "a.jpg"
        out2 = tmp_path / "b.jpg"
        spec = self._spec(test_font, with_channel=True)
        for out in (out1, out2):
            compose_thumbnail_text(
                background=background,
                output=out,
                spec=spec,
                title_lines=["Same Title"],
                channel_name="My Channel",
            )
        assert out1.read_bytes() == out2.read_bytes()

    def test_channel_name_changes_rendered_output(self, tmp_path: Path, background: Path, test_font: Path):
        spec = self._spec(test_font, with_channel=True)
        out_without_channel = tmp_path / "without-channel.jpg"
        out_with_channel = tmp_path / "with-channel.jpg"

        compose_thumbnail_text(
            background=background,
            output=out_without_channel,
            spec=spec,
            title_lines=["Same Title"],
        )
        compose_thumbnail_text(
            background=background,
            output=out_with_channel,
            spec=spec,
            title_lines=["Same Title"],
            channel_name="My Channel",
        )

        assert out_without_channel.read_bytes() != out_with_channel.read_bytes()

    def test_empty_title_raises(self, tmp_path: Path, background: Path, test_font: Path):
        with pytest.raises(ConfigError, match="タイトル行が空"):
            compose_thumbnail_text(
                background=background,
                output=tmp_path / "out.jpg",
                spec=self._spec(test_font),
                title_lines=["  ", ""],
            )

    def test_missing_background_raises(self, tmp_path: Path, test_font: Path):
        with pytest.raises(ConfigError, match="背景画像が見つかりません"):
            compose_thumbnail_text(
                background=tmp_path / "missing.png",
                output=tmp_path / "out.jpg",
                spec=self._spec(test_font),
                title_lines=["Title"],
            )

    def test_broken_background_raises_config_error(self, tmp_path: Path, test_font: Path):
        broken = tmp_path / "broken.png"
        broken.write_bytes(b"not a real image")
        with pytest.raises(ConfigError, match="背景画像を読み込めません"):
            compose_thumbnail_text(
                background=broken,
                output=tmp_path / "out.jpg",
                spec=self._spec(test_font),
                title_lines=["Title"],
            )

    def test_broken_font_raises_with_guidance(self, tmp_path: Path, background: Path):
        broken = tmp_path / "broken.ttf"
        broken.write_bytes(b"not a real font")
        style = TextStyle(font_path=broken, size=96, color="#FFFFFF", stroke_width=0, stroke_color="#000000")
        spec = OverlaySpec(
            title_style=style,
            channel_name_style=None,
            anchor="center",
            margin_x=64,
            margin_y=48,
            line_spacing=1.15,
            gap=24,
        )
        with pytest.raises(ConfigError) as exc_info:
            compose_thumbnail_text(
                background=background,
                output=tmp_path / "out.jpg",
                spec=spec,
                title_lines=["Title"],
            )
        message = str(exc_info.value)
        assert "フォントファイルを読み込めません" in message
        assert "対処:" in message


class TestCli:
    def _patch_config(self, monkeypatch: pytest.MonkeyPatch, *, channel_root: Path, cfg: dict) -> None:
        from youtube_automation.scripts import thumbnail_text as cli

        monkeypatch.setattr(cli, "channel_dir", lambda: channel_root)
        monkeypatch.setattr(cli, "load_skill_config", lambda _skill: cfg)

    def _patch_input_only(self, monkeypatch: pytest.MonkeyPatch, *, channel_root: Path) -> None:
        from youtube_automation.scripts import thumbnail_text as cli

        monkeypatch.setattr(cli, "channel_dir", lambda: channel_root)
        monkeypatch.setattr(
            cli,
            "load_skill_config",
            lambda _skill: pytest.fail("input validation should stop before skill-config loading"),
        )

    def test_success_creates_output_and_prints_ok(
        self,
        tmp_path: Path,
        background: Path,
        test_font: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        from youtube_automation.scripts.thumbnail_text import main

        self._patch_config(monkeypatch, channel_root=tmp_path, cfg=_skill_config_dict(test_font))
        output = tmp_path / "thumbnail-v1.jpg"

        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Test Title",
                "--channel-name",
                "Test Channel",
                "--output",
                str(output),
            ]
        )

        assert code == 0
        assert output.is_file()
        stdout = capsys.readouterr().out
        assert "[OK]" in stdout
        assert str(output) in stdout

    def test_success_uses_real_channel_skill_config(
        self,
        tmp_path: Path,
        background: Path,
        test_font: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        from youtube_automation.scripts.thumbnail_text import main

        fonts_dir = tmp_path / "assets" / "fonts"
        fonts_dir.mkdir(parents=True)
        font = fonts_dir / "font.ttf"
        font.write_bytes(test_font.read_bytes())
        skill_dir = tmp_path / "config" / "skills"
        skill_dir.mkdir(parents=True)
        (skill_dir / "thumbnail.yaml").write_text(
            "\n".join(
                [
                    "image_generation:",
                    "  gemini:",
                    "    thumbnail_text:",
                    "      overlay:",
                    "        font:",
                    "          title: assets/fonts/font.ttf",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
        config_mod.reset()
        skill_config.reset()
        output = tmp_path / "thumbnail-v1.jpg"

        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Real Config",
                "--output",
                str(output),
            ]
        )

        assert code == 0
        assert output.is_file()
        assert "[OK]" in capsys.readouterr().out

    @pytest.mark.parametrize("name", ["thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png"])
    def test_final_thumbnail_output_name_exits_2(self, tmp_path: Path, background: Path, name: str, capsys):
        from youtube_automation.scripts.thumbnail_text import main

        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Test",
                "--output",
                str(tmp_path / name),
            ]
        )

        assert code == 2
        assert "最終サムネイル名への直接出力はできません" in capsys.readouterr().err

    def test_existing_output_file_exits_2_without_overwrite(self, tmp_path: Path, background: Path, capsys):
        from youtube_automation.scripts.thumbnail_text import main

        output = tmp_path / "thumbnail-v1.jpg"
        output.write_bytes(b"keep me")

        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Test",
                "--output",
                str(output),
            ]
        )

        assert code == 2
        assert output.read_bytes() == b"keep me"
        assert "出力先ファイルは既に存在します" in capsys.readouterr().err

    @pytest.mark.parametrize("output_name", ["thumbnail-v1", "thumbnail-v1.bad"])
    def test_invalid_output_extension_exits_2_before_config(
        self,
        tmp_path: Path,
        background: Path,
        output_name: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        from youtube_automation.scripts.thumbnail_text import main

        self._patch_input_only(monkeypatch, channel_root=tmp_path)

        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Test",
                "--output",
                str(tmp_path / output_name),
            ]
        )

        assert code == 2
        assert "出力先の拡張子" in capsys.readouterr().err

    def test_broken_symlink_output_exits_2_before_config(
        self,
        tmp_path: Path,
        background: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        from youtube_automation.scripts.thumbnail_text import main

        self._patch_input_only(monkeypatch, channel_root=tmp_path)
        output = tmp_path / "thumbnail-v1.jpg"
        output.symlink_to(tmp_path / "missing-target.jpg")

        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Test",
                "--output",
                str(output),
            ]
        )

        assert code == 2
        assert "シンボリックリンク" in capsys.readouterr().err

    def test_parent_symlink_output_exits_2_before_config(
        self,
        tmp_path: Path,
        background: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        from youtube_automation.scripts.thumbnail_text import main

        self._patch_input_only(monkeypatch, channel_root=tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        link_dir = tmp_path / "linked"
        link_dir.symlink_to(outside, target_is_directory=True)

        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Test",
                "--output",
                str(link_dir / "thumbnail-v1.jpg"),
            ]
        )

        assert code == 2
        assert "親ディレクトリにシンボリックリンク" in capsys.readouterr().err

    def test_output_outside_channel_dir_exits_2_before_config(
        self,
        tmp_path: Path,
        background: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        from youtube_automation.scripts.thumbnail_text import main

        channel_root = tmp_path / "channel"
        channel_root.mkdir()
        self._patch_input_only(monkeypatch, channel_root=channel_root)

        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Test",
                "--output",
                str(tmp_path / "thumbnail-v1.jpg"),
            ]
        )

        assert code == 2
        assert "channel_dir 配下" in capsys.readouterr().err

    def test_whitespace_only_title_exits_2_before_config(
        self,
        tmp_path: Path,
        background: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        from youtube_automation.scripts import thumbnail_text as cli

        monkeypatch.setattr(cli, "channel_dir", lambda: pytest.fail("title validation should stop before channel_dir"))
        monkeypatch.setattr(
            cli,
            "load_skill_config",
            lambda _skill: pytest.fail("title validation should stop before skill-config loading"),
        )

        code = cli.main(
            [
                "--background",
                str(background),
                "--title",
                "  ",
                "--output",
                str(tmp_path / "thumbnail-v1.jpg"),
            ]
        )

        assert code == 2
        assert "--title に空でないタイトル行" in capsys.readouterr().err

    def test_font_unconfigured_exits_1_with_guidance(
        self,
        tmp_path: Path,
        background: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        """default 設定 (overlay.font.title 未設定) では理由 + 代替手順を出して exit 1"""
        from youtube_automation.scripts.thumbnail_text import main

        self._patch_config(monkeypatch, channel_root=tmp_path, cfg={})
        code = main(
            [
                "--background",
                str(background),
                "--title",
                "Test Title",
                "--output",
                str(tmp_path / "out.jpg"),
            ]
        )
        assert code == 1
        stderr = capsys.readouterr().err
        assert "フォント指定が未設定です" in stderr
        assert "対処:" in stderr

    def test_missing_background_exits_2(self, tmp_path: Path, capsys):
        from youtube_automation.scripts.thumbnail_text import main

        code = main(
            [
                "--background",
                str(tmp_path / "missing.png"),
                "--title",
                "Test",
                "--output",
                str(tmp_path / "out.jpg"),
            ]
        )
        assert code == 2
        assert "背景画像が見つかりません" in capsys.readouterr().err

    def test_broken_background_exits_2(
        self,
        tmp_path: Path,
        test_font: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
    ):
        from youtube_automation.scripts.thumbnail_text import main

        broken = tmp_path / "broken.png"
        broken.write_bytes(b"not a real image")
        self._patch_config(monkeypatch, channel_root=tmp_path, cfg=_skill_config_dict(test_font))

        code = main(
            [
                "--background",
                str(broken),
                "--title",
                "Test",
                "--output",
                str(tmp_path / "out.jpg"),
            ]
        )

        assert code == 2
        assert "背景画像を読み込めません" in capsys.readouterr().err
