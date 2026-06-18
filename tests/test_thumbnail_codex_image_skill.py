"""thumbnail skill の codex 補助生成導線に関する静的契約テスト。

Issue #501 では provider 抽象化 (`bunx tayk generate-image` / `ImageProvider`) に触らず、
`.claude/skills/thumbnail/references/codex-image.sh` という独立 shell script を
追加し、`thumbnail/SKILL.md` から直接案内する。Issue #547 で codex CLI 0.131 系の
新プロトコル（旧 stdout `generated image <id> <base64>` 廃止）に追従して書き直し。

このテストは以下を固定する:

1. shell script が canonical path に存在し、実行可能で、bash strict mode を使う
2. script が `codex exec --json --sandbox workspace-write --add-dir <out_dir>
   --skip-git-repo-check` で起動し、JSONL の `item.completed` (`type=agent_message`)
   から最終 `text` を path として取り出して PNG を保存する。prompt 末尾には
   `After generation, copy the produced PNG to <out>. Then reply with exactly <out>.`
   を自動付与する
3. script が未ログイン検知 (`codex login status`)・空出力検知・PNG ヘッダ検証を行う
4. `thumbnail/SKILL.md` に provider 表の `codex` 行と codex 経路セクションがあり、
   新プロトコル（`--json` + `jq` + agent が cp + prompt は短く保つ）を案内する
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_THUMBNAIL_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "thumbnail" / "SKILL.md"
_CODEX_IMAGE_SH = _REPO_ROOT / ".claude" / "skills" / "thumbnail" / "references" / "codex-image.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bash_available() -> bool:
    return shutil.which("bash") is not None


def _run_script(
    script_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script_path), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_fake_codex(bin_dir: Path) -> Path:
    """Fake codex CLI を tmp PATH に配置する。

    挙動:
    - `login status` サブコマンドは `$FAKE_CODEX_LOGIN_STATUS` を stdout に返す
    - `$FAKE_CODEX_LOGIN_STATUS_RC` が非空のときは `login status` をその値で
      非 0 終了させる（`$FAKE_CODEX_LOGIN_STATUS` が指定されていれば stderr に
      流す）。wrapper の `codex login status` 自体が非 0 終了する failure mode
      の回帰テスト用
    - `exec` サブコマンドは prompt 末尾の
      `copy the produced PNG to <path>` から `<path>` を抽出し、PNG マジックバイト
      を書き出した上で、最小 JSONL（`thread.started` / `turn.started` /
      `item.completed` × 2 (`agent_message`) / `turn.completed`）を stdout に流す
    - `$FAKE_CODEX_EXEC_FAIL` が非空のときは `exec` で stderr に診断行を 2 行出し、
      その値を exit code として非 0 終了する（wrapper の codex exec 失敗診断経路の
      回帰テスト用）
    - `$FAKE_CODEX_SKIP_CP` が非空のときは `exec` で PNG を書き出さずに agent_message
      JSONL だけ返す（agent が image_generation tool を skip した failure mode の
      再現 / 既存 PNG が stale artifact として残るケースの再現用）
    - `$FAKE_CODEX_AGENT_MESSAGE_OVERRIDE` が指定された場合、最終 agent_message の
      `text` を prompt から抽出した `<path>` ではなくこの値で上書きする（`final_msg
      != $out` の failure mode の再現用）
    - `$FAKE_CODEX_OUT_FROM_REF` が指定された場合、`exec` で PNG マジックを書き出す
      代わりにそのパスのファイルをそのまま `<path>` へコピーする（agent が
      image_generation tool を skip して reference 画像を $out に cp するだけで
      終わる failure mode の再現用）
    - 引数は `$FAKE_CODEX_LOG` に invocation 単位で記録する（`invocation_start` /
      `arg_b64: <base64(arg)>` × N / `invocation_end` フォーマット。改行を含む
      prompt 引数も復元できるよう base64 でエンコードする）
    """
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
  if [[ -n "${FAKE_CODEX_LOGIN_STATUS_RC:-}" ]]; then
    if [[ -n "${FAKE_CODEX_LOGIN_STATUS:-}" ]]; then
      printf '%s\n' "${FAKE_CODEX_LOGIN_STATUS}" >&2
    fi
    exit "${FAKE_CODEX_LOGIN_STATUS_RC}"
  fi
  printf '%s\n' "${FAKE_CODEX_LOGIN_STATUS:-Logged in using ChatGPT}"
  exit 0
fi

if [[ "${1:-}" == "exec" ]]; then
  if [[ -n "${FAKE_CODEX_EXEC_FAIL:-}" ]]; then
    # codex exec が非0で終了する failure mode を再現する。
    # wrapper の `if ! final_msg=$(...); then ... fi` 経路が踏まれ、
    # stderr ログの tail dump が呼び出し元 stderr に流れることを確認する。
    printf 'fake codex exec: simulated failure line 1\n' >&2
    printf 'fake codex exec: simulated failure line 2\n' >&2
    exit "${FAKE_CODEX_EXEC_FAIL}"
  fi

  # `--` 区切り以降に来る prompt を取り出す
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
  if [[ "$prompt" =~ copy\ the\ produced\ PNG\ to\ ([^[:space:]]+\.png) ]]; then
    out_path="${BASH_REMATCH[1]}"
  fi

  if [ -n "$out_path" ] && [ -z "${FAKE_CODEX_SKIP_CP:-}" ]; then
    if [ -n "${FAKE_CODEX_OUT_FROM_REF:-}" ]; then
      # agent が image_generation tool を skip して reference をそのまま
      # $out に cp する failure mode を再現する。
      cp "${FAKE_CODEX_OUT_FROM_REF}" "$out_path"
    else
      # PNG マジック (89 50 4E 47 0D 0A 1A 0A) + 最小 IEND チャンク
      printf '\x89PNG\r\n\x1a\n' > "$out_path"
      printf 'IEND\xae\x42\x60\x82' >> "$out_path"
    fi
  fi

  final_text="$out_path"
  if [ -n "${FAKE_CODEX_AGENT_MESSAGE_OVERRIDE:-}" ]; then
    final_text="${FAKE_CODEX_AGENT_MESSAGE_OVERRIDE}"
  fi

  thread_id="019e4eca-6cab-7eb2-8855-e056b221f56c"
  msg_predictive='{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hi"}}'
  msg_final='{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"'"$final_text"'"}}'
  printf '%s\n' "{\"type\":\"thread.started\",\"thread_id\":\"$thread_id\"}"
  printf '%s\n' "{\"type\":\"turn.started\"}"
  printf '%s\n' "$msg_predictive"
  printf '%s\n' "$msg_final"
  printf '%s\n' "{\"type\":\"turn.completed\"}"
  exit 0
fi

echo "unexpected codex invocation: $*" >&2
exit 1
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    return fake_codex


def _prepare_fake_codex_env(
    tmp_path: Path,
    *,
    login_status: str | None = None,
    exec_fail_rc: int | None = None,
    login_status_rc: int | None = None,
    skip_cp: bool = False,
    agent_message_override: str | None = None,
    out_from_ref: Path | None = None,
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
    if exec_fail_rc is not None:
        env["FAKE_CODEX_EXEC_FAIL"] = str(exec_fail_rc)
    if login_status_rc is not None:
        env["FAKE_CODEX_LOGIN_STATUS_RC"] = str(login_status_rc)
    if skip_cp:
        env["FAKE_CODEX_SKIP_CP"] = "1"
    if agent_message_override is not None:
        env["FAKE_CODEX_AGENT_MESSAGE_OVERRIDE"] = agent_message_override
    if out_from_ref is not None:
        env["FAKE_CODEX_OUT_FROM_REF"] = str(out_from_ref)

    return env, log_file


def _parse_invocations(log_text: str) -> list[list[str]]:
    """`_write_fake_codex` 形式のログを invocation 単位の args リストに分解する。"""
    import base64

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


def _codex_section(text: str) -> str:
    match = re.search(
        r"^## codex 経由.*?(?=^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("thumbnail/SKILL.md に `## codex 経由...` セクションが見つかりません")
    return match.group(0)


def _provider_section(text: str) -> str:
    match = re.search(
        r"^## プロバイダー切り替え\b.*?(?=^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("thumbnail/SKILL.md に `## プロバイダー切り替え` セクションが見つかりません")
    return match.group(0)


def test_codex_image_script_exists() -> None:
    """Given Issue #501 / #547 の実装後
    When canonical path の script を探す
    Then `.claude/skills/thumbnail/references/codex-image.sh` が存在する。
    """
    assert _CODEX_IMAGE_SH.exists(), f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない"


def test_codex_image_script_is_executable() -> None:
    """Given codex-image.sh
    When ファイル属性を確認する
    Then 実行ビットが付いている。
    """
    assert os.access(_CODEX_IMAGE_SH, os.X_OK), (
        f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} に実行ビットがない (chmod +x 漏れ)"
    )


def test_codex_image_script_has_bash_shebang_and_strict_mode() -> None:
    """Given codex-image.sh
    When 先頭付近を読む
    Then bash shebang と `set -euo pipefail` を含む。
    """
    text = _read(_CODEX_IMAGE_SH)
    first_line = text.splitlines()[0]
    assert first_line == "#!/usr/bin/env bash"
    assert re.search(r"^set\s+-euo\s+pipefail\s*$", text, flags=re.MULTILINE), (
        "codex-image.sh に `set -euo pipefail` が無い"
    )


def test_codex_image_script_usage_comment_points_to_canonical_path() -> None:
    """Given codex-image.sh
    When Usage コメントを読む
    Then 実行パスとして `.claude/skills/thumbnail/references/codex-image.sh` を案内する。
    """
    head = "\n".join(_read(_CODEX_IMAGE_SH).splitlines()[:12])
    assert ".claude/skills/thumbnail/references/codex-image.sh" in head, (
        "Usage コメントが canonical path を案内していない"
    )


def test_codex_image_script_invokes_codex_exec_json_and_parses_agent_message() -> None:
    """Given codex-image.sh
    When 本文を読む
    Then `codex exec --json` 系の新フラグセットと `jq` 経由の `agent_message` 解析がある。

    旧プロトコル (`--enable image_generation` / `awk '/^generated image /` /
    `base64 -d`) の残骸が無いこともここで確定する。
    """
    text = _read(_CODEX_IMAGE_SH)

    # 新プロトコルのフラグ・パイプライン
    assert "--json" in text, "`codex exec --json` が無い"
    assert "--sandbox workspace-write" in text, "`--sandbox workspace-write` が無い"
    assert "--add-dir" in text, "`--add-dir <out_dir>` が無い"
    assert "--skip-git-repo-check" in text, "`--skip-git-repo-check` が無い"
    assert re.search(r"\bjq\b", text), "`jq` パイプラインが無い"
    assert "agent_message" in text, "`agent_message` イベントを対象にした jq フィルタが無い"

    # 旧プロトコル残骸が無いこと
    assert "--enable image_generation" not in text, "旧 `--enable image_generation` フラグが残っている（要件 #4 違反）"
    assert "generated image" not in text, "旧プロトコル文字列 `generated image` が残っている（要件 #4 違反）"
    assert not re.search(r"awk\s+'/\^generated image /", text), "旧 awk 抽出パターンが残っている（要件 #4 違反）"
    assert not re.search(r"\bbase64\s+-d\b", text), "旧 `base64 -d` 復号が残っている（要件 #4 違反）"


def test_codex_image_script_appends_cp_instructions_to_prompt(tmp_path: Path) -> None:
    """Given codex-image.sh
    When 偽 codex で `codex exec` の `--` 後 prompt を観測する
    Then prompt 末尾に
        `After generation, copy the produced PNG to <out>. Then reply with exactly <out>.`
    が自動付与されている。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path)
    output_path = tmp_path / "output.png"

    result = _run_script(_CODEX_IMAGE_SH, "tiny prompt", str(output_path), env=env)

    assert result.returncode == 0, result.stderr
    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    exec_invocations = [args for args in invocations if args and args[0] == "exec"]
    assert exec_invocations, f"`codex exec` の呼び出しが記録されていない: {invocations!r}"

    exec_args = exec_invocations[-1]
    # `--` 区切り以降の prompt 引数 1 つを取り出す
    assert "--" in exec_args, f"`--` 区切りが無い: {exec_args!r}"
    sep_index = exec_args.index("--")
    prompt_args = exec_args[sep_index + 1 :]
    assert len(prompt_args) == 1, f"prompt 引数は 1 つにまとめて渡す必要がある: {prompt_args!r}"
    prompt = prompt_args[0]

    expected_cp = f"copy the produced PNG to {output_path}"
    expected_reply = f"reply with exactly {output_path}"
    assert "tiny prompt" in prompt, f"元 prompt が prompt 引数に含まれていない: {prompt!r}"
    assert expected_cp in prompt, f"prompt 末尾に `{expected_cp}` が自動付与されていない: {prompt!r}"
    assert expected_reply in prompt, f"prompt 末尾に `{expected_reply}` が自動付与されていない: {prompt!r}"


