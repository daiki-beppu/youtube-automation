"""experiment と insight の 2 ファイル更新を journal 付きで一体 commit する。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

from youtube_automation.core.errors import ValidationError

JOURNAL_NAME = ".experiment-judge-transaction.json"


def _bytes(path: Path) -> bytes:
    if not path.exists():
        return b""
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise ValidationError(f"JSONL を確認できません: {path}") from error
    if not stat.S_ISREG(mode):
        raise ValidationError(f"JSONL は regular file である必要があります: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValidationError(f"JSONL を読めません: {path}") from error


def rewrite_jsonl(original: bytes, replacements: dict[str, dict[str, object]]) -> bytes:
    found: set[str] = set()
    output: list[bytes] = []
    for raw_line in original.splitlines(keepends=True):
        content = raw_line.rstrip(b"\r\n")
        if not content.strip():
            output.append(raw_line)
            continue
        entry = json.loads(content)
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        replacement = replacements.get(entry_id) if isinstance(entry_id, str) else None
        if replacement is None:
            output.append(raw_line)
            continue
        newline = raw_line[len(content) :]
        output.append(
            json.dumps(replacement, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            + newline
        )
        found.add(entry_id)
    if found != replacements.keys():
        raise ValidationError(f"experiment replacement target が不足しています: {sorted(replacements.keys() - found)}")
    return b"".join(output)


def append_jsonl(original: bytes, records: list[dict[str, object]]) -> bytes:
    if not records:
        return original
    separator = b"" if not original or original.endswith(b"\n") else b"\n"
    encoded = b"".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        for record in records
    )
    return original + separator + encoded


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _temp_file(destination: Path, content: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if destination.exists():
            os.chmod(temporary, stat.S_IMODE(destination.stat().st_mode))
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _write_journal(path: Path, payload: dict[str, object]) -> None:
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    temporary = _temp_file(path, content)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _payload(
    paths: tuple[Path, Path],
    before: tuple[bytes, bytes],
    after: tuple[bytes, bytes],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "files": [
            {
                "path": str(path.resolve()),
                "before_sha256": _sha256(old),
                "after_sha256": _sha256(new),
                "after_base64": base64.b64encode(new).decode("ascii"),
            }
            for path, old, new in zip(paths, before, after, strict=True)
        ],
    }


def _journal_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"experiment judge journal を読めません: {path}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"experiment judge journal が不正です: {path}")
    return value


def recover(journal_path: Path, expected_paths: tuple[Path, Path]) -> None:
    if not journal_path.exists():
        return
    payload = _journal_object(journal_path)
    files = payload.get("files")
    if payload.get("schema_version") != 1 or not isinstance(files, list) or len(files) != 2:
        raise ValidationError(f"experiment judge journal が不正です: {journal_path}")
    by_path = {str(path.resolve()): path for path in expected_paths}
    plans: list[tuple[Path, bytes]] = []
    for record in files:
        if not isinstance(record, dict) or record.get("path") not in by_path:
            raise ValidationError(f"experiment judge journal の path が不正です: {journal_path}")
        destination = by_path[str(record["path"])]
        try:
            after = base64.b64decode(str(record["after_base64"]), validate=True)
        except (KeyError, ValueError, binascii.Error) as error:
            raise ValidationError(f"experiment judge journal の payload が不正です: {journal_path}") from error
        if _sha256(after) != record.get("after_sha256"):
            raise ValidationError(f"experiment judge journal の after hash が不正です: {destination}")
        if _sha256(_bytes(destination)) not in {record.get("before_sha256"), record.get("after_sha256")}:
            raise ValidationError(f"experiment judge recovery conflict: {destination}")
        plans.append((destination, after))
    for destination, after in plans:
        if _bytes(destination) == after:
            continue
        temporary = _temp_file(destination, after)
        try:
            _replace_file(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    journal_path.unlink()


def commit_pair(
    paths: tuple[Path, Path],
    before: tuple[bytes, bytes],
    after: tuple[bytes, bytes],
) -> None:
    journal_path = paths[0].parent / JOURNAL_NAME
    temporaries: list[Path] = []
    try:
        for path, content in zip(paths, after, strict=True):
            temporaries.append(_temp_file(path, content))
        _write_journal(journal_path, _payload(paths, before, after))
        for temporary, destination in zip(temporaries, paths, strict=True):
            _replace_file(temporary, destination)
        journal_path.unlink()
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
