"""yt-automation-update — 下流チャンネルリポジトリの upstream 追従を機械実行する。

Subcommands:
    check : 実行場所・pin 形式・upstream 最新リリースとの差分を判定 (read-only)
    apply : pin 書き換え → uv lock → yt-skills sync → smoke check を順に一括実行

設計原則:
    判断が必要な手順（リリース内容の要約 / local fix 上書き判断 / 同意取得）は
    automation-update スキル側に残し、本 CLI は機械的に決まる手順のみを担う。
    commit は apply --commit で任意に実行し、push はスキル・人間側で実施する。

Exit codes:
    check : 0 = 既に最新 / 1 = 差分あり（要追従） / 2 = エラー
    apply : 0 = 成功 / 1 = ステップ失敗 / 2 = エラー
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path

from youtube_automation.commands.system.automation_update_refs import (
    _DEPENDENCY_NAME_RE,
    _SHA_RE,
    PACKAGE_NAME,
    UPSTREAM_REPO,
    Pin,
    _canonicalize_name,
    _classify_git_ref,
    _describe_pin,
    _detect_pin,
    _rewrite_pin,
)
from youtube_automation.commands.system.automation_update_remote import _github_api_get as _remote_github_api_get
from youtube_automation.commands.system.automation_update_remote import _locked_git_sha
from youtube_automation.commands.system.skills_sync import bundled_skill_names
from youtube_automation.core.errors import ConfigError

EXIT_UP_TO_DATE = 0
EXIT_DIFF = 1
EXIT_ERROR = 2
_STABLE_RELEASE_TAG_RE = re.compile(r"v\d+\.\d+\.\d+")
_TARGET_HELP = "下流チャンネルリポジトリのルート。省略時は CWD から親方向へ自動解決"


class _StepFailed(Exception):
    """apply のステップ失敗（どのステップで失敗したかは実行ループ側が表示する）."""


def _resolve_repo_root(target: str | None) -> Path:
    if target:
        path = Path(target).resolve()
        if not (path / "pyproject.toml").is_file():
            raise ConfigError(f"--target で指定されたディレクトリに pyproject.toml がありません: {path}")
        return path
    for parent in [Path.cwd(), *list(Path.cwd().parents)]:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise ConfigError(
        "pyproject.toml が見つかりません。チャンネルリポジトリ配下で実行するか --target DIR を指定してください"
    )


def _load_pyproject(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"pyproject.toml を読み込めません: {path}: {e}") from e


def _classify_repo(pyproject: dict) -> str:
    """pyproject を upstream / dependency (下流) / other に分類する."""
    project = pyproject.get("project")
    if not isinstance(project, dict):
        return "other"
    name = project.get("name")
    if isinstance(name, str) and _canonicalize_name(name) == PACKAGE_NAME:
        return "upstream"
    dependencies = project.get("dependencies")
    if isinstance(dependencies, list):
        for dependency in dependencies:
            if not isinstance(dependency, str):
                continue
            match = _DEPENDENCY_NAME_RE.match(dependency)
            if match and _canonicalize_name(match.group(1)) == PACKAGE_NAME:
                return "dependency"
    return "other"


def _require_downstream(pyproject: dict, root: Path) -> None:
    kind = _classify_repo(pyproject)
    if kind == "dependency":
        return
    hint = (
        "移動先候補の探し方: [project].dependencies に youtube-channels-automation を含む\n"
        "pyproject.toml を持つチャンネルリポジトリへ cd してから再実行してください（-, _, . は同一扱い）:\n"
        "  find \"$HOME\" -maxdepth 4 -type f -name pyproject.toml -not -path '*/.venv/*' -not -path '*/.git/*'"
    )
    if kind == "upstream":
        raise ConfigError(
            f"ここは upstream リポ ({PACKAGE_NAME} 本体) です: {root}\n"
            f"yt-automation-update は下流チャンネルリポジトリ専用です。\n{hint}"
        )
    raise ConfigError(f"{root} は {PACKAGE_NAME} を依存として参照するチャンネルリポジトリではありません。\n{hint}")


def _validate_sync_only(sync_only: list[str] | None) -> None:
    if not sync_only:
        return
    available = set(bundled_skill_names())
    unknown = sorted(set(sync_only) - available)
    if unknown:
        raise ConfigError(f"--sync-only に同梱版に存在しない skill が指定されています: {', '.join(unknown)}")


def _github_api_get(path: str) -> object:
    return _remote_github_api_get(path)


def _fetch_latest_release_tag() -> str:
    releases = _github_api_get(f"repos/{UPSTREAM_REPO}/releases?per_page=100&page=1")
    if not isinstance(releases, list):
        raise ConfigError("upstream release 一覧を取得できません")

    candidates: list[tuple[str, str]] = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") is True or release.get("prerelease") is True:
            continue
        tag = release.get("tag_name")
        published_at = release.get("published_at")
        if isinstance(tag, str) and _STABLE_RELEASE_TAG_RE.fullmatch(tag) and isinstance(published_at, str):
            candidates.append((published_at, tag))
    if not candidates:
        raise ConfigError("upstream release 一覧に本体の stable release tag (vX.Y.Z) がありません")
    return max(candidates)[1]


def _fetch_branch_head_sha(branch: str) -> str:
    commit = _github_api_get(f"repos/{UPSTREAM_REPO}/commits/{branch}")
    if not isinstance(commit, dict):
        raise ConfigError(f"upstream {branch} の commit 情報を取得できません")
    sha = commit.get("sha")
    if not isinstance(sha, str) or not sha:
        raise ConfigError(f"upstream {branch} の HEAD sha を取得できません")
    return sha


def _require_tag_ref(ref: str, *, source: str) -> str:
    kind, value = _classify_git_ref(ref)
    if kind != "tag":
        raise ConfigError(f"{source} には vX.Y.Z 形式の tag を指定してください: {ref}")
    return value


def _git_status_porcelain(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        raise _StepFailed(f"git status を起動できません: {e}") from e
    if proc.returncode != 0:
        raise _StepFailed(f"git status に失敗しました: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _git_status_paths(root: Path) -> set[str]:
    """Return all paths currently reported by status, including untracked files."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        raise _StepFailed(f"git status を起動できません: {e}") from e
    if proc.returncode != 0:
        raise _StepFailed(f"git status に失敗しました: {proc.stderr.strip()}")

    records = proc.stdout.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        status = record[:2]
        paths.add(record[3:])
        index += 2 if "R" in status or "C" in status else 1
    return paths


