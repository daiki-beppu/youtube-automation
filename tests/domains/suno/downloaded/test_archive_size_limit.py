"""Suno downloaded ZIP の展開サイズ上限テスト。"""

from __future__ import annotations

from zipfile import ZipInfo

import pytest

from youtube_automation.domains.suno.downloaded import archive


def test_multitrack_archive_allows_measured_long_wav_total() -> None:
    """Given 長尺 WAV 20 曲の Studio Multitrack ZIP（実測 3.6 GiB 相当）がある
    When 展開サイズ上限を検査する
    Then 上限内として受理する。
    """
    infos = [ZipInfo(f"track-{index}.wav") for index in range(20)]
    for info in infos:
        info.file_size = 185 * 1024 * 1024

    assert sum(info.file_size for info in infos) > 3.6 * 1024 * 1024 * 1024
    assert archive._zip_within_size_limits(infos)


def test_oversize_message_shows_actual_limit_and_action(capsys: pytest.CaptureFixture[str]) -> None:
    """Given 展開後が上限を超える ZIP がある
    When 展開サイズ上限を検査する
    Then 実サイズ・上限値・分割手順を定数と一致する表記で案内する。
    """
    infos = [ZipInfo(f"oversize-{index}.wav") for index in range(18)]
    for info in infos:
        info.file_size = 490 * 1024 * 1024

    assert not archive._zip_within_size_limits(infos)
    output = capsys.readouterr().out
    assert "実サイズ" in output
    assert f"上限 {archive._ZIP_MAX_TOTAL_SIZE} bytes" in output
    assert f"{archive._ZIP_MAX_TOTAL_SIZE_GIB} GiB を超える場合" in output
    assert "複数バッチ" in output
    assert archive._ZIP_MAX_TOTAL_SIZE_ENV in output


def test_total_size_limit_is_configurable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 全トラックがプロジェクト長にパディングされた Studio Multitrack ZIP（9 GiB 超）がある
    When SUNO_ZIP_MAX_TOTAL_SIZE_GIB で上限を引き上げる
    Then 引き上げた上限内として受理する。
    """
    infos = [ZipInfo(f"track-{index}.wav") for index in range(60)]
    for info in infos:
        info.file_size = 160 * 1024 * 1024
    assert sum(info.file_size for info in infos) > archive._ZIP_MAX_TOTAL_SIZE
    monkeypatch.setenv(archive._ZIP_MAX_TOTAL_SIZE_ENV, "12")

    assert archive._zip_within_size_limits(infos)


@pytest.mark.parametrize("raw", ["large", "0", "-1"])
def test_invalid_total_size_env_fails_loud(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """Given SUNO_ZIP_MAX_TOTAL_SIZE_GIB に非数値または 0 以下が設定されている
    When 展開サイズ上限を検査する
    Then 環境変数名つきで fail-loud する。
    """
    monkeypatch.setenv(archive._ZIP_MAX_TOTAL_SIZE_ENV, raw)

    with pytest.raises(ValueError, match=archive._ZIP_MAX_TOTAL_SIZE_ENV):
        archive._zip_within_size_limits([])
