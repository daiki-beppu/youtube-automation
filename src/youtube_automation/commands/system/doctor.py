"""yt-doctor: ツール・API 設定の診断と限定的な client secret 配置 CLI。"""

from __future__ import annotations

import argparse
import importlib.metadata
import io
import json
import os
import re
import shlex
import shutil
import site
import stat
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager, redirect_stdout
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

from youtube_automation.commands.system.automation_update_refs import UPSTREAM_REPO
from youtube_automation.commands.system.skills_sync import bundled_skill_names
from youtube_automation.configuration import (
    channel_dir,
    explicit_channel_selection,
    find_workspace_root,
    workspace_channels,
)
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import AutomationError, ConfigError, YouTubeAPIError
from youtube_automation.domains.channel_readiness import (
    ReadinessResult,
    approved_ttp_exceptions,
    evaluate_initial_setup_readiness,
    evaluate_ttp_wf_new_readiness,
)
from youtube_automation.domains.documents.operational_artifacts import resolve_artifacts
from youtube_automation.infrastructure.auth import (
    UPLOAD_REQUIRED_SCOPES,
    OAuthCredentialState,
    build_youtube_service,
    load_credentials,
    load_refreshable_credentials,
)
from youtube_automation.infrastructure.auth.youtube import (
    YouTubeOAuthHandler,
    resolve_client_secrets_location,
)
from youtube_automation.infrastructure.collections.numbered_duplicates import (
    CLEANUP_GUIDE_URL,
    format_duplicate_name,
    format_scan_error_reason,
    scan_numbered_duplicates,
)
from youtube_automation.infrastructure.retry import QUOTA_REASONS
from youtube_automation.infrastructure.youtube.reporting_api import ReportingAPIClient
from youtube_automation.infrastructure.youtube.streaming.state_reconciliation import reconcile_streaming_vps

PYPROJECT_FILENAME = "pyproject.toml"
CLAUDE_SKILLS_DIR = Path(".claude") / "skills"
AGENTS_SKILLS_LINK = Path(".agents") / "skills"
SKILL_FILENAME = "SKILL.md"
AUTOMATION_PACKAGE_NAME = "youtube-channels-automation"
SKILLS_SYNC_ARGV = ("uv", "run", "yt-skills", "sync", "--asset", "skills", "--force")
SKILLS_SYNC_PRUNE_ARGV = (*SKILLS_SYNC_ARGV, "--prune", "--yes")
SKILLS_SYNC_CMD = shlex.join(SKILLS_SYNC_ARGV)
LEGACY_BUNDLED_SKILLS = (
    "onboard",
    "distrokid-prep",
    "channel-import",
    "channel-direction",
    "channel-setup",
)

BOOTSTRAP_CATEGORY = "bootstrap"
API_CATEGORY = "api"
CHANNEL_CATEGORY = "channel"
DATA_CATEGORY = "data"
UPLOAD_CATEGORY = "upload"

REQUIRED_APIS = [
    "youtube.googleapis.com",
    "youtubeanalytics.googleapis.com",
    "youtubereporting.googleapis.com",
    "aiplatform.googleapis.com",
    "generativelanguage.googleapis.com",
]

MAX_DISPLAY_VALUE_LEN = 120
GCP_PROJECT_ID_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")
BILLING_ACCOUNT_ID_RE = re.compile(r"[A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6}\Z")
_APPLY_PROJECT_ID: ContextVar[str | None] = ContextVar("doctor_apply_project_id", default=None)


class ApplyKind(Enum):
    """診断の apply 可否と特別な入力契約。"""

    NONE = "none"
    AI_EXEC = "ai-exec"
    PROJECT = "project"
    BILLING = "billing"


class CwdSemantics(Enum):
    """apply command を実行する基準ディレクトリ。"""

    CHANNEL = "channel"
    BOOTSTRAP_ROOT = "bootstrap-root"


class _ActionMapping(Mapping):
    def _internal_dict(self) -> dict:
        raise NotImplementedError

    def __getitem__(self, key: str) -> object:
        return self._internal_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._internal_dict())

    def __len__(self) -> int:
        return len(self._internal_dict())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return self._internal_dict() == dict(other)
        return NotImplemented


@dataclass(frozen=True, eq=False)
class AgentCommand(_ActionMapping):
    """A validated, non-interactive command which the apply loop may execute."""

    argv: tuple[str, ...]
    cmd: str
    auto_apply: bool = True
    public_fields: tuple[tuple[str, object], ...] = ()

    def to_public_dict(self) -> dict:
        return {"kind": "ai-exec", "cmd": self.cmd, **dict(self.public_fields)}

    def _internal_dict(self) -> dict:
        payload = {**self.to_public_dict(), "argv": list(self.argv)}
        if not self.auto_apply:
            payload["auto_apply"] = False
        return payload


@dataclass(frozen=True, eq=False)
class HumanBrowserAuth(_ActionMapping):
    """A browser authentication hand-off; its command is never auto-applied."""

    public_fields: tuple[tuple[str, object], ...]
    argv: tuple[str, ...] = ()

    def to_public_dict(self) -> dict:
        return {"kind": "human", **dict(self.public_fields)}

    def _internal_dict(self) -> dict:
        return {**self.to_public_dict(), "argv": list(self.argv)}


@dataclass(frozen=True, eq=False)
class ManualRemediation(_ActionMapping):
    """A public action which requires a person or an explicit decision."""

    public_fields: tuple[tuple[str, object], ...]

    def to_public_dict(self) -> dict:
        return dict(self.public_fields)

    def _internal_dict(self) -> dict:
        return self.to_public_dict()


RemediationAction = AgentCommand | HumanBrowserAuth | ManualRemediation

# 公開 JSON へ出してはならない内部専用キー（apply loop だけが使う実行情報）。
_INTERNAL_ACTION_KEYS = frozenset({"argv", "auto_apply"})


def _remediation_action(value: RemediationAction | dict | None) -> RemediationAction | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return value
    exposed = tuple((key, item) for key, item in value.items() if key not in _INTERNAL_ACTION_KEYS)
    public = tuple((key, item) for key, item in exposed if key != "kind")
    kind = value.get("kind")
    raw_argv = value.get("argv")
    argv = tuple(raw_argv) if isinstance(raw_argv, list) and all(isinstance(item, str) for item in raw_argv) else ()
    if kind == "ai-exec" and argv:
        return AgentCommand(argv, str(value.get("cmd", shlex.join(argv))), value.get("auto_apply") is not False, public)
    if kind == "human" and value.get("reason") == "authentication":
        return HumanBrowserAuth(public, argv)
    return ManualRemediation(exposed)


@dataclass
class CheckResult:
    id: str
    status: str  # ok / info / warn / fail / unknown
    message: str
    category: str = API_CATEGORY  # bootstrap / api / channel / data / upload
    next_action: RemediationAction | dict | None = None
    data: Optional[dict] = None

    def __post_init__(self) -> None:
        self.next_action = _remediation_action(self.next_action)


@dataclass(frozen=True)
class CheckDefinition:
    """1 件の doctor check を構成する宣言。"""

    id: str
    category: str
    run: Callable[[Path], CheckResult]
    apply_kind: ApplyKind
    cwd_semantics: CwdSemantics

    def command_cwd(self, channel_dir: Path) -> Path:
        return _bootstrap_root(channel_dir) if self.cwd_semantics is CwdSemantics.BOOTSTRAP_ROOT else channel_dir


def _ai_exec_action(
    argv: list[str] | tuple[str, ...],
    *,
    auto_apply: bool = True,
    display_cmd: str | None = None,
) -> AgentCommand:
    return AgentCommand(tuple(argv), display_cmd or shlex.join(argv), auto_apply)


def _human_auth_action(argv: list[str] | tuple[str, ...], instructions: str) -> HumanBrowserAuth:
    """Return an auth hand-off without delegating command execution to the user."""
    return HumanBrowserAuth(
        (
            ("reason", "authentication"),
            ("cmd", shlex.join(argv)),
            ("execution_owner", "ai-or-setup"),
            ("human_role", "browser-authentication"),
            ("instructions", instructions),
        ),
        tuple(argv),
    )


def _youtube_oauth_action(instructions: str) -> HumanBrowserAuth:
    """Return the agent-driven YouTube OAuth hand-off contract."""
    action = _human_auth_action(
        ["uv", "run", "yt-oauth"],
        "AI または setup が `uv run yt-oauth` を background session で起動し、stdout の同意 URL を利用者へ中継します。"
        "利用者はブラウザで OAuth 同意だけを完了してください。AI は同じ process の exit 0 を待ち、"
        f"`uv run yt-doctor --json` で再検証します。{instructions}",
    )
    return HumanBrowserAuth(
        (
            *action.public_fields,
            ("execution_mode", "background"),
            ("url_source", "stdout"),
            ("completion_signal", "process-exit"),
            ("post_check_cmd", "uv run yt-doctor --json"),
        ),
        action.argv,
    )


def _youtube_readonly_oauth_action(channel_dir: Path) -> HumanBrowserAuth:
    """Return the agent-driven read-only OAuth hand-off in the target channel context."""
    action = _human_auth_action(
        ["uv", "run", "yt-oauth", "--readonly"],
        "AI または setup が対象チャンネルのディレクトリで `uv run yt-oauth --readonly` を background session "
        "として起動し、stdout の同意 URL を利用者へ中継します。利用者はブラウザで OAuth 同意だけを"
        "完了してください。AI は同じ process の exit 0 を待ち、`uv run yt-doctor --json` で再検証します。",
    )
    return HumanBrowserAuth(
        (
            *action.public_fields,
            ("cwd", str(channel_dir)),
            ("execution_mode", "background"),
            ("url_source", "stdout"),
            ("completion_signal", "process-exit"),
            ("post_check_cmd", "uv run yt-doctor --json"),
        ),
        action.argv,
    )


@dataclass(frozen=True)
class _WfNewInputMode:
    mode: str
    report_count: int
    benchmark_count: int
    stale_report: bool
    stale_reason: str | None = None
    invalid_report: bool = False


