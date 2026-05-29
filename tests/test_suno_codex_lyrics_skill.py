"""suno skill の Codex 歌詞生成 wrapper に関する契約テスト。"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CODEX_LYRICS_SH = _REPO_ROOT / ".claude" / "skills" / "suno" / "references" / "codex-lyrics.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bash_available() -> bool:
    return shutil.which("bash") is not None


def _run_script(
    script_path: Path,
    prompt_path: Path,
    output_path: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script_path), str(prompt_path), str(output_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_fake_codex(bin_dir: Path) -> None:
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        r"""#!/usr/bin/env bash
set -euo pipefail

log_file=${FAKE_CODEX_LOG:?}

{
  printf 'invocation_start\n'
  for a in "$@"; do
    printf 'arg_b64: %s\n' "$(printf '%s' "$a" | base64 | tr -d '\n')"
  done
  printf 'invocation_end\n'
} >> "$log_file"

if [[ "${1:-}" == "login" && "${2:-}" == "status" ]]; then
  printf '%s\n' "${FAKE_CODEX_LOGIN_STATUS:-Logged in using ChatGPT}"
  exit 0
fi

if [[ "${1:-}" == "exec" ]]; then
  prompt=""
  found_sep=0
  for a in "$@"; do
    if [ "$found_sep" -eq 1 ]; then
      prompt="$a"
      break
    fi
    if [ "$a" = "--" ]; then
      found_sep=1
    fi
  done

  out_path=""
  if [[ "$prompt" =~ [Ww]rite\ the\ final\ lyrics\ to\ ([^[:space:]]+\.md) ]]; then
    out_path="${BASH_REMATCH[1]}"
  fi

  if [ -n "$out_path" ]; then
    printf '[Verse 1]\nThe kettle hums in the hallway light\n' > "$out_path"
  fi

  final_text="$out_path"
  if [ -n "${FAKE_CODEX_AGENT_MESSAGE_OVERRIDE:-}" ]; then
    final_text="${FAKE_CODEX_AGENT_MESSAGE_OVERRIDE}"
  fi

  printf '%s\n' '{"type":"thread.started","thread_id":"thread_1"}'
  printf '%s\n' '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"drafting"}}'
  printf '%s\n' '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"'"$final_text"'"}}'
  printf '%s\n' '{"type":"turn.completed"}'
  exit 0
fi

echo "unexpected codex invocation: $*" >&2
exit 1
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)


def _prepare_fake_codex_env(
    tmp_path: Path,
    *,
    login_status: str | None = None,
    agent_message_override: str | None = None,
) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_codex(bin_dir)

    log_file = tmp_path / "codex.log"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_CODEX_LOG"] = str(log_file)
    if login_status is not None:
        env["FAKE_CODEX_LOGIN_STATUS"] = login_status
    if agent_message_override is not None:
        env["FAKE_CODEX_AGENT_MESSAGE_OVERRIDE"] = agent_message_override
    return env, log_file


def _parse_invocations(log_text: str) -> list[list[str]]:
    invocations: list[list[str]] = []
    current: list[str] | None = None
    for line in log_text.splitlines():
        if line == "invocation_start":
            current = []
        elif line == "invocation_end":
            if current is not None:
                invocations.append(current)
            current = None
        elif current is not None and line.startswith("arg_b64: "):
            encoded = line[len("arg_b64: ") :]
            current.append(base64.b64decode(encoded).decode("utf-8"))
    return invocations


def test_codex_lyrics_script_exists_and_is_executable() -> None:
    """Given /suno の Codex provider
    When canonical path を確認する
    Then wrapper が実体として存在し、実行可能である。
    """
    assert _CODEX_LYRICS_SH.exists(), f"{_CODEX_LYRICS_SH.relative_to(_REPO_ROOT)} が存在しない"
    assert os.access(_CODEX_LYRICS_SH, os.X_OK), f"{_CODEX_LYRICS_SH.relative_to(_REPO_ROOT)} に実行ビットがない"


