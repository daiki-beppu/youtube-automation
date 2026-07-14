"""yt-doctor: ツール・API 設定の状態診断 CLI (read-only)"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stdout
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml
from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from youtube_automation.auth.oauth_handler import resolve_client_secrets_location
from youtube_automation.cli.automation_update_refs import UPSTREAM_REPO
from youtube_automation.cli.skills_sync import bundled_skill_names
from youtube_automation.scripts.benchmark_collector import load_benchmark_videos, select_top_vod_benchmark_videos
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.numbered_duplicates import (
    CLEANUP_GUIDE_URL,
    format_duplicate_name,
    format_scan_error_reason,
    scan_numbered_duplicates,
)
from youtube_automation.utils.preflight_checks import (
    check_descriptions_md_parseability,
    check_suno_genre_line_char_limit,
    check_thumbnail_skill_config,
)
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.thumbnail_references import resolve_configured_benchmark_references

PYPROJECT_FILENAME = "pyproject.toml"
CLAUDE_SKILLS_DIR = Path(".claude") / "skills"
AGENTS_SKILLS_LINK = Path(".agents") / "skills"
SKILL_FILENAME = "SKILL.md"
AUTOMATION_PACKAGE_NAME = "youtube-channels-automation"
# fork 運用時に suggested command が official upstream 検証とズレないよう、
# automation_update_refs.UPSTREAM_REPO（単一ソース）から組み立てる
AUTOMATION_PACKAGE_INSTALL_CMD = f"uv add git+https://github.com/{UPSTREAM_REPO}.git"
SKILLS_SYNC_CMD = "uv run yt-skills sync --asset skills --force"
SKILLS_SYNC_PRUNE_CMD = "uv run yt-skills sync --asset skills --force --prune --yes"
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

REQUIRED_ENV_KEYS = [
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_GENAI_USE_VERTEXAI",
]

UPLOAD_REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

UNSUPPORTED_VIDEO_ANALYZE_MODELS = {
    "gemini-3.5-flash",
}

TTP_VIDEO_ANALYZE_TOP_N = 5
MAX_DISPLAY_VALUE_LEN = 120


@dataclass
class CheckResult:
    id: str
    status: str  # ok / warn / fail / unknown
    message: str
    category: str = API_CATEGORY  # bootstrap / api / channel / data / upload
    next_action: Optional[dict] = None


@dataclass(frozen=True)
class _WfNewInputMode:
    mode: str
    report_count: int
    benchmark_count: int
    stale_report: bool
    stale_reason: str | None = None


@dataclass(frozen=True)
class _MappingRead:
    data: dict[str, object]
    error: str | None = None


@dataclass(frozen=True)
class _BenchmarkChannelsRead:
    channels: list[dict[str, object]]
    errors: list[str]


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {' '.join(cmd)}"


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


def _read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    result: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


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
    env = _read_env_file(channel_dir / ".env")
    return env.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or _adc_quota_project()


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


def _skills_sync_failure(message: str) -> CheckResult:
    return CheckResult(
        id="skills_synced",
        status="fail",
        category=BOOTSTRAP_CATEGORY,
        message=message,
        next_action={"kind": "ai-exec", "cmd": SKILLS_SYNC_CMD},
    )


def _skills_sync_prune_failure(message: str) -> CheckResult:
    return CheckResult(
        id="skills_synced",
        status="fail",
        category=BOOTSTRAP_CATEGORY,
        message=message,
        next_action={"kind": "ai-exec", "cmd": SKILLS_SYNC_PRUNE_CMD},
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
    pyproject_path = channel_dir / PYPROJECT_FILENAME
    if not pyproject_path.exists():
        return CheckResult(
            id="uv_project",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message=f"{PYPROJECT_FILENAME} が無い",
            next_action={"kind": "ai-exec", "cmd": "uv init"},
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
    pyproject_path = channel_dir / PYPROJECT_FILENAME
    if not pyproject_path.is_file():
        return CheckResult(
            id="automation_package",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message=f"{PYPROJECT_FILENAME} が無いため automation パッケージを確認できない",
            next_action={"kind": "ai-exec", "cmd": "uv init"},
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
        return CheckResult(
            id="automation_package",
            status="fail",
            category=BOOTSTRAP_CATEGORY,
            message="automation パッケージが pyproject.toml の dependencies に無い",
            next_action={
                "kind": "ai-exec",
                "cmd": AUTOMATION_PACKAGE_INSTALL_CMD,
            },
        )
    return CheckResult(
        id="automation_package",
        status="ok",
        category=BOOTSTRAP_CATEGORY,
        message="automation パッケージ導入済み",
    )


def check_skills_synced(channel_dir: Path) -> CheckResult:
    skills_dir = channel_dir / CLAUDE_SKILLS_DIR
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
    if not _agents_skills_link_is_valid(channel_dir, skills_dir):
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
    findings: list[str] = []
    scan_targets = (
        (".venv/bin", channel_dir / ".venv" / "bin", False),
        (str(CLAUDE_SKILLS_DIR), channel_dir / CLAUDE_SKILLS_DIR, True),
    )
    for label, directory, recursive in scan_targets:
        result = scan_numbered_duplicates(directory, recursive=recursive, root_boundary=channel_dir)
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
            next_action={
                "kind": "human",
                "instructions": (
                    "あなたのターミナルで `gcloud auth login` を実行してください。"
                    "Claude Code 等の AI セッション内では PKCE フローが完結しません。"
                ),
            },
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
            message="project_id が .env / 環境変数 / ADC quota project のいずれにも無い",
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
            next_action={
                "kind": "ai-exec",
                "cmd": f"gcloud services enable {' '.join(missing)} --project={project_id}",
            },
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
            next_action={
                "kind": "human",
                "instructions": (
                    "あなたのターミナルで `gcloud auth application-default login` を実行してください。"
                    "Claude Code 等の AI セッション内では PKCE フローが完結しません。"
                ),
            },
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
            next_action={
                "kind": "ai-exec",
                "cmd": f"gcloud auth application-default set-quota-project {project_id}",
            },
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
            next_action={
                "kind": "ai-exec",
                "cmd": (
                    f"gcloud projects add-iam-policy-binding {project_id} "
                    f"--member=user:{account} --role=roles/aiplatform.user "
                    f"--condition=None --quiet"
                ),
            },
        )
    return CheckResult(
        id="iam_aiplatform_user",
        status="ok",
        message=f"user:{account} は roles/aiplatform.user を保持",
    )


def check_env_file(channel_dir: Path) -> CheckResult:
    env_path = channel_dir / ".env"
    if not env_path.exists():
        return CheckResult(
            id="env_file",
            status="fail",
            message=f"{env_path} が無い",
            next_action={
                "kind": "ai-exec",
                "cmd": (
                    ".claude/skills/channel-new/references/gcp-bootstrap.sh <project-id> を実行して .env を書き出す"
                ),
            },
        )
    env = _read_env_file(env_path)
    missing = [k for k in REQUIRED_ENV_KEYS if k not in env]
    if missing:
        return CheckResult(
            id="env_file",
            status="warn",
            message=f".env に不足キー: {','.join(missing)}",
        )
    return CheckResult(
        id="env_file",
        status="ok",
        message=f".env 必須キー揃い済み ({', '.join(REQUIRED_ENV_KEYS)})",
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
            from youtube_automation.utils.exceptions import ConfigError
            from youtube_automation.utils.secrets import get_secret

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
                    "発行した `client_id` / `project_id` / `client_secret` を "
                    "`auth/client_secrets.template.json` へ転記し、"
                    f"`{path}` に配置してください。" + (f" fallback 状態: {fallback_error}" if fallback_error else "")
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


def check_oauth_token(channel_dir: Path) -> CheckResult:
    path = channel_dir / "auth" / "token.json"
    if not path.exists():
        return CheckResult(
            id="oauth_token",
            status="fail",
            message=f"{path} が無い",
            next_action={
                "kind": "ai-exec",
                "cmd": "uv run yt-channel-status を 1 回叩くと初回認証フロー (loopback redirect) が発火する",
            },
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return CheckResult(
            id="oauth_token",
            status="fail",
            message=f"token.json 読み込み失敗: {e}",
        )
    scopes = data.get("scopes") or []
    return CheckResult(
        id="oauth_token",
        status="ok",
        message=f"token.json 存在 (scopes: {len(scopes)} 件)",
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
                    "/channel-new を実行して新規チャンネル設定を作成してください"
                ),
            },
        )

    from youtube_automation.utils.config import load_config
    from youtube_automation.utils.exceptions import ConfigError
    from youtube_automation.utils.metadata_generator import validate_localizations_title_templates

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
                        "instructions": (
                            "/channel-new（既存チャンネル取り込みモード）を実行して設定を修復してください"
                        ),
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
                    "instructions": ("/channel-new（既存チャンネル取り込みモード）を実行して設定を修復してください"),
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
                    "/channel-new（再生成モード）で config/channel/playlists.json を作成し、"
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
    from youtube_automation.scripts.playlist_manager import PlaylistManager
    from youtube_automation.utils.exceptions import ConfigError

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
    from youtube_automation.utils.config import reset as reset_config

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
    if input_mode.stale_report:
        if input_mode.stale_reason == "absolute":
            message = (
                "最新 data/analytics_data_*.json が実行日から freshness_days を超えて古い。"
                "/wf-new は stale report では開始不可"
            )
            instructions = "/analytics-collect → /analytics-analyze の順で再実行してください"
        else:
            message = (
                "reports/analysis_*.md が最新 data/analytics_data_*.json より古い。/wf-new は stale report では開始不可"
            )
            instructions = "/analytics-analyze を再実行してください（必要なら先に /analytics-collect）"
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
            message=f"reports/analysis_*.md {input_mode.report_count} 件存在 ({input_mode.mode})",
        )

    return CheckResult(
        id="analytics_report",
        status="ok",
        category=DATA_CATEGORY,
        message=f"reports/analysis_*.md 未生成。/wf-new は {input_mode.mode} で開始可能",
    )


def _resolve_wf_new_input_mode(channel_dir: Path) -> _WfNewInputMode:
    reports_dir = channel_dir / "reports"
    data_dir = channel_dir / "data"
    reports = _matching_files(reports_dir, "analysis_*.md")
    benchmarks = _matching_files(data_dir, "benchmark_*.json")
    data_files = _matching_files(data_dir, "analytics_data_*.json")

    if reports:
        latest_report = _latest_filename_date(reports)
        latest_data = _latest_filename_date(data_files)
        stale_reason: str | None = None
        if latest_data is not None and (latest_report is None or latest_report[0] < latest_data[0]):
            stale_reason = "relative"
        elif latest_data is not None and _analytics_data_exceeds_freshness_days(latest_data[0], channel_dir):
            stale_reason = "absolute"
        return _WfNewInputMode(
            mode="analytics mode",
            report_count=len(reports),
            benchmark_count=len(benchmarks),
            stale_report=stale_reason is not None,
            stale_reason=stale_reason,
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
                "/collection-ideate が /benchmark の鮮度確認・必要時更新を扱う"
            ),
        )

    return CheckResult(
        id="benchmark_data",
        status="ok",
        category=DATA_CATEGORY,
        message=f"data/benchmark_*.json 未生成。/wf-new は {input_mode.mode} で開始可能",
    )


def check_ttp_wf_new_readiness(channel_dir: Path) -> CheckResult:
    analytics_path = channel_dir / "config" / "channel" / "analytics.json"
    if not analytics_path.is_file():
        return CheckResult(
            id="ttp_wf_new_readiness",
            status="warn",
            category=DATA_CATEGORY,
            message="config/channel/analytics.json 未生成。/wf-new 接続前に承認済み TTP 対象の保存が必要",
            next_action={
                "kind": "human",
                "instructions": (
                    "/channel-new Step 4 で config を生成し、Step 5 以降で承認済み TTP 対象を "
                    "config/channel/analytics.json::benchmark.channels に保存してください"
                ),
            },
        )

    analytics_read = _read_json_mapping(analytics_path)
    if analytics_read.error:
        return CheckResult(
            id="ttp_wf_new_readiness",
            status="warn",
            category=DATA_CATEGORY,
            message="TTP 完了条件が未充足: " + analytics_read.error,
            next_action={
                "kind": "human",
                "instructions": "config/channel/analytics.json を修正してから yt-doctor を再実行してください",
            },
        )

    analytics = analytics_read.data
    channels_read = _benchmark_channels(analytics)
    channels = channels_read.channels
    if not channels:
        return CheckResult(
            id="ttp_wf_new_readiness",
            status="warn",
            category=DATA_CATEGORY,
            message="承認済み TTP 対象が 0 件。/channel-new は /wf-new 接続前に TTP 対象承認が必要",
            next_action={
                "kind": "human",
                "instructions": (
                    "/channel-new Step 1/5 に戻り、TTP 対象を確認して "
                    "config/channel/analytics.json::benchmark.channels に承認済み対象を保存してください"
                ),
            },
        )

    missing, approved_exceptions = _missing_ttp_readiness_items(channel_dir, channels)
    missing.extend(channels_read.errors)
    benchmark_missing, benchmark_notes = _missing_channel_new_benchmark_items(
        channel_dir,
        approved_exceptions,
        channels,
    )
    missing.extend(benchmark_missing)
    # live 配信除外の note は未充足条件ではないため missing に混ぜず、message 末尾に併記する
    note_suffix = ("。" + "; ".join(benchmark_notes)) if benchmark_notes else ""
    if missing:
        return CheckResult(
            id="ttp_wf_new_readiness",
            status="warn",
            category=DATA_CATEGORY,
            message="/channel-new benchmark 反映未完了の可能性 / TTP 完了条件が未充足: "
            + "; ".join(missing)
            + note_suffix,
            next_action={
                "kind": "human",
                "instructions": (
                    "/channel-new 初回モード Step 5-9 と再生成モード Step R3.5 の不足項目を解消してください。"
                    "意図的にスキップする場合は docs/channel/ttp-seed-confirmation.md に "
                    "ユーザー承認済み例外として未反映項目を明記し、最後に `uv run yt-doctor --json` で "
                    "`ttp_wf_new_readiness` が ok になることを確認してください"
                ),
            },
        )

    return CheckResult(
        id="ttp_wf_new_readiness",
        status="ok",
        category=DATA_CATEGORY,
        message=(
            "TTP 対象承認・branding snapshot・benchmark docs・thumbnail / music readiness が "
            "/wf-new 接続可能（/channel-new 再生成モード完了相当）" + note_suffix
        ),
    )


def _read_json_mapping(path: Path) -> _MappingRead:
    if not path.exists():
        return _MappingRead({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return _MappingRead({}, f"{_diagnostic_path(path)} が JSON として不正 ({e.msg})")
    except OSError as e:
        return _MappingRead({}, f"{_diagnostic_path(path)} を読み込めません ({e})")
    if not isinstance(data, dict):
        return _MappingRead({}, f"{_diagnostic_path(path)} のトップレベルが object ではありません")
    return _MappingRead(data)


def _read_yaml_mapping(path: Path) -> _MappingRead:
    if not path.exists():
        return _MappingRead({})
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return _MappingRead({}, f"{_diagnostic_path(path)} が YAML として不正 ({e})")
    except OSError as e:
        return _MappingRead({}, f"{_diagnostic_path(path)} を読み込めません ({e})")
    if not isinstance(data, dict):
        return _MappingRead({}, f"{_diagnostic_path(path)} のトップレベルが object ではありません")
    return _MappingRead(data)


def _skill_config_mapping(channel_dir: Path, skill: str) -> _MappingRead:
    try:
        return _MappingRead(load_skill_config(skill, use_cache=False, channel_dir=channel_dir))
    except ConfigError as exc:
        return _MappingRead({}, str(exc))


def _diagnostic_path(path: Path) -> str:
    return path.as_posix()


def _benchmark_channels(analytics: dict[str, object]) -> _BenchmarkChannelsRead:
    benchmark = analytics.get("benchmark")
    if not isinstance(benchmark, dict):
        return _BenchmarkChannelsRead([], [])
    channels = benchmark.get("channels")
    if not isinstance(channels, list):
        return _BenchmarkChannelsRead([], [])
    valid_channels: list[dict[str, object]] = []
    errors: list[str] = []
    for index, channel in enumerate(channels):
        if isinstance(channel, dict):
            valid_channels.append(channel)
        else:
            errors.append(f"benchmark.channels entry #{index + 1} が object ではありません")
    return _BenchmarkChannelsRead(valid_channels, errors)


def _missing_ttp_readiness_items(channel_dir: Path, channels: list[dict[str, object]]) -> tuple[list[str], set[str]]:
    missing: list[str] = []
    approved_exceptions: set[str] = set()
    seed_text = ""

    channels_without_relationship = [
        _channel_diagnostic_label(index, channel)
        for index, channel in enumerate(channels)
        if _is_placeholder_relationship(str(channel.get("relationship") or ""))
    ]
    if channels_without_relationship:
        missing.append(
            "benchmark.channels の relationship 未設定または placeholder ("
            + ", ".join(channels_without_relationship)
            + ")"
        )

    seed_confirmation = channel_dir / "docs" / "channel" / "ttp-seed-confirmation.md"
    if not seed_confirmation.is_file():
        missing.append("docs/channel/ttp-seed-confirmation.md 未作成")
    else:
        seed_text = seed_confirmation.read_text(encoding="utf-8", errors="replace")
        seed_missing, approved_exceptions = _validate_ttp_seed_confirmation(seed_text, channels)
        missing.extend(seed_missing)

    missing.extend(_missing_branding_snapshot_items(channel_dir, channels, seed_text))

    thumbnail_read = _skill_config_mapping(channel_dir, "thumbnail")
    if thumbnail_read.error:
        missing.append(thumbnail_read.error)
    if "thumbnail" not in approved_exceptions:
        thumbnail_missing = _thumbnail_ttp_reference_missing_reason(channel_dir, thumbnail_read.data)
        if thumbnail_missing:
            missing.append(thumbnail_missing)

    video_analyze_read = _skill_config_mapping(channel_dir, "video-analyze")
    if video_analyze_read.error:
        missing.append(video_analyze_read.error)
    model = video_analyze_read.data.get("model")
    if isinstance(model, str) and model in UNSUPPORTED_VIDEO_ANALYZE_MODELS:
        missing.append(f"video-analyze model が旧/非対応: {model}")

    youtube_read = _read_json_mapping(channel_dir / "config" / "channel" / "youtube.json")
    if youtube_read.error:
        missing.append(youtube_read.error)
    youtube = youtube_read.data
    if youtube.get("music_engine", "suno") == "suno" and "music" not in approved_exceptions:
        music_readiness = _suno_music_readiness(channel_dir, channels)
        missing.extend(music_readiness.errors)
        if not music_readiness.ready:
            missing.append("Suno genre_line または data/video_analysis の suno_preset 未設定")

    return missing, approved_exceptions


def _missing_channel_new_benchmark_items(
    channel_dir: Path,
    approved_exceptions: set[str],
    channels: list[dict[str, object]],
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    if not _matching_files(channel_dir / "data", "benchmark_*.json"):
        missing.append("data/benchmark_*.json が無い")
    analysis_missing, notes = _missing_video_analysis_items(channel_dir, _approved_ttp_channel_slugs(channels))
    missing.extend(analysis_missing)
    if not _benchmark_report_files(channel_dir):
        missing.append("docs/benchmarks/*.md が無い")
    if "thumbnail" not in approved_exceptions and not _benchmark_thumbnail_files(channel_dir):
        missing.append("data/thumbnail_compare/benchmark/ に TTP 参照画像が無い")
    return missing, notes


def _missing_video_analysis_items(channel_dir: Path, approved_slugs: list[str]) -> tuple[list[str], list[str]]:
    approved_slug_set = set(approved_slugs)
    if not approved_slug_set:
        return [], []
    benchmark_by_slug, errors = _latest_benchmark_videos_by_slug(channel_dir, approved_slug_set)
    missing = list(errors)
    notes: list[str] = []
    video_analysis_dir = channel_dir / "data" / "video_analysis"
    for slug in approved_slugs:
        slug_dir, slug_error = _video_analysis_slug_dir(channel_dir, video_analysis_dir, slug)
        if slug_error:
            missing.append(slug_error)
            continue
        videos = benchmark_by_slug.get(slug, [])
        top_videos, skipped_live = select_top_vod_benchmark_videos(videos, TTP_VIDEO_ANALYZE_TOP_N)
        excluded_live = len(skipped_live)
        if excluded_live:
            notes.append(
                f"{slug}: live 配信 {excluded_live} 本は Gemini で解析不能のため "
                f"benchmark top {TTP_VIDEO_ANALYZE_TOP_N} の判定から除外（次点 VOD を繰り上げ）"
            )
        if len(videos) < TTP_VIDEO_ANALYZE_TOP_N and not excluded_live:
            missing.append(
                f"{slug}: benchmark top {TTP_VIDEO_ANALYZE_TOP_N} が不足 ({len(top_videos)}/{TTP_VIDEO_ANALYZE_TOP_N})"
            )
        expected_ids = {str(video.get("video_id")) for video in top_videos if video.get("video_id")}
        if len(expected_ids) < len(top_videos):
            missing.append(f"{slug}: benchmark top {TTP_VIDEO_ANALYZE_TOP_N} に video_id 欠落があります")
        if not expected_ids:
            if excluded_live and videos:
                missing.append(f"{slug}: benchmark 上位が live 配信のみで解析可能な VOD がありません")
            else:
                missing.append(f"{slug}: benchmark top {TTP_VIDEO_ANALYZE_TOP_N} に video_id がありません")
            continue
        done_ids, analysis_errors = _verified_video_analysis_ids(
            slug,
            slug_dir or video_analysis_dir / slug,
            expected_ids,
        )
        missing.extend(analysis_errors)
        done = len(done_ids)
        # live 除外が発生した場合のみ母数を実際に解析可能な VOD 数へ縮小する
        # （除外なしで benchmark が N 本未満の従来ケースは分母 N のまま warn を維持）
        required = len(top_videos) if excluded_live else TTP_VIDEO_ANALYZE_TOP_N
        if done == 0:
            missing.append(f"{slug}: video_analysis 未実行 (0/{required})")
        elif done < required:
            missing.append(f"{slug}: video_analysis が一部のみ ({done}/{required})")
    return missing, notes


def _latest_benchmark_videos_by_slug(
    channel_dir: Path,
    approved_slugs: set[str],
) -> tuple[dict[str, list[dict[str, object]]], list[str]]:
    try:
        videos = load_benchmark_videos(channel_dir / "data")
    except (ConfigError, json.JSONDecodeError, OSError, ValueError) as exc:
        return {}, [str(exc)]
    result: dict[str, list[dict[str, object]]] = {}
    for video in videos:
        slug = str(video.get("channel_slug") or "").strip()
        if slug in approved_slugs:
            result.setdefault(slug, []).append(video)
    return result, []


def _verified_video_analysis_ids(slug: str, slug_dir: Path, expected_ids: set[str]) -> tuple[set[str], list[str]]:
    done: set[str] = set()
    errors: list[str] = []
    for video_id in sorted(expected_ids):
        path = slug_dir / f"{video_id}.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{slug}: {path.name} 読み込み失敗: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{slug}: {path.name} のトップレベルが object ではありません")
            continue
        payload_video_id = data.get("video_id")
        if payload_video_id is not None and str(payload_video_id) != video_id:
            errors.append(f"{slug}: {path.name} の video_id が期待値と一致しません")
            continue
        done.add(video_id)
    return done, errors


_SEED_CONFIRMATION_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("source", ("source", "ソース", "url", "handle", "channel id", "チャンネルid")),
    ("seed fetch 要約", ("seed fetch", "fetch", "取得要約", "収集要約")),
    ("承認 / 不採用判断", ("承認 / 不採用判断", "承認判断", "不採用判断", "判断:", "approved:", "rejected:")),
    ("転写したい要素", ("転写したい要素", "転写", "要素:")),
    ("relationship", ("relationship", "関係性")),
    ("未反映項目", ("未反映", "未適用", "none", "なし")),
)


_PLACEHOLDER_RELATIONSHIPS = {"", "seed", "default", "unknown", "none", "n/a", "未設定", "なし"}


def _validate_ttp_seed_confirmation(seed_text: str, channels: list[dict[str, object]]) -> tuple[list[str], set[str]]:
    missing: list[str] = []
    sections = _seed_confirmation_sections(seed_text)

    for index, channel in enumerate(channels):
        label = _channel_diagnostic_label(index, channel)
        identifiers = _channel_seed_identifiers(channel)
        if not identifiers:
            missing.append(f"ttp-seed-confirmation.md 照合用の id / slug が benchmark.channels に未設定 ({label})")
            continue

        candidate_sections = _sections_for_identifiers(sections, identifiers)
        if not candidate_sections:
            missing.append(f"ttp-seed-confirmation.md に承認済み TTP 対象の識別子が未記録 ({label})")
            continue

        candidate_text = "\n".join(candidate_sections)
        for marker_label, markers in _SEED_CONFIRMATION_MARKERS:
            if not _contains_any_marker(candidate_text, markers):
                missing.append(f"ttp-seed-confirmation.md に {marker_label} が未記録 ({label})")
        if not _has_branding_transfer_policy(candidate_text):
            missing.append(f"ttp-seed-confirmation.md に branding snapshot 参照または転写方針が未記録 ({label})")

        relationship = str(channel.get("relationship") or "").strip()
        if (
            relationship
            and not _is_placeholder_relationship(relationship)
            and relationship.lower() not in candidate_text.lower()
        ):
            missing.append(f"ttp-seed-confirmation.md に承認済み TTP 対象の relationship が未記録 ({label})")

    unapproved_skip_lines = [
        line.strip()
        for line in seed_text.splitlines()
        if _line_mentions_ttp_skip(line) and not _line_mentions_approved_exception(line)
    ]
    if unapproved_skip_lines:
        missing.append("ttp-seed-confirmation.md に未承認の TTP 未反映 / スキップ項目あり")

    approved_exceptions, exception_missing = _approved_ttp_exceptions(seed_text)
    missing.extend(exception_missing)
    return missing, approved_exceptions


def _seed_confirmation_sections(seed_text: str) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for line in seed_text.splitlines():
        stripped = line.strip()
        starts_new_heading = stripped.startswith("#") and current
        starts_new_list_channel = bool(
            current and re.match(r"^[-*]\s+(?:channel|チャンネル|候補)\b", stripped, re.IGNORECASE)
        )
        if not stripped or starts_new_heading or starts_new_list_channel:
            if current:
                sections.append("\n".join(current))
                current = []
            if not stripped:
                continue
        current.append(line)
    if current:
        sections.append("\n".join(current))
    return sections or [seed_text]


def _sections_for_identifiers(sections: list[str], identifiers: list[str]) -> list[str]:
    return [
        section
        for section in sections
        if any(_section_mentions_identifier(section, identifier) for identifier in identifiers)
    ]


def _section_mentions_identifier(section: str, identifier: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(identifier)}(?![A-Za-z0-9_-])", re.IGNORECASE)
    identifier_line_markers = ("source", "ソース", "url", "handle", "channel", "チャンネル", "id", "slug")
    return any(
        any(marker in line.lower() for marker in identifier_line_markers) and pattern.search(line)
        for line in section.splitlines()
    )


def _is_placeholder_relationship(relationship: str) -> bool:
    return relationship.strip().lower() in _PLACEHOLDER_RELATIONSHIPS


def _channel_seed_identifiers(channel: dict[str, object]) -> list[str]:
    return [value for value in (str(channel.get("id") or "").strip(), str(channel.get("slug") or "").strip()) if value]


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lower_text = text.lower()
    return any(marker.lower() in lower_text for marker in markers)


def _has_branding_transfer_policy(text: str) -> bool:
    lower_text = text.lower()
    if "competitor-branding-snapshot.json" in lower_text or "branding snapshot" in lower_text:
        return True
    policy_markers = ("description", "keywords", "localizations")
    transfer_markers = ("転写", "方針", "参照", "構造", "抽出")
    return any(
        any(policy_marker in line.lower() for policy_marker in policy_markers)
        and any(transfer_marker in line for transfer_marker in transfer_markers)
        for line in text.splitlines()
    )


def _line_mentions_ttp_skip(line: str) -> bool:
    lower_line = line.lower()
    if "スキップ" in line or "skip" in lower_line:
        return True
    if "未反映" not in line and "未適用" not in line:
        return False
    return not _line_declares_no_unapplied_items(line)


def _line_declares_no_unapplied_items(line: str) -> bool:
    lower_line = line.lower()
    return ("なし" in line or "none" in lower_line) and "ただし" not in line and "but" not in lower_line


def _line_mentions_approved_exception(line: str) -> bool:
    lower_line = line.lower()
    return "ユーザー承認済み例外" in line or "approved exception" in lower_line


def _approved_ttp_exceptions(seed_text: str) -> tuple[set[str], list[str]]:
    exceptions: set[str] = set()
    missing: list[str] = []
    for line in seed_text.splitlines():
        if not _line_mentions_approved_exception(line):
            continue
        lower_line = line.lower()
        categories: set[str] = set()
        if "thumbnail" in lower_line or "サムネ" in line:
            categories.add("thumbnail")
        if "music" in lower_line or "suno" in lower_line or "曲構造" in line or "音楽" in line:
            categories.add("music")

        if not categories:
            missing.append("ユーザー承認済み例外に対象 category が未記録")
            continue
        if not _line_mentions_ttp_skip(line):
            missing.append("ユーザー承認済み例外に具体的な未反映 / スキップ内容が未記録")
            continue
        if not _approved_exception_has_reason(line):
            missing.append("ユーザー承認済み例外に進める理由が未記録")
            continue
        if "thumbnail" in categories and "/thumbnail" not in lower_line:
            missing.append("thumbnail のユーザー承認済み例外に後続 /thumbnail が未記録")
            continue
        if "music" in categories and "/suno" not in lower_line:
            missing.append("music のユーザー承認済み例外に後続 /suno が未記録")
            continue

        exceptions.update(categories)
    return exceptions, missing


def _approved_exception_has_reason(line: str) -> bool:
    lower_line = line.lower()
    return "ため" in line or "理由" in line or "because" in lower_line or "進める" in line


def _missing_branding_snapshot_items(
    channel_dir: Path,
    channels: list[dict[str, object]],
    seed_text: str,
) -> list[str]:
    branding_read = _read_json_mapping(channel_dir / "docs" / "channel" / "competitor-branding-snapshot.json")
    if branding_read.error:
        return [branding_read.error]

    branding_snapshot = branding_read.data
    snapshot_items = branding_snapshot.get("items")
    if branding_snapshot.get("untrusted_data") is not True:
        return ["docs/channel/competitor-branding-snapshot.json 未作成または空"]
    if not isinstance(snapshot_items, list):
        return ["docs/channel/competitor-branding-snapshot.json の items が list ではありません"]
    if not snapshot_items:
        return ["docs/channel/competitor-branding-snapshot.json 未作成または空"]

    missing: list[str] = []
    if branding_snapshot.get("reference_only") is not True:
        missing.append("competitor-branding-snapshot.json の reference_only が true ではありません")
    if any(not isinstance(item, dict) for item in snapshot_items):
        missing.append("competitor-branding-snapshot.json の items に object ではない要素があります")
    image_references = branding_snapshot.get("channel_image_references")
    if not isinstance(image_references, list):
        missing.append("competitor-branding-snapshot.json の channel_image_references が list ではありません")
        image_references = []
    elif any(not isinstance(item, dict) for item in image_references):
        missing.append("competitor-branding-snapshot.json の channel_image_references に object ではない要素があります")
    approved_ids = _approved_ttp_channel_ids(channels)
    snapshot_by_id = {
        str(item.get("id")): item
        for item in snapshot_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    image_reference_by_id = {
        str(item.get("channel_id")): item
        for item in image_references
        if isinstance(item, dict) and str(item.get("channel_id") or "").strip()
    }

    channels_without_id = [
        _channel_diagnostic_label(index, channel)
        for index, channel in enumerate(channels)
        if not str(channel.get("id") or "").strip()
    ]
    if channels_without_id:
        missing.append(f"benchmark.channels の id 未設定 ({', '.join(channels_without_id)})")

    missing_ids = [channel_id for channel_id in approved_ids if channel_id not in snapshot_by_id]
    if missing_ids:
        missing.append(
            "competitor-branding-snapshot.json に承認済み TTP 対象の snapshot 不足 (" + ", ".join(missing_ids) + ")"
        )
    missing_image_reference_ids = [channel_id for channel_id in approved_ids if channel_id not in image_reference_by_id]
    if missing_image_reference_ids:
        missing.append(
            "competitor-branding-snapshot.json に承認済み TTP 対象の画像参照メタ不足 ("
            + ", ".join(missing_image_reference_ids)
            + ")"
        )

    for channel_id in approved_ids:
        item = snapshot_by_id.get(channel_id)
        if item is None:
            continue
        missing_fields = [
            field for field in ("snippet", "brandingSettings", "localizations") if not isinstance(item.get(field), dict)
        ]
        if missing_fields:
            missing.append(
                f"competitor-branding-snapshot.json の {channel_id} に必須 field 不足 ({', '.join(missing_fields)})"
            )
        image_reference = image_reference_by_id.get(channel_id)
        if image_reference is None:
            continue
        if image_reference.get("reference_only") is not True:
            missing.append(
                f"competitor-branding-snapshot.json の {channel_id} 画像参照メタ reference_only が true ではありません"
            )
        fallback_note_recorded = _channel_branding_fallback_note_recorded(channel_dir)
        if not _channel_image_reference_has_icon_source(image_reference) and not fallback_note_recorded:
            missing.append(
                f"competitor-branding-snapshot.json の {channel_id} に "
                "icon 画像参照または fallback 根拠 note がありません"
            )
        if not _channel_image_reference_has_banner_source(image_reference) and not fallback_note_recorded:
            missing.append(
                f"competitor-branding-snapshot.json の {channel_id} に "
                "banner 画像参照または fallback 根拠 note がありません"
            )

    missing.extend(
        _missing_channel_branding_thumbnail_config(channel_dir, approved_ids, image_references, image_reference_by_id)
    )
    missing.extend(_missing_channel_branding_outputs(channel_dir, seed_text))
    return missing


def _approved_ttp_channel_ids(channels: list[dict[str, object]]) -> list[str]:
    return [channel_id for channel in channels if (channel_id := str(channel.get("id") or "").strip())]


def _channel_image_reference_has_icon_source(image_reference: dict[str, object]) -> bool:
    icon = image_reference.get("icon")
    return isinstance(icon, dict) and isinstance(icon.get("url"), str) and bool(icon["url"].strip())


def _channel_image_reference_has_banner_source(image_reference: dict[str, object]) -> bool:
    banner = image_reference.get("banner")
    return isinstance(banner, list) and any(
        isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"].strip() for item in banner
    )


def _missing_channel_branding_thumbnail_config(
    channel_dir: Path,
    approved_ids: list[str],
    image_references: list[object],
    image_reference_by_id: dict[str, dict[str, object]],
) -> list[str]:
    thumbnail_read = _skill_config_mapping(channel_dir, "thumbnail")
    if thumbnail_read.error:
        return []
    image_generation = thumbnail_read.data.get("image_generation")
    if not isinstance(image_generation, dict):
        return ["thumbnail.yaml の image_generation.gemini.reference_images.channel_branding 未設定"]
    gemini = image_generation.get("gemini")
    if not isinstance(gemini, dict):
        return ["thumbnail.yaml の image_generation.gemini.reference_images.channel_branding 未設定"]
    reference_images = gemini.get("reference_images")
    if not isinstance(reference_images, dict):
        return ["thumbnail.yaml の image_generation.gemini.reference_images.channel_branding 未設定"]
    channel_branding = reference_images.get("channel_branding")
    if not isinstance(channel_branding, dict):
        return ["thumbnail.yaml の reference_images.channel_branding 未設定"]

    missing: list[str] = []
    if channel_branding.get("snapshot") != "docs/channel/competitor-branding-snapshot.json":
        missing.append("thumbnail.yaml の reference_images.channel_branding.snapshot が未設定または不正")
    if channel_branding.get("output_icon") != "branding/icon.png":
        missing.append("thumbnail.yaml の reference_images.channel_branding.output_icon が未設定または不正")
    if channel_branding.get("output_banner") != "branding/banner.png":
        missing.append("thumbnail.yaml の reference_images.channel_branding.output_banner が未設定または不正")

    icon_required = any(
        _channel_image_reference_has_icon_source(image_reference_by_id[channel_id])
        for channel_id in approved_ids
        if channel_id in image_reference_by_id
    )
    banner_required = any(
        _channel_image_reference_has_banner_source(image_reference_by_id[channel_id])
        for channel_id in approved_ids
        if channel_id in image_reference_by_id
    )
    if icon_required:
        missing.extend(
            _missing_channel_branding_reference_list(
                "icon_references",
                channel_branding.get("icon_references"),
                image_references,
                "icon",
            )
        )
    if banner_required:
        missing.extend(
            _missing_channel_branding_reference_list(
                "banner_references",
                channel_branding.get("banner_references"),
                image_references,
                "banner",
            )
        )
    return missing


def _missing_channel_branding_reference_list(
    field_name: str,
    value: object,
    image_references: list[object],
    kind: str,
) -> list[str]:
    label = f"thumbnail.yaml の reference_images.channel_branding.{field_name}"
    if not isinstance(value, list) or not value:
        return [f"{label} 未設定"]

    invalid_refs = [
        str(item) for item in value if not _channel_branding_reference_resolves(item, image_references, kind)
    ]
    if invalid_refs:
        return [f"{label} に snapshot fragment として解決できない参照があります ({', '.join(invalid_refs)})"]
    return []


def _channel_branding_reference_resolves(value: object, image_references: list[object], kind: str) -> bool:
    if not isinstance(value, str) or not value.strip() or "{{" in value:
        return False

    if kind == "icon":
        match = re.fullmatch(
            r"docs/channel/competitor-branding-snapshot\.json#channel_image_references\[(\d+)\]\.icon",
            value.strip(),
        )
        if match is None:
            return False
        index = int(match.group(1))
        if index >= len(image_references):
            return False
        image_reference = image_references[index]
        return isinstance(image_reference, dict) and _channel_image_reference_has_icon_source(image_reference)

    if kind == "banner":
        match = re.fullmatch(
            r"docs/channel/competitor-branding-snapshot\.json#channel_image_references\[(\d+)\]\.banner\[(\d+)\]",
            value.strip(),
        )
        if match is None:
            return False
        image_index = int(match.group(1))
        banner_index = int(match.group(2))
        if image_index >= len(image_references):
            return False
        image_reference = image_references[image_index]
        if not isinstance(image_reference, dict):
            return False
        banner = image_reference.get("banner")
        if not isinstance(banner, list) or banner_index >= len(banner):
            return False
        banner_reference = banner[banner_index]
        return (
            isinstance(banner_reference, dict)
            and isinstance(banner_reference.get("url"), str)
            and bool(banner_reference["url"].strip())
        )

    return False


def _missing_channel_branding_outputs(channel_dir: Path, seed_text: str) -> list[str]:
    missing: list[str] = []
    missing.extend(
        _missing_channel_branding_output_image(
            channel_dir,
            "branding/icon.png",
            expected_ratio=1.0,
            max_size_bytes=4 * 1024 * 1024,
            label="branding/icon.png",
        )
    )
    missing.extend(
        _missing_channel_branding_output_image(
            channel_dir,
            "branding/banner.png",
            expected_ratio=16 / 9,
            max_size_bytes=6 * 1024 * 1024,
            label="branding/banner.png",
        )
    )
    if not _channel_branding_output_approved(seed_text):
        missing.append("docs/channel/ttp-seed-confirmation.md に channel branding 画像のユーザー承認記録がありません")
    return missing


def _missing_channel_branding_output_image(
    channel_dir: Path,
    relative_path: str,
    *,
    expected_ratio: float,
    max_size_bytes: int,
    label: str,
) -> list[str]:
    path = channel_dir / relative_path
    if not path.is_file():
        candidates = _channel_branding_output_candidates(channel_dir, relative_path)
        if candidates:
            candidate_list = ", ".join(candidates)
            if len(candidates) > 1:
                return [
                    f"{label} は見つかりませんが、既存候補が複数あります: {candidate_list}。"
                    f"最終版を確認してから変換してください。採用後に {label} にしてください（自動判定はしません）"
                ]
            return [
                f"{label} は見つかりませんが、既存候補があります: {candidate_list}。{label} にリネーム/変換してください"
            ]
        return [f"{label} が未生成"]
    try:
        if path.stat().st_size > max_size_bytes:
            return [f"{label} のファイルサイズが上限を超えています"]
    except OSError as exc:
        return [f"{label} のファイルサイズを確認できません ({exc})"]

    try:
        with PILImage.open(path) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        return [f"{label} を画像として読み込めません ({exc})"]

    if width <= 0 or height <= 0:
        return [f"{label} の画像サイズが不正です"]
    actual_ratio = width / height
    if abs(actual_ratio - expected_ratio) > 0.03:
        return [f"{label} のアスペクト比が不正です"]
    return []


def _channel_branding_output_candidates(channel_dir: Path, relative_path: str) -> list[str]:
    target = Path(relative_path)
    branding_dir = channel_dir / target.parent
    if not branding_dir.is_dir():
        return []

    allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    target_stem = target.stem
    versioned_pattern = re.compile(rf"^{re.escape(target_stem)}-v\d+$")
    candidates: list[str] = []
    for candidate in sorted(branding_dir.iterdir(), key=lambda item: item.name):
        if not candidate.is_file() or candidate.suffix.lower() not in allowed_suffixes:
            continue
        if candidate.stem == target_stem or versioned_pattern.fullmatch(candidate.stem):
            candidates.append(candidate.relative_to(channel_dir).as_posix())
    return candidates


def _channel_branding_output_approved(seed_text: str) -> bool:
    for line in seed_text.splitlines():
        lower_line = line.lower()
        mentions_branding_output = (
            "branding/icon.png" in lower_line
            or "branding/banner.png" in lower_line
            or "channel branding" in lower_line
            or "チャンネル画像" in line
        )
        if mentions_branding_output and ("承認済み" in line or "approved" in lower_line):
            return True
    return False


def _channel_branding_fallback_note_recorded(channel_dir: Path) -> bool:
    thumbnail_read = _skill_config_mapping(channel_dir, "thumbnail")
    if thumbnail_read.error:
        return False
    image_generation = thumbnail_read.data.get("image_generation")
    if not isinstance(image_generation, dict):
        return False
    gemini = image_generation.get("gemini")
    if not isinstance(gemini, dict):
        return False
    reference_images = gemini.get("reference_images")
    if not isinstance(reference_images, dict):
        return False
    notes = reference_images.get("notes")
    if not isinstance(notes, str):
        return False
    lower_notes = notes.lower()
    return "fallback" in lower_notes or "取得できない" in notes or "参照画像なし" in notes


def _approved_ttp_channel_slugs(channels: list[dict[str, object]]) -> list[str]:
    return [slug for channel in channels if (slug := str(channel.get("slug") or "").strip())]


def _video_analysis_slug_dir(channel_dir: Path, video_analysis_dir: Path, slug: str) -> tuple[Path | None, str | None]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", slug):
        return None, f"benchmark.channels の slug が不正 ({_safe_diagnostic_value(slug)})"
    channel_root = channel_dir.resolve(strict=False)
    root = video_analysis_dir.resolve(strict=False)
    candidate = (video_analysis_dir / slug).resolve(strict=False)
    try:
        root.relative_to(channel_root)
    except ValueError:
        return None, "data/video_analysis の channel_dir 外参照を拒否"
    try:
        candidate.relative_to(root)
        candidate.relative_to(channel_root)
    except ValueError:
        return None, f"data/video_analysis の channel_dir 外参照を拒否 ({_safe_diagnostic_value(slug)})"
    return candidate, None


def _channel_diagnostic_label(index: int, channel: dict[str, object]) -> str:
    parts = [f"entry #{index + 1}"]
    if channel_id := _safe_diagnostic_value(channel.get("id")):
        parts.append(f"id={channel_id}")
    if slug := _safe_diagnostic_value(channel.get("slug")):
        parts.append(f"slug={slug}")
    return " ".join(parts)


def _safe_diagnostic_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"[^A-Za-z0-9_.:@/-]", "_", text)[:80]


def _thumbnail_ttp_reference_missing_reason(channel_dir: Path, thumbnail: dict[str, object]) -> str | None:
    refs, invalid_refs = _thumbnail_reference_images(channel_dir, thumbnail)
    if invalid_refs:
        sample = ", ".join(invalid_refs[:3])
        return f"reference_images.default の参照パスが不正: {sample}"
    if not refs:
        return "thumbnail reference_images.default 未設定 / reference_images.default が空または未転記"

    missing_refs = [str(path) for path in refs if not path.is_file()]
    if missing_refs:
        sample = ", ".join(missing_refs[:3])
        return f"reference_images.default の参照先が見つからない / 参照画像が存在しない: {sample}"
    return None


def _benchmark_report_files(channel_dir: Path) -> list[Path]:
    return _matching_files(channel_dir / "docs" / "benchmarks", "*.md")


def _benchmark_thumbnail_files(channel_dir: Path) -> list[Path]:
    root = channel_dir / "data" / "thumbnail_compare" / "benchmark"
    if not root.is_dir():
        return []
    patterns = ("*.jpg", "*.jpeg", "*.png", "*.webp")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in root.rglob(pattern) if path.is_file())
    return sorted(files)


def _thumbnail_reference_images(
    channel_dir: Path,
    thumbnail: dict[str, object] | None = None,
) -> tuple[list[Path], list[str]]:
    if thumbnail is None:
        thumbnail_read = _skill_config_mapping(channel_dir, "thumbnail")
        if thumbnail_read.error:
            return [], [thumbnail_read.error]
        thumbnail = thumbnail_read.data

    image_generation = thumbnail.get("image_generation")
    if not isinstance(image_generation, dict):
        return [], []
    gemini = image_generation.get("gemini")
    if not isinstance(gemini, dict):
        return [], []
    reference_images = gemini.get("reference_images")
    if not isinstance(reference_images, dict):
        return [], []

    resolved = resolve_configured_benchmark_references(channel_dir, reference_images.get("default"))
    invalid_refs = list(resolved.invalid_reasons)
    invalid_refs.extend(f"未解決 placeholder が残っている: {value}" for value in resolved.placeholders)
    return resolved.references, invalid_refs


@dataclass(frozen=True)
class _MusicReadiness:
    ready: bool
    errors: list[str]


def _suno_music_readiness(channel_dir: Path, channels: list[dict[str, object]]) -> _MusicReadiness:
    errors: list[str] = []
    suno_read = _skill_config_mapping(channel_dir, "suno")
    if suno_read.error:
        errors.append(suno_read.error)
    suno = suno_read.data
    genre_line = str(suno.get("genre_line") or "")
    style_char_limit = suno.get("style_char_limit", 120)
    try:
        limit = int(style_char_limit)
    except (TypeError, ValueError):
        limit = 120
        errors.append("suno.style_char_limit が数値ではありません")
    genre_ready = False
    if genre_line.strip():
        if len(genre_line) <= limit:
            genre_ready = True
        else:
            errors.append(f"Suno genre_line が style_char_limit 超過 ({len(genre_line)}/{limit})")
    variants = suno.get("style_variants")
    if isinstance(variants, dict):
        for name, variant in variants.items():
            if not isinstance(variant, dict):
                continue
            variant_genre_line = variant.get("genre_line")
            if isinstance(variant_genre_line, str) and len(variant_genre_line) > limit:
                errors.append(
                    "Suno style_variants."
                    f"{_safe_diagnostic_value(name)}.genre_line が style_char_limit 超過 "
                    f"({len(variant_genre_line)}/{limit})"
                )
    if genre_ready:
        return _MusicReadiness(True, errors)

    video_analysis_dir = channel_dir / "data" / "video_analysis"
    slug_dirs: list[Path] = []
    for slug in _approved_ttp_channel_slugs(channels):
        slug_dir, slug_error = _video_analysis_slug_dir(channel_dir, video_analysis_dir, slug)
        if slug_error:
            errors.append(slug_error)
            continue
        if slug_dir is None:
            continue
        slug_dirs.append(slug_dir)
    if not video_analysis_dir.is_dir():
        return _MusicReadiness(False, errors)
    for slug_dir in slug_dirs:
        for path in slug_dir.glob("*.json"):
            payload_read = _read_json_mapping(path)
            if payload_read.error:
                errors.append(payload_read.error)
                continue
            payload = payload_read.data
            preset = payload.get("suno_preset")
            if isinstance(preset, dict) and str(preset.get("genre_line") or "").strip():
                return _MusicReadiness(True, errors)
    return _MusicReadiness(False, errors)


def check_initial_setup_readiness(channel_dir: Path) -> CheckResult:
    issues: list[str] = []

    thumbnail_cfg, thumbnail_error = _load_skill_config_for_channel("thumbnail", channel_dir)
    if thumbnail_error:
        issues.append(thumbnail_error)
    else:
        issues.extend(check_thumbnail_skill_config(channel_dir, thumbnail_cfg))

    suno_cfg, suno_error = _load_skill_config_for_channel("suno", channel_dir)
    if suno_error:
        issues.append(suno_error)
    else:
        msg = check_suno_genre_line_char_limit(suno_cfg)
        if msg:
            issues.append(msg)

    for desc_md in _planning_descriptions_md_paths(channel_dir):
        msg = check_descriptions_md_parseability(desc_md, allowed_root=channel_dir)
        if msg:
            issues.append(msg)

    if not issues:
        return CheckResult(
            id="initial_setup_readiness",
            status="ok",
            category=DATA_CATEGORY,
            message="初期セットアップの thumbnail / suno / descriptions.md 事前検査 OK",
        )

    return CheckResult(
        id="initial_setup_readiness",
        status="warn",
        category=DATA_CATEGORY,
        message="; ".join(issues),
        next_action={
            "kind": "human",
            "instructions": (
                "/channel-new（再生成モード）で config/skills/thumbnail.yaml と config/skills/suno.yaml を再確認し、"
                "descriptions.md の parse 失敗は /video-description で再生成してください"
            ),
        },
    )


def _load_skill_config_for_channel(skill: str, target_channel_dir: Path) -> tuple[dict, str | None]:
    from youtube_automation.utils.exceptions import ConfigError
    from youtube_automation.utils.skill_config import load_skill_config

    try:
        with _temporary_channel_dir(target_channel_dir):
            return load_skill_config(skill, use_cache=False), None
    except (ConfigError, OSError, yaml.YAMLError) as exc:
        return {}, f"config/skills/{skill}.yaml 読み込み失敗: {exc}"


def _planning_descriptions_md_paths(channel_dir: Path) -> list[Path]:
    planning_root = channel_dir / "collections" / "planning"
    if not planning_root.is_dir():
        return []
    return sorted(planning_root.glob("*/20-documentation/descriptions.md"))


def check_upload_ready(channel_dir: Path) -> CheckResult:
    token_path = channel_dir / "auth" / "token.json"

    if not token_path.exists():
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message="auth/token.json が存在しない",
            next_action={
                "kind": "ai-exec",
                "cmd": "uv run yt-channel-status を実行して OAuth 認証を完了してください",
            },
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

    if not issues:
        return CheckResult(
            id="upload_ready",
            status="ok",
            category=UPLOAD_CATEGORY,
            message=f"upload 必須 scope 充足, channel_id 設定済み ({channel_id})",
        )

    # scope 不足が最優先事由: 再認証が必要
    if missing_scopes:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category=UPLOAD_CATEGORY,
            message="; ".join(issues),
            next_action={
                "kind": "human",
                "instructions": (
                    "token.json を削除して `uv run yt-channel-status` で再認証し、"
                    "youtube / youtube.force-ssl scope を含む OAuth 同意で取得し直してください"
                ),
            },
        )

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


def run_all_checks(channel_dir: Path) -> list[CheckResult]:
    return [
        check_ffmpeg(),
        check_ffprobe(),
        check_uv(),
        check_uv_project(channel_dir),
        check_automation_package(channel_dir),
        check_skills_synced(channel_dir),
        check_numbered_duplicates(channel_dir),
        check_gcloud(),
        check_gcloud_account(),
        check_gcp_project(channel_dir),
        check_billing(channel_dir),
        check_apis_enabled(channel_dir),
        check_adc(),
        check_adc_quota_project(channel_dir),
        check_iam_aiplatform_user(channel_dir),
        check_env_file(channel_dir),
        check_client_secrets(channel_dir),
        check_oauth_token(channel_dir),
        check_channel_config(channel_dir),
        check_playlist_config(channel_dir),
        check_playlist_create_dry_run(channel_dir),
        check_analytics_report(channel_dir),
        check_benchmark_data(channel_dir),
        check_ttp_wf_new_readiness(channel_dir),
        check_initial_setup_readiness(channel_dir),
        check_upload_ready(channel_dir),
    ]


def summarize(results: list[CheckResult]) -> dict:
    counts = {"ok": 0, "warn": 0, "fail": 0, "unknown": 0}
    next_check_id: Optional[str] = None
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        if next_check_id is None and r.status in ("fail", "warn", "unknown"):
            next_check_id = r.id
    return {**counts, "next_check_id": next_check_id}


def resolve_channel_dir(target: Optional[str]) -> Path:
    if target:
        return Path(target).resolve()
    env_dir = os.environ.get("CHANNEL_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return Path.cwd().resolve()


_COLORS = {
    "ok": "\033[0;32m",
    "warn": "\033[0;33m",
    "fail": "\033[0;31m",
    "unknown": "\033[0;90m",
}
_RESET = "\033[0m"
_STATUS_ICONS = {"ok": "✓", "warn": "!", "fail": "✗", "unknown": "?"}


def render_table(results: list[CheckResult], summary: dict, channel_dir: Path) -> str:
    lines: list[str] = []
    lines.append(f"channel_dir: {channel_dir}")

    current_category: Optional[str] = None
    for r in results:
        if r.category != current_category:
            current_category = r.category
            lines.append("")
            lines.append(f"=== {current_category} ===")
            lines.append(f"{'STATUS':<8} {'CHECK':<22} MESSAGE")
            lines.append("-" * 78)
        color = _COLORS.get(r.status, "")
        icon = _STATUS_ICONS.get(r.status, "?")
        lines.append(f"{color}{icon} {r.status:<5}{_RESET} {r.id:<22} {r.message}")
        if r.next_action:
            kind = r.next_action.get("kind")
            if kind == "human":
                if r.next_action.get("url"):
                    lines.append(f"  → {r.next_action['url']}")
                if r.next_action.get("instructions"):
                    lines.append(f"  → {r.next_action['instructions']}")
            elif kind == "ai-exec":
                lines.append(f"  → run: {r.next_action.get('cmd', '')}")

    lines.append("")
    lines.append(
        f"summary: ok={summary['ok']} warn={summary['warn']} fail={summary['fail']} unknown={summary.get('unknown', 0)}"
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
    results = run_all_checks(channel_dir)
    summary = summarize(results)

    if args.json:
        payload = {
            "channel_dir": str(channel_dir),
            "summary": summary,
            "checks": [asdict(r) for r in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_table(results, summary, channel_dir))

    return 0


if __name__ == "__main__":
    sys.exit(main())
