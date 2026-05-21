"""thumbnail skill の codex 補助生成導線に関する静的契約テスト。

Issue #501 では provider 抽象化 (`yt-generate-image` / `ImageProvider`) に触らず、
`.claude/skills/thumbnail/references/codex-image.sh` という独立 shell script を
追加し、`thumbnail/SKILL.md` から直接案内する。

このテストは未実装段階で以下を固定する:

1. shell script が canonical path に存在し、実行可能で、bash strict mode を使う
2. script が `codex exec --enable image_generation` の stdout から
   `generated image ...` 行を抽出して PNG を保存する
3. script が未ログイン検知 (`codex login status`)・空出力検知・PNG ヘッダ検証を行う
4. `thumbnail/SKILL.md` に provider 表とは独立した
   `## codex 経由の補助生成` セクションがあり、直接実行方法を案内する
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
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

log_file=${FAKE_CODEX_LOG:?}
printf '%s\\n' "$*" >> "$log_file"

if [[ "$1" == "login" && "$2" == "status" ]]; then
  printf '%s\\n' "${FAKE_CODEX_LOGIN_STATUS:-Logged in using ChatGPT}"
  exit 0
fi

if [[ "$1" == "exec" ]]; then
  printf '%s\\n' "${FAKE_CODEX_EXEC_STDOUT:-generated image iVBORw0KGgo=}"
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
    exec_stdout: str = "generated image iVBORw0KGgo=",
) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_codex(bin_dir)

    log_file = tmp_path / "codex.log"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_CODEX_LOG"] = str(log_file)
    env["FAKE_CODEX_EXEC_STDOUT"] = exec_stdout
    if login_status is not None:
        env["FAKE_CODEX_LOGIN_STATUS"] = login_status

    return env, log_file


def _codex_section(text: str) -> str:
    match = re.search(
        r"^## codex 経由の補助生成\b.*?(?=^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("thumbnail/SKILL.md に `## codex 経由の補助生成` セクションが見つかりません")
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
    """Given Issue #501 の実装後
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


def test_codex_image_script_invokes_codex_exec_and_decodes_generated_image() -> None:
    """Given codex-image.sh
    When 本文を読む
    Then `codex exec --enable image_generation` と `generated image` 抽出 + `base64 -d` がある。
    """
    text = _read(_CODEX_IMAGE_SH)
    assert "codex exec --enable image_generation" in text
    assert re.search(r"""awk\s+'/\^generated image /\s*\{[^}]*\$3[^}]*exit[^}]*\}'""", text), (
        "`generated image` 行から base64 を抽出する awk が無い"
    )
    assert re.search(r'base64\s+-d\s*>\s*"?\$out"?', text), '`base64 -d > "$out"` が無い'


def test_codex_image_script_passes_reference_images_as_repeated_image_flags(tmp_path: Path) -> None:
    """Given 参照画像つきの codex-image.sh 実行
    When 偽 codex で引数列を記録する
    Then `--image <path>` が可変長で繰り返し渡される。
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
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert any(line == "login status" for line in lines), "`codex login status` が先に呼ばれていない"
    assert any(line == (f"exec --enable image_generation --image {ref_a} --image {ref_b} prompt") for line in lines), (
        f"`--image <path>` の反復契約を満たしていない: {lines!r}"
    )


def test_codex_image_script_succeeds_with_zero_reference_images(tmp_path: Path) -> None:
    """Given 参照画像なしの codex-image.sh 実行
    When 偽 codex で引数列を記録する
    Then 成功し、`codex exec` に `--image` を混ぜない。
    """
    if not _CODEX_IMAGE_SH.exists():
        pytest.fail(f"{_CODEX_IMAGE_SH.relative_to(_REPO_ROOT)} が存在しない")

    env, log_file = _prepare_fake_codex_env(tmp_path)
    output_path = tmp_path / "output.png"

    result = _run_script(_CODEX_IMAGE_SH, "prompt", str(output_path), env=env)

    assert result.returncode == 0, result.stderr
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert any(line == "login status" for line in lines), "`codex login status` が先に呼ばれていない"
    assert any(line == "exec --enable image_generation prompt" for line in lines), (
        f"参照画像なしのとき `--image` なしで実行されていない: {lines!r}"
    )
    assert all("--image" not in line for line in lines if line.startswith("exec ")), (
        f"参照画像なしのとき `--image` が混入している: {lines!r}"
    )


def test_codex_image_script_checks_login_output_and_png_validity() -> None:
    """Given codex-image.sh
    When 本文を読む
    Then `codex login status` 前提確認と空出力・PNG ヘッダ検証が含まれる。
    """
    text = _read(_CODEX_IMAGE_SH)
    assert "codex login status" in text, "未ログイン時の事前確認が無い"
    assert "Logged in" in text, "`codex login status` の期待出力が本文に無い"
    assert re.search(r'\[\s*!\s+-s\s+"\$out"\s*\]', text), '`! -s "$out"` による空出力検知が無い'
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
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines == ["login status"], f"未ログイン時に `codex exec` を呼んではいけない: {lines!r}"
    assert not output_path.exists(), "未ログイン時は出力ファイルを作らない"


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


def test_thumbnail_skill_keeps_codex_out_of_provider_switch_table() -> None:
    """Given thumbnail/SKILL.md の provider 表
    When `## プロバイダー切り替え` セクションだけを読む
    Then `codex` は provider 行として追加されていない。
    """
    section = _provider_section(_read(_THUMBNAIL_SKILL_MD))
    assert "| `codex` |" not in section, "`codex` は provider 抽象化に追加せず、独立導線として文書化する必要がある"


def test_thumbnail_skill_has_codex_helper_generation_section() -> None:
    """Given thumbnail/SKILL.md
    When 該当セクションを抽出する
    Then `## codex 経由の補助生成` セクションが存在する。
    """
    section = _codex_section(_read(_THUMBNAIL_SKILL_MD))
    assert "codex 経由の補助生成" in section


def test_thumbnail_skill_codex_section_documents_login_and_direct_command() -> None:
    """Given `## codex 経由の補助生成` セクション
    When 本文を読む
    Then `codex login status` 前提と `codex-image.sh` の直接実行例を案内している。
    """
    section = _codex_section(_read(_THUMBNAIL_SKILL_MD))
    assert "codex login status" in section
    assert ".claude/skills/thumbnail/references/codex-image.sh" in section
    assert "main-codex.png" in section


def test_thumbnail_skill_codex_section_mentions_independent_scope() -> None:
    """Given `## codex 経由の補助生成` セクション
    When 本文を読む
    Then provider 抽象化に乗せない独立経路であることが分かる説明を含む。
    """
    section = _codex_section(_read(_THUMBNAIL_SKILL_MD))
    assert ("yt-generate-image" in section) or ("ImageProvider" in section), (
        "独立経路であり provider 抽象化に組み込まないことへの言及が無い"
    )