def _commit_apply_changes(root: Path, before_paths: set[str], ref: str) -> None:
    # #4911: --allow-dirty でも開始前の変更は含めない。既存の staged 変更も commit --only で保護する。
    paths = sorted(_git_status_paths(root) - before_paths)
    if not paths:
        raise _StepFailed("apply 前後の git status に commit 対象の差分がありません")
    commands = [
        ["git", "add", "--", *paths],
        ["git", "commit", "--only", "-m", f"chore: youtube-automation {ref} への追従", "--", *paths],
    ]
    for command in commands:
        try:
            proc = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        except OSError as e:
            raise _StepFailed(f"{' '.join(command[:2])} を起動できません: {e}") from e
        if proc.returncode != 0:
            details = proc.stderr.strip() or proc.stdout.strip()
            raise _StepFailed(f"exit code {proc.returncode}: {' '.join(command[:2])}\n{details}")


def _commit_ref(root: Path, pin: Pin, new_ref: str | None) -> str:
    """apply 後の commit message に使う追従先 ref を pin 種別から解決する。"""
    if pin.kind == "branch":
        locked_sha = _locked_git_sha(root)
        if locked_sha is None:
            raise _StepFailed("uv.lock から追従後の git sha を取得できません")
        return locked_sha[:12]
    assert new_ref is not None
    return new_ref if pin.kind == "tag" else new_ref[:12]


def _append_optional_step(
    steps: list[tuple[str, Callable[[], None]]], *, enabled: bool, name: str, action: Callable[[], None]
) -> None:
    """条件付き step の組み立てを orchestrator の分岐から分離する。"""
    if enabled:
        steps.append((name, action))


def _print_apply_success(*, committed: bool) -> None:
    if committed:
        print("✓ 追従と commit が完了しました。push は本 CLI の責務外です（スキル / 人間側で実施してください）")
        return
    print("✓ 追従が完了しました。commit / push は本 CLI の責務外です（スキル / 人間側で実施してください）")


def _run_command(cmd: list[str], cwd: Path) -> int:
    try:
        return subprocess.run(cmd, cwd=cwd, check=False).returncode
    except OSError as e:
        raise _StepFailed(f"{' '.join(cmd)} を起動できません: {e}") from e