def test_codex_image_script_appends_generate_new_image_directive(tmp_path: Path) -> None:
    """Given codex-image.sh
    When 偽 codex で `codex exec` の `--` 後 prompt を観測する
    Then prompt 末尾に「image_generation tool で新画像を生成」「reference を copy するな」
    という指示が自動付与されている（agent が reference を $out へ cp するだけで終わる
    failure mode を抑止するため）。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path)
    output_path = tmp_path / "output.png"

    result = _run_script(_CODEX_IMAGE_SH, "tiny prompt", str(output_path), env=env)
    assert result.returncode == 0, result.stderr

    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    exec_invocations = [args for args in invocations if args and args[0] == "exec"]
    assert exec_invocations, f"`codex exec` の呼び出しが記録されていない: {invocations!r}"

    exec_args = exec_invocations[-1]
    sep_index = exec_args.index("--")
    prompt = exec_args[sep_index + 1]

    assert "image_generation tool" in prompt, (
        f"prompt 末尾に image_generation tool 指示が自動付与されていない: {prompt!r}"
    )
    assert re.search(r"[Dd]o not copy.*reference", prompt), (
        f"prompt 末尾に reference を copy するなという指示が自動付与されていない: {prompt!r}"
    )


def test_codex_image_script_passes_reference_images_as_repeated_image_flags(tmp_path: Path) -> None:
    """Given 参照画像つきの codex-image.sh 実行
    When 偽 codex で引数列を記録する
    Then `--image <path>` が可変長で繰り返し渡され、新フラグセットの中に混ぜられる。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path)
    output_path = tmp_path / "output.png"
    ref_a = tmp_path / "a.png"
    ref_b = tmp_path / "b.png"
    ref_a.write_text("a", encoding="utf-8")
    ref_b.write_text("b", encoding="utf-8")

    result = _run_script(_CODEX_IMAGE_SH, "prompt", str(output_path), str(ref_a), str(ref_b), env=env)

    assert result.returncode == 0, result.stderr
    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    assert any(args == ["login", "status"] for args in invocations), (
        f"`codex login status` が先に呼ばれていない: {invocations!r}"
    )

    exec_invocations = [args for args in invocations if args and args[0] == "exec"]
    assert exec_invocations, f"`codex exec` の呼び出しが無い: {invocations!r}"
    exec_args = exec_invocations[-1]

    # 新フラグセットがそろっている
    assert "--json" in exec_args
    assert "--sandbox" in exec_args and "workspace-write" in exec_args
    assert "--add-dir" in exec_args
    assert str(output_path.parent) in exec_args, (
        f"`--add-dir <out_dir>` に出力先親ディレクトリが渡されていない: {exec_args!r}"
    )
    assert "--skip-git-repo-check" in exec_args
    assert "--enable" not in exec_args, f"旧 `--enable image_generation` フラグが残っている: {exec_args!r}"

    # `--image <path>` が反復で渡されている
    image_flag_positions = [i for i, a in enumerate(exec_args) if a == "--image"]
    assert len(image_flag_positions) == 2, f"`--image` の反復回数が想定外: {exec_args!r}"
    image_values = [exec_args[i + 1] for i in image_flag_positions]
    assert image_values == [str(ref_a), str(ref_b)], f"`--image <path>` の順序・値が想定外: {image_values!r}"


