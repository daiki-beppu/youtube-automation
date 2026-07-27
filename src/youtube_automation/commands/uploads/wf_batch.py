#!/usr/bin/env python3
"""複数 collection を /wf-next 相当の CLI チェーンで直列に自動進行させる batch orchestrator（#1667）。

`collections/planning/` 配下を走査し、以下の条件を満たす collection を対象とする:

- ``phase == "prepared"``
- ``assets.music_prompts == true``
- ``assets.raw_master == null``
- ``planning.music.suno_playlist_url`` 記録済み
- ``02-Individual-music/`` に音声ファイル（mp3 / m4a / wav）が 1 件以上存在

対象 collection を 1 件ずつ直列処理し、1 件が失敗しても後続の処理を継続する。
各 collection の処理は /wf-next の状態遷移を非対話で辿る CLI チェーン:

1. ``yt-collection-preflight``（骨格検証）
2. ``yt-suno-select-tracks``（採用トラック選別）
3. ``yt-generate-master``（raw master 生成）
4. ``yt-raw-master-check --apply``（``assets.raw_master`` 記録）
5. ``master_audio_transition.py``（2-B: prepared → mastered。``adopted`` 以外は失敗扱い）
6. ``generate_videos.sh``（マスター動画生成）→ ``assets.master_video`` / ``phase: publishing`` 記録
7. ``yt-upload-collection``（アップロード + tracking + planning → live 移行を一体実行）

`workflow.wf_next.skip_*_approval` が false のチャンネルでは非対話で承認を
処理できないため fail-loud で停止する（``/wf-next`` を使う）。

実行結果は ``reports/wf-batch-<timestamp>/summary.json`` と per-collection の
``<slug>.log`` に出力する。

Usage:
    uv run yt-wf-batch --dry-run          # 対象一覧と対象外警告のみ表示（実処理なし）
    uv run yt-wf-batch                    # 対象全件を直列処理
    uv run yt-wf-batch --only slug1,slug2 # 対象を slug で絞り込み
    uv run yt-wf-batch --from slug        # 指定 slug 以降から再開
    uv run yt-wf-batch --limit 2          # 先頭 N 件だけ試運転

Exit codes:
    0: 全対象成功（対象 0 件・--dry-run 含む）
    1: 実行エラー（設定不備・引数エラー・承認ゲート有効）
    2: 1 件以上の collection が失敗（後続は継続済み）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.infrastructure.errors import ConfigError, ValidationError
from youtube_automation.utils.collection_paths import CollectionPaths

# 02-Individual-music/ のダウンロード済み判定に使う音声拡張子（/wf-next Suno パスと同一）。
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav")

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

# master_audio_transition.py が state を更新して mastered へ進めたことを示す action 値。
TRANSITION_ACTION_ADOPTED = "adopted"


@dataclass(frozen=True)
class WfBatchTarget:
    """batch 処理対象の collection。slug はディレクトリ名そのもの。"""

    slug: str
    path: Path


@dataclass(frozen=True)
class ExcludedCollection:
    """対象条件を満たさず警告表示する collection。"""

    slug: str
    reason: str


@dataclass(frozen=True)
class WfNextSettings:
    """batch 実行に影響する workflow.wf_next 設定のスナップショット。"""

    skip_manual_mastering: bool
    skip_audio_approval: bool
    skip_upload_approval: bool


@dataclass
class CollectionOutcome:
    """1 collection の処理結果（summary.json の results entry になる）。"""

    slug: str
    status: str
    error: str | None = None
    video_id: str | None = None
    video_url: str | None = None
    live_path: str | None = None

    def to_json(self) -> dict:
        entry: dict = {"slug": self.slug, "status": self.status}
        if self.status == STATUS_SUCCESS:
            entry["video_id"] = self.video_id
            entry["video_url"] = self.video_url
            entry["live_path"] = self.live_path
        else:
            entry["error"] = self.error
        return entry


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


def _write_state(workflow_state_path: Path, state: dict) -> None:
    """workflow-state.json を同一ディレクトリの一時ファイル + os.replace で原子的に更新する。"""
    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=workflow_state_path.parent,
        prefix=".workflow-state.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_name, workflow_state_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _has_downloaded_audio(music_dir: Path) -> bool:
    if not music_dir.is_dir():
        return False
    return any(p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS for p in music_dir.iterdir())


def discover_targets(planning_root: Path) -> tuple[list[WfBatchTarget], list[ExcludedCollection]]:
    """collections/planning/ を走査し、batch 対象と対象外（警告付き）を返す。

    対象条件（#1667）: phase=prepared / assets.music_prompts=true / assets.raw_master=null /
    planning.music.suno_playlist_url 記録済み / 02-Individual-music/ に音声あり。
    prepared 以外のフェーズや raw_master 記録済み（進行中）の collection は警告なしで
    スキップする（/wf-next で個別に進める領域のため）。
    """
    targets: list[WfBatchTarget] = []
    excluded: list[ExcludedCollection] = []
    if not planning_root.is_dir():
        return targets, excluded

    for coll in sorted(p for p in planning_root.iterdir() if p.is_dir()):
        state_path = coll / "workflow-state.json"
        if not state_path.is_file():
            continue
        try:
            state = _load_state(state_path)
        except ValidationError as e:
            excluded.append(ExcludedCollection(coll.name, f"workflow-state.json を読めません: {e}"))
            continue

        assets = state.get("assets")
        if not isinstance(assets, dict):
            excluded.append(ExcludedCollection(coll.name, "workflow-state.json::assets が object ではありません"))
            continue

        if state.get("phase") != "prepared":
            continue
        if assets.get("music_prompts") is not True:
            continue
        if assets.get("raw_master") is not None:
            continue

        planning = state.get("planning")
        music = planning.get("music") if isinstance(planning, dict) else None
        url = music.get("suno_playlist_url") if isinstance(music, dict) else None
        has_url = isinstance(url, str) and bool(url.strip())
        has_audio = _has_downloaded_audio(coll / "02-Individual-music")

        if has_url and has_audio:
            targets.append(WfBatchTarget(slug=coll.name, path=coll))
            continue

        reasons = []
        if not has_url:
            reasons.append("planning.music.suno_playlist_url が未記録です")
        if not has_audio:
            reasons.append("02-Individual-music/ に音声ファイルがありません（未ダウンロード）")
        excluded.append(ExcludedCollection(coll.name, " / ".join(reasons)))

    return targets, excluded


def select_targets(
    targets: list[WfBatchTarget],
    only: list[str] | None = None,
    from_slug: str | None = None,
    limit: int | None = None,
) -> list[WfBatchTarget]:
    """--only / --from / --limit を discover 結果へ順に適用する。"""
    selected = list(targets)

    if only:
        known = {t.slug for t in selected}
        unknown = [s for s in only if s not in known]
        if unknown:
            raise ValidationError(f"--only 指定の slug が対象一覧にありません: {', '.join(unknown)}")
        wanted = set(only)
        selected = [t for t in selected if t.slug in wanted]

    if from_slug is not None:
        slugs = [t.slug for t in selected]
        if from_slug not in slugs:
            raise ValidationError(f"--from 指定の slug が対象一覧にありません: {from_slug}")
        selected = selected[slugs.index(from_slug) :]

    if limit is not None:
        if limit < 1:
            raise ValidationError("--limit は 1 以上を指定してください")
        selected = selected[:limit]

    return selected


def _wf_next_settings() -> WfNextSettings:
    wf_next = load_config().workflow.wf_next
    return WfNextSettings(
        skip_manual_mastering=wf_next.skip_manual_mastering,
        skip_audio_approval=wf_next.skip_audio_approval,
        skip_upload_approval=wf_next.skip_upload_approval,
    )


def _skill_reference(relative: str) -> Path:
    """チャンネルへ sync 済みの skill reference script を解決する。"""
    path = Path(channel_dir()) / ".claude" / "skills" / relative
    if not path.is_file():
        raise ValidationError(
            f"skill reference script が見つかりません: {path}（`uv run yt-skills sync` 済みか確認してください）"
        )
    return path


def _run_command(cmd: list[str], log_path: Path, cwd: Path) -> tuple[int, str]:
    """コマンドを実行し、stdout+stderr を log へ追記して (returncode, output) を返す。"""
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {' '.join(cmd)}\n")
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        output = proc.stdout or ""
        code = proc.returncode
    except OSError as e:
        output = f"[wf-batch] コマンド起動に失敗: {e}\n"
        code = 127
    with log_path.open("a", encoding="utf-8") as log:
        log.write(output)
        log.write(f"[wf-batch] exit {code}\n")
    return code, output


def _parse_transition_action(output: str) -> str:
    """master_audio_transition.py の stdout（1 行 JSON）から action を取り出す。"""
    for line in reversed(output.strip().splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        action = payload.get("action")
        if isinstance(action, str):
            return action
    return "unknown"


def _record_master_video(collection_dir: Path) -> str:
    """動画生成後の state 更新（assets.master_video / phase: publishing / updated_at）。"""
    paths = CollectionPaths(collection_dir)
    video = paths.find_master_video()
    if video is None:
        raise ValidationError("01-master/ にマスター動画 (*.mp4) が生成されていません")

    state = _load_state(paths.workflow_state_path)
    assets = state.setdefault("assets", {})
    if not isinstance(assets, dict):
        raise ValidationError("workflow-state.json::assets は object である必要があります")
    assets["master_video"] = video.name
    state["phase"] = "publishing"
    state["updated_at"] = _utc_now()
    _write_state(paths.workflow_state_path, state)
    return video.name


def _verify_live_migration(channel_root: Path, slug: str) -> tuple[str, str, Path]:
    """upload 後の live 移行と upload.video_id / video_url の記録を検証する。"""
    live_dir = channel_root / "collections" / "live" / slug
    state_path = live_dir / "workflow-state.json"
    if not state_path.is_file():
        raise ValidationError(f"collections/live/{slug}/workflow-state.json が見つかりません（live 移行が未完了）")

    state = _load_state(state_path)
    upload = state.get("upload")
    if not isinstance(upload, dict):
        raise ValidationError("workflow-state.json::upload が記録されていません（アップロード未完了）")
    video_id = upload.get("video_id")
    if not isinstance(video_id, str) or not video_id:
        raise ValidationError("workflow-state.json::upload.video_id が記録されていません（アップロード未完了）")
    video_url = upload.get("video_url")
    if not isinstance(video_url, str) or not video_url:
        video_url = f"https://youtu.be/{video_id}"
    return video_id, video_url, live_dir


def process_collection(
    target: WfBatchTarget,
    settings: WfNextSettings,
    log_path: Path,
    channel_root: Path,
) -> CollectionOutcome:
    """1 collection を prepared → complete まで非対話で進める。失敗時は途中で打ち切る。"""
    transition_script = _skill_reference("wf-next/references/master_audio_transition.py")
    videos_script = _skill_reference("videoup/references/generate_videos.sh")
    collection = str(target.path)

    def _failed(step: str, detail: str) -> CollectionOutcome:
        return CollectionOutcome(
            slug=target.slug,
            status=STATUS_FAILED,
            error=f"step {step}: {detail}（詳細: {log_path.name}）",
        )

    # 1-4. 骨格検証 → 選曲 → raw master 生成 → assets.raw_master 記録
    for step, cmd in (
        ("collection-preflight", ["yt-collection-preflight", collection]),
        ("suno-select-tracks", ["yt-suno-select-tracks", collection]),
        ("generate-master", ["yt-generate-master", collection]),
        ("raw-master-check", ["yt-raw-master-check", collection, "--apply"]),
    ):
        code, _ = _run_command(cmd, log_path, channel_root)
        if code != 0:
            return _failed(step, f"exit {code}")

    # 5. 2-B: prepared → mastered（承認ゲート無効は起動時に検証済みのため false 固定）
    cmd = [
        sys.executable,
        str(transition_script),
        collection,
        "--skip-manual-mastering",
        "true" if settings.skip_manual_mastering else "false",
        "--skip-audio-approval",
        "true",
    ]
    code, output = _run_command(cmd, log_path, channel_root)
    if code != 0:
        return _failed("master-audio-transition", f"exit {code}")
    action = _parse_transition_action(output)
    if action != TRANSITION_ACTION_ADOPTED:
        return _failed(
            "master-audio-transition",
            f"action={action}（非対話 batch では処理できません。/wf-next で個別に進めてください）",
        )

    # 6. マスター動画生成 → state 更新（publishing）
    code, _ = _run_command(["bash", str(videos_script), collection], log_path, channel_root)
    if code != 0:
        return _failed("generate-videos", f"exit {code}")
    try:
        _record_master_video(target.path)
    except ValidationError as e:
        return _failed("record-master-video", str(e))

    # 7. アップロード（実 CLI が tracking / state 更新 / planning → live 移行を一体で行う）
    code, _ = _run_command(["yt-upload-collection", "-c", target.slug], log_path, channel_root)
    if code != 0:
        return _failed("upload-collection", f"exit {code}")
    try:
        video_id, video_url, live_dir = _verify_live_migration(channel_root, target.slug)
    except ValidationError as e:
        return _failed("verify-live-migration", str(e))

    return CollectionOutcome(
        slug=target.slug,
        status=STATUS_SUCCESS,
        video_id=video_id,
        video_url=video_url,
        live_path=str(live_dir),
    )


def _build_summary(
    outcomes: list[CollectionOutcome],
    excluded: list[ExcludedCollection],
    elapsed_sec: float,
) -> dict:
    success = sum(1 for o in outcomes if o.status == STATUS_SUCCESS)
    return {
        "total": len(outcomes),
        "success": success,
        "failed": len(outcomes) - success,
        "elapsed_sec": round(elapsed_sec, 1),
        "results": [o.to_json() for o in outcomes],
        "excluded": [{"slug": e.slug, "reason": e.reason} for e in excluded],
    }


def _parse_only(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    slugs = [s.strip() for s in raw.split(",") if s.strip()]
    if not slugs:
        raise ValidationError("--only に有効な slug がありません")
    return slugs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="prepared 済み collection 群を /wf-next 相当の CLI チェーンで直列自動進行させる",
    )
    parser.add_argument("--dry-run", action="store_true", help="対象一覧と対象外警告のみ表示（実処理なし）")
    parser.add_argument("--only", metavar="SLUG[,SLUG...]", help="対象をディレクトリ名で絞り込み（カンマ区切り）")
    parser.add_argument("--from", dest="from_slug", metavar="SLUG", help="指定 slug 以降の対象から再開")
    parser.add_argument("--limit", type=int, metavar="N", help="先頭 N 件だけ処理（試運転用）")
    args = parser.parse_args(argv)

    try:
        channel_root = Path(channel_dir())
        planning_root = channel_root / "collections" / "planning"
        targets, excluded = discover_targets(planning_root)
        selected = select_targets(
            targets,
            only=_parse_only(args.only),
            from_slug=args.from_slug,
            limit=args.limit,
        )
    except (ValidationError, ConfigError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"対象 collection: {len(selected)} 件")
    for target in selected:
        print(f"  - {target.slug}")
    for entry in excluded:
        print(f"WARNING: {entry.slug}: {entry.reason}", file=sys.stderr)

    if args.dry_run:
        print(f"[dry-run] 対象 {len(selected)} 件 / 対象外 {len(excluded)} 件（実処理は行いません）")
        return 0

    if not selected:
        print("処理対象の collection がありません")
        return 0

    try:
        settings = _wf_next_settings()
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if not settings.skip_audio_approval or not settings.skip_upload_approval:
        print(
            "ERROR: workflow.wf_next.skip_audio_approval / skip_upload_approval が false です。"
            "yt-wf-batch は非対話のため承認を処理できません。",
            file=sys.stderr,
        )
        return 1

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = channel_root / "reports" / f"wf-batch-{timestamp}"
    report_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    outcomes: list[CollectionOutcome] = []
    for target in selected:
        log_path = report_dir / f"{target.slug}.log"
        log_path.touch()
        print(f"▶ {target.slug} を処理中... (log: {log_path})")
        try:
            outcome = process_collection(target, settings, log_path, channel_root)
        except (ValidationError, OSError) as e:
            # 1 件の失敗で batch 全体を止めない（後続 collection の処理を継続する）
            outcome = CollectionOutcome(slug=target.slug, status=STATUS_FAILED, error=str(e))
        outcomes.append(outcome)
        if outcome.status == STATUS_SUCCESS:
            print(f"  ✅ {target.slug}: {outcome.video_url}")
        else:
            print(f"  ❌ {target.slug}: {outcome.error}", file=sys.stderr)

    elapsed = time.monotonic() - started
    summary = _build_summary(outcomes, excluded, elapsed)
    summary_path = report_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"完了: success {summary['success']}/{summary['total']} / "
        f"failed {summary['failed']} / elapsed {summary['elapsed_sec']}s"
    )
    print(f"summary: {summary_path}")
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
