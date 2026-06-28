"""yt-doctor: API 設定の状態診断 CLI (read-only)"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

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
    category: str = "api"  # system / api / channel / data / upload
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


# --- checks ---


def check_ffmpeg() -> CheckResult:
    path = shutil.which("ffmpeg")
    if not path:
        return CheckResult(
            id="ffmpeg",
            status="fail",
            category="system",
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
    return CheckResult(id="ffmpeg", status="ok", category="system", message=f"ffmpeg found: {path}")


def check_ffprobe() -> CheckResult:
    path = shutil.which("ffprobe")
    if not path:
        return CheckResult(
            id="ffprobe",
            status="fail",
            category="system",
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
    return CheckResult(id="ffprobe", status="ok", category="system", message=f"ffprobe found: {path}")


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


def check_client_secrets(channel_dir: Path) -> CheckResult:
    path = channel_dir / "auth" / "client_secrets.json"
    if not path.exists():
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
                    "Console で「認証情報を作成 → OAuth クライアント ID → "
                    "アプリの種類: デスクトップ」を選び、ダウンロードした JSON を "
                    f"`{path}` に配置してください。"
                ),
            },
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return CheckResult(
            id="client_secrets",
            status="fail",
            message=f"client_secrets.json 読み込み失敗: {e}",
        )
    installed = data.get("installed") or data.get("web") or {}
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
                "cmd": "yt-channel-status を 1 回叩くと初回認証フロー (loopback redirect) が発火する",
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
            category="channel",
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
            category="channel",
            message="config/channel/ ロード成功",
        )
    except ConfigError as e:
        return CheckResult(
            id="channel_config",
            status="fail",
            category="channel",
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
            category="data",
            message=(
                "reports/analysis_*.md が最新 data/analytics_data_*.json より古い。/wf-new は stale report では開始不可"
            ),
            next_action={
                "kind": "human",
                "instructions": (
                    "/analytics-analyze を再実行してください。"
                    "必要なら先に /analytics-collect で最新データを収集してください"
                ),
            },
        )
    if input_mode.report_count > 0:
        return CheckResult(
            id="analytics_report",
            status="ok",
            category="data",
            message=f"reports/analysis_*.md {input_mode.report_count} 件存在 ({input_mode.mode})",
        )

    return CheckResult(
        id="analytics_report",
        status="ok",
        category="data",
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
    return [path for path in directory.glob(pattern) if path.is_file()]


def _latest_filename_date(paths: list[Path]) -> Optional[tuple[int, Path]]:
    dated_paths: list[tuple[int, Path]] = []
    for path in paths:
        match = re.search(r"(\d{8})", path.name)
        if match:
            dated_paths.append((int(match.group(1)), path))
    if not dated_paths:
        return None
    return max(dated_paths, key=lambda item: item[0])


def check_benchmark_data(channel_dir: Path) -> CheckResult:
    input_mode = _resolve_wf_new_input_mode(channel_dir)
    if input_mode.benchmark_count > 0:
        return CheckResult(
            id="benchmark_data",
            status="ok",
            category="data",
            message=f"data/benchmark_*.json {input_mode.benchmark_count} 件存在 ({input_mode.mode} 対応)",
        )

    if input_mode.mode == "analytics mode":
        return CheckResult(
            id="benchmark_data",
            status="ok",
            category="data",
            message=(
                "data/benchmark_*.json 未生成。analytics mode では "
                "/collection-ideate が /benchmark の鮮度確認・必要時更新を扱う"
            ),
        )

    return CheckResult(
        id="benchmark_data",
        status="ok",
        category="data",
        message=f"data/benchmark_*.json 未生成。/wf-new は {input_mode.mode} で開始可能",
    )


def check_upload_ready(channel_dir: Path) -> CheckResult:
    token_path = channel_dir / "auth" / "token.json"

    if not token_path.exists():
        return CheckResult(
            id="upload_ready",
            status="fail",
            category="upload",
            message="auth/token.json が存在しない",
            next_action={
                "kind": "ai-exec",
                "cmd": "yt-channel-status を実行して OAuth 認証を完了してください",
            },
        )

    try:
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category="upload",
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
            category="upload",
            message=f"upload 必須 scope 充足, channel_id 設定済み ({channel_id})",
        )

    # scope 不足が最優先事由: 再認証が必要
    if missing_scopes:
        return CheckResult(
            id="upload_ready",
            status="fail",
            category="upload",
            message="; ".join(issues),
            next_action={
                "kind": "human",
                "instructions": (
                    "token.json を削除して `yt-channel-status` で再認証し、"
                    "youtube / youtube.force-ssl scope を含む OAuth 同意で取得し直してください"
                ),
            },
        )

    return CheckResult(
        id="upload_ready",
        status="fail",
        category="upload",
        message="; ".join(issues),
        next_action={
            "kind": "human",
            "instructions": (
                "config/channel/meta.json の channel.channel_id に YouTube チャンネル ID を設定してください。"
                "`yt-channel-status` でチャンネル ID を確認できます。"
            ),
        },
    )


def run_all_checks(channel_dir: Path) -> list[CheckResult]:
    return [
        check_ffmpeg(),
        check_ffprobe(),
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


def _find_channel_dirs(search_root: Path) -> list[Path]:
    """search_root 直下のディレクトリで auth/client_secrets.json を持つものを返す。"""
    dirs: list[Path] = []
    if not search_root.is_dir():
        return dirs
    for child in sorted(search_root.iterdir()):
        if child.is_dir() and (child / "auth" / "client_secrets.json").exists():
            dirs.append(child)
    return dirs


def _extract_oauth_info(channel_dir: Path) -> dict:
    """client_secrets.json から GCP プロジェクト・クライアント ID を抽出する。"""
    cs_path = channel_dir / "auth" / "client_secrets.json"
    info: dict = {"channel": channel_dir.name, "path": str(channel_dir)}
    try:
        data = json.loads(cs_path.read_text(encoding="utf-8"))
        installed = data.get("installed") or data.get("web") or {}
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
    parser = argparse.ArgumentParser(prog="yt-doctor", description="API 設定の状態診断")
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