def test_codex_image_script_succeeds_with_zero_reference_images(tmp_path: Path) -> None:
    """Given 参照画像なしの codex-image.sh 実行
    When 偽 codex で引数列を記録する
    Then 成功し、`codex exec` に `--image` を混ぜず、新フラグセットだけが付く。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path)
    output_path = tmp_path / "output.png"

    result = _run_script(_CODEX_IMAGE_SH, "prompt", str(output_path), env=env)

    assert result.returncode == 0, result.stderr
    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    assert any(args == ["login", "status"] for args in invocations), (
        f"`codex login status` が先に呼ばれていない: {invocations!r}"
    )

    exec_invocations = [args for args in invocations if args and args[0] == "exec"]
    assert exec_invocations, f"`codex exec` の呼び出しが無い: {invocations!r}"
    exec_args = exec_invocations[-1]

    assert "--json" in exec_args
    assert "--sandbox" in exec_args and "workspace-write" in exec_args
    assert "--add-dir" in exec_args
    assert "--skip-git-repo-check" in exec_args
    assert "--image" not in exec_args, f"参照画像なしのとき `--image` が混入している: {exec_args!r}"


def test_codex_image_script_checks_login_output_and_png_validity() -> None:
    """Given codex-image.sh
    When 本文を読む
    Then `codex login status` 前提確認、`$out` の非ゼロサイズ検証、PNG ヘッダ検証が含まれる。
    """
    text = _read(_CODEX_IMAGE_SH)
    assert "codex login status" in text, "未ログイン時の事前確認が無い"
    assert "Logged in" in text, "`codex login status` の期待出力が本文に無い"
    assert re.search(r'-s\s+"\$out"', text), '`-s "$out"` による非ゼロサイズ検証が無い'
    assert "89504e470d0a1a0a" in text, "PNG ヘッダ検証のマジック値が無い"


def test_codex_image_script_stops_when_codex_is_not_logged_in(tmp_path: Path) -> None:
    """Given 未ログイン状態の codex CLI
    When codex-image.sh を実行する
    Then 非 0 で停止し、案内を出し、`codex exec` を呼ばない。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path, login_status="Not signed in")
    output_path = tmp_path / "output.png"

    result = _run_script(_CODEX_IMAGE_SH, "prompt", str(output_path), env=env)

    assert result.returncode != 0, "未ログイン時は失敗終了する必要がある"
    assert ("login" in result.stderr.lower()) or ("logged in" in result.stderr.lower()), (
        f"未ログイン時の案内が stderr に無い: {result.stderr!r}"
    )
    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    assert invocations == [["login", "status"]], f"未ログイン時に `codex exec` を呼んではいけない: {invocations!r}"
    assert not output_path.exists(), "未ログイン時は出力ファイルを作らない"


