"""generate_master の --loop / --target-duration / --shuffle 実装テスト。"""

from __future__ import annotations

import random as real_random
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


class TestCliSkillConfigTargetDuration:
    """skill-config の audio.target_duration_min を CLI 未指定時のデフォルトとして解決する。"""

    def _patch_main_dependencies(
        self,
        monkeypatch,
        skill_config: dict,
    ) -> dict:
        """`load_skill_config` と `generate_master` を差し替えて kwargs を捕捉する。"""
        monkeypatch.setattr(
            "youtube_automation.scripts.generate_master.load_skill_config",
            lambda _: skill_config,
        )

        captured: dict = {}

        def fake_generate_master(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return Path("/tmp/fake-master.mp3")

        monkeypatch.setattr(
            "youtube_automation.scripts.generate_master.generate_master",
            fake_generate_master,
        )
        return captured

    def test_skill_config_target_duration_used_when_cli_unspecified(self, monkeypatch, tmp_path):
        # Given: skill-config に target_duration_min=120、CLI フラグ未指定
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"target_duration_min": 120}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: target_duration_min=120, loops=None で generate_master が呼ばれる
        assert rc == 0
        assert captured["kwargs"]["loops"] is None
        assert captured["kwargs"]["target_duration_min"] == 120

    def test_cli_target_duration_overrides_skill_config(self, monkeypatch, tmp_path):
        # Given: skill-config と CLI 両方に値があり CLI が優先されるべき
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"target_duration_min": 120}},
        )
        monkeypatch.setattr(
            "sys.argv",
            ["yt-generate-master", str(tmp_path), "--target-duration", "90"],
        )

        # When
        rc = generate_master.main()

        # Then: CLI 値 90 が採用される (skill-config の 120 は無視)
        assert rc == 0
        assert captured["kwargs"]["loops"] is None
        assert captured["kwargs"]["target_duration_min"] == 90

    def test_cli_loop_ignores_skill_config_target_duration(self, monkeypatch, tmp_path):
        # Given: --loop 指定時は skill-config の target_duration_min を黙って無視
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"target_duration_min": 120}},
        )
        monkeypatch.setattr(
            "sys.argv",
            ["yt-generate-master", str(tmp_path), "--loop", "3"],
        )

        # When
        rc = generate_master.main()

        # Then: loops=3, target_duration_min=None (skill-config 値が漏れない)
        assert rc == 0
        assert captured["kwargs"]["loops"] == 3
        assert captured["kwargs"]["target_duration_min"] is None

    def test_skill_config_target_duration_below_one_raises_validation_error(self, monkeypatch, capsys, tmp_path):
        # Given: skill-config 値が境界外 (< 1) — CLI と同じ境界条件で弾く
        self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"target_duration_min": 0}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: ValidationError で exit code 1、エラーメッセージにソースが明示される
        assert rc == 1
        err = capsys.readouterr().err
        assert "skill-config" in err
        assert "target_duration_min" in err

    def test_no_skill_config_target_duration_preserves_default_behavior(self, monkeypatch, tmp_path):
        # Given: skill-config に target_duration_min が無い (現行のデフォルト挙動)
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"crossfade_duration": 1.0, "bitrate": "192k"}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: 既存挙動どおり target_duration_min=None で渡る (= 1 ループ)
        assert rc == 0
        assert captured["kwargs"]["loops"] is None
        assert captured["kwargs"]["target_duration_min"] is None


def _setup_shuffle_collection(tmp_path: Path, file_count: int) -> tuple[Path, list[str]]:
    """シャッフル検証用のコレクション。並びが分かるように `01-track.mp3 ... NN-track.mp3`。"""
    (tmp_path / "01-master").mkdir()
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    names: list[str] = []
    for i in range(1, file_count + 1):
        name = f"{i:02d}-track.mp3"
        (music_dir / name).write_bytes(b"\x00" * 128)
        names.append(name)
    return tmp_path, names


def _input_files_in_cmd(cmd: list[str]) -> list[str]:
    """ffmpeg コマンドから `-i <path>` の <path> 部分を順序通りに抽出する。"""
    inputs: list[str] = []
    for i, token in enumerate(cmd):
        if token == "-i":
            inputs.append(cmd[i + 1])
    return inputs


