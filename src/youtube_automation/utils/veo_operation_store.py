"""Veo operation 永続化ストア。

Ctrl+C 中断時に operation_name と入力画像 SHA-256 を <CHANNEL_DIR>/tmp/veo-operations/ に保存し、
同一入力の再実行時に resume できるようにする pure I/O モジュール。google.genai 非依存。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_HASH_LEN = 16
_REQUIRED_KEYS = {"operation_name", "model", "output_path", "input_image_sha256"}


def image_sha256(image_path: Path) -> str:
    """入力画像の内容を識別する SHA-256 ハッシュを返す。"""
    digest = hashlib.sha256()
    with image_path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_channel_root(channel_root: Path | None) -> Path:
    if channel_root is not None:
        return channel_root
    from youtube_automation.utils.config import channel_dir

    return channel_dir()


def state_path(output_path: Path, *, channel_root: Path | None = None) -> Path:
    """output_path に対応する state ファイルパスを返す（決定的）。"""
    root = _resolve_channel_root(channel_root)
    key = hashlib.sha1(str(output_path.resolve()).encode()).hexdigest()[:_HASH_LEN]
    return root / "tmp" / "veo-operations" / f"{key}.json"


def save(
    output_path: Path,
    image_path: Path,
    operation_name: str,
    model: str,
    *,
    channel_root: Path | None = None,
) -> Path:
    """入力画像識別子を含む state を JSON で永続化する（atomic write）。"""
    path = state_path(output_path, channel_root=channel_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "operation_name": operation_name,
        "output_path": str(output_path.resolve()),
        "model": model,
        "input_image_sha256": image_sha256(image_path),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load(output_path: Path, *, channel_root: Path | None = None) -> dict | None:
    """state を読み込む。存在しない / JSON 破損 / 必須キー欠落 / output_path 不一致の場合は None を返す。"""
    path = state_path(output_path, channel_root=channel_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        print(f"  [Warn]   state ファイルが破損しています（無視します）: {path}")
        return None

    # JSON のルートが object でない場合は無効な state
    if not isinstance(data, dict):
        print(f"  [Warn]   state ファイルが object ではありません（削除します）: {path}")
        path.unlink(missing_ok=True)
        return None

    # 必須キー検証
    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        print(f"  [Warn]   state に必須キーが欠落しています {sorted(missing)}（削除します）: {path}")
        path.unlink(missing_ok=True)
        return None

    # 型検証: operation_name, model, output_path, input_image_sha256 は文字列である必要
    if (
        not isinstance(data["operation_name"], str)
        or not isinstance(data["model"], str)
        or not isinstance(data["output_path"], str)
        or not isinstance(data["input_image_sha256"], str)
    ):
        print(
            "  [Warn]   state の operation_name/model/output_path/input_image_sha256 が文字列ではありません"
            f"（削除します）: {path}"
        )
        path.unlink(missing_ok=True)
        return None

    # output_path 整合性検証
    if Path(data["output_path"]).resolve() != output_path.resolve():
        print(f"  [Warn]   state の output_path が不一致です（削除します）: {path}")
        path.unlink(missing_ok=True)
        return None

    return data


def clear(output_path: Path, *, channel_root: Path | None = None) -> None:
    """state ファイルを削除する。存在しない場合は何もしない。"""
    path = state_path(output_path, channel_root=channel_root)
    if path.exists():
        path.unlink()
