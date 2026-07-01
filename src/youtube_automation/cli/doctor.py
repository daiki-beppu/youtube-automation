"""yt-doctor: ツール・API 設定の状態診断 CLI (read-only)"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import yaml

from youtube_automation.auth.oauth_handler import resolve_client_secrets_location
from youtube_automation.cli.skills_sync import bundled_skill_names

PYPROJECT_FILENAME = "pyproject.toml"
CLAUDE_SKILLS_DIR = Path(".claude") / "skills"
AGENTS_SKILLS_LINK = Path(".agents") / "skills"
SKILL_FILENAME = "SKILL.md"
AUTOMATION_PACKAGE_NAME = "youtube-channels-automation"
SKILLS_SYNC_CMD = "uv run yt-skills sync --asset skills --force"
SKILLS_SYNC_PRUNE_CMD = "uv run yt-skills sync --asset skills --force --prune --yes"
LEGACY_BUNDLED_SKILLS = ("onboard", "distrokid-prep")

BOOTSTRAP_CATEGORY = "bootstrap"
API_CATEGORY = "api"
CHANNEL_CATEGORY = "channel"
DATA_CATEGORY = "data"
UPLOAD_CATEGORY = "upload"

REQUIRED_APIS = [
    "youtube.googleapis.com",
    "youtubeanalytics.googleapis.com",
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


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {' '.join(cmd)}"


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
                "cmd": "uv add git+https://github.com/daiki-beppu/youtube-automation.git",
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
                    ".claude/skills/channel-setup/references/gcp-bootstrap.sh <project-id> を実行して .env を書き出す"
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
            message="config/channel/ ディレクトリが存在しない (新規チャンネル)",
            next_action={
                "kind": "human",
                "instructions": "/channel-new を実行して新規チャンネル設定を作成してください",
            },
        )

    # config/channel/ 存在 → load_config() でロード可能か検証。
    # CHANNEL_DIR を一時的に上書きしてシングルトンを差し替え、終了後に必ず復元する。
    from youtube_automation.utils.config import load_config
    from youtube_automation.utils.config import reset as reset_config
    from youtube_automation.utils.exceptions import ConfigError

    old_env = os.environ.get("CHANNEL_DIR")
    os.environ["CHANNEL_DIR"] = str(channel_dir)
    try:
        reset_config()
        load_config()
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
                "instructions": "/channel-import を実行して設定を修復してください",
            },
        )
    finally:
        reset_config()
        if old_env is None:
            os.environ.pop("CHANNEL_DIR", None)
        else:
            os.environ["CHANNEL_DIR"] = old_env


def check_analytics_report(channel_dir: Path) -> CheckResult:
    input_mode = _resolve_wf_new_input_mode(channel_dir)
    if input_mode.stale_report:
        return CheckResult(
            id="analytics_report",
            status="fail",
            category=DATA_CATEGORY,
            message=(
                "reports/analysis_*.md が最新 data/analytics_data_*.json より古い。/wf-new は stale report では開始不可"
            ),
            next_action={
                "kind": "human",
                "instructions": "/analytics-analyze を再実行してください（必要なら先に /analytics-collect）",
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
        stale_report = latest_data is not None and (latest_report is None or latest_report[0] < latest_data[0])
        return _WfNewInputMode(
            mode="analytics mode",
            report_count=len(reports),
            benchmark_count=len(benchmarks),
            stale_report=stale_report,
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
            status="ok",
            category=DATA_CATEGORY,
            message="config/channel/analytics.json 未生成のため TTP readiness は未適用 (/channel-new 初回 preflight)",
        )

    analytics = _read_json_mapping(analytics_path)
    channels = _benchmark_channels(analytics)
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

    missing = _missing_ttp_readiness_items(channel_dir, channels)
    if missing:
        return CheckResult(
            id="ttp_wf_new_readiness",
            status="warn",
            category=DATA_CATEGORY,
            message="TTP 完了条件が未充足: " + "; ".join(missing),
            next_action={
                "kind": "human",
                "instructions": (
                    "/channel-new Step 5-9 の不足項目を解消してください。"
                    "意図的にスキップする場合は docs/channel/ttp-seed-confirmation.md に "
                    "ユーザー承認済み例外として未反映項目を明記してください"
                ),
            },
        )

    return CheckResult(
        id="ttp_wf_new_readiness",
        status="ok",
        category=DATA_CATEGORY,
        message="TTP 対象承認・branding snapshot・thumbnail / music readiness が /wf-new 接続可能",
    )


def _read_json_mapping(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_yaml_mapping(path: Path) -> dict[str, object]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _benchmark_channels(analytics: dict[str, object]) -> list[dict[str, object]]:
    benchmark = analytics.get("benchmark")
    if not isinstance(benchmark, dict):
        return []
    channels = benchmark.get("channels")
    if not isinstance(channels, list):
        return []
    return [channel for channel in channels if isinstance(channel, dict)]


def _missing_ttp_readiness_items(channel_dir: Path, channels: list[dict[str, object]]) -> list[str]:
    missing: list[str] = []
    approved_exceptions: set[str] = set()

    channels_without_relationship = [
        str(channel.get("name") or channel.get("id") or index + 1)
        for index, channel in enumerate(channels)
        if not str(channel.get("relationship") or "").strip()
    ]
    if channels_without_relationship:
        missing.append(f"benchmark.channels の relationship 未設定 ({', '.join(channels_without_relationship)})")

    seed_confirmation = channel_dir / "docs" / "channel" / "ttp-seed-confirmation.md"
    if not seed_confirmation.is_file():
        missing.append("docs/channel/ttp-seed-confirmation.md 未作成")
    else:
        seed_text = seed_confirmation.read_text(encoding="utf-8", errors="replace")
        seed_missing, approved_exceptions = _validate_ttp_seed_confirmation(seed_text)
        missing.extend(seed_missing)

    missing.extend(_missing_branding_snapshot_items(channel_dir, channels))

    thumbnail = _read_yaml_mapping(channel_dir / "config" / "skills" / "thumbnail.yaml")
    if not _has_thumbnail_ttp_reference(thumbnail) and "thumbnail" not in approved_exceptions:
        missing.append("thumbnail reference_images.default 未設定")

    youtube = _read_json_mapping(channel_dir / "config" / "channel" / "youtube.json")
    if (
        youtube.get("music_engine") == "suno"
        and not _has_suno_music_readiness(channel_dir)
        and "music" not in approved_exceptions
    ):
        missing.append("Suno genre_line または data/video_analysis の suno_preset 未設定")

    return missing


_SEED_CONFIRMATION_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("source", ("source", "ソース", "url", "handle", "channel id", "チャンネルid")),
    ("seed fetch 要約", ("seed fetch", "fetch", "取得要約", "収集要約")),
    ("承認 / 不採用判断", ("承認", "不採用", "approved", "rejected")),
    ("転写したい要素", ("転写", "ttp", "要素")),
    ("relationship", ("relationship", "関係性")),
    ("未反映項目", ("未反映", "未適用", "none", "なし")),
)


def _validate_ttp_seed_confirmation(seed_text: str) -> tuple[list[str], set[str]]:
    missing = [
        f"ttp-seed-confirmation.md に {label} が未記録"
        for label, markers in _SEED_CONFIRMATION_MARKERS
        if not _contains_any_marker(seed_text, markers)
    ]

    unapproved_skip_lines = [
        line.strip()
        for line in seed_text.splitlines()
        if _line_mentions_ttp_skip(line) and not _line_mentions_approved_exception(line)
    ]
    if unapproved_skip_lines:
        missing.append("ttp-seed-confirmation.md に未承認の TTP 未反映 / スキップ項目あり")

    return missing, _approved_ttp_exceptions(seed_text)


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lower_text = text.lower()
    return any(marker.lower() in lower_text for marker in markers)


def _line_mentions_ttp_skip(line: str) -> bool:
    lower_line = line.lower()
    if "なし" in line or "none" in lower_line:
        return False
    return "未反映" in line or "スキップ" in line or "skip" in lower_line


def _line_mentions_approved_exception(line: str) -> bool:
    lower_line = line.lower()
    return "ユーザー承認済み例外" in line or "approved exception" in lower_line


def _approved_ttp_exceptions(seed_text: str) -> set[str]:
    exceptions: set[str] = set()
    for line in seed_text.splitlines():
        if not _line_mentions_approved_exception(line):
            continue
        lower_line = line.lower()
        if "thumbnail" in lower_line or "サムネ" in line:
            exceptions.add("thumbnail")
        if "music" in lower_line or "suno" in lower_line or "曲構造" in line or "音楽" in line:
            exceptions.add("music")
    return exceptions


def _missing_branding_snapshot_items(channel_dir: Path, channels: list[dict[str, object]]) -> list[str]:
    branding_snapshot = _read_json_mapping(channel_dir / "docs" / "channel" / "competitor-branding-snapshot.json")
    snapshot_items = branding_snapshot.get("items")
    if (
        branding_snapshot.get("untrusted_data") is not True
        or not isinstance(snapshot_items, list)
        or not snapshot_items
    ):
        return ["docs/channel/competitor-branding-snapshot.json 未作成または空"]

    missing: list[str] = []
    approved_ids = _approved_ttp_channel_ids(channels)
    snapshot_by_id = {
        str(item.get("id")): item
        for item in snapshot_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }

    channels_without_id = [
        str(channel.get("name") or index + 1)
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

    return missing


def _approved_ttp_channel_ids(channels: list[dict[str, object]]) -> list[str]:
    return [channel_id for channel in channels if (channel_id := str(channel.get("id") or "").strip())]


def _has_thumbnail_ttp_reference(thumbnail: dict[str, object]) -> bool:
    image_generation = thumbnail.get("image_generation")
    if not isinstance(image_generation, dict):
        return False
    gemini = image_generation.get("gemini")
    if not isinstance(gemini, dict):
        return False
    reference_images = gemini.get("reference_images")
    if not isinstance(reference_images, dict):
        return False
    default = reference_images.get("default")
    if isinstance(default, str):
        return bool(default.strip())
    if isinstance(default, list):
        return any(isinstance(item, str) and item.strip() for item in default)
    return False


def _has_suno_music_readiness(channel_dir: Path) -> bool:
    suno = _read_yaml_mapping(channel_dir / "config" / "skills" / "suno.yaml")
    if str(suno.get("genre_line") or "").strip():
        return True

    video_analysis_dir = channel_dir / "data" / "video_analysis"
    if not video_analysis_dir.is_dir():
        return False
    for path in video_analysis_dir.glob("*/*.json"):
        payload = _read_json_mapping(path)
        preset = payload.get("suno_preset")
        if isinstance(preset, dict) and str(preset.get("genre_line") or "").strip():
            return True
    return False


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
        check_analytics_report(channel_dir),
        check_benchmark_data(channel_dir),
        check_ttp_wf_new_readiness(channel_dir),
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