def _run(cmd: list[str], timeout: int = 30, *, cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {' '.join(cmd)}"


def _parse_project_id(value: str) -> str:
    if not GCP_PROJECT_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("project ID は GCP の 6-30 文字形式で指定してください")
    return value


def _parse_billing_account_id(value: str) -> str:
    if not BILLING_ACCOUNT_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("billing account ID は XXXXXX-XXXXXX-XXXXXX 形式で指定してください")
    return value


def _format_external_display_value(value: object) -> str:
    text = "".join(_escape_display_character(char) for char in str(value))
    if len(text) <= MAX_DISPLAY_VALUE_LEN:
        return text
    return text[: MAX_DISPLAY_VALUE_LEN - 3] + "..."


def _escape_display_character(char: str) -> str:
    if char == "\n":
        return "\\n"
    if char == "\r":
        return "\\r"
    if char == "\t":
        return "\\t"
    if unicodedata.category(char)[0] == "C":
        return char.encode("unicode_escape").decode("ascii")
    return char


def _adc_quota_project() -> Optional[str]:
    adc_json = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if not adc_json.exists():
        return None
    try:
        data = json.loads(adc_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data.get("quota_project_id")


def _project_id_for(channel_dir: Path) -> Optional[str]:
    apply_project_id = _APPLY_PROJECT_ID.get()
    if apply_project_id:
        return apply_project_id
    return os.environ.get("GOOGLE_CLOUD_PROJECT") or _adc_quota_project()


def _project_table(pyproject_path: Path) -> dict[str, object]:
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ValueError(f"{pyproject_path} 読み込み失敗: {e}") from e

    project = data.get("project")
    if not isinstance(project, dict):
        return {}
    return project


def _project_dependencies(project: dict[str, object]) -> list[str]:
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return []
    return [item for item in dependencies if isinstance(item, str)]


def _project_name(project: dict[str, object]) -> Optional[str]:
    name = project.get("name")
    return name if isinstance(name, str) else None


def _canonical_package_name(package_name: str) -> str:
    return re.sub(r"[-_.]+", "-", package_name).lower()


def _dependency_package_name(dependency: str) -> Optional[str]:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", dependency)
    if not match:
        return None
    return _canonical_package_name(match.group(1))


def _has_automation_dependency(dependencies: list[str]) -> bool:
    return any(_dependency_package_name(dependency) == AUTOMATION_PACKAGE_NAME for dependency in dependencies)


def _is_automation_project(project_name: Optional[str]) -> bool:
    return project_name is not None and _canonical_package_name(project_name) == AUTOMATION_PACKAGE_NAME


def _path_is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _uv_tool_root() -> Path | None:
    returncode, stdout, _ = _run(["uv", "tool", "dir"])
    if returncode != 0 or not stdout.strip():
        return None
    return Path(stdout.strip()).expanduser().resolve()


def _running_global_installation_mode() -> str | None:
    try:
        distribution = importlib.metadata.distribution(AUTOMATION_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return None

    installation_path = Path(distribution.locate_file("")).resolve()
    installer_text = distribution.read_text("INSTALLER")
    installer = installer_text.strip().lower() if installer_text is not None else None

    if sys.prefix == sys.base_prefix:
        if installer == "pip":
            user_site = Path(site.getusersitepackages()).expanduser().resolve()
            return "pip user" if _path_is_within(installation_path, user_site) else "pip system"
        return "global（installer 不明）"

    tool_root = _uv_tool_root()
    if (
        tool_root is not None
        and _path_is_within(Path(sys.prefix).resolve(), tool_root)
        and _path_is_within(installation_path, tool_root)
    ):
        return "uv tool"
    return None


def _skills_sync_failure(message: str) -> CheckResult:
    return CheckResult(
        id="skills_synced",
        status="fail",
        category=BOOTSTRAP_CATEGORY,
        message=message,
        next_action=_ai_exec_action(SKILLS_SYNC_ARGV),
    )


def _skills_sync_prune_failure(message: str) -> CheckResult:
    return CheckResult(
        id="skills_synced",
        status="fail",
        category=BOOTSTRAP_CATEGORY,
        message=message,
        next_action=_ai_exec_action(SKILLS_SYNC_PRUNE_ARGV),
    )


def _skills_sync_warning(message: str) -> CheckResult:
    return CheckResult(
        id="skills_synced",
        status="warn",
        category=BOOTSTRAP_CATEGORY,
        message=message,
        next_action={
            "kind": "human",
            "instructions": (
                f"{AGENTS_SKILLS_LINK} を {CLAUDE_SKILLS_DIR} へ向ける symlink として手動作成してください"
            ),
        },
    )


def _agents_skills_link_is_valid(channel_dir: Path, skills_dir: Path) -> bool:
    link = channel_dir / AGENTS_SKILLS_LINK
    if not link.is_symlink():
        return False
    try:
        return link.resolve(strict=True) == skills_dir.resolve(strict=True)
    except OSError:
        return False


def _workspace_root_for_channel(channel_dir: Path) -> Path | None:
    """登録済み workspace channel の共有 root だけを返す."""
    resolved_channel = channel_dir.resolve()
    workspace_root = find_workspace_root(resolved_channel)
    if workspace_root is None:
        return None
    registered_channels = {path.resolve() for path in workspace_channels(workspace_root).values()}
    return workspace_root if resolved_channel in registered_channels else None


def _bootstrap_root(channel_dir: Path) -> Path:
    """共有 tool / skill を検査・更新する repository root を返す."""
    return _workspace_root_for_channel(channel_dir) or channel_dir


# --- checks ---


def check_ffmpeg() -> CheckResult:
    path = shutil.which("ffmpeg")
    if not path:
        return CheckResult(
            id="ffmpeg",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message="ffmpeg が見つからない",
            next_action={
                "kind": "human",
                "instructions": (
                    "macOS: `brew install ffmpeg` / "
                    "Ubuntu/Debian: `sudo apt-get install -y ffmpeg` / "
                    "その他: https://ffmpeg.org/download.html を参照"
                ),
            },
        )
    return CheckResult(id="ffmpeg", status="ok", category=BOOTSTRAP_CATEGORY, message=f"ffmpeg found: {path}")


def check_ffprobe() -> CheckResult:
    path = shutil.which("ffprobe")
    if not path:
        return CheckResult(
            id="ffprobe",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message="ffprobe が見つからない",
            next_action={
                "kind": "human",
                "instructions": (
                    "ffprobe は通常 ffmpeg に同梱されます。"
                    "macOS: `brew install ffmpeg` / "
                    "Ubuntu/Debian: `sudo apt-get install -y ffmpeg` / "
                    "その他: https://ffmpeg.org/download.html を参照"
                ),
            },
        )
    return CheckResult(id="ffprobe", status="ok", category=BOOTSTRAP_CATEGORY, message=f"ffprobe found: {path}")


def check_uv() -> CheckResult:
    path = shutil.which("uv")
    if not path:
        return CheckResult(
            id="uv",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message="uv が見つからない",
            next_action={
                "kind": "human",
                "instructions": (
                    "https://docs.astral.sh/uv/getting-started/installation/ を参照して uv を install してください"
                ),
            },
        )
    return CheckResult(id="uv", status="ok", category=BOOTSTRAP_CATEGORY, message=f"uv found: {path}")


def check_uv_project(channel_dir: Path) -> CheckResult:
    pyproject_path = _bootstrap_root(channel_dir) / PYPROJECT_FILENAME
    if not pyproject_path.exists():
        installation_mode = _running_global_installation_mode()
        if installation_mode is not None:
            return CheckResult(
                id="uv_project",
                status="ok",
                category=BOOTSTRAP_CATEGORY,
                message=f"{installation_mode} 導入済み（uv project 初期化不要）",
            )
        return CheckResult(
            id="uv_project",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message=f"{PYPROJECT_FILENAME} が無い",
            next_action=_ai_exec_action(["uv", "init"], auto_apply=False),
        )
    if not pyproject_path.is_file():
        return CheckResult(
            id="uv_project",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message=f"{PYPROJECT_FILENAME} がファイルではない",
        )
    return CheckResult(id="uv_project", status="ok", category=BOOTSTRAP_CATEGORY, message="uv project 初期化済み")


def check_automation_package(channel_dir: Path) -> CheckResult:
    pyproject_path = _bootstrap_root(channel_dir) / PYPROJECT_FILENAME
    if not pyproject_path.exists():
        installation_mode = _running_global_installation_mode()
        if installation_mode is not None:
            return CheckResult(
                id="automation_package",
                status="ok",
                category=BOOTSTRAP_CATEGORY,
                message=f"{installation_mode} で automation パッケージ導入済み",
            )
        return CheckResult(
            id="automation_package",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message=f"{PYPROJECT_FILENAME} が無いため automation パッケージを確認できない",
            next_action=_ai_exec_action(["uv", "init"], auto_apply=False),
        )
    if not pyproject_path.is_file():
        return CheckResult(
            id="automation_package",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message=f"{PYPROJECT_FILENAME} が無いため automation パッケージを確認できない",
            next_action=_ai_exec_action(["uv", "init"], auto_apply=False),
        )
    try:
        project = _project_table(pyproject_path)
    except ValueError as e:
        return CheckResult(
            id="automation_package",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message=str(e),
        )
    dependencies = _project_dependencies(project)
    if _is_automation_project(_project_name(project)):
        return CheckResult(
            id="automation_package",
            status="ok",
            category=BOOTSTRAP_CATEGORY,
            message="automation パッケージ本体プロジェクト",
        )
    if not _has_automation_dependency(dependencies):
        installation_mode = _running_global_installation_mode()
        if installation_mode is not None:
            return CheckResult(
                id="automation_package",
                status="ok",
                category=BOOTSTRAP_CATEGORY,
                message=f"{installation_mode} で automation パッケージ導入済み",
            )
        return CheckResult(
            id="automation_package",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message="automation パッケージが pyproject.toml の dependencies に無い",
            next_action=_ai_exec_action(
                ["uv", "add", f"git+https://github.com/{UPSTREAM_REPO}.git"],
                auto_apply=False,
            ),
        )
    return CheckResult(
        id="automation_package",
        status="ok",
        category=BOOTSTRAP_CATEGORY,
        message="uv project で automation パッケージ導入済み",
    )


def check_skills_synced(channel_dir: Path) -> CheckResult:
    bootstrap_root = _bootstrap_root(channel_dir)
    skills_dir = bootstrap_root / CLAUDE_SKILLS_DIR
    bundled_skills = bundled_skill_names()
    for legacy_skill in LEGACY_BUNDLED_SKILLS:
        if (skills_dir / legacy_skill / SKILL_FILENAME).exists():
            return _skills_sync_prune_failure(
                f"旧 {legacy_skill} skill が残存: {CLAUDE_SKILLS_DIR / legacy_skill / SKILL_FILENAME}"
            )
    missing_skill_files = [
        Path(skill_name) / SKILL_FILENAME
        for skill_name in bundled_skills
        if not (skills_dir / skill_name / SKILL_FILENAME).is_file()
    ]
    if missing_skill_files:
        sample = ", ".join(str(CLAUDE_SKILLS_DIR / path) for path in missing_skill_files[:5])
        return _skills_sync_failure(f"同梱 skill が未展開: {sample}")
    if not _agents_skills_link_is_valid(bootstrap_root, skills_dir):
        return _skills_sync_warning(f"{AGENTS_SKILLS_LINK} が {CLAUDE_SKILLS_DIR} を指す symlink になっていない")
    return CheckResult(
        id="skills_synced",
        status="ok",
        category=BOOTSTRAP_CATEGORY,
        message=f"skills synced ({len(bundled_skills)} bundled skills)",
    )


def check_numbered_duplicates(channel_dir: Path) -> CheckResult:
    """iCloud Drive 等の同期コンフリクトで生成される番号付き重複ファイルの検知。

    `.venv/bin/` (entry point) と `.claude/skills/` (配布 skill) は uv /
    yt-skills sync が同名上書きで管理する領域のため、`<名前> <数字>` 形式が
    現れたら外部要因 (同期サービス) による汚染とみなす (#1409 / #1410)。
    """
    bootstrap_root = _bootstrap_root(channel_dir)
    findings: list[str] = []
    scan_targets = (
        (".venv/bin", bootstrap_root / ".venv" / "bin", False),
        (str(CLAUDE_SKILLS_DIR), bootstrap_root / CLAUDE_SKILLS_DIR, True),
    )
    for label, directory, recursive in scan_targets:
        result = scan_numbered_duplicates(directory, recursive=recursive, root_boundary=bootstrap_root)
        if result.duplicates:
            sample = ", ".join(format_duplicate_name(path) for path in result.duplicates[:3])
            findings.append(f"{label} に {len(result.duplicates)} 件 (例: {sample})")
        for error in result.errors:
            findings.append(
                f"{label} を走査できません "
                f"({format_duplicate_name(error.path)}: {format_scan_error_reason(error.reason)})"
            )
    if not findings:
        return CheckResult(
            id="numbered_duplicates",
            status="ok",
            category=BOOTSTRAP_CATEGORY,
            message="番号付き重複ファイルなし",
        )
    return CheckResult(
        id="numbered_duplicates",
        status="warn",
        category=BOOTSTRAP_CATEGORY,
        message="番号付き重複ファイルを検出: " + " / ".join(findings),
        next_action={
            "kind": "human",
            "instructions": (
                "iCloud Drive 等のクラウド同期コンフリクトで生成された可能性が高い。"
                "リポジトリが同期対象パス (~/Desktop, ~/Documents, iCloud Drive) に"
                "ないか確認する。`.venv` は `rm -rf .venv && uv sync` で再作成、"
                f"{CLAUDE_SKILLS_DIR} は重複を削除して `{SKILLS_SYNC_CMD}` で再展開する。"
                f"詳細手順: {CLEANUP_GUIDE_URL}"
            ),
        },
    )


def check_gcloud() -> CheckResult:
    code, out, _ = _run(["gcloud", "--version"])
    if code != 0:
        return CheckResult(
            id="gcloud",
            status="fail",
            message="gcloud CLI が見つからない",
            next_action={
                "kind": "human",
                "instructions": (
                    "macOS なら `brew install --cask google-cloud-sdk`、"
                    "その他は https://cloud.google.com/sdk/docs/install を参照"
                ),
            },
        )
    first_line = out.splitlines()[0] if out else "unknown"
    return CheckResult(id="gcloud", status="ok", message=first_line)


def check_gcloud_account() -> CheckResult:
    code, out, err = _run(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=json"])
    if code != 0:
        return CheckResult(
            id="gcloud_account",
            status="unknown",
            message=f"gcloud auth list 失敗: {(err or out).strip()}",
        )
    try:
        accounts = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        accounts = []
    if not accounts:
        return CheckResult(
            id="gcloud_account",
            status="fail",
            message="active な gcloud アカウントが無い",
            next_action=_human_auth_action(
                ["gcloud", "auth", "login"],
                "AI または setup が `gcloud auth login` を対話 session で起動し、"
                "利用者はブラウザで Google ログインと同意を完了してください。",
            ),
        )
    return CheckResult(
        id="gcloud_account",
        status="ok",
        message=f"active: {accounts[0].get('account', 'unknown')}",
    )


def check_gcp_project(channel_dir: Path) -> CheckResult:
    project_id = _project_id_for(channel_dir)
    if not project_id:
        return CheckResult(
            id="gcp_project",
            status="fail",
            message="project_id が環境変数 / ADC quota project のいずれにも無い",
        )
    code, _, err = _run(["gcloud", "projects", "describe", project_id, "--format=value(projectId)"])
    if code != 0:
        return CheckResult(
            id="gcp_project",
            status="fail",
            message=f"プロジェクト {project_id} が見つからない: {err.strip()}",
        )
    return CheckResult(id="gcp_project", status="ok", message=f"プロジェクト {project_id} 存在")


def check_billing(channel_dir: Path) -> CheckResult:
    project_id = _project_id_for(channel_dir)
    if not project_id:
        return CheckResult(
            id="billing_linked",
            status="unknown",
            message="project_id が未設定のためスキップ",
        )
    code, out, err = _run(
        [
            "gcloud",
            "beta",
            "billing",
            "projects",
            "describe",
            project_id,
            "--format=value(billingEnabled)",
        ]
    )
    if code != 0:
        return CheckResult(
            id="billing_linked",
            status="fail",
            message=f"billing 情報取得失敗: {err.strip()}",
        )
    if out.strip().lower() != "true":
        return CheckResult(
            id="billing_linked",
            status="fail",
            message=f"プロジェクト {project_id} に billing 未紐付け",
            next_action={
                "kind": "ai-exec",
                "cmd": (
                    "gcloud beta billing accounts list --format=json で候補確認 → "
                    f"gcloud beta billing projects link {project_id} --billing-account=<ID>"
                ),
            },
        )
    return CheckResult(id="billing_linked", status="ok", message="billing 紐付け済み")


def check_apis_enabled(channel_dir: Path) -> CheckResult:
    project_id = _project_id_for(channel_dir)
    if not project_id:
        return CheckResult(
            id="apis_enabled",
            status="unknown",
            message="project_id が未設定のためスキップ",
        )
    code, out, err = _run(
        [
            "gcloud",
            "services",
            "list",
            "--enabled",
            f"--project={project_id}",
            "--format=value(config.name)",
        ]
    )
    if code != 0:
        return CheckResult(
            id="apis_enabled",
            status="fail",
            message=f"services list 失敗: {err.strip()}",
        )
    enabled = set(out.strip().splitlines())
    missing = [a for a in REQUIRED_APIS if a not in enabled]
    if missing:
        return CheckResult(
            id="apis_enabled",
            status="fail",
            message=f"未有効 API: {', '.join(missing)}",
            next_action=_ai_exec_action(["gcloud", "services", "enable", *missing, f"--project={project_id}"]),
        )
    return CheckResult(
        id="apis_enabled",
        status="ok",
        message=f"{len(REQUIRED_APIS)} 個の必須 API 有効",
    )


def check_adc() -> CheckResult:
    code, _, _ = _run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        timeout=15,
    )
    if code != 0:
        return CheckResult(
            id="adc",
            status="fail",
            message="ADC が未設定 (print-access-token 失敗)",
            next_action=_human_auth_action(
                ["gcloud", "auth", "application-default", "login"],
                "AI または setup が `gcloud auth application-default login` を対話 session で起動し、"
                "利用者はブラウザで Google ログインと同意を完了してください。",
            ),
        )
    return CheckResult(id="adc", status="ok", message="ADC 有効")


def check_adc_quota_project(channel_dir: Path) -> CheckResult:
    project_id = _project_id_for(channel_dir)
    if not project_id:
        return CheckResult(
            id="adc_quota_project",
            status="unknown",
            message="project_id が未設定のため判定不可",
        )
    adc_json = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if not adc_json.exists():
        return CheckResult(
            id="adc_quota_project",
            status="unknown",
            message="ADC 認証ファイルが見つからない",
        )
    try:
        data = json.loads(adc_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return CheckResult(
            id="adc_quota_project",
            status="unknown",
            message="ADC 認証ファイル読み込み失敗",
        )
    quota = data.get("quota_project_id")
    if quota != project_id:
        return CheckResult(
            id="adc_quota_project",
            status="warn",
            message=(f"ADC quota project ({quota}) が project_id ({project_id}) と不一致"),
            next_action=_ai_exec_action(["gcloud", "auth", "application-default", "set-quota-project", project_id]),
        )
    return CheckResult(
        id="adc_quota_project",
        status="ok",
        message=f"ADC quota project = {project_id}",
    )


def check_iam_aiplatform_user(channel_dir: Path) -> CheckResult:
    project_id = _project_id_for(channel_dir)
    if not project_id:
        return CheckResult(
            id="iam_aiplatform_user",
            status="unknown",
            message="project_id が未設定のためスキップ",
        )
    code, out, _ = _run(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"])
    if code != 0 or not out.strip():
        return CheckResult(
            id="iam_aiplatform_user",
            status="unknown",
            message="active アカウント取得失敗",
        )
    account = out.strip().splitlines()[0]
    code, out, err = _run(
        [
            "gcloud",
            "projects",
            "get-iam-policy",
            project_id,
            "--flatten=bindings[].members",
            (f"--filter=bindings.role:roles/aiplatform.user AND bindings.members:user:{account}"),
            "--format=value(bindings.role)",
        ]
    )
    if code != 0:
        return CheckResult(
            id="iam_aiplatform_user",
            status="fail",
            message=f"IAM policy 取得失敗: {err.strip()}",
        )
    if not out.strip():
        return CheckResult(
            id="iam_aiplatform_user",
            status="fail",
            message=f"user:{account} に roles/aiplatform.user 未付与",
            next_action=_ai_exec_action(
                [
                    "gcloud",
                    "projects",
                    "add-iam-policy-binding",
                    project_id,
                    f"--member=user:{account}",
                    "--role=roles/aiplatform.user",
                    "--condition=None",
                    "--quiet",
                ]
            ),
        )
    return CheckResult(
        id="iam_aiplatform_user",
        status="ok",
        message=f"user:{account} は roles/aiplatform.user を保持",
    )


def _load_client_secrets_data(channel_dir: Path) -> tuple[Path | str, object | None, str | None, str | None]:
    """client_secrets を副作用なしで読み込む。

    実行時 OAuth は 1Password fallback を一時ファイル化して
    InstalledAppFlow に渡すが、yt-doctor は read-only 診断なので
    `CLIENT_SECRETS_JSON` をメモリ上で構造検査する。
    """
    kind, path = resolve_client_secrets_location(channel_dir)
    if kind == "file":
        try:
            return path, json.loads(path.read_text(encoding="utf-8")), None, None
        except (json.JSONDecodeError, OSError) as e:
            return path, None, f"client_secrets.json 読み込み失敗: {e}", None
    if kind == "invalid-file":
        return path, None, f"client_secrets.json は通常ファイルである必要があります: {path}", None

    if kind == "secret-fallback":
        try:
            from youtube_automation.core.errors import ConfigError
            from youtube_automation.infrastructure.secrets import get_secret

            return "CLIENT_SECRETS_JSON", json.loads(get_secret("CLIENT_SECRETS_JSON")), None, None
        except ConfigError as e:
            return path, None, None, f"1Password / CLIENT_SECRETS_JSON fallback 取得失敗: {e}"
        except json.JSONDecodeError as e:
            return "CLIENT_SECRETS_JSON", None, f"CLIENT_SECRETS_JSON 読み込み失敗: {e}", None

    return path, None, None, None


def check_client_secrets(channel_dir: Path) -> CheckResult:
    path, data, error, fallback_error = _load_client_secrets_data(channel_dir)
    if error:
        return CheckResult(
            id="client_secrets",
            status="fail",
            message=error,
        )
    if data is None:
        project_id = _project_id_for(channel_dir) or ""
        fix_destination = channel_dir / "auth" / "client_secrets.json"
        override_instructions = (
            " `CLIENT_SECRETS_DIR` を解除してから fix と再診断を実行してください。" if path != fix_destination else ""
        )
        return CheckResult(
            id="client_secrets",
            status="fail",
            message=f"{path} が無い",
            next_action={
                "kind": "human",
                "url": (
                    f"https://console.cloud.google.com/apis/credentials?project={project_id}"
                    if project_id
                    else "https://console.cloud.google.com/apis/credentials"
                ),
                "instructions": (
                    "Console の Google Auth Platform で Branding を保存し、"
                    "Audience > Test users に OAuth 認証でログインする Google アカウントを追加してください "
                    "(未追加だと初回認証が 403 access_denied で止まります)。"
                    "その後 Clients > Create client で Application type Desktop app を選び、"
                    "Clients > 対象 client > Client secrets > Add secret で secret を発行してください。"
                    "続けて Download JSON を実行して Downloads に保存し、"
                    "`uv run yt-doctor --fix-client-secrets` で "
                    f"`{fix_destination}` へ自動移動してください。"
                    + override_instructions
                    + (f" fallback 状態: {fallback_error}" if fallback_error else "")
                ),
            },
        )
    assert data is not None
    if not isinstance(data, dict):
        return CheckResult(
            id="client_secrets",
            status="fail",
            message="client_secrets.json は JSON object である必要があります",
        )
    installed = data.get("installed")
    if not isinstance(installed, dict):
        return CheckResult(
            id="client_secrets",
            status="fail",
            message="Desktop app の client_secrets.json が必要です: installed セクションがありません",
        )
    required_keys = ("client_id", "client_secret", "redirect_uris")
    missing = [k for k in required_keys if k not in installed]
    if missing:
        return CheckResult(
            id="client_secrets",
            status="fail",
            message=f"client_secrets.json に必須キー不足: {','.join(missing)}",
        )
    return CheckResult(id="client_secrets", status="ok", message="client_secrets.json 構造妥当")


def check_oauth_client_sharing(channel_dir: Path) -> CheckResult:
    """per-channel OAuth client を workspace ルートで共有できる場合に案内する。"""
    workspace_root = find_workspace_root(channel_dir)
    channels = workspace_channels(workspace_root) if workspace_root is not None else {}
    if workspace_root is None or channel_dir.resolve() not in {path.resolve() for path in channels.values()}:
        return CheckResult(
            id="oauth_client_sharing",
            status="ok",
            message="単一チャンネル構成のため OAuth クライアント共有診断は対象外",
        )

    per_channel_secrets = [slug for slug, path in channels.items() if (path / "auth" / "client_secrets.json").is_file()]
    if len(per_channel_secrets) < 2:
        return CheckResult(
            id="oauth_client_sharing",
            status="ok",
            message="個別 OAuth クライアントを持つ workspace チャンネルは複数ありません",
        )

    shared_path = workspace_root / "auth" / "client_secrets.json"
    return CheckResult(
        id="oauth_client_sharing",
        status="info",
        message=(f"OAuth クライアントをルート共有（{shared_path}）へ統合可能。統合には全チャンネルの再認証が必要"),
        data={"channels": per_channel_secrets, "shared_path": str(shared_path)},
    )


def _oauth_failure_action(state: OAuthCredentialState) -> dict | None:
    if not state.reauthentication_required:
        return None
    return _youtube_oauth_action("更新用トークンが利用できないため、ブラウザで OAuth 同意を完了してください。")


def check_oauth_token(channel_dir: Path) -> CheckResult:
    path = channel_dir / "auth" / "token.json"
    if not path.exists():
        return CheckResult(
            id="oauth_token",
            status="fail",
            message=f"{path} が無い",
            next_action=_youtube_oauth_action("初回 OAuth 認証として対象アカウントを選択してください。"),
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return CheckResult(
            id="oauth_token",
            status="fail",
            message=f"token.json 読み込み失敗: {e}",
        )
    state = load_refreshable_credentials(path)
    if state.credentials is None:
        return CheckResult(
            id="oauth_token",
            status="fail",
            message=state.error or "OAuth トークンを利用できません",
            next_action=_oauth_failure_action(state),
        )
    scopes = data.get("scopes") or []
    refresh_status = "・期限切れ token 更新済み" if state.refreshed else ""
    return CheckResult(
        id="oauth_token",
        status="ok",
        message=f"token.json 利用可能 (scopes: {len(scopes)} 件{refresh_status})",
    )


def check_oauth_token_readonly(channel_dir: Path) -> CheckResult:
    """Check whether the independently issued read-only token is available."""
    with _temporary_channel_dir(channel_dir):
        path = YouTubeOAuthHandler.readonly_token_path()
    if path is None or not path.is_file():
        return CheckResult(
            id="oauth_token_readonly",
            status="warn",
            message="token.readonly.json が未発行",
            next_action=_youtube_readonly_oauth_action(channel_dir),
        )
    return CheckResult(
        id="oauth_token_readonly",
        status="ok",
        message="token.readonly.json 発行済み",
    )


def check_reporting_job(channel_dir: Path) -> CheckResult:
    token_path = channel_dir / "auth" / "token.json"
    if not token_path.exists():
        return CheckResult(
            id="reporting_job",
            status="unknown",
            message="OAuth トークン未取得または不正のためスキップ",
        )

    state = load_refreshable_credentials(token_path)
    if state.credentials is None:
        return CheckResult(
            id="reporting_job",
            status="fail",
            message=f"Reporting API ジョブ確認失敗: {state.error}",
            next_action=_oauth_failure_action(state),
        )
    credentials = state.credentials

    try:
        with _temporary_channel_dir(channel_dir), redirect_stdout(io.StringIO()):
            service = build("youtubereporting", "v1", credentials=credentials)
            client = ReportingAPIClient(service)
            report_type_id = client.select_report_type()
            existing_job = client.find_existing_job(report_type_id)
    except HttpError as error:
        api_error = YouTubeAPIError.from_http_error(error, "reporting:jobs.list")
        return CheckResult(
            id="reporting_job",
            status="fail",
            message=f"Reporting API ジョブ確認失敗: {api_error}",
        )
    except (AutomationError, FileNotFoundError, HttpLib2Error, OSError) as error:
        return CheckResult(
            id="reporting_job",
            status="fail",
            message=f"Reporting API ジョブ確認失敗: {error}",
        )

    if existing_job is None:
        return CheckResult(
            id="reporting_job",
            status="fail",
            message="Reporting API ジョブが未作成",
            next_action=_ai_exec_action(["uv", "run", "yt-analytics", "--reporting-create-job"]),
        )

    return CheckResult(
        id="reporting_job",
        status="ok",
        message=f"Reporting API ジョブ作成済み (jobId: {existing_job['id']})",
    )


def check_streaming_vps_state(channel_dir: Path) -> CheckResult:
    """Vultr 上の streaming VPS と全 GCS workspace state を突合する。"""
    terraform_dir = _bootstrap_root(channel_dir) / "infra" / "terraform" / "streaming"
    if not terraform_dir.is_dir():
        return CheckResult(
            id="streaming_vps_state",
            status="info",
            message="streaming Terraform module がないため VPS state 突合をスキップ",
            data={"reason": "streaming_terraform_module_missing"},
        )

    api_key = os.environ.get("VULTR_API_KEY", "").strip() or os.environ.get("TF_VAR_vultr_api_key", "").strip()
    if not api_key:
        return CheckResult(
            id="streaming_vps_state",
            status="info",
            message="Vultr API key 未設定のため VPS state 突合をスキップ",
            data={"reason": "vultr_api_key_missing"},
        )

    try:
        inventory = reconcile_streaming_vps(
            terraform_dir=terraform_dir,
            api_key=api_key,
            run_command=_run,
        )
    except AutomationError as error:
        return CheckResult(
            id="streaming_vps_state",
            status="unknown",
            message=f"streaming VPS state 突合に失敗: {error}",
        )

    unmanaged_ids = sorted(inventory.unmanaged_instance_ids)
    data = {
        "actual_instance_count": len(inventory.actual_instance_ids),
        "managed_instance_count": len(inventory.managed_instance_ids),
        "unmanaged_instance_ids": unmanaged_ids,
    }
    if unmanaged_ids:
        return CheckResult(
            id="streaming_vps_state",
            status="warn",
            message=f"Terraform state 管理外の youtube-stream VPS を検出: {', '.join(unmanaged_ids)}",
            next_action={
                "kind": "human",
                "instructions": (
                    "`infra/terraform/streaming/README.md` の既存 Vultr リソース import 手順で"
                    "対応 workspace へ手動 import し、`uv run yt-doctor --json` を再実行してください"
                ),
            },
            data=data,
        )

    return CheckResult(
        id="streaming_vps_state",
        status="ok",
        message="youtube-stream VPS はすべて Terraform state 管理下",
        data=data,
    )


def check_channel_config(channel_dir: Path) -> CheckResult:
    config_dir = channel_dir / "config" / "channel"

    if not config_dir.is_dir():
        return CheckResult(
            id="channel_config",
            status="fail",
            category=CHANNEL_CATEGORY,
            message="config/channel/ ディレクトリが存在しない (新規チャンネル、setup 用ディレクトリのみでは未生成)",
            next_action={
                "kind": "human",
                "instructions": (
                    "setup 用ディレクトリ生成は完了していても config は未作成です。"
                    "/setup --channel を実行して新規チャンネル設定を作成してください"
                ),
            },
        )

    from youtube_automation.configuration import load_config
    from youtube_automation.core.errors import ConfigError
    from youtube_automation.domains.metadata import validate_localizations_title_templates

    with _temporary_channel_dir(channel_dir):
        try:
            config = load_config()
            localization_errors = validate_localizations_title_templates(config.localizations.data)
            if localization_errors:
                return CheckResult(
                    id="channel_config",
                    status="fail",
                    category=CHANNEL_CATEGORY,
                    message="config/localizations.json 検証失敗: " + "\n".join(localization_errors),
                    next_action={
                        "kind": "human",
                        "instructions": ("/setup --import を実行して設定を修復してください"),
                    },
                )
            return CheckResult(
                id="channel_config",
                status="ok",
                category=CHANNEL_CATEGORY,
                message="config/channel/ ロード成功",
            )
        except ConfigError as e:
            return CheckResult(
                id="channel_config",
                status="fail",
                category=CHANNEL_CATEGORY,
                message=f"config/channel/ ロード失敗: {e}",
                next_action={
                    "kind": "human",
                    "instructions": ("/setup --import を実行して設定を修復してください"),
                },
            )


def check_playlist_config(channel_dir: Path) -> CheckResult:
    path = channel_dir / "config" / "channel" / "playlists.json"
    if not path.exists():
        return CheckResult(
            id="playlist_config",
            status="warn",
            category=CHANNEL_CATEGORY,
            message="config/channel/playlists.json が存在しない",
            next_action={
                "kind": "human",
                "instructions": (
                    "/setup --regenerate で config/channel/playlists.json を作成し、"
                    "playlist スキルが使う playlists 定義を追加してください"
                ),
            },
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return CheckResult(
            id="playlist_config",
            status="fail",
            category=CHANNEL_CATEGORY,
            message=f"config/channel/playlists.json JSON パース失敗: {e}",
            next_action={
                "kind": "human",
                "instructions": "config/channel/playlists.json の JSON 構文を修正してください",
            },
        )
    except OSError as e:
        return CheckResult(
            id="playlist_config",
            status="fail",
            category=CHANNEL_CATEGORY,
            message=f"config/channel/playlists.json 読み込み失敗: {e}",
            next_action={
                "kind": "human",
                "instructions": "config/channel/playlists.json の存在と読み取り権限を確認してください",
            },
        )

    if not isinstance(data, dict):
        return CheckResult(
            id="playlist_config",
            status="fail",
            category=CHANNEL_CATEGORY,
            message="config/channel/playlists.json のトップレベルは object でなければなりません",
            next_action={
                "kind": "human",
                "instructions": 'config/channel/playlists.json を {"playlists": {...}} 形式に修正してください',
            },
        )

    playlists = data.get("playlists")
    if playlists is None:
        return CheckResult(
            id="playlist_config",
            status="warn",
            category=CHANNEL_CATEGORY,
            message="config/channel/playlists.json に playlists セクションがありません",
            next_action={
                "kind": "human",
                "instructions": "config/channel/playlists.json に playlists セクションを追加してください",
            },
        )
    if not isinstance(playlists, dict):
        return CheckResult(
            id="playlist_config",
            status="fail",
            category=CHANNEL_CATEGORY,
            message=f"playlists セクションは object でなければなりません（got {type(playlists).__name__}）",
            next_action={
                "kind": "human",
                "instructions": (
                    'playlists セクションを {"key": {"playlist_id": "...", "title": "..."}} 形式に修正してください'
                ),
            },
        )

    invalid_entries: list[str] = []
    missing_playlist_ids: list[str] = []
    for key, value in playlists.items():
        display_key = _format_external_display_value(key)
        if isinstance(value, str):
            if not value.strip():
                missing_playlist_ids.append(display_key)
            continue
        if isinstance(value, dict):
            playlist_id = value.get("playlist_id")
            if not isinstance(playlist_id, str) or not playlist_id.strip():
                missing_playlist_ids.append(display_key)
            continue
        invalid_entries.append(f"{display_key} ({type(value).__name__})")

    if invalid_entries:
        return CheckResult(
            id="playlist_config",
            status="fail",
            category=CHANNEL_CATEGORY,
            message=f"playlists の値は string または object でなければなりません: {', '.join(invalid_entries)}",
            next_action={
                "kind": "human",
                "instructions": (
                    "各 playlist 定義を playlist_id 文字列、または playlist_id/title を持つ object に修正してください"
                ),
            },
        )

    if missing_playlist_ids:
        return CheckResult(
            id="playlist_config",
            status="warn",
            category=CHANNEL_CATEGORY,
            message=f"playlist_id 未設定: {', '.join(missing_playlist_ids)}",
            next_action={
                "kind": "human",
                "instructions": (
                    "`uv run yt-playlist-manager --init --dry-run` で作成計画を確認し、"
                    "問題なければ `uv run yt-playlist-manager --init` で playlist_id を書き戻してください"
                ),
            },
        )

    return CheckResult(
        id="playlist_config",
        status="ok",
        category=CHANNEL_CATEGORY,
        message=f"config/channel/playlists.json ロード成功 ({len(playlists)} 件)",
    )


def check_playlist_create_dry_run(channel_dir: Path) -> CheckResult:
    from youtube_automation.core.errors import ConfigError
    from youtube_automation.domains.uploads.playlists import PlaylistManager

    with _temporary_channel_dir(channel_dir):
        try:
            manager = PlaylistManager()
            missing_titles = [
                _format_external_display_value(key)
                for key, playlist in manager.config.playlists.items.items()
                if not playlist.get("playlist_id")
                and (not isinstance(playlist.get("title"), str) or not playlist["title"].strip())
            ]
            if missing_titles:
                return CheckResult(
                    id="playlist_create_dry_run",
                    status="fail",
                    category=CHANNEL_CATEGORY,
                    message=f"playlist 作成 dry-run の title 未設定: {', '.join(missing_titles)}",
                    next_action={
                        "kind": "human",
                        "instructions": (
                            "playlist_id 未設定の playlist 定義には title を追加してください。"
                            "`uv run yt-playlist-manager --init --dry-run` の作成計画に必要です"
                        ),
                    },
                )
            with redirect_stdout(io.StringIO()):
                manager.create_all_playlists(dry_run=True)
        except ConfigError as e:
            return CheckResult(
                id="playlist_create_dry_run",
                status="fail",
                category=CHANNEL_CATEGORY,
                message=f"playlist 作成 dry-run の設定ロード失敗: {e}",
                next_action={
                    "kind": "human",
                    "instructions": "config/channel/*.json と config/channel/playlists.json の設定を修正してください",
                },
            )
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            return CheckResult(
                id="playlist_create_dry_run",
                status="fail",
                category=CHANNEL_CATEGORY,
                message=f"playlist 作成 dry-run 失敗: {e}",
                next_action={
                    "kind": "human",
                    "instructions": (
                        "`uv run yt-playlist-manager --init --dry-run` を実行し、"
                        "表示されたエラーに従って playlists.json または認証/API 前提を修正してください"
                    ),
                },
            )

    return CheckResult(
        id="playlist_create_dry_run",
        status="ok",
        category=CHANNEL_CATEGORY,
        message="PlaylistManager.create_all_playlists(dry_run=True) 成功",
    )


@contextmanager
def _temporary_channel_dir(channel_dir: Path) -> Iterator[None]:
    """Temporarily point config singleton consumers at ``channel_dir``."""
    from youtube_automation.configuration import reset as reset_config

    old_env = os.environ.get("CHANNEL_DIR")
    os.environ["CHANNEL_DIR"] = str(channel_dir)
    try:
        reset_config()
        yield
    finally:
        reset_config()
        if old_env is None:
            os.environ.pop("CHANNEL_DIR", None)
        else:
            os.environ["CHANNEL_DIR"] = old_env


def check_analytics_report(channel_dir: Path) -> CheckResult:
    input_mode = _resolve_wf_new_input_mode(channel_dir)
    if input_mode.invalid_report:
        return CheckResult(
            id="analytics_report",
            status="fail",
            category=DATA_CATEGORY,
            message="reports/analysis_*.json が schema 不正、HTML 欠損、または JSON と不一致",
            next_action={"kind": "human", "instructions": "/analytics --analyze を再実行してください"},
        )
    if input_mode.stale_report:
        if input_mode.stale_reason == "absolute":
            message = (
                "最新 data/analytics_data_*.json が実行日から freshness_days を超えて古い。"
                "/wf-new は stale report では開始不可"
            )
            instructions = "/analytics --collect → /analytics --analyze の順で再実行してください"
        else:
            message = (
                "reports/analysis_*.json が最新 data/analytics_data_*.json より古い。"
                "/wf-new は stale report では開始不可"
            )
            instructions = "/analytics --analyze を再実行してください（必要なら先に /analytics --collect）"
        return CheckResult(
            id="analytics_report",
            status="fail",
            category=DATA_CATEGORY,
            message=message,
            next_action={
                "kind": "human",
                "instructions": instructions,
            },
        )

    if input_mode.report_count > 0:
        return CheckResult(
            id="analytics_report",
            status="ok",
            category=DATA_CATEGORY,
            message=f"reports/analysis_*.json {input_mode.report_count} 件存在 ({input_mode.mode})",
        )

    return CheckResult(
        id="analytics_report",
        status="ok",
        category=DATA_CATEGORY,
        message=f"reports/analysis_*.json 未生成。/wf-new は {input_mode.mode} で開始可能",
    )


def _resolve_wf_new_input_mode(channel_dir: Path) -> _WfNewInputMode:
    data_dir = channel_dir / "data"
    reports = resolve_artifacts(channel_dir, "reports/analysis_*.json")
    benchmarks = _matching_files(data_dir, "benchmark_*.json")
    data_files = _matching_files(data_dir, "analytics_data_*.json")

    if reports.valid:
        latest_data = _latest_filename_date(data_files)
        freshness = reports.freshness(against=data_files)
        stale_reason = freshness.reason if freshness.is_stale else None
        if stale_reason == "missing":
            stale_reason = None
        elif (
            stale_reason is None
            and latest_data is not None
            and _analytics_data_exceeds_freshness_days(latest_data[0], channel_dir)
        ):
            stale_reason = "absolute"
        return _WfNewInputMode(
            mode="analytics mode",
            report_count=len(reports.valid),
            benchmark_count=len(benchmarks),
            stale_report=stale_reason is not None,
            stale_reason=stale_reason,
            invalid_report=bool(reports.invalid),
        )
    if reports.invalid:
        return _WfNewInputMode(
            mode="invalid analytics report",
            report_count=len(reports.invalid),
            benchmark_count=len(benchmarks),
            stale_report=False,
            invalid_report=True,
        )
    if benchmarks:
        return _WfNewInputMode(
            mode="benchmark fallback mode",
            report_count=0,
            benchmark_count=len(benchmarks),
            stale_report=False,
        )
    return _WfNewInputMode(
        mode="minimal mode",
        report_count=0,
        benchmark_count=0,
        stale_report=False,
    )


def _matching_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def _latest_filename_date(paths: list[Path]) -> Optional[tuple[str, Path]]:
    dated_paths: list[tuple[str, Path]] = []
    for path in paths:
        match = re.search(r"(\d{8})", path.name)
        if match:
            dated_paths.append((match.group(1), path))
    if not dated_paths:
        return None
    return max(dated_paths, key=lambda item: item[0])


def _analytics_data_exceeds_freshness_days(data_date: str, channel_dir: Path) -> bool:
    cfg = load_skill_config("collection-ideate", use_cache=False, channel_dir=channel_dir)
    freshness_days = _parse_positive_int(cfg.get("freshness_days", 7), "collection-ideate.freshness_days")
    elapsed_days = (_yyyymmdd_to_date(_today_yyyymmdd()) - _yyyymmdd_to_date(data_date)).days
    return elapsed_days > freshness_days


def _parse_positive_int(value: object, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} は整数である必要があります: {value!r}") from exc
    if parsed < 0:
        raise ConfigError(f"{label} は 0 以上である必要があります: {value!r}")
    return parsed


def _yyyymmdd_to_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _today_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def check_benchmark_data(channel_dir: Path) -> CheckResult:
    input_mode = _resolve_wf_new_input_mode(channel_dir)
    if input_mode.benchmark_count > 0:
        return CheckResult(
            id="benchmark_data",
            status="ok",
            category=DATA_CATEGORY,
            message=f"data/benchmark_*.json {input_mode.benchmark_count} 件存在 ({input_mode.mode} 対応)",
        )

    if input_mode.mode == "analytics mode":
        return CheckResult(
            id="benchmark_data",
            status="ok",
            category=DATA_CATEGORY,
            message=(
                "data/benchmark_*.json 未生成。analytics mode では "
                "/wf-new の企画工程が /channel-research --benchmark の鮮度確認・必要時更新を扱う"
            ),
        )

    return CheckResult(
        id="benchmark_data",
        status="ok",
        category=DATA_CATEGORY,
        message=f"data/benchmark_*.json 未生成。/wf-new は {input_mode.mode} で開始可能",
    )


def check_wf_new_readiness(channel_dir: Path) -> CheckResult:
    input_mode = _resolve_wf_new_input_mode(channel_dir)
    collection_ideate_config = load_skill_config("collection-ideate", use_cache=False, channel_dir=channel_dir)
    ttp_mode = collection_ideate_config.get("ttp_mode", False) is True
    ttp_mode_display = str(ttp_mode).lower()

    if ttp_mode and input_mode.mode == "minimal mode":
        return CheckResult(
            id="wf_new_readiness",
            status="warn",
            category=DATA_CATEGORY,
            message=(
                "minimal mode / ttp_mode: true では転写元ベンチマークが必須のため、"
                "/wf-new の企画工程が停止し、制作開始へ到達不可"
            ),
            next_action={
                "kind": "human",
                "instructions": (
                    "config/channel/analytics.json::benchmark.channels に TTP 対象を保存 → "
                    "/channel-research --benchmark を実行 → `uv run yt-doctor --json` を再実行してください"
                ),
            },
        )

    return CheckResult(
        id="wf_new_readiness",
        status="ok",
        category=DATA_CATEGORY,
        message=f"{input_mode.mode} / ttp_mode: {ttp_mode_display} で /wf-new を開始可能",
    )


def _readiness_check_result(check_id: str, result: ReadinessResult) -> CheckResult:
    return CheckResult(
        id=check_id,
        status=result.status,
        category=DATA_CATEGORY,
        message=result.message,
        next_action=result.next_action,
    )


def _approved_ttp_exceptions(seed_text: str) -> tuple[set[str], list[str]]:
    return approved_ttp_exceptions(seed_text)


def check_ttp_wf_new_readiness(channel_dir: Path) -> CheckResult:
    return _readiness_check_result("ttp_wf_new_readiness", evaluate_ttp_wf_new_readiness(channel_dir))


def check_initial_setup_readiness(channel_dir: Path) -> CheckResult:
    return _readiness_check_result("initial_setup_readiness", evaluate_initial_setup_readiness(channel_dir))


def _upload_ready_api_error_result(error: YouTubeAPIError) -> CheckResult:
    status_code = error.status_code
    is_quota_or_server_error = (
        status_code == 429
        or (status_code is not None and 500 <= status_code < 600)
        or (status_code == 403 and error.reason in QUOTA_REASONS)
    )
    is_auth_error = status_code == 401 or (status_code == 403 and error.reason not in QUOTA_REASONS)

    if is_auth_error:
        status = "fail"
        instructions = "承認後に AI が auth/token.json を削除してから、意図したアカウントで再認証してください。"
    elif is_quota_or_server_error:
        status = "warn"
        instructions = "クォータのリセットまたはサービス復旧を待ってから `uv run yt-doctor` を再実行してください"
    else:
        status = "warn"
        instructions = "時間をおいて `uv run yt-doctor` を再実行してください"

    next_action = (
        _youtube_oauth_action(instructions) if is_auth_error else {"kind": "human", "instructions": instructions}
    )
    return CheckResult(
        id="upload_ready",
        status=status,
        category=UPLOAD_CATEGORY,
        message=(f"チャンネル存在確認の API 呼び出しに失敗しました（チャンネル未作成とは判定していません）: {error}"),
        next_action=next_action,
        data={"reason": "api_error", "api_context": str(error)},
    )


def check_upload_ready(channel_dir: Path) -> CheckResult:
    token_path = channel_dir / "auth" / "token.json"

    if not token_path.exists():
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message="auth/token.json が存在しない",
            next_action=_youtube_oauth_action("対象アカウントを選択してください。"),
        )

    try:
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message=f"token.json 読み込み失敗: {e}",
        )

    token_scopes = set(token_data.get("scopes") or [])
    missing_scopes = [s for s in UPLOAD_REQUIRED_SCOPES if s not in token_scopes]

    meta_path = channel_dir / "config" / "channel" / "meta.json"
    channel_id: Optional[str] = None
    meta_issue: Optional[str] = None

    if not meta_path.exists():
        meta_issue = "config/channel/meta.json が存在しない"
    else:
        try:
            meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta_data, dict):
                meta_issue = "meta.json の形式が不正 (dict でない)"
            else:
                raw_channel_id = (meta_data.get("channel") or {}).get("channel_id")
                channel_id = raw_channel_id if raw_channel_id else None
                if channel_id is None:
                    meta_issue = "channel.channel_id が未設定"
        except (json.JSONDecodeError, OSError) as e:
            meta_issue = f"meta.json 読み込み失敗: {e}"

    issues = []
    if missing_scopes:
        issues.append(f"upload 必須 scope 不足: {', '.join(missing_scopes)}")
    if meta_issue:
        issues.append(meta_issue)

    # scope 不足が最優先事由: 再認証が必要
    if missing_scopes:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message="; ".join(issues),
            next_action=_youtube_oauth_action(
                "承認後に AI が token.json を削除します。"
                "youtube / youtube.force-ssl scope を含む同意を完了してください。"
            ),
        )

    if meta_issue:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message="; ".join(issues),
            next_action={
                "kind": "human",
                "instructions": (
                    "config/channel/meta.json の channel.channel_id に YouTube チャンネル ID を設定してください。"
                    "`uv run yt-channel-status` でチャンネル ID を確認できます。"
                ),
            },
        )

    try:
        credentials = load_credentials(token_path)
    except (OSError, ValueError) as error:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message=f"token.json から credentials を構築できません: {error}",
            next_action=_youtube_oauth_action("承認後に AI が auth/token.json を削除してから再認証します。"),
        )

    try:
        service = build_youtube_service(credentials)
        response = service.channels().list(part="id,snippet", mine=True).execute()
    except RefreshError:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message="OAuth token の更新に失敗しました。token が期限切れまたは失効しています",
            next_action=_youtube_oauth_action("承認後に AI が auth/token.json を削除してから再認証します。"),
            data={"reason": "oauth_refresh_failed"},
        )
    except HttpError as error:
        return _upload_ready_api_error_result(YouTubeAPIError.from_http_error(error, "doctor:channels.list"))
    except (AutomationError, HttpLib2Error, OSError) as error:
        return CheckResult(
            id="upload_ready",
            status="warn",
            category=UPLOAD_CATEGORY,
            message=(
                f"チャンネル存在確認の API 呼び出しに失敗しました（チャンネル未作成とは判定していません）: {error}"
            ),
            next_action={
                "kind": "human",
                "instructions": "ネットワーク接続を確認して `uv run yt-doctor` を再実行してください",
            },
            data={"reason": "api_error", "api_context": str(error)},
        )

    items = response.get("items") or []
    if not items:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message="認証済みアカウントに YouTube チャンネルが存在しません",
            next_action={
                "kind": "human",
                "instructions": ("YouTube に該当アカウントでログインし、チャンネルを作成してから再実行してください"),
                "url": "https://www.youtube.com/create_channel",
            },
            data={"reason": "channel_not_found"},
        )

    remote_channel_id = items[0].get("id", "")
    if remote_channel_id != channel_id:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message=(
                f"ローカル channel ID ({channel_id}) と認証済みアカウントのチャンネル ID "
                f"({remote_channel_id}) が一致しません。token と meta.json の取り違えの可能性があります"
            ),
            next_action={
                "kind": "human",
                "instructions": (
                    "意図したアカウントの token なら `uv run yt-channel-settings pull "
                    "--channel-id-only --apply` で meta.json を更新し、別アカウントの token なら "
                    "auth/token.json を削除し、AI が `uv run yt-oauth` を background 起動して再認証した後、"
                    "`uv run yt-doctor --json` で検証してください"
                ),
            },
            data={
                "reason": "channel_id_mismatch",
                "remote_channel_id": remote_channel_id,
                "local_channel_id": channel_id,
            },
        )

    return CheckResult(
        id="upload_ready",
        status="ok",
        category=UPLOAD_CATEGORY,
        message="アップロード前提を満たしています（チャンネル存在 + ID 一致を API で確認済み）",
        data={"remote_channel_id": remote_channel_id},
    )