def test_codex_image_script_rejects_not_logged_in_substring_false_positive(tmp_path: Path) -> None:
    """Given `codex login status` が `Not Logged in` を返す未ログイン状態
    When codex-image.sh を実行する
    Then 非 0 で停止し、`codex exec` を呼ばない。

    回帰防止 (AI-547-002): `*"Logged in"*` の部分一致だと `Not Logged in` も
    通過してしまい未ログイン状態で `codex exec` まで進む failure mode がある。
    `*"Logged in using ChatGPT"*` の厳密一致で阻止する契約を保証する。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path, login_status="Not Logged in")
    output_path = tmp_path / "output.png"

    result = _run_script(_CODEX_IMAGE_SH, "prompt", str(output_path), env=env)

    assert result.returncode != 0, "`Not Logged in` でも `Logged in` の部分一致が通って未ログインで進んでしまっている"
    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    assert invocations == [["login", "status"]], (
        f"`Not Logged in` 時に `codex exec` を呼んではいけない: {invocations!r}"
    )
    assert not output_path.exists(), "`Not Logged in` 時は出力ファイルを作らない"


def test_codex_image_script_requires_chatgpt_login_phrase() -> None:
    """Given codex-image.sh
    When ログイン判定の条件式を読む
    Then `Logged in using ChatGPT` の厳密一致を要求している。

    回帰防止 (AI-547-002): `*"Logged in"*` の部分一致だと `Not Logged in` が
    通過する。実装側でも文字列を `Logged in using ChatGPT` に固定する契約を担保。
    """
    text = _read(_CODEX_IMAGE_SH)
    assert '!= *"Logged in using ChatGPT"*' in text, (
        "ログイン判定が `Logged in using ChatGPT` の厳密一致になっていない（"
        '`*"Logged in"*` だと `Not Logged in` を通してしまう）'
    )


def test_codex_image_script_surfaces_codex_login_status_nonzero_exit(tmp_path: Path) -> None:
    """Given fake `codex login status` が非 0 で終了する状況
    When codex-image.sh を実行する
    Then 非 0 で停止し、stderr に明示 ERROR 行が出て、`codex exec` を呼ばない。

    回帰防止 (AI-547-004 / AI-547-005 / ARCH-547-001):
    `set -e` 下で `login_status=$(codex login status 2>&1)`
    の command substitution が非 0 終了すると、直後の明示エラーメッセージや
    `*"Logged in using ChatGPT"*` 判定に到達せずそのまま silent abort してしまう
    failure mode を阻止する。`if ! login_status=$(...); then ... fi` 経路で必ず
    診断 ERROR が出ることを保証する。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(
        tmp_path,
        login_status="codex: not logged in",
        login_status_rc=42,
    )
    output_path = tmp_path / "output.png"

    result = _run_script(_CODEX_IMAGE_SH, "prompt", str(output_path), env=env)

    assert result.returncode != 0, (
        "`codex login status` が非 0 で終了したのに wrapper が 0 で終わっている (silent abort 再発)"
    )
    assert "ERROR" in result.stderr, f"非 0 終了時の ERROR 診断行が stderr に届いていない: {result.stderr!r}"
    assert "rc=42" in result.stderr, (
        "非 0 終了時の実 exit code (rc=42) が stderr に出ていない。"
        "`if ! cmd=$(...); then rc=$?` パターンだと bash の `!` 反転後の `$?` "
        "(常に 0) を拾ってしまうため、`if cmd=$(...); then :; else rc=$?; fi` "
        f"経路で実 exit code を捕捉すること: {result.stderr!r}"
    )
    invocations = _parse_invocations(log_file.read_text(encoding="utf-8"))
    assert invocations == [["login", "status"]], (
        f"`codex login status` 非 0 終了時に `codex exec` を呼んではいけない: {invocations!r}"
    )
    assert not output_path.exists(), "`codex login status` 非 0 終了時は出力ファイルを作らない"