class TestGenerateMasterShuffle:
    """generate_master() の shuffle / shuffle_seed kwargs を検証する。"""

    def test_shuffle_disabled_keeps_sorted_order(self, tmp_path, monkeypatch, capsys):
        # Given: shuffle=False (default) — 並びは sorted() のまま
        collection, names = _setup_shuffle_collection(tmp_path, file_count=5)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(collection, crossfade=1.0, bitrate="192k", quiet=True)

        inputs = _input_files_in_cmd(captured["cmd"])
        # ファイル名は sorted() 通り
        assert [Path(p).name for p in inputs] == names
        # シャッフルログは出ない
        assert "[Shuffle]" not in capsys.readouterr().out

    def test_shuffle_with_seed_is_deterministic(self, tmp_path, monkeypatch):
        # Given: shuffle=True, shuffle_seed=42 — random.Random(42) と同じ並びになる
        collection, names = _setup_shuffle_collection(tmp_path, file_count=5)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        expected = names.copy()
        real_random.Random(42).shuffle(expected)
        # 安全確認: 5 ファイル + seed 42 で sorted と異なる順序になることを保証
        assert expected != names

        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                shuffle=True,
                shuffle_seed=42,
                quiet=True,
            )

        inputs = _input_files_in_cmd(captured["cmd"])
        assert [Path(p).name for p in inputs] == expected

    def test_same_seed_gives_same_order_across_calls(self, tmp_path, monkeypatch):
        # Given: 同じ seed で 2 回呼べば同じ順序になる (再現性)
        collection, _ = _setup_shuffle_collection(tmp_path, file_count=5)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        results: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            results.append(_input_files_in_cmd(cmd))
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(collection, crossfade=1.0, bitrate="192k", shuffle=True, shuffle_seed=7, quiet=True)
            run_generate_master(collection, crossfade=1.0, bitrate="192k", shuffle=True, shuffle_seed=7, quiet=True)

        assert results[0] == results[1]

    def test_shuffle_log_includes_seed(self, tmp_path, monkeypatch, capsys):
        # Given: shuffle=True, shuffle_seed=42 — stdout に `[Shuffle] seed=42` が出る
        collection, _ = _setup_shuffle_collection(tmp_path, file_count=3)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        with patch.object(generate_master.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                shuffle=True,
                shuffle_seed=42,
                quiet=True,
            )

        out = capsys.readouterr().out
        assert "[Shuffle] seed=42" in out

    def test_shuffle_log_emitted_even_in_quiet_mode(self, tmp_path, monkeypatch, capsys):
        # Given: quiet=True でもシャッフル再現性ログは抑制しない (要件 4)
        collection, _ = _setup_shuffle_collection(tmp_path, file_count=3)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        with patch.object(generate_master.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                shuffle=True,
                shuffle_seed=99,
                quiet=True,
            )

        out = capsys.readouterr().out
        assert "[Shuffle] seed=99" in out

    def test_shuffle_without_seed_uses_system_random(self, tmp_path, monkeypatch, capsys):
        # Given: shuffle_seed=None — SystemRandom().randrange(2**32) で seed を確定
        collection, names = _setup_shuffle_collection(tmp_path, file_count=5)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        # SystemRandom().randrange(...) が固定値 12345 を返すように差し替え
        fake_sr = SimpleNamespace(randrange=lambda _bound: 12345)
        monkeypatch.setattr(generate_master.random, "SystemRandom", lambda: fake_sr, raising=False)

        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                shuffle=True,
                shuffle_seed=None,
                quiet=True,
            )

        # 自動生成 seed (12345) がログに出る
        out = capsys.readouterr().out
        assert "[Shuffle] seed=12345" in out
        # 並びは Random(12345) と一致する (= ログの seed が実際に使われた)
        expected = names.copy()
        real_random.Random(12345).shuffle(expected)
        inputs = _input_files_in_cmd(captured["cmd"])
        assert [Path(p).name for p in inputs] == expected

    def test_shuffle_happens_before_loop_expansion(self, tmp_path, monkeypatch):
        # Given: shuffle=True + loops=3 — shuffled_files * 3 (= 同じシャッフル順を 3 回繰り返す)
        # ループごとの独立シャッフルではない
        collection, names = _setup_shuffle_collection(tmp_path, file_count=4)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        expected_single = names.copy()
        real_random.Random(123).shuffle(expected_single)
        expected_expanded = expected_single * 3

        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                loops=3,
                shuffle=True,
                shuffle_seed=123,
                quiet=True,
            )

        inputs = _input_files_in_cmd(captured["cmd"])
        assert [Path(p).name for p in inputs] == expected_expanded
        # -i 数 = 4 files * 3 loops = 12
        assert captured["cmd"].count("-i") == 12

    def test_no_shuffle_ignores_shuffle_seed(self, tmp_path, monkeypatch, capsys):
        # Given: shuffle=False で shuffle_seed が渡っても並びは sorted のまま、ログも出ない
        collection, names = _setup_shuffle_collection(tmp_path, file_count=5)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with patch.object(generate_master.subprocess, "run", side_effect=fake_run):
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                shuffle=False,
                shuffle_seed=42,
                quiet=True,
            )

        inputs = _input_files_in_cmd(captured["cmd"])
        assert [Path(p).name for p in inputs] == names
        assert "[Shuffle]" not in capsys.readouterr().out

    def test_shuffle_with_single_file_does_not_error(self, tmp_path, monkeypatch, capsys):
        # Given: 1 file + shuffle=True — エラーにならず copy 経路を通る (ログは出る)
        collection, _ = _setup_shuffle_collection(tmp_path, file_count=1)
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        with patch.object(generate_master.subprocess, "run") as mock_run:
            run_generate_master(
                collection,
                crossfade=1.0,
                bitrate="192k",
                shuffle=True,
                shuffle_seed=1,
                quiet=True,
            )

        # ffmpeg は呼ばれず copy 経路
        mock_run.assert_not_called()
        assert (collection / "01-master" / "master.mp3").exists()
        # シャッフルログは出る (seed が記録されることが大事)
        assert "[Shuffle] seed=1" in capsys.readouterr().out


