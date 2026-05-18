"""yt-doctor: API 設定の状態診断 CLI (read-only)"""

from __future__ import annotations

import argparse
import json
import os
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
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_GENAI_USE_VERTEXAI",
]


@dataclass
class CheckResult:
    id: str
    status: str  # ok / warn / fail / unknown
    message: str
    next_action: Optional[dict] = None


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


def _project_id_for(channel_dir: Path) -> Optional[str]:
    env = _read_env_file(channel_dir / ".env")
    return env.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")


# --- checks ---


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
            message="GOOGLE_CLOUD_PROJECT が .env / 環境変数に無い",
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
            message="GOOGLE_CLOUD_PROJECT が未設定のため判定不可",
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
            message=(f"ADC quota project ({quota}) が GOOGLE_CLOUD_PROJECT ({project_id}) と不一致"),
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
                "cmd": "scripts/gcp-bootstrap.sh <project-id> を実行して .env を書き出す",
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


def run_all_checks(channel_dir: Path) -> list[CheckResult]:
    return [
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
    lines.append("")
    lines.append(f"{'STATUS':<8} {'CHECK':<22} MESSAGE")
    lines.append("-" * 78)
    for r in results:
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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="yt-doctor", description="API 設定の状態診断")
    parser.add_argument("--json", action="store_true", help="JSON 出力 (AI 用)")
    parser.add_argument("--target", help="対象 channel dir (既定: CHANNEL_DIR env → CWD)")
    args = parser.parse_args(argv)

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
