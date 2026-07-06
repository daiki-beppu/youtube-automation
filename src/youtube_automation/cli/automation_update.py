"""yt-automation-update — 下流チャンネルリポジトリの upstream 追従を機械実行する。

Subcommands:
    check : 実行場所・pin 形式・upstream 最新リリースとの差分を判定 (read-only)
    apply : pin 書き換え → uv lock → yt-skills sync → smoke check を順に一括実行

設計原則:
    判断が必要な手順（リリース内容の要約 / local fix 上書き判断 / 同意取得）は
    automation-update スキル側に残し、本 CLI は機械的に決まる手順のみを担う。
    commit / push は責務外（スキル・人間側で実施する）。

Exit codes:
    check : 0 = 既に最新 / 1 = 差分あり（要追従） / 2 = エラー
    apply : 0 = 成功 / 1 = ステップ失敗 / 2 = エラー
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path

from youtube_automation.cli.automation_update_refs import (
    _DEPENDENCY_NAME_RE,
    _SHA_RE,
    PACKAGE_NAME,
    UPSTREAM_REPO,
    _canonicalize_name,
    _classify_git_ref,
    _describe_pin,
    _detect_pin,
    _rewrite_pin,
)
from youtube_automation.cli.automation_update_remote import _github_api_get as _remote_github_api_get
from youtube_automation.cli.automation_update_remote import _locked_git_sha
from youtube_automation.cli.skills_sync import bundled_skill_names
from youtube_automation.utils.exceptions import ConfigError

EXIT_UP_TO_DATE = 0
EXIT_DIFF = 1
EXIT_ERROR = 2


class _StepFailed(Exception):
    """apply のステップ失敗（どのステップで失敗したかは実行ループ側が表示する）."""


def _resolve_repo_root(target: str | None) -> Path:
    if target:
        path = Path(target).resolve()
        if not (path / "pyproject.toml").is_file():
            raise ConfigError(f"--target で指定されたディレクトリに pyproject.toml がありません: {path}")
        return path
    for parent in [Path.cwd()] + list(Path.cwd().parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    raise ConfigError(
        "pyproject.toml が見つかりません。チャンネルリポジトリ配下で実行するか --target DIR を指定してください"
    )


def _load_pyproject(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"pyproject.toml を読み込めません: {path}: {e}")


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


def _github_api_get(path: str) -> dict:
    return _remote_github_api_get(path)


def _fetch_latest_release_tag() -> str:
    release = _github_api_get(f"repos/{UPSTREAM_REPO}/releases/latest")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise ConfigError("upstream 最新リリースの tag_name を取得できません")
    return tag


def _fetch_branch_head_sha(branch: str) -> str:
    commit = _github_api_get(f"repos/{UPSTREAM_REPO}/commits/{branch}")
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
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        raise _StepFailed(f"git status を起動できません: {e}")
    if proc.returncode != 0:
        raise _StepFailed(f"git status に失敗しました: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _run_command(cmd: list[str], cwd: Path) -> int:
    try:
        return subprocess.run(cmd, cwd=cwd, check=False).returncode
    except OSError as e:
        raise _StepFailed(f"{' '.join(cmd)} を起動できません: {e}")


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
        raise _StepFailed(f"{' '.join(cmd)} を起動できません: {e}")
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    local_fix_markers = (
        "内容が異なる",
        "target にのみ存在",
        "target がファイルではありません",
    )
    safe_missing_markers = (
        "同梱版にのみ存在",
        "target が存在しません",
    )
    known_markers = local_fix_markers + safe_missing_markers
    if proc.returncode != 0 and not any(marker in output for marker in known_markers):
        raise _StepFailed(f"exit code {proc.returncode}: {' '.join(cmd)}\n{output.strip()}")
    return any(marker in output for marker in local_fix_markers)


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
            print(f"upstream {pin.value} HEAD: {head[:12]}")
            if locked is None:
                print("→ uv.lock に解決済み sha がありません（yt-automation-update apply で取り込めます）")
                return EXIT_DIFF
            print(f"uv.lock 解決済み sha: {locked[:12]}")
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

    def step_worktree() -> None:
        status = _git_status_porcelain(root)
        if status:
            raise _StepFailed(
                "作業ツリーに未コミットの変更があります。"
                f"stash / commit で clean にしてから再実行してください:\n{status}"
            )

    def step_local_fix_guard() -> None:
        if args.force_sync or args.sync_only:
            return
        if _skills_diff_has_changes(root):
            raise _StepFailed(
                "yt-skills diff で local fix 差分を検出しました。"
                "--force-sync で upstream 版へ上書きするか、"
                "--sync-only <skill...> で安全に同期する skill だけを指定してください"
            )

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

    def run(cmd: list[str]) -> Callable[[], None]:
        def _invoke() -> None:
            print(f"  $ {' '.join(cmd)}")
            code = _run_command(cmd, root)
            if code != 0:
                raise _StepFailed(f"exit code {code}: {' '.join(cmd)}")

        return _invoke

    force = ["--force"]
    steps: list[tuple[str, Callable[[], None]]] = []
    if not args.allow_dirty:
        steps.append(("git 作業ツリー確認", step_worktree))
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
        steps.append(("yt-skills sync (--asset all --force)", run(["uv", "run", "yt-skills", "sync", *force])))
    steps.append(("smoke check: yt-skills list", run(["uv", "run", "yt-skills", "list"])))
    steps.append(
        (
            "smoke check: yt-config-migrate verify",
            run(["uv", "run", "yt-config-migrate", "verify", "--target", str(root)]),
        )
    )

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
    print("✓ 追従が完了しました。commit / push は本 CLI の責務外です（スキル / 人間側で実施してください）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-automation-update",
        description="下流チャンネルリポジトリの youtube-channels-automation 追従を機械実行する",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="実行場所・pin 形式・upstream 最新との差分を判定 (read-only)")
    p_check.add_argument("--target", default=None, help="対象チャンネルリポジトリ (default: CWD から自動解決)")
    p_check.add_argument("--tag", default=None, help="比較先 tag を明示 (default: upstream 最新リリース)")
    p_check.set_defaults(func=cmd_check)

    p_apply = sub.add_parser("apply", help="pin 書き換え → uv lock → yt-skills sync → smoke check を一括実行")
    p_apply.add_argument("--target", default=None, help="対象チャンネルリポジトリ (default: CWD から自動解決)")
    p_apply.add_argument("--tag", default=None, help="追従先 tag を明示 (default: upstream 最新リリース)")
    p_apply.add_argument("--rev", default=None, help="sha pin の bump 先 sha（sha pin では必須）")
    p_apply.add_argument(
        "--force-sync",
        action="store_true",
        help="互換用。apply は human step 後の機械実行として常に yt-skills sync --force を使う",
    )
    p_apply.add_argument(
        "--sync-only",
        nargs="+",
        default=None,
        metavar="SKILL",
        help="skills asset を指定スキルのみ同期する（claude-md asset は通常どおり同期）",
    )
    p_apply.add_argument(
        "--allow-dirty",
        action="store_true",
        help="作業ツリーが clean でなくても実行する（途中失敗からの再実行用）",
    )
    p_apply.set_defaults(func=cmd_apply)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
