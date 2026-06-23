"""generate_lyria_master CLI のユニットテスト。

`lyria_client.generate_music` を monkeypatch でダミー化し、ffmpeg subprocess も mock して
セグメント生成 → クロスフェード結合パスを検証する。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.scripts import generate_lyria_master
from youtube_automation.scripts.generate_lyria_master import (
    _LYRIA_SEGMENT_SEC,
    _generate_one_segment,
    _resolve_segment_count,
)
from youtube_automation.utils.exceptions import ValidationError


@pytest.fixture(autouse=True)
def _isolate_channel_dir(tmp_path, monkeypatch):
    """`CHANNEL_DIR` を tmp_path に向けて cost_tracker の data/ 書き込みを隔離する。"""
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))


def _make_collection(root: Path) -> Path:
    """01-master / 02-Individual-music を持つ最小コレクションを作る。"""
    (root / "01-master").mkdir(parents=True, exist_ok=True)
    (root / "02-Individual-music").mkdir(parents=True, exist_ok=True)
    return root


class TestResolveSegmentCount:
    """`(target + padding) * 60 / _LYRIA_SEGMENT_SEC` の切り上げで N を算出する。"""

    def test_typical_60min_with_3min_padding(self):
        # (60 + 3) * 60 / 184 = 20.54... → 21
        assert _resolve_segment_count(60, 3) == 21

    def test_typical_120min_with_3min_padding(self):
        # (120 + 3) * 60 / 184 = 40.10... → 41
        assert _resolve_segment_count(120, 3) == 41

    def test_short_duration_clamped_to_one(self):
        # 1 分 + padding 0 でも最低 1 セグメント
        assert _resolve_segment_count(1, 0) == 1

    def test_exact_segment_boundary(self):
        # ちょうど 1 セグメント (184 秒) になる場合
        target_min = _LYRIA_SEGMENT_SEC / 60
        assert _resolve_segment_count(target_min, 0) == 1

    def test_just_over_one_segment_requires_two(self):
        # 184 秒 + 1 秒 → 2 セグメント
        target_min = (_LYRIA_SEGMENT_SEC + 1) / 60
        assert _resolve_segment_count(target_min, 0) == 2

    def test_zero_target_raises(self):
        with pytest.raises(ValidationError, match="target-duration"):
            _resolve_segment_count(0, 3)

    def test_negative_padding_raises(self):
        with pytest.raises(ValidationError, match="padding-min"):
            _resolve_segment_count(60, -1)


def _patch_lyria_generate(monkeypatch, *, payload: bytes | None = b"FAKE_MP3", call_log: list | None = None):
    """`lyria_client.generate_music` を差し替え。call_log があれば各呼び出しの kwargs を記録する。"""
    log = call_log if call_log is not None else []

    def fake_generate(prompt, model, **kwargs):  # noqa: ARG001
        log.append({"prompt": prompt, "model": model, **kwargs})
        return payload

    monkeypatch.setattr(generate_lyria_master.lyria_client, "generate_music", fake_generate)
    return log


def _patch_ffmpeg(monkeypatch, *, segment_size: int = 1024):
    """ffmpeg subprocess を mock し、`_save_audio_as_wav` の出力ファイルを実体化する。

    `_save_audio_as_wav` は `subprocess.run([..., "-i", tmp, ..., str(path)], check=True)` を呼ぶ。
    mock 内で path にダミーバイトを書き込んで「ffmpeg が WAV を出力した」状態を再現する。
    """

    def fake_run(cmd, **kwargs):
        # cmd[-1] が出力 path、cmd[-3] (Lyria CLI からの呼び出し時) も検査用に保持
        if cmd[0] == "ffmpeg":
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00" * segment_size)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(generate_lyria_master.subprocess, "run", fake_run)


def _patch_skill_configs(monkeypatch, *, lyria: dict | None = None, masterup: dict | None = None):
    lyria_cfg = lyria if lyria is not None else {"model": "lyria-3-pro-preview", "duration_padding_min": 3}
    masterup_cfg = masterup if masterup is not None else {"audio": {"crossfade_duration": 1.0, "bitrate": "192k"}}

    def fake_load(skill, *, use_cache=True):  # noqa: ARG001
        if skill == "lyria":
            return lyria_cfg
        if skill == "masterup":
            return masterup_cfg
        raise AssertionError(f"unexpected skill: {skill}")

    monkeypatch.setattr(generate_lyria_master, "load_skill_config", fake_load)


def _patch_generate_master(monkeypatch, *, return_path: Path | None = None):
    """`generate_master.generate_master` を差し替えて呼び出し引数を記録する。"""
    captured: dict = {}

    def fake_generate(collection_dir, crossfade, bitrate, **kwargs):
        captured["args"] = (collection_dir, crossfade, bitrate)
        captured["kwargs"] = kwargs
        return return_path or (Path(collection_dir) / "01-master" / "master.wav")

    monkeypatch.setattr(generate_lyria_master.generate_master, "generate_master", fake_generate)
    return captured


def _patch_load_config(monkeypatch, *, target_duration_min: float | None = None):
    """`utils.config.load_config()` を差し替えて audio.target_duration_min をテスト制御下に置く。"""
    audio_ns = SimpleNamespace(target_duration_min=target_duration_min)
    cfg_ns = SimpleNamespace(audio=audio_ns)

    monkeypatch.setattr(generate_lyria_master, "load_config", lambda: cfg_ns)


class TestGenerateSegments:
    """セグメント生成ループの挙動: N 回呼び出し / resume / リトライ。"""

    def test_generates_n_segments_named_correctly(self, tmp_path, monkeypatch, capsys):
        collection = _make_collection(tmp_path / "coll")
        call_log = _patch_lyria_generate(monkeypatch)
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(monkeypatch)
        _patch_load_config(monkeypatch, target_duration_min=None)  # CLI で渡す
        master_capture = _patch_generate_master(monkeypatch)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "celtic folk, soft fingerpicked guitar",
                "--name",
                "rain-glass",
                "--target-duration",
                "9",  # (9+3)*60/184 = 3.91 → 4 セグメント
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 0

        # 4 回呼ばれる
        assert len(call_log) == 4
        # 各呼び出しで prompt / model が転送される
        for entry in call_log:
            assert entry["prompt"] == "celtic folk, soft fingerpicked guitar"
            assert entry["model"] == "lyria-3-pro-preview"

        # 02-Individual-music/01_rain-glass.wav 〜 04_rain-glass.wav が作成される
        music_dir = collection / "02-Individual-music"
        for i in range(1, 5):
            assert (music_dir / f"{i:02d}_rain-glass.wav").exists()

        # 結合段に渡る crossfade / bitrate は skill-config の値
        assert master_capture["args"][0] == collection
        assert master_capture["args"][1] == 1.0
        assert master_capture["args"][2] == "192k"

        out = capsys.readouterr().out
        assert "Segments   : 4" in out

    def test_resume_skips_existing_segments(self, tmp_path, monkeypatch, capsys):
        collection = _make_collection(tmp_path / "coll")
        # 1 番目セグメントが既存
        (collection / "02-Individual-music" / "01_resume.wav").write_bytes(b"existing")

        call_log = _patch_lyria_generate(monkeypatch)
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(monkeypatch)
        _patch_load_config(monkeypatch, target_duration_min=None)
        _patch_generate_master(monkeypatch)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "p",
                "--name",
                "resume",
                "--target-duration",
                "9",  # 4 セグメント
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 0
        # 既存の 01 は skip、残り 3 セグメントだけ生成
        assert len(call_log) == 3
        # 既存ファイル内容が上書きされない
        assert (collection / "02-Individual-music" / "01_resume.wav").read_bytes() == b"existing"

        out = capsys.readouterr().out
        assert "[skip] seg_01" in out

    def test_retries_on_none_and_succeeds(self, tmp_path, monkeypatch):
        collection = _make_collection(tmp_path / "coll")
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(monkeypatch)
        _patch_load_config(monkeypatch, target_duration_min=None)
        _patch_generate_master(monkeypatch)
        # time.sleep を無効化（リトライ待機を省略）
        monkeypatch.setattr(generate_lyria_master.time, "sleep", lambda _s: None)

        # 1 回目 None、2 回目で成功するパターン (1 セグメントだけ)
        responses = iter([None, b"OK"])
        call_count = {"n": 0}

        def fake_generate(*args, **kwargs):  # noqa: ARG001
            call_count["n"] += 1
            return next(responses)

        monkeypatch.setattr(generate_lyria_master.lyria_client, "generate_music", fake_generate)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "p",
                "--name",
                "retry",
                "--target-duration",
                "2",  # 1 セグメント
                "--padding-min",
                "0",
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 0
        assert call_count["n"] == 2

    def test_max_retries_exceeded_returns_1(self, tmp_path, monkeypatch, capsys):
        collection = _make_collection(tmp_path / "coll")
        _patch_lyria_generate(monkeypatch, payload=None)  # 常に None
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(monkeypatch)
        _patch_load_config(monkeypatch, target_duration_min=None)
        _patch_generate_master(monkeypatch)
        monkeypatch.setattr(generate_lyria_master.time, "sleep", lambda _s: None)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "p",
                "--name",
                "fail",
                "--target-duration",
                "2",
                "--padding-min",
                "0",
                "--max-retries",
                "2",
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 1
        out = capsys.readouterr().out
        # max_retries=2 → 初回 + 2 リトライ = 3 回失敗
        assert "3 回失敗" in out


class TestMasterCombineDelegation:
    """セグメント揃ったら generate_master.generate_master が skill-config 由来の引数で呼ばれる。"""

    def test_invokes_generate_master_with_skill_config_values(self, tmp_path, monkeypatch):
        collection = _make_collection(tmp_path / "coll")
        _patch_lyria_generate(monkeypatch)
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(
            monkeypatch,
            lyria={"model": "lyria-3-pro-preview", "duration_padding_min": 0},
            masterup={"audio": {"crossfade_duration": 2.5, "bitrate": "256k"}},
        )
        _patch_load_config(monkeypatch, target_duration_min=None)
        capture = _patch_generate_master(monkeypatch)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "p",
                "--name",
                "delegate",
                "--target-duration",
                "2",
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 0
        assert capture["args"] == (collection, 2.5, "256k")
        assert capture["kwargs"]["input_exts"] == ("wav",)
        assert capture["kwargs"]["output_ext"] == "wav"


class TestCli:
    """CLI 引数バリデーションと到達経路。"""

    def test_falls_back_to_channel_audio_config(self, tmp_path, monkeypatch):
        # --target-duration 省略時は channel config の audio.target_duration_min を使う
        collection = _make_collection(tmp_path / "coll")
        call_log = _patch_lyria_generate(monkeypatch)
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(monkeypatch, lyria={"model": "lyria-3-pro-preview", "duration_padding_min": 0})
        _patch_load_config(monkeypatch, target_duration_min=6)  # 6 * 60 / 184 = 1.95 → 2
        _patch_generate_master(monkeypatch)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "p",
                "--name",
                "ch",
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 0
        assert len(call_log) == 2

    def test_no_target_duration_anywhere_fails(self, tmp_path, monkeypatch, capsys):
        # --target-duration も channel config も無ければ ValidationError で exit 1
        collection = _make_collection(tmp_path / "coll")
        _patch_lyria_generate(monkeypatch)
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(monkeypatch)
        _patch_load_config(monkeypatch, target_duration_min=None)
        _patch_generate_master(monkeypatch)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "p",
                "--name",
                "x",
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "target_duration_min" in err or "--target-duration" in err

    def test_cli_flags_forwarded_to_lyria(self, tmp_path, monkeypatch):
        # --bpm / --intensity / --mode / --lyrics / --reference-image が generate_music に転送される
        collection = _make_collection(tmp_path / "coll")
        # 参照画像を実体化
        ref = collection / "10-assets"
        ref.mkdir()
        ref_path = ref / "main.png"
        ref_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        call_log = _patch_lyria_generate(monkeypatch)
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(monkeypatch, lyria={"model": "lyria-3-pro-preview", "duration_padding_min": 0})
        _patch_load_config(monkeypatch, target_duration_min=None)
        _patch_generate_master(monkeypatch)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "p",
                "--name",
                "f",
                "--target-duration",
                "2",
                "--bpm",
                "72",
                "--intensity",
                "low",
                "--mode",
                "instrumental",
                "--lyrics",
                "la la la",
                "--reference-image",
                "10-assets/main.png",
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 0
        assert len(call_log) == 1
        entry = call_log[0]
        assert entry["bpm"] == 72
        assert entry["intensity"] == "low"
        assert entry["mode"] == "instrumental"
        assert entry["lyrics"] == "la la la"
        assert entry["reference_image"] == ref_path.resolve()

    def test_missing_reference_image_raises(self, tmp_path, monkeypatch, capsys):
        collection = _make_collection(tmp_path / "coll")
        _patch_lyria_generate(monkeypatch)
        _patch_ffmpeg(monkeypatch)
        _patch_skill_configs(monkeypatch, lyria={"model": "lyria-3-pro-preview", "duration_padding_min": 0})
        _patch_load_config(monkeypatch, target_duration_min=2)
        _patch_generate_master(monkeypatch)

        monkeypatch.setattr(
            "sys.argv",
            [
                "yt-generate-lyria-master",
                "--prompt",
                "p",
                "--name",
                "f",
                "--reference-image",
                "10-assets/missing.png",
                "--collection",
                str(collection),
            ],
        )

        rc = generate_lyria_master.main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "参照画像" in err


class TestSaveInterruptRecovery:
    """#481: WAV 保存 (ffmpeg) 中の Ctrl+C でも支払い済みオーディオを退避する。"""

    def test_keyboard_interrupt_during_save_persists_paid_audio(self, tmp_path, monkeypatch):
        # Given: generate_music は課金済み bytes を返すが、_save_audio_as_wav 中に Ctrl+C
        audio = b"PAID_MP3_BYTES"
        monkeypatch.setattr(generate_lyria_master.lyria_client, "generate_music", lambda *a, **k: audio)

        def _boom(*_a, **_k):
            raise KeyboardInterrupt

        monkeypatch.setattr(generate_lyria_master, "_save_audio_as_wav", _boom)

        seg_path = tmp_path / "coll" / "02-Individual-music" / "01_x.wav"

        # When / Then: 中断は伝播しつつ、支払い済み bytes は退避ファイルに残る
        with pytest.raises(KeyboardInterrupt):
            _generate_one_segment(
                index=1,
                seg_path=seg_path,
                prompt="p",
                model="m",
                reference_image=None,
                bpm=None,
                intensity=None,
                mode=None,
                lyrics=None,
                max_retries=0,
            )

        recovered = list((tmp_path / "tmp" / "lyria-recovered").glob("*.mp3"))
        assert len(recovered) == 1
        assert recovered[0].read_bytes() == audio
