from zipfile import ZipInfo

from youtube_automation.domains.suno.downloaded import archive


def test_multitrack_archive_allows_36_gib() -> None:
    infos = [ZipInfo(f"track-{index}.wav") for index in range(20)]
    for info in infos:
        info.file_size = 190 * 1024 * 1024

    assert archive._zip_within_size_limits(infos)


def test_oversize_message_shows_actual_limit_and_action(capsys) -> None:
    infos = [ZipInfo(f"oversize-{index}.wav") for index in range(18)]
    for info in infos:
        info.file_size = 490 * 1024 * 1024

    assert not archive._zip_within_size_limits(infos)
    output = capsys.readouterr().out
    assert "実サイズ" in output
    assert "上限" in output
    assert "複数バッチ" in output
