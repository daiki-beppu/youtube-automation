from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

_V2_COLLECTION = "collections/planning/v2-prepared"
_STATE_FILENAME = "workflow-state.json"
_RAW_MASTER_COMMAND = f'uv run yt-raw-master-check {_V2_COLLECTION}; echo "EXIT=$?"'
_MISSING = object()


def _build_command(prompt: str, *, max_turns: int) -> list[str]:
    evaluation_prompt = (
        f"{prompt}\n\n"
        "評価 fixture の外へは書き込まず、/wf-status の手順に従って読み取り専用で回答してください。"
        f"raw master の突合には `{_RAW_MASTER_COMMAND}` の完全一致だけを使ってください。"
    )
    return [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--tools",
        "Read,Glob,Grep,Bash",
        "--allowed-tools",
        "Read",
        "Glob",
        "Grep",
        f"Bash({_RAW_MASTER_COMMAND})",
        "--no-session-persistence",
        "--max-turns",
        str(max_turns),
        evaluation_prompt,
    ]


def _snapshot_fixture(fixture_dir: Path) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    for path in sorted(fixture_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"eval fixture に symlink は置けません: {path.relative_to(fixture_dir)}")
        relative_path = path.relative_to(fixture_dir).as_posix()
        snapshot[relative_path] = None if path.is_dir() else path.read_bytes()
    return snapshot


def _changed_files(fixture_dir: Path, before: dict[str, bytes | None]) -> list[str]:
    after = _snapshot_fixture(fixture_dir)
    return sorted(path for path in set(before) | set(after) if before.get(path, _MISSING) != after.get(path, _MISSING))


def _restore_fixture(fixture_dir: Path, snapshot: dict[str, bytes | None]) -> None:
    current = _snapshot_fixture(fixture_dir)
    type_changes = {
        path for path in set(current) & set(snapshot) if (current[path] is None) != (snapshot[path] is None)
    }
    removal_paths = (set(current) - set(snapshot)) | type_changes
    for relative_path in sorted(removal_paths, key=lambda path: len(Path(path).parts), reverse=True):
        path = fixture_dir / relative_path
        if current[relative_path] is None:
            path.rmdir()
        else:
            path.unlink()
    for relative_path, content in sorted(snapshot.items(), key=lambda item: len(Path(item[0]).parts)):
        path = fixture_dir / relative_path
        if content is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _tool_calls(payload: dict[str, object]) -> list[dict[str, object]]:
    denials = payload.get("permission_denials")
    if not isinstance(denials, list):
        raise ValueError("Claude Code JSON の permission_denials が配列ではありません")
    calls: list[dict[str, object]] = []
    for denial in denials:
        if not isinstance(denial, dict):
            raise ValueError("Claude Code JSON の permission_denials 要素が object ではありません")
        name = denial.get("tool_name")
        tool_input = denial.get("tool_input")
        if not isinstance(name, str) or not isinstance(tool_input, dict):
            raise ValueError("Claude Code JSON の denied tool call が不正です")
        calls.append({"name": name, "input": tool_input, "denied": True})
    return calls


def _build_output(
    claude_stdout: str,
    *,
    changed_state_files: list[str],
    changed_fixture_files: list[str],
) -> str:
    try:
        payload = json.loads(claude_stdout)
    except json.JSONDecodeError as error:
        raise ValueError("Claude Code JSON を parse できません") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), str):
        raise ValueError("Claude Code JSON に result 文字列がありません")
    result = {
        "response": payload["result"],
        "tool_calls": _tool_calls(payload),
        "workflow_state_unchanged": not changed_state_files,
        "fixture_unchanged": not changed_fixture_files,
        "changed_workflow_state_files": changed_state_files,
        "changed_fixture_files": changed_fixture_files,
    }
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.communicate()


def _run_claude(command: list[str], *, fixture_dir: Path, timeout_seconds: int) -> str:
    environment = dict(os.environ)
    environment["CHANNEL_DIR"] = str(fixture_dir)
    process = subprocess.Popen(
        command,
        cwd=fixture_dir,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate(process)
        raise TimeoutError(f"claude -p が {timeout_seconds} 秒で timeout しました") from error
    if process.returncode != 0:
        raise RuntimeError(f"claude -p が exit {process.returncode} で失敗しました")
    return stdout


def _positive_int(config: dict[str, object], key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"provider config `{key}` は正の整数でなければなりません")
    return value


def _fixture_dir(config: dict[str, object]) -> Path:
    base_path = config.get("basePath")
    relative = config.get("fixtureDir")
    if not isinstance(base_path, str) or not isinstance(relative, str) or not relative:
        raise ValueError("provider config に basePath / fixtureDir が必要です")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("provider config `fixtureDir` は config 配下の相対 path に限定されます")
    fixture_dir = (Path(base_path) / relative_path).resolve()
    if not fixture_dir.is_dir():
        raise ValueError(f"eval fixture が見つかりません: {fixture_dir}")
    return fixture_dir


def call_api(prompt: str, options: dict[str, object], _context: dict[str, object]) -> dict[str, object]:
    config = options.get("config")
    if not isinstance(config, dict):
        return {"output": "", "error": "provider config が object ではありません"}
    try:
        fixture_dir = _fixture_dir(config)
        timeout_seconds = _positive_int(config, "timeoutSeconds")
        max_turns = _positive_int(config, "maxTurns")
        before = _snapshot_fixture(fixture_dir)
        try:
            stdout = _run_claude(
                _build_command(prompt, max_turns=max_turns),
                fixture_dir=fixture_dir,
                timeout_seconds=timeout_seconds,
            )
            changed_fixture_files = _changed_files(fixture_dir, before)
        finally:
            _restore_fixture(fixture_dir, before)
        changed_state_files = [path for path in changed_fixture_files if Path(path).name == _STATE_FILENAME]
        return {
            "output": _build_output(
                stdout,
                changed_state_files=changed_state_files,
                changed_fixture_files=changed_fixture_files,
            ),
            "cached": False,
        }
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        return {"output": "", "error": str(error), "cached": False}