def test_codex_image_script_surfaces_codex_exec_failure_diagnostics(tmp_path: Path) -> None:
    """Given fake codex exec が非0で終了する状況
    When codex-image.sh を実行する
    Then 非 0 で停止し、stderr に診断（ERROR 文言 + codex stderr 末尾）が出る。

    回帰防止: `set -euo pipefail` 下で `final_msg=$(codex exec ... | jq ... | tail)`
    がコマンド置換失敗時に即 abort してしまうと、stderr 退避ログの tail dump や
    エラーメッセージが呼び出し元に届かない (silent failure)。`if ! ...; then` 経路で
    必ず診断ブロックを通すことを保証する。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, _ = _prepare_fake_codex_env(tmp_path, exec_fail_rc=42)
    output_path = tmp_path / "output.png"

    result = _run_script(_CODEX_IMAGE_SH, "tiny prompt", str(output_path), env=env)

    assert result.returncode != 0, "codex exec 非0終了時は wrapper も非0終了する必要がある"
    assert "ERROR" in result.stderr, f"診断ブロックの ERROR 行が stderr に届いていない: {result.stderr!r}"
    assert "fake codex exec: simulated failure" in result.stderr, (
        f"codex stderr の tail dump が呼び出し元 stderr に出ていない (silent failure 再発): {result.stderr!r}"
    )
    assert not output_path.exists() or output_path.stat().st_size == 0, (
        "codex exec 失敗時は出力ファイルを作らない / 空のままにする"
    )


def test_codex_image_script_rejects_stale_artifact_when_agent_skips_cp(tmp_path: Path) -> None:
    """Given 出力先 `$out` に有効な PNG が既に存在する状況で
        fake codex が agent_message JSONL は返すが PNG を cp しない（agent が
        image_generation tool を skip した failure mode の再現）
    When codex-image.sh を実行する
    Then 非 0 で停止する。

    回帰防止 (ARCH-547-002): wrapper が `final_msg` を取得しているのに成功判定に
    使わず、`-s "$out"` と PNG ヘッダ検証だけだと、実行前に valid PNG が `$out` に
    残っていれば agent が何も cp していなくても偽陽性 success になる。
    `rm -f "$out"` で stale artifact を消し、`final_msg == "$out"` で JSON プロトコル
    側からも contract を検証する経路を担保する。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, _ = _prepare_fake_codex_env(tmp_path, skip_cp=True)
    output_path = tmp_path / "output.png"
    # 事前に有効な PNG ヘッダで「stale artifact」を仕込む
    output_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"IEND\xae\x42\x60\x82")
    assert output_path.exists() and output_path.stat().st_size > 0

    result = _run_script(_CODEX_IMAGE_SH, "tiny prompt", str(output_path), env=env)

    assert result.returncode != 0, (
        "agent が cp していないのに wrapper が 0 で終わっている "
        "(stale artifact による偽陽性 success が再発: ARCH-547-002)"
    )
    assert "ERROR" in result.stderr, f"stale artifact 検知時の ERROR 診断行が stderr に届いていない: {result.stderr!r}"