def test_codex_lyrics_script_has_shell_contracts() -> None:
    """Given codex-lyrics.sh
    When 本文を読む
    Then Codex JSONL と agent_message path 契約を使う。
    """
    text = _read(_CODEX_LYRICS_SH)

    assert text.splitlines()[0] == "#!/usr/bin/env bash"
    assert "set -euo pipefail" in text
    assert "codex login status" in text
    assert "Logged in using ChatGPT" in text
    assert "--json" in text
    assert "--sandbox workspace-write" in text
    assert "--add-dir" in text
    assert "--skip-git-repo-check" in text
    assert "jq" in text
    assert "agent_message" in text


def test_codex_lyrics_script_bash_syntax_is_valid() -> None:
    """Given codex-lyrics.sh
    When bash -n を実行する
    Then shell 構文エラーがない。
    """
    if not _bash_available():
        pytest.skip("bash が PATH に無いため syntax check をスキップ")
    if not _CODEX_LYRICS_SH.exists():
        pytest.fail(f"{_CODEX_LYRICS_SH.relative_to(_REPO_ROOT)} が存在しない")

    result = subprocess.run(
        ["bash", "-n", str(_CODEX_LYRICS_SH)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_codex_lyrics_script_succeeds_with_fake_codex(tmp_path: Path) -> None:
    """Given fake codex が output.md を生成する状態
    When codex-lyrics.sh を実行する
    Then 成功し、prompt file 本文と出力契約を Codex に渡す。
    """
    if not _CODEX_LYRICS_SH.exists():
        pytest.fail(f"{_CODEX_LYRICS_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path)
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "output.md"
    prompt_path.write_text("Use observational diary tone and ABCB loose rhyme.", encoding="utf-8")

    result = _run_script(_CODEX_LYRICS_SH, prompt_path, output_path, env)

    assert result.returncode == 0, result.stderr
    assert output_path.read_text(encoding="utf-8").startswith("[Verse 1]")

    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    assert any(args == ["login", "status"] for args in invocations)
    exec_invocations = [args for args in invocations if args and args[0] == "exec"]
    assert exec_invocations, f"`codex exec` の呼び出しが無い: {invocations!r}"

    exec_args = exec_invocations[-1]
    assert "--json" in exec_args
    assert "--sandbox" in exec_args and "workspace-write" in exec_args
    assert "--add-dir" in exec_args and str(output_path.parent) in exec_args
    assert "--skip-git-repo-check" in exec_args
    assert "--" in exec_args

    prompt = exec_args[exec_args.index("--") + 1]
    assert "Use observational diary tone and ABCB loose rhyme." in prompt
    assert f"Write the final lyrics to {output_path}" in prompt
    assert f"reply with exactly {output_path}" in prompt
    assert "Do not copy style references verbatim" in prompt


def test_codex_lyrics_script_rejects_agent_message_path_mismatch(tmp_path: Path) -> None:
    """Given fake codex が別 path を最終 agent_message に返す状態
    When codex-lyrics.sh を実行する
    Then 非 0 で停止する。
    """
    if not _CODEX_LYRICS_SH.exists():
        pytest.fail(f"{_CODEX_LYRICS_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, _log_file = _prepare_fake_codex_env(
        tmp_path,
        agent_message_override=str(tmp_path / "elsewhere.md"),
    )
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "output.md"
    prompt_path.write_text("draft lyrics", encoding="utf-8")

    result = _run_script(_CODEX_LYRICS_SH, prompt_path, output_path, env)

    assert result.returncode != 0, "agent_message が output path と違う場合は失敗する必要がある"
    assert "agent_message" in result.stderr


def test_codex_lyrics_script_stops_when_not_logged_in(tmp_path: Path) -> None:
    """Given codex CLI が未ログイン状態
    When codex-lyrics.sh を実行する
    Then codex exec を呼ばずに停止する。
    """
    if not _CODEX_LYRICS_SH.exists():
        pytest.fail(f"{_CODEX_LYRICS_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path, login_status="Not Logged in")
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "output.md"
    prompt_path.write_text("draft lyrics", encoding="utf-8")

    result = _run_script(_CODEX_LYRICS_SH, prompt_path, output_path, env)

    assert result.returncode != 0, "`Not Logged in` は失敗させる必要がある"
    assert not output_path.exists()
    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    assert invocations == [["login", "status"]], f"未ログイン時に codex exec を呼んではいけない: {invocations!r}"