def _channel_roots(root: Path) -> list[Path]:
    candidates = [root] if (root / "config" / "channel").is_dir() else []
    candidates.extend(
        channel_root
        for channel_root in sorted((root / "channels").glob("*"))
        if channel_root.is_dir() and (channel_root / "config" / "channel").is_dir()
    )
    return candidates or [root]


def _check_single_channel_config(channel_root: Path) -> str:
    cmd = [
        "uv",
        "run",
        "yt-doctor",
        "--check",
        "channel_config",
        "--json",
        "--target",
        str(channel_root),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=channel_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        raise _StepFailed(f"{' '.join(cmd)} を起動できません: {e}") from e
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        if proc.returncode != 0:
            details = proc.stderr.strip() or proc.stdout.strip()
            raise _StepFailed(f"exit code {proc.returncode}: {' '.join(cmd)}\n{details}") from e
        raise _StepFailed(f"yt-doctor --json の出力を解析できません: {e}") from e
    if not isinstance(payload, dict) or not isinstance(payload.get("checks"), list):
        raise _StepFailed("yt-doctor --json の出力に checks 配列がありません")
    result = next(
        (check for check in payload["checks"] if isinstance(check, dict) and check.get("id") == "channel_config"),
        None,
    )
    if result is None:
        raise _StepFailed("yt-doctor --json の出力に channel_config check がありません")
    message = result.get("message")
    if result.get("status") != "ok":
        raise _StepFailed(message if isinstance(message, str) else "channel_config check が失敗しました")
    success_message = message if isinstance(message, str) else "channel_config check 成功"
    if proc.returncode != 0:
        return f"{success_message}（warning: yt-doctor の他 check が失敗し exit code {proc.returncode}）"
    return success_message


def _check_channel_config(root: Path) -> str:
    channel_roots = _channel_roots(root)
    results = [_check_single_channel_config(channel_root) for channel_root in channel_roots]
    if len(results) == 1:
        return results[0]
    return f"{len(results)} チャンネルの config/channel/ ロード成功"


def _skills_diff_has_changes(root: Path) -> bool:
    cmd = ["uv", "run", "yt-skills", "diff"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        raise _StepFailed(f"{' '.join(cmd)} を起動できません: {e}") from e
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    local_fix_markers = (
        "内容が異なる",
        "target がファイルではありません",
    )
    safe_missing_markers = (
        "同梱版にのみ存在",
        "target が存在しません",
        "target にのみ存在 (未知のローカル entry として prune から保護されます)",
    )
    known_markers = local_fix_markers + safe_missing_markers
    if proc.returncode != 0 and not any(marker in output for marker in known_markers):
        raise _StepFailed(f"exit code {proc.returncode}: {' '.join(cmd)}\n{output.strip()}")
    return any(marker in output for marker in local_fix_markers)


def _hooks_snapshot(root: Path) -> dict[str, object] | None:
    settings_path = root / ".claude" / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(settings, dict):
        return None
    hooks = settings.get("hooks", {})
    return hooks if isinstance(hooks, dict) else None


def cmd_check(args: argparse.Namespace) -> int:
    try:
        root = _resolve_repo_root(args.target)
        pyproject = _load_pyproject(root / "pyproject.toml")
        _require_downstream(pyproject, root)
        pin = _detect_pin(pyproject)
        print(f"実行場所: {root} (下流チャンネルリポジトリ)")
        print(f"pin 形式: {_describe_pin(pin)}")

        if pin.kind == "registry":
            raise ConfigError(
                "registry 参照 (git 参照ではない) のため差分を自動判定できません。"
                "pyproject.toml を git 参照 (tag pin / main 追従) へ切り替えてください"
            )

        if pin.kind == "tag":
            latest = _require_tag_ref(args.tag or _fetch_latest_release_tag(), source="比較先")
            print(f"upstream 最新リリース: {latest}")
            if pin.value == latest:
                print(f"✓ 既に最新です ({latest})")
                return EXIT_UP_TO_DATE
            print(f"→ 差分あり: {pin.value} → {latest}（yt-automation-update apply で追従できます）")
            return EXIT_DIFF

        if pin.kind == "branch":
            head = _fetch_branch_head_sha(pin.value)
            locked = _locked_git_sha(root)
            print(f"upstream {pin.value} HEAD: {head}")
            if locked is None:
                print("→ uv.lock に解決済み sha がありません（yt-automation-update apply で取り込めます）")
                return EXIT_DIFF
            print(f"uv.lock 解決済み sha: {locked}")
            if locked == head:
                print("✓ 既に最新です (uv.lock が upstream HEAD と一致)")
                return EXIT_UP_TO_DATE
            print("→ 差分あり: uv.lock が upstream HEAD より古い状態です（yt-automation-update apply で追従できます）")
            return EXIT_DIFF

        # sha pin: bump 先の決定は人間判断（スキル側の [HUMAN STEP]）。
        # network freshness does not help because the desired sha may not be the latest release tag.
        print(
            "→ sha pin は差分を自動判定できません。"
            "bump 先 sha を決めて yt-automation-update apply --rev <sha> を実行してください"
        )
        return EXIT_DIFF
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return EXIT_ERROR


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        root = _resolve_repo_root(args.target)
        pyproject_path = root / "pyproject.toml"
        pyproject = _load_pyproject(pyproject_path)
        _require_downstream(pyproject, root)
        pin = _detect_pin(pyproject)
        _validate_sync_only(args.sync_only)
        if pin.kind == "registry":
            raise ConfigError(
                "registry 参照 (git 参照ではない) のため自動追従できません。"
                "pyproject.toml を git 参照 (tag pin / main 追従) へ切り替えてください"
            )
        if args.rev is not None and pin.kind != "sha":
            raise ConfigError("--rev は sha pin の apply でのみ指定できます")
        if args.tag is not None and pin.kind != "tag":
            raise ConfigError("--tag は tag pin の apply でのみ指定できます")
        if pin.kind == "sha" and not args.rev:
            raise ConfigError(
                "sha pin は bump 先の判断が必要です。--rev <sha> で明示してください"
                "（bump 先の決定はスキル側の [HUMAN STEP]）"
            )
        if args.rev is not None and not _SHA_RE.fullmatch(args.rev):
            raise ConfigError("--rev には 40 桁の hex sha を指定してください")
        new_ref: str | None = None
        if pin.kind == "tag":
            new_ref = _require_tag_ref(args.tag or _fetch_latest_release_tag(), source="追従先")
        elif pin.kind == "sha":
            new_ref = args.rev
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return EXIT_ERROR

    print(f"対象: {root}")
    print(f"pin 形式: {_describe_pin(pin)}")
    if new_ref:
        print(f"追従先: {new_ref}")
    hooks_before = _hooks_snapshot(root)
    status_before: set[str] = set()

    def step_worktree() -> None:
        status = _git_status_porcelain(root)
        if status:
            raise _StepFailed(
                "作業ツリーに未コミットの変更があります。"
                f"stash / commit で clean にしてから再実行してください:\n{status}"
            )

    def step_local_fix_guard() -> None:
        if args.force_sync:
            return
        if _skills_diff_has_changes(root):
            raise _StepFailed(
                "yt-skills diff で local fix 差分を検出しました。"
                "--force-sync で upstream 版へ上書きするか、"
                "local fix を手動解消してから再実行してください"
            )

    def step_status_snapshot() -> None:
        status_before.update(_git_status_paths(root))

    def step_rewrite() -> None:
        if pin.kind == "branch":
            print(f"  main 追従 (branch={pin.value}) のため pin 書き換えは不要です")
            return
        assert new_ref is not None
        if pin.value == new_ref:
            print(f"  pin は既に {new_ref} です（書き換えなし）")
            return
        try:
            text = pyproject_path.read_text(encoding="utf-8")
            pyproject_path.write_text(_rewrite_pin(text, pin, new_ref), encoding="utf-8")
        except OSError as e:
            raise _StepFailed(f"pyproject.toml を書き換えられません: {e}") from e
        print(f"  {pin.value} → {new_ref}")

    def step_channel_config() -> None:
        print(f"  {_check_channel_config(root)}")

    def step_commit() -> None:
        commit_ref = _commit_ref(root, pin, new_ref)
        _commit_apply_changes(root, status_before, commit_ref)
        print(f"  chore: youtube-automation {commit_ref} への追従")

    def run(cmd: list[str]) -> Callable[[], None]:
        def _invoke() -> None:
            print(f"  $ {' '.join(cmd)}")
            code = _run_command(cmd, root)
            if code != 0:
                raise _StepFailed(f"exit code {code}: {' '.join(cmd)}")

        return _invoke

    force = ["--force"]
    hook_flags = ["--accept-hooks"] if args.accept_hooks else []
    steps: list[tuple[str, Callable[[], None]]] = []
    if not args.allow_dirty:
        steps.append(("git 作業ツリー確認", step_worktree))
    _append_optional_step(steps, enabled=args.commit, name="commit 対象の事前確認", action=step_status_snapshot)
    steps.append(("yt-skills diff による local fix 確認", step_local_fix_guard))
    steps.append(("pyproject.toml の pin 書き換え", step_rewrite))
    steps.append(("uv lock", run(["uv", "lock", "--upgrade-package", PACKAGE_NAME])))
    if args.sync_only:
        steps.append(
            (
                "yt-skills sync (--asset skills --only --force)",
                run(["uv", "run", "yt-skills", "sync", "--asset", "skills", "--only", *args.sync_only, *force]),
            )
        )
        steps.append(
            (
                "yt-skills sync (--asset claude-md --force)",
                run(["uv", "run", "yt-skills", "sync", "--asset", "claude-md", *force]),
            )
        )
    else:
        steps.append(
            (
                "yt-skills sync (--asset all --force)",
                run(["uv", "run", "yt-skills", "sync", *force, *hook_flags]),
            )
        )
    steps.append(("smoke check: yt-skills list", run(["uv", "run", "yt-skills", "list"])))
    steps.append(("smoke check: channel config", step_channel_config))
    _append_optional_step(steps, enabled=args.commit, name="追従差分を commit", action=step_commit)

    total = len(steps)
    for index, (name, action) in enumerate(steps, start=1):
        print(f"[{index}/{total}] {name}")
        try:
            action()
        except (_StepFailed, ConfigError) as e:
            print(f"[error] ステップ {index}/{total} '{name}' で失敗しました: {e}", file=sys.stderr)
            print(
                "[error] 原因を解消して同じコマンドを再実行すると、続きから冪等にやり直せます"
                "（apply 自身の pin 書き換えで作業ツリーが dirty になっている場合は --allow-dirty を付ける）",
                file=sys.stderr,
            )
            return 1
    _print_apply_success(committed=args.commit)
    hooks_after = _hooks_snapshot(root)
    if args.accept_hooks and hooks_before is not None and hooks_after is not None and hooks_before != hooks_after:
        print(
            "⚠ hook の変更は次回の Claude Code セッションから有効になります。"
            "現在のセッションには反映されないため、Claude Code を再起動してください。"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-automation-update",
        description="下流チャンネルリポジトリの youtube-channels-automation 追従を機械実行する",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="実行場所・pin 形式・upstream 最新との差分を判定 (read-only)")
    p_check.add_argument("--target", default=None, help=_TARGET_HELP)
    p_check.add_argument(
        "--tag",
        default=None,
        help="tag pin 専用の比較先。vX.Y.Z 形式で指定し、省略時は upstream の最新 stable release",
    )
    p_check.set_defaults(func=cmd_check)

    p_apply = sub.add_parser("apply", help="pin 書き換え → uv lock → yt-skills sync → smoke check を一括実行")
    p_apply.add_argument("--target", default=None, help=_TARGET_HELP)
    p_apply.add_argument(
        "--tag",
        default=None,
        help="tag pin 専用の追従先。vX.Y.Z 形式で指定し、省略時は upstream の最新 stable release",
    )
    p_apply.add_argument(
        "--rev",
        default=None,
        help="sha pin 専用の追従先。40 桁の hex SHA を指定し、sha pin では必須",
    )
    p_apply.add_argument(
        "--force-sync",
        action="store_true",
        help=(
            "local fix の破棄を承認済みの場合に、yt-skills diff の local fix guard だけを bypass し、"
            "upstream 版で上書きする"
        ),
    )
    p_apply.add_argument(
        "--accept-hooks",
        action="store_true",
        help=(
            "--sync-only では使用しない。全 asset 同期時に settings asset の新規 hook 追加を承認する。"
            "省略時は新規 hook だけ追加しない"
        ),
    )
    p_apply.add_argument(
        "--sync-only",
        nargs="+",
        default=None,
        metavar="SKILL",
        help=(
            "配布済み skill 名を 1 件以上指定し、skills asset の指定スキルと claude-md asset だけを同期する。"
            "local fix guard は既定で維持し、--force-sync 併用時のみ bypass"
        ),
    )
    p_apply.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "途中失敗からの再実行時に作業ツリーの clean guard だけを bypass する。それ単独では local fix guard は維持"
        ),
    )
    p_apply.add_argument(
        "--commit",
        action="store_true",
        help="apply が新たに作った差分だけを stage し、追従 ref を含むメッセージで commit する",
    )
    p_apply.set_defaults(func=cmd_apply)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