def test_codex_image_script_rejects_when_agent_message_does_not_match_out(tmp_path: Path) -> None:
    """Given fake codex が `$out` とは別の path を agent_message に返す状況
    When codex-image.sh を実行する
    Then 非 0 で停止し、`agent_message` の不一致を ERROR で報告する。

    回帰防止 (ARCH-547-002): wrapper の prompt 末尾は
    `reply with exactly <out>` を要求しているのに、agent が別 path を返した場合
    （tool skip + 既存ファイルへ流れる failure mode 等）でも成功扱いしてしまうと
    JSON プロトコル契約と成果物の境界が崩れる。`final_msg == "$out"` の一致検証で
    阻止する契約を担保する。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    output_path = tmp_path / "output.png"
    env, _ = _prepare_fake_codex_env(
        tmp_path,
        agent_message_override=str(tmp_path / "elsewhere.png"),
    )

    result = _run_script(_CODEX_IMAGE_SH, "tiny prompt", str(output_path), env=env)

    assert result.returncode != 0, (
        "agent_message が $out と一致しないのに wrapper が 0 で終わっている "
        "(JSON プロトコル契約検証が抜けている: ARCH-547-002)"
    )
    assert "ERROR" in result.stderr, f"agent_message 不一致時の ERROR 診断行が stderr に届いていない: {result.stderr!r}"
    assert str(tmp_path / "elsewhere.png") in result.stderr, (
        f"不一致 path の診断が stderr に出ていない: {result.stderr!r}"
    )


def test_codex_image_script_rejects_output_matching_reference(tmp_path: Path) -> None:
    """Given fake codex が image_generation tool を skip して reference 画像を
        そのまま `$out` に cp する failure mode
    When codex-image.sh を reference 画像つきで実行する
    Then 非 0 で停止し、reference との一致を ERROR で報告する。

    `final_msg == "$out"` / PNG ヘッダ検証は通過してしまうため、
    バイト列ハッシュの一致で最終ゲートを敷くという契約を担保する。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    # reference 画像として有効な PNG ヘッダを持つファイルを 1 つ用意する
    ref_path = tmp_path / "ref.png"
    ref_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"IEND\xae\x42\x60\x82")

    output_path = tmp_path / "output.png"
    env, _ = _prepare_fake_codex_env(tmp_path, out_from_ref=ref_path)

    result = _run_script(
        _CODEX_IMAGE_SH,
        "tiny prompt",
        str(output_path),
        str(ref_path),
        env=env,
    )

    assert result.returncode != 0, (
        "出力 PNG が reference 画像とバイト一致しているのに wrapper が 0 で終わっている "
        "(agent が image_generation tool を skip した failure mode を検出できていない)"
    )
    assert "ERROR" in result.stderr, f"reference 一致時の ERROR 診断行が stderr に届いていない: {result.stderr!r}"
    assert "reference" in result.stderr, f"reference 一致を示す診断文が stderr に出ていない: {result.stderr!r}"