class TestCliShuffle:
    """CLI 引数 (--shuffle / --shuffle-seed) が generate_master() に渡る kwargs を検証する。"""

    def _patch_main_dependencies(self, monkeypatch, skill_config: dict | None = None) -> dict:
        monkeypatch.setattr(
            "youtube_automation.scripts.generate_master.load_skill_config",
            lambda _: skill_config or {},
        )

        captured: dict = {}

        def fake_generate_master(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return Path("/tmp/fake-master.mp3")

        monkeypatch.setattr(
            "youtube_automation.scripts.generate_master.generate_master",
            fake_generate_master,
        )
        return captured

    def test_no_flags_disables_shuffle(self, monkeypatch, tmp_path):
        # Given: --shuffle / --shuffle-seed どちらも未指定
        captured = self._patch_main_dependencies(monkeypatch, {})
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: shuffle=False, shuffle_seed=None
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is False
        assert captured["kwargs"]["shuffle_seed"] is None

    def test_cli_shuffle_flag_enables_shuffle(self, monkeypatch, tmp_path):
        # Given: --shuffle のみ指定
        captured = self._patch_main_dependencies(monkeypatch, {})
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path), "--shuffle"])

        # When
        rc = generate_master.main()

        # Then: shuffle=True, shuffle_seed=None
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True
        assert captured["kwargs"]["shuffle_seed"] is None

    def test_cli_shuffle_seed_implies_shuffle(self, monkeypatch, tmp_path):
        # Given: --shuffle-seed N 単独指定 (--shuffle 未指定)
        captured = self._patch_main_dependencies(monkeypatch, {})
        monkeypatch.setattr(
            "sys.argv",
            ["yt-generate-master", str(tmp_path), "--shuffle-seed", "42"],
        )

        # When
        rc = generate_master.main()

        # Then: shuffle=True (暗黙有効化), shuffle_seed=42
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True
        assert captured["kwargs"]["shuffle_seed"] == 42

    def test_cli_shuffle_seed_zero_is_treated_as_specified(self, monkeypatch, tmp_path):
        # Given: --shuffle-seed 0 — 値 0 でも "指定された" とみなして shuffle 有効化
        captured = self._patch_main_dependencies(monkeypatch, {})
        monkeypatch.setattr(
            "sys.argv",
            ["yt-generate-master", str(tmp_path), "--shuffle-seed", "0"],
        )

        # When
        rc = generate_master.main()

        # Then: shuffle=True, shuffle_seed=0
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True
        assert captured["kwargs"]["shuffle_seed"] == 0

    def test_cli_shuffle_with_explicit_seed(self, monkeypatch, tmp_path):
        # Given: --shuffle と --shuffle-seed を併用
        captured = self._patch_main_dependencies(monkeypatch, {})
        monkeypatch.setattr(
            "sys.argv",
            ["yt-generate-master", str(tmp_path), "--shuffle", "--shuffle-seed", "777"],
        )

        # When
        rc = generate_master.main()

        # Then: shuffle=True, shuffle_seed=777
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True
        assert captured["kwargs"]["shuffle_seed"] == 777


