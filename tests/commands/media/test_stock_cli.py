"""``yt-stock-*`` CLI のスモークテスト。

実 channel_dir を fixtures から拝借せず、tmp 配下に固有の CHANNEL_DIR を
立てて isolated に動かす。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from youtube_automation.commands.media import stock_archive, stock_list, stock_preview, stock_prune
from youtube_automation.configuration import skills as skill_config_mod


@pytest.fixture
def isolated_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """最小限の config/channel/ を持つ tmp channel を立てて CHANNEL_DIR に設定する。

    `_reset_config_singleton` autouse fixture が configuration.reset() を呼ぶので
    ここでは skill_config キャッシュだけ追加でクリアする。
    """

    channel = tmp_path / "channel"
    (channel / "config" / "channel").mkdir(parents=True)
    monkeypatch.setenv("CHANNEL_DIR", str(channel))
    skill_config_mod.reset()
    return channel


def _make_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PNG")
    return path


def _patch_skill_config(monkeypatch: pytest.MonkeyPatch, cfg: dict) -> None:
    """``load_skill_config('thumbnail')`` の戻り値を差し替える。"""

    def fake(skill: str, *, use_cache: bool = True) -> dict:
        return cfg

    monkeypatch.setattr(stock_archive, "load_skill_config", fake)
    monkeypatch.setattr(stock_prune, "load_skill_config", fake)


# ---- yt-stock-archive ------------------------------------------------------


class TestStockArchiveCLI:
    def test_archives_with_flags(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": True}}})

        exit_code = stock_archive.main(
            [
                str(image),
                "--theme",
                "tavern",
                "--source-collection",
                "col-A",
                "--source-role",
                "thumbnail_candidate",
            ]
        )

        assert exit_code == 0
        assert not image.exists()
        archived = list((isolated_channel / "assets" / "stock" / "tavern").glob("*.jpg"))
        assert len(archived) == 1
        out = capsys.readouterr().out
        assert "archived" in out

    def test_archives_with_meta_json_stdin(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": True}}})

        payload = json.dumps(
            {
                "theme": "library",
                "source_collection": "col-B",
                "source_role": "ideate_preview",
                "prompt": "study lamp",
            }
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))

        exit_code = stock_archive.main([str(image), "--meta-json", "-"])
        assert exit_code == 0

        archived = list((isolated_channel / "assets" / "stock" / "library").glob("*.jpg"))
        assert len(archived) == 1
        meta_files = list((isolated_channel / "assets" / "stock" / "library").glob("*.meta.json"))
        assert meta_files
        meta = json.loads(meta_files[0].read_text())
        assert meta["prompt"] == "study lamp"

    def test_disabled_unlinks(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": False}}})

        exit_code = stock_archive.main([str(image), "--theme", "tavern"])
        assert exit_code == 0
        assert not image.exists()
        assert not (isolated_channel / "assets" / "stock" / "tavern").exists()
        out = capsys.readouterr().out
        assert "stock disabled" in out

    def test_exclude_pattern(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        keep = _make_image(tmp_path / "plan-a.png")
        drop = _make_image(tmp_path / "plan-b.png")
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": True}}})

        exit_code = stock_archive.main(
            [
                str(keep),
                str(drop),
                "--theme",
                "tavern",
                "--exclude",
                "plan-a.png",
            ]
        )
        assert exit_code == 0
        assert keep.exists()  # excluded → 退避されず元の場所に残る
        assert not drop.exists()

    def test_partial_failure_keeps_prior_archive_and_stops_before_later_input(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from youtube_automation.core.errors import ValidationError

        first = _make_image(tmp_path / "first.jpg")
        second = _make_image(tmp_path / "second.jpg")
        third = _make_image(tmp_path / "third.jpg")
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": True}}})
        real_archive = stock_archive.archive_to_stock
        calls: list[Path] = []

        def archive(path: Path, meta: dict, **kwargs):
            calls.append(path)
            if path == second:
                raise ValidationError("archive failed")
            return real_archive(path, meta, **kwargs)

        monkeypatch.setattr(stock_archive, "archive_to_stock", archive)

        exit_code = stock_archive.main([str(first), str(second), str(third), "--theme", "tavern"])

        assert exit_code == 2
        assert calls == [first, second]
        assert not first.exists()
        assert second.exists()
        assert third.exists()
        assert len(list((isolated_channel / "assets" / "stock" / "tavern").glob("*.jpg"))) == 1
        assert "archive failed" in capsys.readouterr().err

    def test_duplicate_input_is_archived_once_and_then_skipped(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        image = _make_image(tmp_path / "duplicate.jpg")
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": True}}})

        exit_code = stock_archive.main([str(image), str(image), "--theme", "tavern"])

        assert exit_code == 0
        assert not image.exists()
        assert len(list((isolated_channel / "assets" / "stock" / "tavern").glob("*.jpg"))) == 1
        captured = capsys.readouterr()
        assert "Summary: archived=1 unlinked=0 skipped=1" in captured.out
        assert f"not found: {image}" in captured.err


# ---- yt-stock-list ---------------------------------------------------------


class TestStockListCLI:
    def test_list_json_empty(
        self,
        isolated_channel: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = stock_list.main(["--format", "json"])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert json.loads(out) == []

    def test_list_table_after_archive(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": True}}})
        stock_archive.main([str(image), "--theme", "tavern"])
        capsys.readouterr()

        exit_code = stock_list.main(["--format", "json", "--theme", "tavern"])
        assert exit_code == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert len(payload) == 1
        assert payload[0]["theme"] == "tavern"


# ---- yt-stock-preview ------------------------------------------------------


class TestStockPreviewCLI:
    def test_print_only_no_entries(
        self,
        isolated_channel: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = stock_preview.main(["--print-only"])
        assert exit_code == 0
        err = capsys.readouterr().err
        assert "no stock entries" in err

    def test_print_only_lists_paths(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        image = _make_image(tmp_path / "main-v1.jpg")
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": True}}})
        stock_archive.main([str(image), "--theme", "tavern"])
        capsys.readouterr()

        exit_code = stock_preview.main(["--print-only", "--theme", "tavern"])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "tavern" in out


# ---- yt-stock-prune --------------------------------------------------------


class TestStockPruneCLI:
    def test_prune_requires_threshold(
        self,
        isolated_channel: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _patch_skill_config(monkeypatch, {})

        exit_code = stock_prune.main([])
        assert exit_code == 2
        err = capsys.readouterr().err
        assert "retention-days" in err

    def test_prune_with_max_per_theme(
        self,
        isolated_channel: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _patch_skill_config(monkeypatch, {"image_generation": {"stock": {"enabled": True}}})
        for i in range(3):
            image = _make_image(tmp_path / f"main-v{i}.jpg")
            stock_archive.main(
                [
                    str(image),
                    "--theme",
                    "tavern",
                    "--source-collection",
                    f"col-{i}",
                ]
            )
        capsys.readouterr()

        exit_code = stock_prune.main(["--max-per-theme", "1"])
        assert exit_code == 0
        remaining = list((isolated_channel / "assets" / "stock" / "tavern").glob("*.jpg"))
        assert len(remaining) == 1