def test_codex_image_script_removes_stale_out_before_invoking_codex() -> None:
    """Given codex-image.sh
    When 本文を読む
    Then codex exec 呼び出し前に `rm -f "$out"` で stale artifact を消すコードがある。

    回帰防止 (ARCH-547-002): 既存 PNG が残っていると agent が cp スキップしても
    `-s "$out"` / PNG ヘッダ検証が通って偽陽性 success になる。実行前削除を契約化する。
    """
    text = _read(_CODEX_IMAGE_SH)
    # rm -f "$out" が codex exec 行より前に出現することを確認する
    rm_match = re.search(r'^\s*rm\s+-f\s+"\$out"\s*$', text, flags=re.MULTILINE)
    assert rm_match is not None, '`rm -f "$out"` で stale artifact を消す処理が無い'

    codex_exec_match = re.search(r"codex\s+exec\b", text)
    assert codex_exec_match is not None, "codex exec の呼び出しが見つからない"
    assert rm_match.start() < codex_exec_match.start(), (
        '`rm -f "$out"` が codex exec の前に出現していない（stale artifact 削除が後置だと意味がない）'
    )


def test_codex_image_script_validates_final_msg_matches_out() -> None:
    """Given codex-image.sh
    When 本文を読む
    Then `final_msg` と `$out` の一致を検証する条件分岐がある。

    回帰防止 (ARCH-547-002): agent_message の path を取り出しているのに成功判定に
    使わない配線漏れを禁止する。`final_msg != $out` を非 0 終了で扱う経路を担保する。
    """
    text = _read(_CODEX_IMAGE_SH)
    assert re.search(r'\[\s*"\$final_msg"\s+!=\s+"\$out"\s*\]', text), (
        '`final_msg == "$out"` の契約検証が無い（agent_message の path と出力先の境界が緩く ARCH-547-002 が再発する）'
    )


def test_codex_image_script_reports_saved_message() -> None:
    """Given codex-image.sh
    When 成功時メッセージの形式を確認する
    Then `saved: <path> (<size> bytes)` を出力する。
    """
    text = _read(_CODEX_IMAGE_SH)
    assert re.search(r"saved:\s+\$out\s+\(\$\([^)]*\)\s*bytes\)", text, flags=re.DOTALL), (
        "成功時の `saved: <path> (<size> bytes)` 出力が見つからない"
    )


def test_codex_image_script_uses_cross_platform_stat_fallback() -> None:
    """Given codex-image.sh
    When ファイルサイズ取得処理を確認する
    Then `stat -f%z ... || stat -c%s ...` のフォールバックを持つ。
    """
    text = _read(_CODEX_IMAGE_SH)
    assert re.search(r"stat\s+-f%z[^|]*\|\|\s*stat\s+-c%s", text), "macOS/Linux 両対応の stat フォールバックが無い"


