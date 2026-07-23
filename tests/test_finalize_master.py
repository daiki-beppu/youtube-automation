"""finalize_master の純粋関数 (build_filter / find_ambient_layers / _parse_loudnorm_json) テスト。

仕様: `branding/rain_layers/rain_*.wav` を N-layer 重ねてマスター音源にレイヤーする
filter_complex 文字列の生成、雨音ファイル探索、loudnorm pass1 出力の JSON 抽出を
純粋関数として分離検証する (subprocess は test_finalize_master_main.py 側で扱う)。
"""

from __future__ import annotations

import pytest

from youtube_automation.scripts.finalize_master import (
    _parse_loudnorm_json,
    build_filter,
    find_ambient_layers,
)
from youtube_automation.utils.exceptions import ValidationError

# build_filter のデフォルト引数 (実装側 _DEFAULT_* と独立に固定値で渡す。
# 実装定数とテスト期待値の二重管理を避けるため、build_filter 自体には
# defaults フォールバックは持たせず、引数で明示的に渡す前提)。
_DEFAULT_LOUDNORM = {"I": -14.0, "LRA": 11.0, "TP": -1.5}
_DEFAULT_VOLUME_DB = -19.0
_DEFAULT_FADEIN_S = 0.5

# pass2 用 measured 値 (ffmpeg loudnorm JSON 出力相当の文字列値)。
_PASS2_MEASURED = {
    "input_i": "-23.0",
    "input_lra": "10.5",
    "input_tp": "-2.1",
    "input_thresh": "-33.0",
    "target_offset": "0.5",
}


class TestFindRainLayers:
    """`branding/rain_layers/rain_*.wav` 探索のゲート挙動。"""

    def test_returns_empty_when_branding_rain_layers_dir_missing(self, tmp_path):
        # Given: branding/rain_layers/ ディレクトリ自体が存在しない (未対応チャンネル)

        # When
        result = find_ambient_layers(tmp_path)

        # Then: 空リスト (pass-through gate を通すための前提)
        assert result == []

    def test_returns_empty_when_dir_exists_but_no_rain_wav(self, tmp_path):
        # Given: ディレクトリは存在するが rain_*.wav が 1 件もない
        rain_dir = tmp_path / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True)
        (rain_dir / "README.md").write_text("placeholder")

        # When
        result = find_ambient_layers(tmp_path)

        # Then: 空リスト (ディレクトリだけ作ったチャンネルでも no-op)
        assert result == []

    def test_returns_rain_wav_files_in_sorted_order(self, tmp_path):
        # Given: rain_*.wav を逆順に作成 (sorted で 001/002/003 の順になることを検証)
        rain_dir = tmp_path / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True)
        for name in ["rain_003.wav", "rain_001.wav", "rain_002.wav"]:
            (rain_dir / name).write_bytes(b"\x00")

        # When
        result = find_ambient_layers(tmp_path)

        # Then: 決定論的にソート済み (ffmpeg 入力順の再現性担保)
        names = [p.name for p in result]
        assert names == ["rain_001.wav", "rain_002.wav", "rain_003.wav"]

    def test_ignores_non_matching_files(self, tmp_path):
        # Given: glob `rain_*.wav` の境界値 (大文字 / 拡張子違い / prefix 違い)
        rain_dir = tmp_path / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True)
        (rain_dir / "rain_001.wav").write_bytes(b"\x00")
        (rain_dir / "RAIN_002.WAV").write_bytes(b"\x00")  # 大文字拡張子
        (rain_dir / "rain_003.mp3").write_bytes(b"\x00")  # 拡張子違い
        (rain_dir / "rainbow_001.wav").write_bytes(b"\x00")  # prefix 違い

        # When
        result = find_ambient_layers(tmp_path)

        # Then: 完全一致した rain_001.wav のみ
        names = [p.name for p in result]
        assert names == ["rain_001.wav"]


