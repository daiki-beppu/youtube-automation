"""skill 改名で残る `__pycache__` 残骸 prune の回帰テスト（#4595）。"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.conftest import _prune_stale_skill_bytecode_dirs


def _write(path: Path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_bytecode_only_skill_dir_is_pruned(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _write(skills / "post-publish" / "references" / "__pycache__" / "state.cpython-314.pyc")

    _prune_stale_skill_bytecode_dirs(skills)

    assert not (skills / "post-publish").exists()


def test_skill_dir_with_real_file_is_kept(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _write(skills / "publish" / "SKILL.md", b"---\n")
    _write(skills / "publish" / "references" / "__pycache__" / "state.cpython-314.pyc")

    _prune_stale_skill_bytecode_dirs(skills)

    assert (skills / "publish" / "SKILL.md").is_file()
    assert (skills / "publish" / "references" / "__pycache__").is_dir()


def test_symlink_and_missing_root_are_untouched(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    real = tmp_path / "outside"
    _write(real / "__pycache__" / "state.cpython-314.pyc")
    skills.mkdir()
    (skills / "linked").symlink_to(real)

    _prune_stale_skill_bytecode_dirs(skills)
    _prune_stale_skill_bytecode_dirs(tmp_path / "does-not-exist")

    assert (real / "__pycache__" / "state.cpython-314.pyc").is_file()
    assert (skills / "linked").is_symlink()


def _rglob_raising(error: OSError) -> Callable[[Path, str], Iterator[Path]]:
    def _rglob(self: Path, pattern: str) -> Iterator[Path]:
        raise error

    return _rglob


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("vanished"), NotADirectoryError("replaced"), PermissionError("unreadable")],
)
def test_scan_race_skips_candidate_without_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    """他プロセスの prune による消失・読めないディレクトリは見送り、削除もしない。"""
    skills = tmp_path / "skills"
    _write(skills / "post-publish" / "references" / "__pycache__" / "state.cpython-314.pyc")
    monkeypatch.setattr(Path, "rglob", _rglob_raising(error))

    _prune_stale_skill_bytecode_dirs(skills)

    assert (skills / "post-publish").is_dir()


def test_unexpected_io_error_is_not_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """レース以外の I/O エラーは無言スキップせず伝播させる。"""
    skills = tmp_path / "skills"
    _write(skills / "post-publish" / "references" / "__pycache__" / "state.cpython-314.pyc")
    monkeypatch.setattr(Path, "rglob", _rglob_raising(OSError("I/O error")))

    with pytest.raises(OSError, match="I/O error"):
        _prune_stale_skill_bytecode_dirs(skills)