class TestCliSkillConfigShuffle:
    """skill-config の audio.shuffle / audio.shuffle_seed を CLI 未指定時のデフォルトとして解決する。"""

    def _patch_main_dependencies(self, monkeypatch, skill_config: dict) -> dict:
        monkeypatch.setattr(
            "youtube_automation.scripts.generate_master.load_skill_config",
            lambda _: skill_config,
        )

        captured: dict = {}

        def fake_generate_master(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return Path("/tmp/fake-master.mp3")

        monkeypatch.setattr(
            "youtube_automation.scripts.generate_master.generate_master",
            fake_generate_master,
        )
        return captured

    def test_skill_config_shuffle_true_enables_shuffle(self, monkeypatch, tmp_path):
        # Given: audio.shuffle: true、CLI フラグ未指定
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle": True}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: shuffle=True (skill-config から)、seed は None
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True
        assert captured["kwargs"]["shuffle_seed"] is None

    def test_skill_config_shuffle_with_seed(self, monkeypatch, tmp_path):
        # Given: audio.shuffle: true + audio.shuffle_seed: 42
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle": True, "shuffle_seed": 42}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: shuffle=True, shuffle_seed=42
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True
        assert captured["kwargs"]["shuffle_seed"] == 42

    def test_skill_config_shuffle_false_keeps_shuffle_disabled(self, monkeypatch, tmp_path):
        # Given: audio.shuffle: false (明示)、CLI フラグ未指定
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle": False}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: shuffle=False のまま
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is False

    def test_skill_config_shuffle_seed_alone_does_not_enable_shuffle(self, monkeypatch, tmp_path):
        # Given: audio.shuffle_seed: 42 のみ (audio.shuffle なし)
        # → 設計判断: shuffle_seed 単独では shuffle を有効化しない (CLI とセマンティクス揃え)
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle_seed": 42}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: shuffle=False (有効化しない)
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is False

    def test_cli_shuffle_overrides_skill_config_disabled(self, monkeypatch, tmp_path):
        # Given: skill-config で shuffle: false、CLI で --shuffle を指定
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle": False}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path), "--shuffle"])

        # When
        rc = generate_master.main()

        # Then: CLI が優先されて shuffle=True
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True

    def test_cli_shuffle_seed_overrides_skill_config_seed(self, monkeypatch, tmp_path):
        # Given: skill-config と CLI 両方に seed があり CLI が優先されるべき
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle": True, "shuffle_seed": 42}},
        )
        monkeypatch.setattr(
            "sys.argv",
            ["yt-generate-master", str(tmp_path), "--shuffle-seed", "5"],
        )

        # When
        rc = generate_master.main()

        # Then: CLI 値 5 が採用される (skill-config の 42 は無視)
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True
        assert captured["kwargs"]["shuffle_seed"] == 5

    def test_cli_shuffle_inherits_skill_config_seed(self, monkeypatch, tmp_path):
        # Given: CLI は --shuffle のみ、skill-config には audio.shuffle_seed: 42
        # CLI が seed を指定していなければ skill-config の seed が使われる
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle_seed": 42}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path), "--shuffle"])

        # When
        rc = generate_master.main()

        # Then: shuffle=True (CLI), shuffle_seed=42 (skill-config フォールバック)
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is True
        assert captured["kwargs"]["shuffle_seed"] == 42

    def test_skill_config_shuffle_seed_non_int_raises_validation_error(self, monkeypatch, capsys, tmp_path):
        # Given: skill-config の shuffle_seed が文字列 (型違反)
        self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle": True, "shuffle_seed": "abc"}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: ValidationError で exit code 1、エラーメッセージにソースとキー名が明示される
        assert rc == 1
        err = capsys.readouterr().err
        assert "skill-config" in err
        assert "shuffle_seed" in err

    def test_skill_config_shuffle_seed_bool_raises_validation_error(self, monkeypatch, capsys, tmp_path):
        # Given: shuffle_seed が True (bool は int サブクラスなので isinstance(x, int) を素通りする)
        self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"shuffle": True, "shuffle_seed": True}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: bool も型エラーとして弾く
        assert rc == 1
        err = capsys.readouterr().err
        assert "skill-config" in err
        assert "shuffle_seed" in err

    def test_no_skill_config_shuffle_preserves_default_behavior(self, monkeypatch, tmp_path):
        # Given: skill-config に shuffle / shuffle_seed のいずれも無い
        captured = self._patch_main_dependencies(
            monkeypatch,
            {"audio": {"crossfade_duration": 1.0, "bitrate": "192k"}},
        )
        monkeypatch.setattr("sys.argv", ["yt-generate-master", str(tmp_path)])

        # When
        rc = generate_master.main()

        # Then: 既存挙動どおり shuffle=False, shuffle_seed=None
        assert rc == 0
        assert captured["kwargs"]["shuffle"] is False
        assert captured["kwargs"]["shuffle_seed"] is None