class TestBuildFilter:
    """filter_complex 文字列の構造契約 (N=1 / N=多 / pass1 / pass2)。"""

    def test_single_layer_pass1_omits_intermediate_amix(self):
        # Given: N=1, measured=None (pass1) — 中間 amix は不要

        # When
        result = build_filter(
            n_rain=1,
            volume_db=_DEFAULT_VOLUME_DB,
            fadein_s=_DEFAULT_FADEIN_S,
            loudnorm=_DEFAULT_LOUDNORM,
            measured=None,
        )

        # Then
        # 中間 [rainmix] ラベルは出ない (N=1 では使わない)
        assert "[rainmix]" not in result
        # rain layer ラベル [r0] が直接最終 mix の入力になる
        assert "[0:a][r0]amix=inputs=2:duration=first:normalize=0[mixed]" in result
        # aloop は 1 個だけ (rain idx=1)
        assert result.count("aloop=") == 1
        # loudnorm は pass1 形式 (json print_format)
        assert "print_format=json" in result
        # 最終ラベルは [aout]
        assert result.endswith("[aout]")

    def test_three_layers_pass1_includes_intermediate_amix(self):
        # Given: N=3, measured=None — 中間 amix で rain 群をミックス

        # When
        result = build_filter(
            n_rain=3,
            volume_db=_DEFAULT_VOLUME_DB,
            fadein_s=_DEFAULT_FADEIN_S,
            loudnorm=_DEFAULT_LOUDNORM,
            measured=None,
        )

        # Then
        # aloop チェーン × 3 (idx 1,2,3 → r0,r1,r2)
        assert result.count("aloop=") == 3
        assert "[r0]" in result
        assert "[r1]" in result
        assert "[r2]" in result
        # 中間 amix=inputs=3:normalize=0[rainmix]
        assert "[r0][r1][r2]amix=inputs=3:normalize=0[rainmix]" in result
        # 最終 mix は [0:a][rainmix] を 2-input で合成
        assert "[0:a][rainmix]amix=inputs=2:duration=first:normalize=0[mixed]" in result

    def test_pass1_omits_measured_keys_and_uses_json_format(self):
        # Given: pass1 (measured=None) — measure 専用、apply パラメータは未確定

        # When
        result = build_filter(
            n_rain=1,
            volume_db=_DEFAULT_VOLUME_DB,
            fadein_s=_DEFAULT_FADEIN_S,
            loudnorm=_DEFAULT_LOUDNORM,
            measured=None,
        )

        # Then
        # measured_* / linear=true は出ない (pass2 専用)
        assert "measured_I" not in result
        assert "measured_LRA" not in result
        assert "measured_TP" not in result
        assert "measured_thresh" not in result
        assert "linear=true" not in result
        # print_format=json で機械可読出力を要求
        assert "print_format=json" in result
        assert "print_format=summary" not in result

    def test_pass2_includes_all_measured_keys_and_linear_true(self):
        # Given: pass2 (measured dict) — pass1 で測った値を fold-in して apply

        # When
        result = build_filter(
            n_rain=1,
            volume_db=_DEFAULT_VOLUME_DB,
            fadein_s=_DEFAULT_FADEIN_S,
            loudnorm=_DEFAULT_LOUDNORM,
            measured=_PASS2_MEASURED,
        )

        # Then: 全 measured キー + linear=true + summary print_format
        assert "measured_I=-23.0" in result
        assert "measured_LRA=10.5" in result
        assert "measured_TP=-2.1" in result
        assert "measured_thresh=-33.0" in result
        assert "offset=0.5" in result
        assert "linear=true" in result
        assert "print_format=summary" in result
        assert "print_format=json" not in result

    def test_volume_db_and_fadein_s_applied_to_each_aloop_layer(self):
        # Given: 設定値が全 rain layer の aloop チェーンに折り込まれる
        result = build_filter(
            n_rain=2,
            volume_db=-12.5,
            fadein_s=1.25,
            loudnorm=_DEFAULT_LOUDNORM,
            measured=None,
        )

        # Then: 各 layer に同じ volume_db / fadein_s が入る
        assert result.count("volume=-12.5dB") == 2
        assert result.count("afade=t=in:st=0:d=1.25") == 2


# ffmpeg pass1 stderr のサンプル (前置き + 末尾 JSON ブロック)。
# `_parse_loudnorm_json` が rfind('{')/rfind('}') で末尾 JSON を抽出できることを検証する。
_PASS1_STDERR_SAMPLE = """\
ffmpeg version N-12345-g1234567 Copyright (c) 2000-2025 the FFmpeg developers
[Parsed_loudnorm_0 @ 0x7fbeefdeadbf]
{
    "input_i" : "-23.0",
    "input_tp" : "-2.1",
    "input_lra" : "10.5",
    "input_thresh" : "-33.0",
    "output_i" : "-14.00",
    "output_tp" : "-1.50",
    "output_lra" : "5.20",
    "output_thresh" : "-24.00",
    "normalization_type" : "dynamic",
    "target_offset" : "0.5"
}
"""


class TestParseLoudnormJson:
    """ffmpeg pass1 stderr 末尾の loudnorm JSON ブロック抽出。"""

    def test_extracts_last_json_block_with_ffmpeg_preamble(self):
        # Given: ffmpeg バナー + parsed_loudnorm 行 + 末尾 JSON ブロック

        # When
        result = _parse_loudnorm_json(_PASS1_STDERR_SAMPLE)

        # Then: build_filter が pass2 で参照する全キーが拾える
        assert result["input_i"] == "-23.0"
        assert result["input_lra"] == "10.5"
        assert result["input_tp"] == "-2.1"
        assert result["input_thresh"] == "-33.0"
        assert result["target_offset"] == "0.5"

    def test_raises_validation_error_when_no_json_block(self):
        # Given: loudnorm 出力が存在しない異常 stderr (ffmpeg 失敗時など)
        stderr = "ffmpeg failed: no loudnorm output produced\n"

        # When / Then: ValidationError で fail-fast (pass2 を起動しない)
        with pytest.raises(ValidationError):
            _parse_loudnorm_json(stderr)