def _without_channel_dir(check: Callable[[], CheckResult]) -> Callable[[Path], CheckResult]:
    def run(_channel_dir: Path) -> CheckResult:
        return check()

    return run


CHECK_REGISTRY = (
    CheckDefinition(
        "ffmpeg", BOOTSTRAP_CATEGORY, _without_channel_dir(check_ffmpeg), ApplyKind.NONE, CwdSemantics.BOOTSTRAP_ROOT
    ),
    CheckDefinition(
        "ffprobe", BOOTSTRAP_CATEGORY, _without_channel_dir(check_ffprobe), ApplyKind.NONE, CwdSemantics.BOOTSTRAP_ROOT
    ),
    CheckDefinition(
        "uv", BOOTSTRAP_CATEGORY, _without_channel_dir(check_uv), ApplyKind.NONE, CwdSemantics.BOOTSTRAP_ROOT
    ),
    CheckDefinition("uv_project", BOOTSTRAP_CATEGORY, check_uv_project, ApplyKind.NONE, CwdSemantics.BOOTSTRAP_ROOT),
    CheckDefinition(
        "automation_package",
        BOOTSTRAP_CATEGORY,
        check_automation_package,
        ApplyKind.NONE,
        CwdSemantics.BOOTSTRAP_ROOT,
    ),
    CheckDefinition(
        "skills_synced",
        BOOTSTRAP_CATEGORY,
        check_skills_synced,
        ApplyKind.AI_EXEC,
        CwdSemantics.BOOTSTRAP_ROOT,
    ),
    CheckDefinition(
        "numbered_duplicates",
        BOOTSTRAP_CATEGORY,
        check_numbered_duplicates,
        ApplyKind.NONE,
        CwdSemantics.BOOTSTRAP_ROOT,
    ),
    CheckDefinition("gcloud", API_CATEGORY, _without_channel_dir(check_gcloud), ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition(
        "gcloud_account", API_CATEGORY, _without_channel_dir(check_gcloud_account), ApplyKind.NONE, CwdSemantics.CHANNEL
    ),
    CheckDefinition("gcp_project", API_CATEGORY, check_gcp_project, ApplyKind.PROJECT, CwdSemantics.CHANNEL),
    CheckDefinition("billing_linked", API_CATEGORY, check_billing, ApplyKind.BILLING, CwdSemantics.CHANNEL),
    CheckDefinition("apis_enabled", API_CATEGORY, check_apis_enabled, ApplyKind.AI_EXEC, CwdSemantics.CHANNEL),
    CheckDefinition("adc", API_CATEGORY, _without_channel_dir(check_adc), ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition(
        "adc_quota_project", API_CATEGORY, check_adc_quota_project, ApplyKind.AI_EXEC, CwdSemantics.CHANNEL
    ),
    CheckDefinition(
        "iam_aiplatform_user", API_CATEGORY, check_iam_aiplatform_user, ApplyKind.AI_EXEC, CwdSemantics.CHANNEL
    ),
    CheckDefinition("client_secrets", API_CATEGORY, check_client_secrets, ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition(
        "oauth_client_sharing", API_CATEGORY, check_oauth_client_sharing, ApplyKind.NONE, CwdSemantics.CHANNEL
    ),
    CheckDefinition("oauth_token", API_CATEGORY, check_oauth_token, ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition(
        "oauth_token_readonly", API_CATEGORY, check_oauth_token_readonly, ApplyKind.NONE, CwdSemantics.CHANNEL
    ),
    CheckDefinition("reporting_job", API_CATEGORY, check_reporting_job, ApplyKind.AI_EXEC, CwdSemantics.CHANNEL),
    CheckDefinition(
        "streaming_vps_state", API_CATEGORY, check_streaming_vps_state, ApplyKind.NONE, CwdSemantics.CHANNEL
    ),
    CheckDefinition("channel_config", CHANNEL_CATEGORY, check_channel_config, ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition("playlist_config", CHANNEL_CATEGORY, check_playlist_config, ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition(
        "playlist_create_dry_run",
        CHANNEL_CATEGORY,
        check_playlist_create_dry_run,
        ApplyKind.NONE,
        CwdSemantics.CHANNEL,
    ),
    CheckDefinition("analytics_report", DATA_CATEGORY, check_analytics_report, ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition("benchmark_data", DATA_CATEGORY, check_benchmark_data, ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition(
        "ttp_wf_new_readiness", DATA_CATEGORY, check_ttp_wf_new_readiness, ApplyKind.NONE, CwdSemantics.CHANNEL
    ),
    CheckDefinition("wf_new_readiness", DATA_CATEGORY, check_wf_new_readiness, ApplyKind.NONE, CwdSemantics.CHANNEL),
    CheckDefinition(
        "initial_setup_readiness", DATA_CATEGORY, check_initial_setup_readiness, ApplyKind.NONE, CwdSemantics.CHANNEL
    ),
    CheckDefinition("upload_ready", UPLOAD_CATEGORY, check_upload_ready, ApplyKind.NONE, CwdSemantics.CHANNEL),
)


def _check_definition(check_id: str) -> CheckDefinition | None:
    return next((definition for definition in CHECK_REGISTRY if definition.id == check_id), None)


def _declared_category(result: CheckResult) -> str:
    definition = _check_definition(result.id)
    return definition.category if definition is not None else result.category


def run_checks(channel_dir: Path, check_ids: Iterable[str]) -> list[CheckResult]:
    """Run the selected check set in registry declaration order."""
    selected_ids = set(check_ids)
    results: list[CheckResult] = []
    for definition in CHECK_REGISTRY:
        if definition.id not in selected_ids:
            continue
        result = definition.run(channel_dir)
        if result.id != definition.id:
            raise RuntimeError(f"doctor check id mismatch: declared={definition.id}, returned={result.id}")
        result.category = definition.category
        results.append(result)
    return results


def run_all_checks(channel_dir: Path) -> list[CheckResult]:
    return run_checks(channel_dir, (definition.id for definition in CHECK_REGISTRY))


def summarize(results: list[CheckResult]) -> dict:
    counts = {"ok": 0, "info": 0, "warn": 0, "fail": 0, "unknown": 0}
    next_check_id: Optional[str] = None
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        if next_check_id is None and r.status in ("fail", "warn", "unknown"):
            next_check_id = r.id
    return {**counts, "next_check_id": next_check_id}


def _first_unresolved_check(results: list[CheckResult]) -> CheckResult | None:
    return next((result for result in results if result.status in ("fail", "warn", "unknown")), None)


@dataclass(frozen=True)
class ExecutedStep:
    check_id: str
    cmd: str
    returncode: int


@dataclass(frozen=True)
class ApplySummary:
    stop_reason: str
    check_id: str | None
    next_action: RemediationAction | None
    executed: tuple[ExecutedStep, ...]
    cmd: str | None = None
    stderr: str | None = None

    def to_dict(self) -> dict:
        payload: dict = {
            "stop_reason": self.stop_reason,
            "check_id": self.check_id,
            "next_action": self.next_action.to_public_dict() if self.next_action else None,
            "executed": [asdict(step) for step in self.executed],
        }
        if self.cmd is not None:
            payload["cmd"] = self.cmd
        if self.stderr is not None:
            payload["stderr"] = self.stderr
        return payload


@dataclass(frozen=True)
class ApplyOutcome:
    results: list[CheckResult]
    summary: ApplySummary
    exit_code: int


def _check_result_to_dict(result: CheckResult) -> dict:
    return {
        "id": result.id,
        "status": result.status,
        "message": result.message,
        "category": _declared_category(result),
        "next_action": result.next_action.to_public_dict() if result.next_action else None,
        "data": result.data,
    }


def _apply_outcome(
    results: list[CheckResult],
    stop_reason: str,
    executed: list[ExecutedStep],
    *,
    check: CheckResult | None = None,
    next_action: RemediationAction | dict | None = None,
    cmd: str | None = None,
    stderr: str | None = None,
    exit_code: int = 0,
) -> ApplyOutcome:
    return ApplyOutcome(
        results=results,
        summary=ApplySummary(
            stop_reason=stop_reason,
            check_id=check.id if check else None,
            next_action=_remediation_action(next_action),
            executed=tuple(executed),
            cmd=cmd,
            stderr=stderr,
        ),
        exit_code=exit_code,
    )


def _run_apply_command(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    return _run(argv, timeout=300, cwd=cwd)


def _forced_project_check(
    results: list[CheckResult],
    project_id: str | None,
    current_project_id: str | None,
) -> CheckResult | None:
    if project_id is None or current_project_id == project_id:
        return None
    gcp_index = next((index for index, result in enumerate(results) if result.id == "gcp_project"), None)
    unresolved_index = next(
        (index for index, result in enumerate(results) if result.status in ("fail", "warn", "unknown")),
        None,
    )
    if gcp_index is None or (unresolved_index is not None and unresolved_index < gcp_index):
        return None
    return CheckResult(id="gcp_project", status="fail", message=f"project {project_id} を選択")


def _run_apply_loop(
    channel_dir: Path,
    project_id: str | None,
    billing_account: str | None,
    executed: list[ExecutedStep],
) -> ApplyOutcome:
    attempted_steps = {(item.check_id, item.cmd) for item in executed}
    while True:
        results = run_all_checks(channel_dir)
        current_project_id = _project_id_for(channel_dir)
        unresolved = _forced_project_check(results, project_id, current_project_id) or _first_unresolved_check(results)
        if unresolved is None:
            return _apply_outcome(results, "completed", executed)
        definition = _check_definition(unresolved.id)
        if definition is None:
            return _apply_outcome(
                results, "human_required", executed, check=unresolved, next_action=unresolved.next_action
            )
        apply_kind = definition.apply_kind
        if apply_kind is ApplyKind.PROJECT and project_id is None:
            return _apply_outcome(
                results,
                "decision_required",
                executed,
                check=unresolved,
                next_action={"kind": "decision", "flag": "--project-id"},
            )
        # remediation がある = billing 未紐付けが確定しているケースだけ --billing-account を要求する。
        # describe 自体の失敗（権限不足など。next_action なし）は
        # account を選んでも解決しないので human_required に落とす。
        if apply_kind is ApplyKind.BILLING and billing_account is None and unresolved.next_action is not None:
            return _apply_outcome(
                results,
                "decision_required",
                executed,
                check=unresolved,
                next_action={"kind": "decision", "flag": "--billing-account"},
            )
        action = unresolved.next_action
        if apply_kind is ApplyKind.PROJECT and project_id is not None:
            action = _ai_exec_action(["gcloud", "config", "set", "project", project_id])
        elif apply_kind is ApplyKind.BILLING and billing_account is not None:
            active_project_id = _project_id_for(channel_dir)
            if not active_project_id:
                return _apply_outcome(
                    results,
                    "decision_required",
                    executed,
                    check=CheckResult(id="gcp_project", status="fail", message="project ID が必要"),
                    next_action={"kind": "decision", "flag": "--project-id"},
                )
            action = _ai_exec_action(
                [
                    "gcloud",
                    "beta",
                    "billing",
                    "projects",
                    "link",
                    active_project_id,
                    f"--billing-account={billing_account}",
                ]
            )
        if apply_kind is ApplyKind.NONE or not isinstance(action, AgentCommand) or not action.auto_apply:
            return _apply_outcome(
                results,
                "human_required",
                executed,
                check=unresolved,
                next_action=action,
            )
        argv = list(action.argv)
        command = shlex.join(argv)
        step_key = (unresolved.id, command)
        if step_key in attempted_steps:
            return _apply_outcome(
                results,
                "command_failed",
                executed,
                check=unresolved,
                next_action=action,
                cmd=command,
                stderr="コマンド成功後の再診断後も未解決です（同じ check が継続）",
                exit_code=1,
            )
        attempted_steps.add(step_key)
        command_cwd = definition.command_cwd(channel_dir)
        returncode, _stdout, stderr = _run_apply_command(argv, command_cwd)
        executed.append(ExecutedStep(unresolved.id, command, returncode))
        if returncode != 0:
            return _apply_outcome(
                results,
                "command_failed",
                executed,
                check=unresolved,
                next_action=action,
                cmd=command,
                stderr=stderr,
                exit_code=1,
            )
        if apply_kind is ApplyKind.PROJECT and project_id is not None:
            _APPLY_PROJECT_ID.set(project_id)
            os.environ["GOOGLE_CLOUD_PROJECT"] = project_id


def run_apply(
    channel_dir: Path,
    project_id: str | None = None,
    billing_account: str | None = None,
) -> ApplyOutcome:
    """診断と ai-exec を human / 決定待ち / 完了まで連続実行する。"""
    executed: list[ExecutedStep] = []
    previous_project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    project_id_token = _APPLY_PROJECT_ID.set(None)
    try:
        return _run_apply_loop(channel_dir, project_id, billing_account, executed)
    finally:
        _APPLY_PROJECT_ID.reset(project_id_token)
        if previous_project_id is None:
            os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
        else:
            os.environ["GOOGLE_CLOUD_PROJECT"] = previous_project_id


def resolve_channel_dir(target: Optional[str]) -> Path:
    if target:
        return Path(target).resolve()
    cwd = Path.cwd().resolve()
    try:
        return channel_dir().resolve()
    except ConfigError:
        selection_requested = (
            explicit_channel_selection() is not None
            or bool(os.environ.get("CHANNEL"))
            or bool(os.environ.get("CHANNEL_DIR"))
            or find_workspace_root(cwd) is not None
        )
        if selection_requested:
            raise
        return cwd


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int

    @classmethod
    def from_stat(cls, metadata: os.stat_result) -> _FileIdentity:
        return cls(metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)


@dataclass(frozen=True)
class _ClientSecretCandidate:
    path: Path
    identity: _FileIdentity
    raw_data: bytes


def _restore_staged_source(staged: Path, original: Path) -> None:
    os.link(staged, original, follow_symlinks=False)
    staged.unlink()
    staged.parent.rmdir()


def _remove_created_destination(destination: Path, expected_identity: tuple[int, int]) -> None:
    metadata = destination.lstat()
    if expected_identity != (metadata.st_dev, metadata.st_ino):
        raise OSError("作成した移動先が置き換えられたため削除しません")
    destination.unlink()


def _rollback_client_secret_install(
    destination: Path,
    destination_identity: tuple[int, int] | None,
    staged_source: Path,
    original_source: Path,
) -> list[str]:
    errors: list[str] = []
    if destination_identity is not None:
        try:
            _remove_created_destination(destination, destination_identity)
        except OSError as error:
            errors.append(f"destination rollback 失敗: {error}")
    try:
        _restore_staged_source(staged_source, original_source)
    except OSError as error:
        errors.append(f"source rollback 失敗: {error}")
    return errors


def fix_client_secrets(channel_dir: Path) -> int:
    """Downloads の対象 OAuth client secret をチャンネルの auth へ移動する。"""
    destination = channel_dir / "auth" / "client_secrets.json"
    if destination.exists() or destination.is_symlink():
        if destination.is_file() and not destination.is_symlink():
            print(f"{destination} は既に存在するためスキップしました")
            return 0
        print(f"{destination} は通常ファイルではないため移動できません")
        return 1

    project_id = _project_id_for(channel_dir)
    if not project_id:
        print("対象チャンネルの GCP project_id を特定できません。GOOGLE_CLOUD_PROJECT または ADC を確認してください。")
        return 1

    matching: list[_ClientSecretCandidate] = []
    errors: list[str] = []
    candidates = list((Path.home() / "Downloads").glob("client_secret*.json"))
    if not candidates:
        print(
            "Downloads に client_secret*.json が見つかりません。"
            "Google Cloud Console で対象 OAuth client の Download JSON を実行してください。"
        )
        return 1

    for candidate in candidates:
        if candidate.is_symlink():
            errors.append(f"{candidate}: 通常ファイルではありません")
            continue
        descriptor: int | None = None
        try:
            descriptor = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as error:
            errors.append(f"{candidate}: ファイル読み込み失敗: {error}")
            continue
        try:
            metadata = os.fstat(descriptor)
        except OSError as error:
            errors.append(f"{candidate}: 更新時刻の取得に失敗: {error}")
            os.close(descriptor)
            continue
        try:
            if not stat.S_ISREG(metadata.st_mode):
                errors.append(f"{candidate}: 通常ファイルではありません")
                continue
            with os.fdopen(descriptor, "rb") as source_file:
                descriptor = None
                raw_data = source_file.read()
            data = json.loads(raw_data)
        except json.JSONDecodeError as error:
            errors.append(f"{candidate}: JSON 読み込み失敗: {error}")
            continue
        except OSError as error:
            errors.append(f"{candidate}: ファイル読み込み失敗: {error}")
            continue
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if not isinstance(data, dict):
            errors.append(f"{candidate}: JSON object ではありません")
            continue
        installed = data.get("installed")
        if not isinstance(installed, dict):
            errors.append(f"{candidate}: installed セクションがありません")
            continue
        missing = [key for key in ("client_id", "client_secret", "redirect_uris") if key not in installed]
        if missing:
            errors.append(f"{candidate}: 必須キー不足: {','.join(missing)}")
            continue
        if installed.get("project_id") == project_id:
            matching.append(_ClientSecretCandidate(candidate, _FileIdentity.from_stat(metadata), raw_data))
        else:
            errors.append(f"{candidate}: project_id が不一致 ({installed.get('project_id')} != {project_id})")

    if not matching:
        print("移動できる client secret が見つかりません:")
        for error in errors:
            print(f"- {error}")
        return 1

    selected = max(matching, key=lambda match: match.identity.modified_ns)
    try:
        staging_dir = Path(tempfile.mkdtemp(prefix=".yt-doctor-client-secret-", dir=selected.path.parent))
    except OSError as error:
        print(f"{selected.path} の固定準備に失敗: {error}")
        return 1
    staged_source = staging_dir / "client_secrets.json"
    try:
        os.rename(selected.path, staged_source)
        staged_metadata = staged_source.lstat()
        if _FileIdentity.from_stat(staged_metadata) != selected.identity:
            raise OSError("検査後に変更されたため移動できません")
    except OSError as error:
        if staged_source.exists() or staged_source.is_symlink():
            try:
                _restore_staged_source(staged_source, selected.path)
            except OSError as rollback_error:
                print(f"{selected.path} の固定に失敗: {error}; rollback 失敗: {rollback_error}")
                return 1
        else:
            try:
                staging_dir.rmdir()
            except OSError as cleanup_error:
                print(f"{selected.path} の固定に失敗: {error}; cleanup 失敗: {cleanup_error}")
                return 1
        print(f"{selected.path} の固定に失敗: {error}")
        return 1

    destination_descriptor: int | None = None
    destination_created = False
    destination_identity: tuple[int, int] | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        destination_created = True
        try:
            destination_metadata = os.fstat(destination_descriptor)
        except OSError:
            destination_metadata = os.stat(destination_descriptor)
            destination_identity = (destination_metadata.st_dev, destination_metadata.st_ino)
            raise
        destination_identity = (destination_metadata.st_dev, destination_metadata.st_ino)
        with os.fdopen(destination_descriptor, "wb") as destination_file:
            destination_descriptor = None
            destination_file.write(selected.raw_data)
            destination_file.flush()
            os.fsync(destination_file.fileno())
    except FileExistsError:
        try:
            _restore_staged_source(staged_source, selected.path)
        except OSError as rollback_error:
            print(f"{destination} は既に存在します; source rollback 失敗: {rollback_error}")
            return 1
        print(f"{destination} は既に存在するため移動できません")
        return 1
    except OSError as error:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
        rollback_identity = destination_identity if destination_created else None
        rollback_errors = _rollback_client_secret_install(destination, rollback_identity, staged_source, selected.path)
        rollback_details = "; " + "; ".join(rollback_errors) if rollback_errors else ""
        print(f"{destination} への移動に失敗: {error}{rollback_details}")
        return 1

    try:
        installed_metadata = destination.lstat()
        source_metadata = staged_source.lstat()
        installed_identity = (installed_metadata.st_dev, installed_metadata.st_ino)
        if installed_identity != destination_identity:
            raise OSError("作成した移動先が置き換えられたため移動できません")
        if _FileIdentity.from_stat(source_metadata) != selected.identity:
            raise OSError("検査後に変更されたため移動できません")
        staged_source.unlink()
    except OSError as error:
        rollback_errors = _rollback_client_secret_install(
            destination, destination_identity, staged_source, selected.path
        )
        rollback_details = "; " + "; ".join(rollback_errors) if rollback_errors else ""
        print(f"{destination} への移動に失敗: {error}{rollback_details}")
        return 1
    try:
        staging_dir.rmdir()
    except OSError as error:
        print(f"{selected.path} を {destination} へ移動しました (staging cleanup 失敗: {error})")
        return 0
    print(f"{selected.path} を {destination} へ移動しました")
    return 0


_COLORS = {
    "ok": "\033[0;32m",
    "info": "\033[0;36m",
    "warn": "\033[0;33m",
    "fail": "\033[0;31m",
    "unknown": "\033[0;90m",
}
_RESET = "\033[0m"
_STATUS_ICONS = {"ok": "✓", "info": "i", "warn": "!", "fail": "✗", "unknown": "?"}


def render_table(results: list[CheckResult], summary: dict, channel_dir: Path) -> str:
    lines: list[str] = []
    lines.append(f"channel_dir: {channel_dir}")

    current_category: Optional[str] = None
    for r in results:
        category = _declared_category(r)
        if category != current_category:
            current_category = category
            lines.append("")
            lines.append(f"=== {current_category} ===")
            lines.append(f"{'STATUS':<8} {'CHECK':<22} MESSAGE")
            lines.append("-" * 78)
        color = _COLORS.get(r.status, "")
        icon = _STATUS_ICONS.get(r.status, "?")
        lines.append(f"{color}{icon} {r.status:<5}{_RESET} {r.id:<22} {r.message}")
        action = r.next_action.to_public_dict() if r.next_action else None
        if action:
            kind = action.get("kind")
            if kind == "human":
                if action.get("url"):
                    lines.append(f"  → {action['url']}")
                if action.get("instructions"):
                    lines.append(f"  → {action['instructions']}")
            elif kind == "ai-exec":
                lines.append(f"  → run: {action.get('cmd', '')}")

    lines.append("")
    lines.append(
        f"summary: ok={summary['ok']} info={summary.get('info', 0)} "
        f"warn={summary['warn']} fail={summary['fail']} unknown={summary.get('unknown', 0)}"
    )
    if summary.get("next_check_id"):
        lines.append(f"next: {summary['next_check_id']}")
    return "\n".join(lines)


def _client_secrets_file_for_accounts(channel_dir: Path) -> Path | None:
    """accounts 表示で使う client_secrets.json を通常ファイル候補から選ぶ。"""
    for candidate in (
        channel_dir / "auth" / "client_secrets.json",
        channel_dir / "automation" / "auth" / "client_secrets.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def _find_channel_dirs(search_root: Path) -> list[Path]:
    """search_root 直下のディレクトリで client_secrets.json 候補を持つものを返す。"""
    dirs: list[Path] = []
    if not search_root.is_dir():
        return dirs
    for child in sorted(search_root.iterdir()):
        if child.is_dir() and _client_secrets_file_for_accounts(child) is not None:
            dirs.append(child)
    return dirs


def _extract_oauth_info(channel_dir: Path) -> dict:
    """client_secrets.json から GCP プロジェクト・クライアント ID を抽出する。"""
    cs_path = _client_secrets_file_for_accounts(channel_dir)
    info: dict = {"channel": channel_dir.name, "path": str(channel_dir)}
    try:
        if cs_path is None:
            raise FileNotFoundError("client_secrets.json not found")
        data = json.loads(cs_path.read_text(encoding="utf-8"))
        installed = data.get("installed") or {}
        info["project_id"] = installed.get("project_id", "?")
        info["client_id"] = installed.get("client_id", "?")
    except (json.JSONDecodeError, OSError):
        info["project_id"] = "read error"
        info["client_id"] = "read error"
    info["has_token"] = (channel_dir / "auth" / "token.json").exists()
    return info


def run_accounts(search_root: Path, as_json: bool) -> int:
    """全チャンネルの GCP プロジェクト + OAuth クライアント対応表を表示する。"""
    channel_dirs = _find_channel_dirs(search_root)
    if not channel_dirs:
        print(f"チャンネルが見つかりません: {search_root}")
        return 1

    rows = [_extract_oauth_info(d) for d in channel_dirs]

    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print(f"search_root: {search_root}")
    print()
    header = f"{'Channel':<24} {'GCP Project':<28} {'OAuth Client ID':<20} {'Token'}"
    print(header)
    print("-" * len(header))
    for r in rows:
        client_short = r["client_id"][:16] + "..." if len(r["client_id"]) > 16 else r["client_id"]
        token_icon = "✓" if r["has_token"] else "✗"
        print(f"{r['channel']:<24} {r['project_id']:<28} {client_short:<20} {token_icon}")

    projects = {r["project_id"] for r in rows if r["project_id"] not in ("?", "read error")}
    print()
    print(f"projects: {len(projects)}  channels: {len(rows)}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="yt-doctor", description="ツール・API 設定の状態診断")
    sub = parser.add_subparsers(dest="command")

    # default (no subcommand): 従来の診断
    parser.add_argument("--json", action="store_true", help="JSON 出力 (AI 用)")
    parser.add_argument("--target", help="対象 channel dir (既定: CHANNEL_DIR env → CWD)")
    parser.add_argument(
        "--check",
        action="append",
        choices=tuple(definition.id for definition in CHECK_REGISTRY),
        help="指定 check のみ実行（複数回指定可）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="ai-exec の診断 step を human / 決定待ちまで自動実行",
    )
    parser.add_argument(
        "--project-id",
        type=_parse_project_id,
        help="--apply の gcp_project step で使う project ID",
    )
    parser.add_argument(
        "--billing-account",
        type=_parse_billing_account_id,
        help="--apply の billing_linked step で使う billing account ID",
    )
    parser.add_argument(
        "--fix-client-secrets",
        action="store_true",
        help="Downloads の OAuth client secret を auth/client_secrets.json へ移動",
    )
    # accounts subcommand
    accounts_parser = sub.add_parser("accounts", help="全チャンネルの GCP/OAuth 対応表")
    accounts_parser.add_argument("--json", action="store_true", help="JSON 出力")
    accounts_parser.add_argument(
        "--search-root",
        help="チャンネルリポ群の親ディレクトリ (既定: CHANNEL_DIR の親 → CWD の親)",
    )

    args = parser.parse_args(argv)

    if args.command == "accounts":
        if args.search_root:
            root = Path(args.search_root).resolve()
        else:
            channel_dir = resolve_channel_dir(None)
            root = channel_dir.parent
        return run_accounts(root, args.json)

    channel_dir = resolve_channel_dir(args.target)
    if args.fix_client_secrets:
        return fix_client_secrets(channel_dir)
    apply_summary: ApplySummary | None = None
    exit_code = 0
    if args.apply:
        outcome = run_apply(
            channel_dir,
            project_id=args.project_id,
            billing_account=args.billing_account,
        )
        results = outcome.results
        apply_summary = outcome.summary
        exit_code = outcome.exit_code
    else:
        results = run_checks(channel_dir, args.check) if args.check else run_all_checks(channel_dir)
    summary = summarize(results)

    if args.json or args.apply:
        payload = {
            "channel_dir": str(channel_dir),
            "summary": summary,
            "checks": [_check_result_to_dict(result) for result in results],
        }
        if apply_summary is not None:
            payload["apply"] = apply_summary.to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_table(results, summary, channel_dir))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