def test_codex_image_script_passes_bash_syntax_check() -> None:
    """Given codex-image.sh
    When `bash -n` で構文チェックする
    Then exit 0 で終わる。
    """
    if not _bash_available():
        pytest.skip("bash が PATH 上に存在しない")

    result = subprocess.run(
        ["bash", "-n", str(_CODEX_IMAGE_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} の bash 構文チェックに失敗:\n{result.stderr}"
    )


def test_codex_image_script_centralizes_stderr_tail_dump_in_helper() -> None:
    """Given codex-image.sh
    When 本文を読む
    Then `dump_codex_stderr` ヘルパが 1 度だけ定義され、3 つの error 分岐から呼ばれている。

    回帰防止 (AI-547-006-N2 / family_tag: dry-violation-error-diagnostics):
    `--- codex stderr (tail) ---` を echo して `tail -n 30 "$err_log"` する 4 行ブロックが
    3 つの error 分岐に直接コピペで散在していた DRY 違反を、共通ヘルパに集約した状態を維持する。
    """
    text = _read(_CODEX_IMAGE_SH)

    # ヘルパ定義は 1 つだけ
    assert len(re.findall(r"^dump_codex_stderr\(\)\s*\{", text, flags=re.MULTILINE)) == 1, (
        "`dump_codex_stderr` ヘルパが 1 度だけ定義されている必要がある"
    )
    # 呼び出しは error 3 分岐ぶん（行頭でない位置にあるかも知れないので空白許可）
    call_sites = re.findall(r"^\s*dump_codex_stderr\s*$", text, flags=re.MULTILINE)
    assert len(call_sites) == 3, (
        f"`dump_codex_stderr` 呼び出しが 3 箇所揃っていない (現在 {len(call_sites)} 件): "
        "codex exec 失敗 / final_msg 不一致 / 画像未生成 の 3 つの error 分岐から呼ばれること"
    )
    # コピペブロックが再び発生していないことを確認
    duplicated_pattern = re.findall(r'echo "--- codex stderr \(tail\) ---" >&2', text)
    assert len(duplicated_pattern) == 1, (
        f'`echo "--- codex stderr (tail) ---"` がヘルパ以外で再びコピペされている (現在 {len(duplicated_pattern)} 件)'
    )


def test_codex_image_script_drops_unreachable_defense_around_final_msg_after_contract() -> None:
    """Given codex-image.sh の `[ ! -s "$out" ]` 分岐
    When 本文を読む
    Then `if [ -n "$final_msg" ]; then echo "agent_message (最終)` の論理到達不能な防御 if が無く、
        `final_msg` を直接 echo している。

    回帰防止 (AI-547-006-N1 / family_tag: logically-unreachable-defense):
    `[ ! -s "$out" ]` 分岐に到達した時点で直前の `[ "$final_msg" != "$out" ]` 契約検証を通過済みであり、
    `out` は `out=${2:?...}` で空文字でない契約。したがって `final_msg == "$out"` も非空が保証され、
    `[ -n "$final_msg" ]` チェックは常に真。「念のため」の防御 if を AI 由来で再追加させない。
    """
    text = _read(_CODEX_IMAGE_SH)

    # `[ ! -s "$out" ]` 分岐の本文を抽出
    match = re.search(
        r'if \[ ! -s "\$out" \]; then(?P<body>.*?)\n  exit 1\nfi',
        text,
        flags=re.DOTALL,
    )
    assert match is not None, '`[ ! -s "$out" ]` 分岐が見つからない'
    body = match.group("body")
    assert re.search(r'if \[ -n "\$final_msg" \]; then', body) is None, (
        '`[ ! -s "$out" ]` 分岐内の `if [ -n "$final_msg" ]` 防御 if は論理到達不能なので削除されている必要がある '
        "(AI 由来の防御コピペ再発: AI-547-006-N1)"
    )
    assert 'echo "agent_message (最終): $final_msg" >&2' in body, (
        "`final_msg` の echo（防御 if 削除後）は維持されている必要がある"
    )


def test_thumbnail_skill_lists_codex_in_provider_switch_table() -> None:
    """Given thumbnail/SKILL.md の provider 表
    When `## プロバイダー切り替え` セクションだけを読む
    Then `codex` は正規 provider 行として追加されている。
    """
    section = _provider_section(_read(_THUMBNAIL_SKILL_MD))
    assert "| `codex` |" in section, "`codex` が provider 表に正規 provider として載っていない"
    assert "ChatGPT" in section
    assert "GCP" in section


def test_thumbnail_skill_has_codex_generation_section() -> None:
    """Given thumbnail/SKILL.md
    When 該当セクションを抽出する
    Then codex 経路のセクションが存在する。
    """
    section = _codex_section(_read(_THUMBNAIL_SKILL_MD))
    assert "codex 経由" in section


def test_thumbnail_skill_codex_section_documents_login_and_direct_command() -> None:
    """Given codex 経路セクション
    When 本文を読む
    Then `codex login status` 前提と `codex-image.sh` の直接実行例を案内している。
    """
    section = _codex_section(_read(_THUMBNAIL_SKILL_MD))
    assert "codex login status" in section
    assert ".claude/skills/thumbnail/references/codex-image.sh" in section
    assert "main-codex.png" in section


def test_thumbnail_skill_codex_section_documents_api_route_boundary() -> None:
    """Given codex 経路セクション
    When 本文を読む
    Then 正規 provider だが bunx tayk generate-image / ImageProvider の API 経路ではないことを説明する。
    """
    section = _codex_section(_read(_THUMBNAIL_SKILL_MD))
    assert "正規" in section
    assert "bunx tayk generate-image" in section
    assert "ImageProvider" in section
    assert "codex-image.sh" in section


def test_thumbnail_skill_codex_section_documents_cost_and_retry_policy() -> None:
    """Given codex 経路セクション
    When 本文を読む
    Then GCP 課金・cost_tracker・fair-use と自動リトライなしの扱いが明文化されている。
    """
    section = _codex_section(_read(_THUMBNAIL_SKILL_MD))
    assert "GCP" in section
    assert "cost_tracker" in section
    assert "fair-use" in section
    assert "リトライ" in section
    assert "自動" in section


def test_thumbnail_skill_codex_section_documents_prompt_length_caveat() -> None:
    """Given codex 経路セクション
    When 本文を読む
    Then 「prompt は短く保つ（長いと agent が image_generation tool を skip する
        failure mode あり）」「画像は agent が cp してくるので wrapper 側 path
        指定がそのまま使える」が明文化されている。
    """
    section = _codex_section(_read(_THUMBNAIL_SKILL_MD))
    assert "短く" in section, "prompt を短く保つ運用ルールが明文化されていない（要件 #5）"
    assert "skip" in section, "長い prompt で agent が tool を skip する failure mode の言及が無い（要件 #5）"
    assert "cp" in section, "agent が cp する設計の言及が無い（要件 #5）"
