"""yt-doctor: registry, rendering, and CLI composition for readiness checks."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from youtube_automation.application.channel_readiness import checks as readiness_checks
from youtube_automation.application.channel_readiness.checks import (
    _APPLY_PROJECT_ID,
    API_CATEGORY,
    BOOTSTRAP_CATEGORY,
    CHANNEL_CATEGORY,
    DATA_CATEGORY,
    UPLOAD_CATEGORY,
    AgentCommand,
    ApplyKind,
    CheckDefinition,
    CheckResult,
    CwdSemantics,
    RemediationAction,
    _ai_exec_action,
    _decision_action,
    _is_interactive_auth_command,
    _parse_billing_account_id,
    _parse_project_id,
    _remediation_action,
    _without_channel_dir,
)
from youtube_automation.application.channel_readiness.checks import (
    _subprocess_run as _run,
)
from youtube_automation.commands.system.skills_sync import bundled_skill_names
from youtube_automation.configuration import (
    channel_dir,
    explicit_channel_selection,
    find_workspace_root,
)
from youtube_automation.core.errors import ConfigError

# Public compatibility exports. Check implementations live in the readiness application module,
# while existing callers can continue importing the result/action vocabulary here.
HumanBrowserAuth = readiness_checks.HumanBrowserAuth
ManualRemediation = readiness_checks.ManualRemediation
REQUIRED_APIS = readiness_checks.REQUIRED_APIS
UPLOAD_REQUIRED_SCOPES = readiness_checks.UPLOAD_REQUIRED_SCOPES
_approved_ttp_exceptions = readiness_checks._approved_ttp_exceptions
_human_auth_action = readiness_checks._human_auth_action
_resolve_wf_new_input_mode = readiness_checks._resolve_wf_new_input_mode
_adc_quota_project = readiness_checks._adc_quota_project
_domain_project_id_for = readiness_checks._project_id_for
_today_yyyymmdd = readiness_checks._today_yyyymmdd
build = readiness_checks.build
build_youtube_service = readiness_checks.build_youtube_service
reconcile_streaming_vps = readiness_checks.reconcile_streaming_vps


def _project_id_for(channel_dir: Path) -> str | None:
    readiness_checks._adc_quota_project = _adc_quota_project
    return _domain_project_id_for(channel_dir)


def _domain_check(name: str):
    """Bind legacy command probes to a readiness check at the CLI boundary."""

    def run(*args, **kwargs):
        readiness_checks._project_id_for = _project_id_for
        readiness_checks._approved_ttp_exceptions = _approved_ttp_exceptions
        readiness_checks._today_yyyymmdd = _today_yyyymmdd
        readiness_checks.build = build
        readiness_checks.build_youtube_service = build_youtube_service
        readiness_checks.bundled_skill_names = bundled_skill_names
        readiness_checks.reconcile_streaming_vps = reconcile_streaming_vps
        probes = readiness_checks.ReadinessProbes(run=_run)
        with readiness_checks.use_probes(probes):
            return getattr(readiness_checks, name)(*args, **kwargs)

    run.__name__ = name
    return run


check_adc = _domain_check("check_adc")
check_adc_quota_project = _domain_check("check_adc_quota_project")
check_analytics_report = _domain_check("check_analytics_report")
check_apis_enabled = _domain_check("check_apis_enabled")
check_automation_package = _domain_check("check_automation_package")
check_benchmark_data = _domain_check("check_benchmark_data")
check_billing = _domain_check("check_billing")
check_channel_config = _domain_check("check_channel_config")
check_client_secrets = _domain_check("check_client_secrets")
check_ffmpeg = _domain_check("check_ffmpeg")
check_ffprobe = _domain_check("check_ffprobe")
check_gcloud = _domain_check("check_gcloud")
check_gcloud_account = _domain_check("check_gcloud_account")
check_gcp_project = _domain_check("check_gcp_project")
check_iam_aiplatform_user = _domain_check("check_iam_aiplatform_user")
check_initial_setup_readiness = _domain_check("check_initial_setup_readiness")
check_numbered_duplicates = _domain_check("check_numbered_duplicates")
check_oauth_client_sharing = _domain_check("check_oauth_client_sharing")
check_oauth_token = _domain_check("check_oauth_token")
check_oauth_token_readonly = _domain_check("check_oauth_token_readonly")
check_playlist_config = _domain_check("check_playlist_config")
check_playlist_create_dry_run = _domain_check("check_playlist_create_dry_run")
check_reporting_job = _domain_check("check_reporting_job")
check_skills_synced = _domain_check("check_skills_synced")
check_streaming_vps_state = _domain_check("check_streaming_vps_state")
check_ttp_wf_new_readiness = _domain_check("check_ttp_wf_new_readiness")
check_upload_ready = _domain_check("check_upload_ready")
check_uv = _domain_check("check_uv")
check_uv_project = _domain_check("check_uv_project")
check_wf_new_readiness = _domain_check("check_wf_new_readiness")

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
                next_action=_decision_action("--project-id"),
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
                next_action=_decision_action("--billing-account"),
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
                    next_action=_decision_action("--project-id"),
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
        if (
            apply_kind is ApplyKind.NONE
            or not isinstance(action, AgentCommand)
            or not action.auto_apply
            # ai-exec と誤ってラベルされても対話 auth は非対話実行しない
            or _is_interactive_auth_command(action.argv)
        ):
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
