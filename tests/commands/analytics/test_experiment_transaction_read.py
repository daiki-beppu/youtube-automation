"""判定と recovery が共有する JSONL reader のファイル境界。"""

from pathlib import Path

import pytest

from youtube_automation.commands.analytics.experiment_transaction import read_jsonl_bytes
from youtube_automation.core.errors import ValidationError


def test_missing_jsonl_is_an_empty_history(tmp_path: Path) -> None:
    assert read_jsonl_bytes(tmp_path / "missing.jsonl") == b""


def test_preserves_history_bytes_including_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    content = '{"title":"検証"}\r\n\n'.encode()
    path.write_bytes(content)

    assert read_jsonl_bytes(path) == content


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_rejects_non_regular_histories(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "history.jsonl"
    if kind == "directory":
        path.mkdir()
    else:
        target = tmp_path / "target.jsonl"
        target.write_bytes(b"{}\n")
        path.symlink_to(target)

    with pytest.raises(ValidationError, match="regular file"):
        read_jsonl_bytes(path)


def test_read_failure_is_a_domain_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "history.jsonl"
    path.write_bytes(b"{}\n")

    def denied(_path: Path) -> bytes:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(ValidationError, match="JSONL を読めません") as error:
        read_jsonl_bytes(path)

    assert isinstance(error.value.__cause__, PermissionError)
