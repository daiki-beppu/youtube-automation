"""``infrastructure/media`` の video task store が共有する state 永続化ヘルパー。

provider ごとの store は保存ディレクトリ名と必須キー集合だけが異なる。原子的な
書き込みと、symlink 拒否 → 存在確認 → JSON parse → 必須キー・型検証 →
``output_path`` 整合という fail-closed の読み出し手順をここに集約し、store が
増えるたびに同じ分岐を複製しない。

共有 state の型契約は ``duration_seconds`` だけが int で、他の必須キーはすべて
str である。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_HASH_LEN = 16
_INTEGER_KEYS = frozenset({"duration_seconds"})


def sha256_file(path: Path) -> str:
    """入力ファイルの内容を識別する SHA-256 を返す。"""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_channel_root(channel_root: Path | None) -> Path:
    """明示指定がなければ設定の channel root へ解決する。"""
    if channel_root is not None:
        return channel_root
    from youtube_automation.configuration import channel_dir

    return channel_dir()


def state_file(output_path: Path, *, root: Path, directory: str) -> Path:
    """output_path に対応する state ファイルパスを決定的に返す。"""
    key = hashlib.sha1(str(output_path.resolve()).encode()).hexdigest()[:_HASH_LEN]
    return root / "tmp" / directory / f"{key}.json"


def write_state(path: Path, data: dict[str, object]) -> None:
    """同じディレクトリの一時ファイル経由で state を原子的に置き換える。"""
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def load_state(path: Path, output_path: Path, *, required_keys: frozenset[str]) -> dict[str, object] | None:
    """有効な state を返し、信頼できない state は削除して None を返す。"""
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return None
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return None
    if not _is_trusted_state(value, output_path, required_keys):
        path.unlink(missing_ok=True)
        return None
    return value


def _is_trusted_state(value: object, output_path: Path, required_keys: frozenset[str]) -> bool:
    if not isinstance(value, dict) or required_keys - value.keys():
        return False
    if not all(isinstance(value[key], str) for key in required_keys - _INTEGER_KEYS):
        return False
    for key in required_keys & _INTEGER_KEYS:
        number = value[key]
        if not isinstance(number, int) or isinstance(number, bool):
            return False
    return Path(value["output_path"]).resolve() == output_path.resolve()
