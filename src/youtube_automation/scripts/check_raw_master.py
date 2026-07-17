#!/usr/bin/env python3
"""workflow-state.json::assets.raw_master と 01-master/ 実ファイルの整合チェック。

`/masterup` のフォールバック運用（Suno 手動 DL → `yt-generate-master` 直接実行）では
`01-master/master.mp3` は生成されるが `assets.raw_master` は自動更新されない。
本 CLI は記録値と実ファイルを突合し、不整合を検知・警告する（#1668）。

- 既定（dry-run）: 検知のみ。workflow-state.json には一切書き込まない
- `--apply`: 検知した候補ファイル名で `assets.raw_master` / `updated_at` を原子的に更新する。
  承認ゲート（AskUserQuestion 等）は呼び出し側 skill の責務で、本 CLI は対話しない

Exit code:
    0: 整合（または --apply で更新完了）
    1: 実行エラー（workflow-state.json 破損など）
    2: 不整合を検知（未解消のまま。--apply でも候補が無く更新できなかった場合を含む)

Usage:
    yt-raw-master-check                   # CWD がコレクションディレクトリ
    yt-raw-master-check <collection-path>
    yt-raw-master-check <collection-path> --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from youtube_automation.utils.collection_paths import (
    CollectionPaths,
    resolve_collection_dir,
)
from youtube_automation.utils.exceptions import ValidationError

# 判定結果の status 値。
STATUS_CONSISTENT = "consistent"
STATUS_MISMATCH = "mismatch"


@dataclass(frozen=True)
class RawMasterCheckResult:
    """raw_master 突合チェックの判定結果。

    Attributes:
        status: ``consistent`` / ``mismatch``
        recorded: workflow-state.json::assets.raw_master の記録値（未設定は None）
        candidate: 実ファイルから推定した更新候補ファイル名（推定不能は None）
        message: ユーザー向け説明（警告表示にそのまま使える日本語文）
    """

    status: str
    recorded: str | None
    candidate: str | None
    message: str

    @property
    def is_consistent(self) -> bool:
        return self.status == STATUS_CONSISTENT


def _load_state(workflow_state_path: Path) -> dict:
    """workflow-state.json を dict として読み込む。破損時は ValidationError。"""
    if not workflow_state_path.is_file():
        raise ValidationError(f"workflow-state.json が見つかりません: {workflow_state_path}")

    try:
        state = json.loads(workflow_state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValidationError(f"workflow-state.json のパースに失敗: {e}") from e

    if not isinstance(state, dict):
        raise ValidationError("workflow-state.json の root は object である必要があります")
    return state


def _recorded_raw_master(state: dict) -> str | None:
    """state から assets.raw_master の記録値を取り出す（型不正は ValidationError）。"""
    assets = state.get("assets")
    if assets is None:
        return None
    if not isinstance(assets, dict):
        raise ValidationError("workflow-state.json::assets は object である必要があります")

    raw_master = assets.get("raw_master")
    if raw_master is None:
        return None
    if not isinstance(raw_master, str) or not raw_master:
        raise ValidationError(f"workflow-state.json::assets.raw_master が不正です: {raw_master!r}")
    if raw_master != Path(raw_master).name:
        raise ValidationError(f"workflow-state.json::assets.raw_master はファイル名のみ指定してください: {raw_master}")
    return raw_master


def check_raw_master(collection_dir: Path) -> RawMasterCheckResult:
    """assets.raw_master と 01-master/ の実ファイルを突合して判定を返す。

    候補ファイルの探索は既存プリミティブ ``CollectionPaths.find_master_audio()``
    （01-master/ の ``*.mp3`` 先頭）に委ねる。``yt-generate-master`` の出力は常に
    ``master.mp3`` のため、フォールバック運用の取りこぼしはこれで検知できる。
    雨レイヤー後処理（``yt-apply-rain-layers``）は CLI 自身が state を更新するため
    本チェックの対象外。
    """
    paths = CollectionPaths(collection_dir)
    state = _load_state(paths.workflow_state_path)
    recorded = _recorded_raw_master(state)

    candidate_path = paths.find_master_audio()
    candidate = candidate_path.name if candidate_path is not None else None

    if recorded is not None:
        if (paths.master_dir / recorded).is_file():
            return RawMasterCheckResult(
                status=STATUS_CONSISTENT,
                recorded=recorded,
                candidate=None,
                message=f"assets.raw_master = {recorded} は実ファイルと整合しています",
            )
        # 記録値のファイルが消えている。候補があれば付け替えを提案する
        detail = f"候補: {candidate}" if candidate is not None else "01-master/ に更新候補もありません"
        return RawMasterCheckResult(
            status=STATUS_MISMATCH,
            recorded=recorded,
            candidate=candidate,
            message=(f"assets.raw_master = {recorded} が 01-master/ に存在しません（{detail}）。更新しますか"),
        )

    if candidate is not None:
        return RawMasterCheckResult(
            status=STATUS_MISMATCH,
            recorded=None,
            candidate=candidate,
            message=(
                f"01-master/{candidate} が存在しますが assets.raw_master が未記録です"
                f"（yt-generate-master 直接実行の取りこぼしの可能性）。{candidate} で更新しますか"
            ),
        )

    return RawMasterCheckResult(
        status=STATUS_CONSISTENT,
        recorded=None,
        candidate=None,
        message="raw master は未生成です（assets.raw_master = null / 01-master/ に音源なし）",
    )


def apply_raw_master(collection_dir: Path, new_name: str) -> None:
    """assets.raw_master と updated_at を原子的に更新する。

    書き込みは同一ディレクトリの一時ファイル + ``os.replace`` で行い、
    途中失敗で workflow-state.json が壊れないことを保証する（非破壊）。
    """
    paths = CollectionPaths(collection_dir)
    if not (paths.master_dir / new_name).is_file():
        raise ValidationError(f"更新候補が 01-master/ に存在しません: {new_name}")

    state = _load_state(paths.workflow_state_path)
    assets = state.setdefault("assets", {})
    if not isinstance(assets, dict):
        raise ValidationError("workflow-state.json::assets は object である必要があります")

    assets["raw_master"] = new_name
    state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=paths.workflow_state_path.parent,
        prefix=".workflow-state.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_name, paths.workflow_state_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="workflow-state.json::assets.raw_master と 01-master/ 実ファイルの整合チェック",
    )
    parser.add_argument(
        "collection",
        nargs="?",
        help="コレクションディレクトリ (省略時は CWD)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="不整合検知時に assets.raw_master / updated_at を候補ファイル名で更新する",
    )
    args = parser.parse_args()

    try:
        collection_dir = resolve_collection_dir(args.collection)
        result = check_raw_master(collection_dir)

        if result.is_consistent:
            print(f"OK: {result.message}")
            return 0

        if not args.apply:
            print(f"WARNING: {result.message}", file=sys.stderr)
            print("(更新する場合は --apply を付けて再実行してください)", file=sys.stderr)
            return 2

        if result.candidate is None:
            print(f"WARNING: {result.message}", file=sys.stderr)
            print(
                "ERROR: 更新候補が無いため --apply できません。01-master/ の実ファイルを確認してください",
                file=sys.stderr,
            )
            return 2

        apply_raw_master(collection_dir, result.candidate)
        print(f"Updated: assets.raw_master = {result.candidate} (updated_at も更新)")
        return 0
    except ValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
