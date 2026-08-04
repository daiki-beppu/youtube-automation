"""``image_provider.composition`` の単価解決・コスト確認・ログ配線テスト。

Issue #132 (PRICING 撤廃) で振る舞いが変わる以下を網羅する:

- ``resolve_cost_per_image`` の戻り値が ``float | None``。skill-config の
  ``cost_per_image_usd`` を尊重し、未設定なら ``None`` (PRICING フォールバックなし)
- ``confirm_cost`` が ``float | None`` を受理し、None 時は「不明」を表示しつつ
  y/N 確認は維持する
- ``log_image_cost`` が ``cost_usd`` 引数を受理しない (deprecated 形式の再投入防止)
  / ``log_generation`` に ``unit="image"`` + metadata で配線される

CLI ヘルパー (``prompt_overwrite_or_rename`` / ``resolve_reference_paths``) は
``test_image_provider_composition_cli.py`` で別途カバー済み。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from youtube_automation.infrastructure.media.image_provider.composition import (
    apply_composition_rules,
    confirm_cost,
    log_image_cost,
    persist_image,
    resolve_cost_per_image,
)


@pytest.fixture
def tmp_channel(tmp_path: Path, monkeypatch):
    """tests/infrastructure/test_cost_tracker.py と同等の最小チャンネル fixture。"""
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    (tmp_path / "config" / "channel").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "channel" / "meta.json").write_text(
        json.dumps(
            {
                "channel": {"name": "test", "slug": "test", "default_language": "ja"},
                "youtube_channel": {"id": "UC_TEST", "handle": "@test", "url": "https://youtube.com/@test"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "channel" / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "test"},
                "tags": {"base": []},
                "descriptions": {"short": "", "long": ""},
                "title": {"prefix": "", "suffix": ""},
            }
        ),
        encoding="utf-8",
    )
    from youtube_automation.configuration import reset

    reset()
    yield tmp_path
    reset()


def _read_log(channel_dir: Path, filename: str) -> list[dict]:
    path = channel_dir / "data" / filename
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================
# resolve_cost_per_image (Test #24-29)
# ============================================================


class TestResolveCostPerImage:
    """``resolve_cost_per_image`` は ``float | None`` を返す。

    PRICING フォールバックは撤廃済み。skill-config に値がなければ None。
    """

    def test_returns_float_from_image_generation_provider_section(self):
        """Given skill_cfg["image_generation"]["gemini"]["cost_per_image_usd"]=0.07
        When resolve_cost_per_image(..., provider="gemini")
        Then 0.07 を float で返す。
        """
        cfg = {"image_generation": {"gemini": {"cost_per_image_usd": 0.07}}}

        result = resolve_cost_per_image(cfg, "gemini")

        assert result == pytest.approx(0.07)
        assert isinstance(result, float)

    def test_returns_none_when_skill_config_has_no_override(self):
        """Given skill_cfg が空 (PRICING フォールバック撤廃を直接検証)
        When resolve_cost_per_image を呼ぶ
        Then None を返す (0.0 にもならない / 例外も投げない)。

        本 PR コア検証: PRICING 撤廃により「設定がないのに値が出る」経路を完全除去。
        """
        result = resolve_cost_per_image({}, "gemini")

        assert result is None

    def test_returns_none_when_provider_section_has_no_cost_per_image_usd(self):
        """Given image_generation.gemini に他キーはあるが cost_per_image_usd 欠落
        When resolve_cost_per_image を呼ぶ
        Then None を返す。
        """
        cfg = {"image_generation": {"gemini": {"model": "gemini-3.1-flash-image-preview"}}}

        result = resolve_cost_per_image(cfg, "gemini")

        assert result is None

    def test_returns_float_for_openai_provider_section(self):
        """Given skill_cfg["image_generation"]["openai"]["cost_per_image_usd"]=0.21
        When resolve_cost_per_image(..., provider="openai")
        Then 0.21 を float で返す (openai Happy パス)。
        """
        cfg = {"image_generation": {"openai": {"cost_per_image_usd": 0.21}}}

        result = resolve_cost_per_image(cfg, "openai")

        assert result == pytest.approx(0.21)
        assert isinstance(result, float)


# ============================================================
# confirm_cost (Test #30-34)
# ============================================================


class TestConfirmCost:
    """``confirm_cost`` は ``float | None`` を受理する。

    数値時は ``$x.xxx`` を表示、None 時は「不明 (skill-config の cost_per_image_usd 未設定)」を
    表示するが、いずれも y/N 確認自体は維持する。
    """

    def test_numeric_cost_with_user_yes_returns_true_and_prints_dollar(self, capsys, monkeypatch: pytest.MonkeyPatch):
        """Given cost_per_image=0.101 / ユーザー 'y'
        When confirm_cost
        Then True を返し、$0.101 表記が stdout に出る。
        """
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        assert confirm_cost("gemini-3.1-flash-image-preview", 0.101) is True

        out = capsys.readouterr().out
        assert "$0.101" in out

    def test_none_cost_with_user_yes_returns_true_and_prints_unknown(self, capsys, monkeypatch: pytest.MonkeyPatch):
        """Given cost_per_image=None / ユーザー 'y'
        When confirm_cost
        Then True を返し、「不明」表記が stdout に出る (F-3 反映)。
        """
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        assert confirm_cost("gemini-3.1-flash-image-preview", None) is True

        out = capsys.readouterr().out
        assert "不明" in out
        assert "$" not in out  # 数値カラム自体を出さない

    def test_none_cost_with_user_no_returns_false(self, monkeypatch: pytest.MonkeyPatch):
        """Given cost_per_image=None / ユーザー 'n'
        When confirm_cost
        Then False を返す (None でも y/N 確認は維持)。
        """
        monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

        assert confirm_cost("gemini-3.1-flash-image-preview", None) is False

    def test_numeric_cost_with_user_no_returns_false(self, monkeypatch: pytest.MonkeyPatch):
        """Given cost_per_image=0.101 / ユーザー 'N'
        When confirm_cost
        Then False を返す (既存挙動の維持)。
        """
        monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

        assert confirm_cost("gemini-3.1-flash-image-preview", 0.101) is False

    def test_none_cost_with_eof_returns_false(self, monkeypatch: pytest.MonkeyPatch):
        """Given cost_per_image=None / 入力で EOFError
        When confirm_cost
        Then False を返す (パイプ実行時の中止経路)。
        """

        def _raise_eof(_prompt: str = "") -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", _raise_eof)

        assert confirm_cost("gemini-3.1-flash-image-preview", None) is False


# ============================================================
# log_image_cost (Test #35-36)
# ============================================================


class TestLogImageCost:
    """``log_image_cost`` は ``log_generation`` を ``unit="image"`` + metadata で呼ぶ。

    ``cost_usd`` 引数は撤廃済み (deprecated 経路の再投入を防ぐ)。
    """

    def test_writes_log_generation_with_unit_image_and_metadata(self, tmp_channel: Path):
        """Given log_image_cost を呼ぶ
        When 引数 (model, image_size, aspect_ratio, output_file, reference_count)
        Then log_generation 経由で image_costs.json に
            unit="image" / metadata に image_size / aspect_ratio / reference_count /
            output_file が格納される。
        """
        output = tmp_channel / "collections" / "foo" / "main.png"

        entry = log_image_cost(
            model="gemini-3.1-flash-image-preview",
            image_size="2K",
            aspect_ratio="16:9",
            output_file=output,
            reference_count=2,
        )

        assert entry is not None
        assert entry["category"] == "image"
        assert entry["unit"] == "image"
        assert entry["estimated_cost_usd"] is None
        assert entry["metadata"]["image_size"] == "2K"
        assert entry["metadata"]["aspect_ratio"] == "16:9"
        assert entry["metadata"]["reference_count"] == 2
        assert entry["metadata"]["output_file"] == "collections/foo/main.png"

        entries = _read_log(tmp_channel, "image_costs.json")
        assert len(entries) == 1
        assert entries[0]["unit"] == "image"
        assert entries[0]["estimated_cost_usd"] is None

    def test_rejects_cost_usd_keyword_argument(self, tmp_channel: Path):
        """Given log_image_cost 呼び出し
        When `cost_usd=` キーワード引数を渡す
        Then TypeError (deprecated シグネチャの再投入を防ぐ)。
        """
        output = tmp_channel / "collections" / "foo" / "main.png"

        with pytest.raises(TypeError, match="cost_usd"):
            log_image_cost(
                model="gemini-3.1-flash-image-preview",
                image_size="2K",
                aspect_ratio="16:9",
                output_file=output,
                cost_usd=0.101,  # type: ignore[call-arg]
                reference_count=0,
            )


class TestApplyCompositionRules:
    @pytest.mark.parametrize(
        ("config", "prompt"),
        [
            ({}, "quiet library"),
            ({"composition_prefix": "Wide shot"}, "quiet library"),
            ({"composition_keywords": ["close-up"]}, "quiet library"),
            (
                {"composition_prefix": "Wide shot", "composition_keywords": ["close-up"]},
                "A close-up portrait",
            ),
            (
                {"composition_prefix": "Wide shot", "composition_keywords": ["close-up"]},
                "Edit this image without changing the subject",
            ),
        ],
    )
    def test_returns_prompt_unchanged_when_prefix_is_not_applicable(self, config, prompt):
        assert apply_composition_rules(prompt, config) == prompt

    def test_prefixes_prompt_when_no_keyword_matches(self):
        result = apply_composition_rules(
            "quiet library",
            {"composition_prefix": "Wide shot", "composition_keywords": ["close-up"]},
        )
        assert result == "Wide shot quiet library"


class TestPersistImage:
    def test_png_writes_lossless_and_jpeg_companion(self, tmp_path: Path):
        output = tmp_path / "thumbnail.png"

        saved = persist_image(Image.new("RGBA", (8, 8), (1, 2, 3, 128)), output, save_as_png=True)

        assert saved == output
        assert output.exists()
        assert output.with_suffix(".jpg").exists()
        with Image.open(output) as png:
            assert png.format == "PNG"
        with Image.open(output.with_suffix(".jpg")) as jpg:
            assert jpg.format == "JPEG"

    def test_jpeg_mode_removes_stale_non_jpeg_output_only_after_save(self, tmp_path: Path):
        output = tmp_path / "thumbnail.png"
        output.write_bytes(b"stale")

        saved = persist_image(Image.new("RGB", (8, 8), "red"), output, save_as_png=False)

        assert saved == output.with_suffix(".jpg")
        assert saved.exists()
        assert not output.exists()

    def test_jpeg_conversion_failure_preserves_existing_source(self, tmp_path: Path):
        output = tmp_path / "thumbnail.png"
        output.write_bytes(b"stale")
        image = MagicMock()
        converted = MagicMock()
        converted.save.side_effect = OSError("disk full")
        image.convert.return_value = converted

        with pytest.raises(OSError, match="disk full"):
            persist_image(image, output, save_as_png=False)

        assert output.read_bytes() == b"stale"
        assert not output.with_suffix(".jpg").exists()
