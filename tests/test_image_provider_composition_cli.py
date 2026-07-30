"""``image_provider.composition`` の CLI 共通ヘルパーの回帰テスト。

このファイルは ``generate_image.py`` の出力上書き確認 + ``-vN`` 採番、
参照画像パス解決を ``composition.py`` のヘルパーに集約した経路を回帰防止する。

family_tag: dry-violation
- ARCH-NEW-scripts-overwrite-prompt-DRY-L141 → ``prompt_overwrite_or_rename``
- ARCH-NEW-scripts-reference-resolution-DRY-L161 → ``resolve_reference_paths``

CLI が同じ helper を使っていることを保証するため、import 経路の存在も検査する。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_automation.commands.media import generate_image
from youtube_automation.domains.media.image import ImageGenerationResult
from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.image_provider.composition import (
    prompt_overwrite_or_rename,
    resolve_reference_paths,
)


class TestPromptOverwriteOrRename:
    """``prompt_overwrite_or_rename`` の分岐網羅。"""

    def test_returns_path_unchanged_when_file_does_not_exist(self, tmp_path: Path):
        """既存ファイルが無い場合は元のパスをそのまま返す（採番もプロンプトもしない）。"""
        target = tmp_path / "out.png"
        # yes=True / yes=False どちらでも非対話で同じ結果
        assert prompt_overwrite_or_rename(target, yes=True) == target
        assert prompt_overwrite_or_rename(target, yes=False) == target

    def test_returns_path_unchanged_when_existing_file_is_empty(self, tmp_path: Path):
        """空サイズの既存ファイルは「未生成扱い」で素通し（採番しない）。"""
        target = tmp_path / "out.png"
        target.touch()  # 0 byte
        assert prompt_overwrite_or_rename(target, yes=True) == target

    def test_yes_true_auto_renames_when_file_exists(self, tmp_path: Path):
        """yes=True かつ既存ファイル（非空）あり → ``-v2`` 採番された新規パスを返す。"""
        target = tmp_path / "out.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n")  # ダミー非空ファイル

        result = prompt_overwrite_or_rename(target, yes=True)

        assert result is not None
        assert result != target
        assert result.parent == target.parent
        assert result.suffix == ".png"
        assert result.stem == "out-v2"
        # 元ファイルは触らない
        assert target.exists()

    def test_yes_false_user_confirms_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """yes=False かつユーザーが ``y`` と返答 → 元のパスを返す（上書き許可）。"""
        target = tmp_path / "out.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        result = prompt_overwrite_or_rename(target, yes=False)

        assert result == target

    def test_yes_false_user_declines_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """yes=False かつユーザーが ``N`` 返答 → ``None``（呼び出し側 sys.exit 用）。"""
        target = tmp_path / "out.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
        monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

        assert prompt_overwrite_or_rename(target, yes=False) is None

    def test_yes_false_eof_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """yes=False で EOF（パイプ入力なし）→ ``None``（中止扱い）。"""
        target = tmp_path / "out.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n")

        def _raise_eof(_prompt: str = "") -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", _raise_eof)

        assert prompt_overwrite_or_rename(target, yes=False) is None

    def test_yes_false_keyboard_interrupt_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """yes=False で Ctrl+C → ``None``（中止扱い）。"""
        target = tmp_path / "out.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n")

        def _raise_kbi(_prompt: str = "") -> str:
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", _raise_kbi)

        assert prompt_overwrite_or_rename(target, yes=False) is None


class TestResolveReferencePaths:
    """``resolve_reference_paths`` の分岐網羅。"""

    def test_returns_empty_list_for_none(self):
        assert resolve_reference_paths(None) == []

    def test_returns_empty_list_for_empty_input(self):
        assert resolve_reference_paths([]) == []

    def test_resolves_absolute_paths_when_files_exist(self, tmp_path: Path):
        ref1 = tmp_path / "a.png"
        ref2 = tmp_path / "b.png"
        ref1.write_bytes(b"x")
        ref2.write_bytes(b"x")

        resolved = resolve_reference_paths([str(ref1), str(ref2)])

        assert resolved == [ref1, ref2]
        assert all(p.is_absolute() for p in resolved)

    def test_relative_paths_are_anchored_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        ref = tmp_path / "rel.png"
        ref.write_bytes(b"x")
        monkeypatch.chdir(tmp_path)

        resolved = resolve_reference_paths(["rel.png"])

        assert resolved == [tmp_path / "rel.png"]
        assert resolved[0].is_absolute()

    def test_missing_file_raises_config_error(self, tmp_path: Path):
        missing = tmp_path / "does-not-exist.png"
        with pytest.raises(ConfigError) as ei:
            resolve_reference_paths([str(missing)])
        assert str(missing) in str(ei.value)

    def test_partial_missing_raises_config_error_for_first_missing(self, tmp_path: Path):
        present = tmp_path / "a.png"
        present.write_bytes(b"x")
        missing = tmp_path / "missing.png"
        with pytest.raises(ConfigError) as ei:
            resolve_reference_paths([str(present), str(missing)])
        # 先頭が成功しても後続の欠損で fail-fast
        assert str(missing) in str(ei.value)


class TestGenerateImageCliHelperContracts:
    @pytest.fixture
    def cli(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        provider = MagicMock()
        provider.supported_aspect_ratios = ()
        provider.generate.side_effect = lambda req: ImageGenerationResult(success=True, saved_path=req.output_path)
        cfg = SimpleNamespace(
            provider="gemini",
            gemini=SimpleNamespace(model="test-model"),
            openai=None,
            gemini_cli=None,
        )
        monkeypatch.setattr(generate_image, "load_image_generation_config", lambda: cfg)
        monkeypatch.setattr(generate_image, "get_provider", lambda _cfg: provider)
        monkeypatch.setattr(generate_image, "_channel_root", lambda: tmp_path)
        monkeypatch.setattr(
            "youtube_automation.utils.skill_config.load_skill_config",
            lambda _name: {"image_generation": {"gemini": {}}},
        )
        monkeypatch.setattr(generate_image, "resolve_cost_per_image", lambda *_args: 0.0)
        monkeypatch.setattr(generate_image, "log_image_cost", lambda *_args, **_kwargs: None, raising=False)
        return provider

    def test_existing_output_with_yes_uses_versioned_path(self, cli, tmp_path: Path, monkeypatch):
        output = tmp_path / "out.png"
        output.write_bytes(b"existing")
        monkeypatch.setattr(
            "sys.argv",
            ["yt-generate-image", "--prompt", "scene", "--output", str(output), "--yes"],
        )

        with pytest.raises(SystemExit, match="0"):
            generate_image.main()

        assert cli.generate.call_args.args[0].output_path == tmp_path / "out-v2.png"
        assert output.read_bytes() == b"existing"

    def test_reference_is_resolved_and_forwarded_to_request(self, cli, tmp_path: Path, monkeypatch):
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"reference")
        output = tmp_path / "out.png"
        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-image",
                "--prompt",
                "scene",
                "--output",
                str(output),
                "--reference",
                str(reference),
                "--yes",
            ],
        )

        with pytest.raises(SystemExit, match="0"):
            generate_image.main()

        assert cli.generate.call_args.args[0].references == [reference]

    def test_missing_reference_exits_before_provider_creation(self, cli, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-image",
                "--prompt",
                "scene",
                "--output",
                str(tmp_path / "out.png"),
                "--reference",
                str(tmp_path / "missing.png"),
                "--yes",
            ],
        )

        with pytest.raises(SystemExit, match="1"):
            generate_image.main()

        captured = capsys.readouterr()
        assert "参照画像が見つかりません" in captured.err
        cli.generate.assert_not_called()
