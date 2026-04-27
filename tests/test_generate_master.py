"""generate_master の --loop / --target-duration 実装テスト。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from youtube_automation.scripts import generate_master
from youtube_automation.scripts.generate_master import (
    _resolve_loop_count,
    _sum_track_duration,
    build_filter,
)
from youtube_automation.scripts.generate_master import (
    generate_master as run_generate_master,
)
from youtube_automation.utils.exceptions import ValidationError


class TestResolveLoopCount:
    def test_explicit_loop_is_passthrough(self):
        assert _resolve_loop_count(3, None, single_loop_sec=0, crossfade=1.0) == 3

    def test_defaults_to_one(self):
        assert _resolve_loop_count(None, None, single_loop_sec=4600, crossfade=1.0) == 1

    def test_target_duration_computes_min_loops(self):
        # 1 ループ 4600s、target 9000s (150 min) → 2 ループで
        #   2 * 4600 - 1 * 1.0 = 9199s >= 9000s, 1 ループでは 4600s < 9000s
        assert _resolve_loop_count(None, 150, single_loop_sec=4600, crossfade=1.0) == 2

    def test_target_duration_exact_boundary_single_loop(self):
        # 1 ループちょうど target 尺を超えるケース → 1 で足りる
        # target = 60 min = 3600s, single_loop = 3600s, crossfade=1.0
        # M >= (3600 - 1.0) / (3600 - 1.0) = 1.0 → 1
        assert _resolve_loop_count(None, 60, single_loop_sec=3600, crossfade=1.0) == 1

    def test_target_duration_requires_three_loops(self):
        # target 180 min = 10800s, single 4600s, crossfade 1.0
        # M=2: 9199 < 10800, M=3: 13798 >= 10800 → 3
        assert _resolve_loop_count(None, 180, single_loop_sec=4600, crossfade=1.0) == 3

    def test_target_duration_min_clamped_to_one(self):
        # target が極小で single_loop が大きいケースでも 1 未満にならない
        assert _resolve_loop_count(None, 1, single_loop_sec=4600, crossfade=1.0) == 1


class TestSumTrackDuration:
    def test_sums_successful_probes(self):
        files = [Path("/fake/a.mp3"), Path("/fake/b.mp3"), Path("/fake/c.mp3")]
        with patch(
            "youtube_automation.scripts.generate_master.probe_duration",
            side_effect=[100.0, 200.5, 50.25],
        ):
            assert _sum_track_duration(files) == pytest.approx(350.75)

    def test_raises_on_probe_failure(self):
        files = [Path("/fake/a.mp3"), Path("/fake/b.mp3")]
        with patch(
            "youtube_automation.scripts.generate_master.probe_duration",
            side_effect=[100.0, None],
        ):
            with pytest.raises(ValidationError, match="probe に失敗"):
                _sum_track_duration(files)


class TestBuildFilter:
    """build_filter のリグレッション防止（ループ機能が既存ロジックを壊さないため）。"""

    def test_two_inputs(self):
        assert build_filter(2, 1.0) == "[0:a][1:a]acrossfade=d=1:c1=tri:c2=tri[aout]"

    def test_four_inputs(self):
        result = build_filter(4, 1.5)
        parts = result.split(";")
        assert len(parts) == 3
        assert parts[0] == "[0:a][1:a]acrossfade=d=1.5:c1=tri:c2=tri[cf1]"
        assert parts[1] == "[cf1][2:a]acrossfade=d=1.5:c1=tri:c2=tri[cf2]"
        assert parts[2] == "[cf2][3:a]acrossfade=d=1.5:c1=tri:c2=tri[aout]"

    def test_six_inputs_chain_indices(self):
        result = build_filter(6, 2.0)
        parts = result.split(";")
        assert len(parts) == 5
        # 最後が [aout] 出力
        assert parts[-1].endswith("[aout]")
        # 中間は [cfN-1][i:a] ... [cfN] の連鎖
        assert parts[1] == "[cf1][2:a]acrossfade=d=2:c1=tri:c2=tri[cf2]"
        assert parts[3] == "[cf3][4:a]acrossfade=d=2:c1=tri:c2=tri[cf4]"


class TestGenerateMasterLoops:
    """generate_master() のループ展開を subprocess.run mock で検証。"""

    def _setup_collection(self, tmp_path: Path, file_count: int = 2) -> Path:
        (tmp_path / "01-master").mkdir()
        music_dir = tmp_path / "02-Individual-music"
        music_dir.mkdir()
        for i in range(file_count):
            (music_dir / f"{i + 1:02d}-track.mp3").write_bytes(b"\x00" * 128)
        return tmp_path

    def test_loop_3_expands_file_list(self, tmp_path, monkeypatch):
        collection = self._setup_collection(tmp_path, file_count=2)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                loops=3,
                quiet=True,
            )

        cmd = captured["cmd"]
        # -i オカレンス数 = 2 files × 3 loops = 6
        assert cmd.count("-i") == 6
        # 出力先は 01-master/master.mp3
        assert cmd[-3] == str(collection / "01-master" / "master.mp3")
        # filter_complex に 6 入力 = 5 crossfade → parts 5 個（";" 4 個）
        idx = cmd.index("-filter_complex")
        filter_expr = cmd[idx + 1]
        assert filter_expr.count(";") == 4
        assert filter_expr.endswith("[aout]")

    def test_no_loop_argument_uses_original_files(self, tmp_path, monkeypatch):
        collection = self._setup_collection(tmp_path, file_count=3)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(collection, crossfade=1.0, bitrate="192k", quiet=True)

        # loops 未指定 → 元ファイル数 3 のまま
        assert captured["cmd"].count("-i") == 3

    def test_target_duration_triggers_probe_and_expansion(self, tmp_path, monkeypatch):
        collection = self._setup_collection(tmp_path, file_count=2)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        # 各ファイル 2300s → 1 ループ 4600s、target 150 min = 9000s → 2 ループ
        monkeypatch.setattr(generate_master, "probe_duration", lambda p: 2300.0)

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                target_duration_min=150,
                quiet=True,
            )

        # 2 files × 2 loops = 4 inputs
        assert captured["cmd"].count("-i") == 4

    def test_single_file_with_loop_1_uses_copy_path(self, tmp_path, monkeypatch):
        collection = self._setup_collection(tmp_path, file_count=1)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        with patch.object(generate_master.subprocess, "run") as mock_run:
            run_generate_master(collection, crossfade=1.0, bitrate="192k", quiet=True)

        # ffmpeg は呼ばれず、shutil.copyfile パスを通る
        mock_run.assert_not_called()
        assert (collection / "01-master" / "master.mp3").exists()

    def test_single_file_with_loop_3_uses_ffmpeg(self, tmp_path, monkeypatch):
        collection = self._setup_collection(tmp_path, file_count=1)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(collection, crossfade=1.0, bitrate="192k", loops=3, quiet=True)

        # 1 file × 3 loops = 3 inputs → ffmpeg 経路
        assert captured["cmd"].count("-i") == 3


class TestCli:
    """CLI 引数バリデーション。"""

    def test_loop_and_target_duration_mutually_exclusive(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "sys.argv",
            ["yt-generate-master", "--loop", "2", "--target-duration", "120"],
        )
        with pytest.raises(SystemExit) as exc:
            generate_master.main()
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "not allowed with argument" in err

    def test_invalid_loop_value(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["yt-generate-master", "--loop", "0"])
        # collection 解決前にバリデーションで落ちる
        monkeypatch.chdir("/tmp")
        rc = generate_master.main()
        assert rc == 1
        assert "--loop は 1 以上" in capsys.readouterr().err

    def test_invalid_target_duration_value(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["yt-generate-master", "--target-duration", "0"])
        monkeypatch.chdir("/tmp")
        rc = generate_master.main()
        assert rc == 1
        assert "--target-duration は 1 以上" in capsys.readouterr().err
