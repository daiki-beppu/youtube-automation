"""全 `yt-*` CLI が設定・credential・API client 生成なしで `--help` を返す契約の回帰テスト.

issue #2308 で、`--help` の引数解析を設定解決・credential 取得・API client 生成より
前に行う契約を敷いた。`tests/test_cli_stdio.py` は registry と dispatch の配線
（どの wrapper がどの command module を呼ぶか）を `_run` のモックで検証しているが、
モックは実 module を import しないため、この契約の回帰は捕まえられない。

本 module は console script の実バイナリを隔離 subprocess で起動し、次を観測する。

- exit 0 で `usage: <script 名>` を返す（`CHANNEL_DIR` 未設定・credential 欠落でも）
- 設定解決 / 認証 / API client 生成の関数が **呼ばれていない**（`sitecustomize` プローブで採取）
- 隔離した `HOME` / CWD にファイルを書いていない
- `_HELP_TIMEOUT_SECONDS` 以内に終了する

設定解決を観測点に含めるのは、「設定が無くても exit 0」だけでは契約を証明できないためである。
`load_config()` を呼んだうえで `ConfigError` を握り潰す fallback を挟めば exit 0 は保てるが、
それは help 文言が設定に依存したままであることを意味する。呼び出し自体を 0 件で固定する。

`googleapiclient` などの import 自体は禁止しない。import は HTTP も認証も起こさず、
契約が禁じているのは「引数解析より前の credential 取得・API client 生成」だからである。
観測点を import ではなく呼び出しに置くことで、起動コスト（重量 import）という別の
関心事を本契約に混ぜずに済む。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT

# CLI 1 件あたりの上限。実測は最遅 0.8 秒程度で、CI の遅い runner でも十分な余裕がある。
_HELP_TIMEOUT_SECONDS = 15.0

# 子プロセスから取り除く「設定・認証の入力」。これらが無い状態で `--help` が
# exit 0 を返すこと自体が、設定解決を引数解析より後ろに置いた証拠になる。
_STRIPPED_ENV_KEYS = (
    "CHANNEL_DIR",
    "YOUTUBE_AUTOMATION_TEST_ISOLATED_CHANNEL_DIR",
    "GOOGLE_APPLICATION_CREDENTIALS",
)

_PROBE_OUTPUT_ENV = "CLI_HELP_PROBE_OUT"

# `--help` 経路で呼ばれてはいけない関数を (module, 属性パス) で宣言する。
# import ではなく呼び出しを観測するため、sitecustomize でこれらを wrap する。
_PROBE_SOURCE = '''"""`--help` 中に設定解決 / 認証 / API client 生成が呼ばれたかを記録する sitecustomize."""

import atexit
import builtins
import json
import os
import sys
from pathlib import Path

_OUT = Path(os.environ["CLI_HELP_PROBE_OUT"])
_CALLS: list[str] = []

_GUARDED = (
    ("googleapiclient.discovery", "build"),
    ("google.auth", "default"),
    ("google.oauth2.credentials", "Credentials.from_authorized_user_file"),
    ("google_auth_oauthlib.flow", "InstalledAppFlow.from_client_secrets_file"),
    # 設定解決の 2 経路。CLI は package 側から import する規約だが、
    # loader 側を直接呼ぶ抜け道も塞ぐため両方を観測する。
    ("youtube_automation.configuration", "load_config"),
    ("youtube_automation.configuration", "channel_dir"),
    ("youtube_automation.configuration.loader", "load_config"),
    ("youtube_automation.configuration.loader", "channel_dir"),
)
_patched: set[str] = set()


def _wrap(owner: object, attribute: str, label: str) -> None:
    original = getattr(owner, attribute)

    def guarded(*args: object, **kwargs: object) -> object:
        _CALLS.append(label)
        return original(*args, **kwargs)

    setattr(owner, attribute, guarded)


def _apply() -> None:
    """import 済みの guard 対象を記録付きに差し替える（冪等）."""
    for module_name, dotted in _GUARDED:
        label = f"{module_name}.{dotted}"
        if label in _patched:
            continue
        module = sys.modules.get(module_name)
        if module is None:
            continue
        owner: object | None = module
        parts = dotted.split(".")
        for part in parts[:-1]:
            owner = getattr(owner, part, None)
            if owner is None:
                break
        if owner is None or not hasattr(owner, parts[-1]):
            continue
        _wrap(owner, parts[-1], label)
        _patched.add(label)


_real_import = builtins.__import__


def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    """import 直後に guard を張る。

    `from googleapiclient.discovery import build` のような from-import でも、
    呼び出し側が属性を取り出す前に差し替えが完了するため取りこぼさない。
    """
    module = _real_import(name, globals, locals, fromlist, level)
    _apply()
    return module


builtins.__import__ = _patched_import
atexit.register(lambda: _OUT.write_text(json.dumps(sorted(set(_CALLS))), encoding="utf-8"))
'''


def _console_scripts() -> dict[str, str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["scripts"]


CONSOLE_SCRIPTS = _console_scripts()


@pytest.fixture(scope="session")
def probe_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`PYTHONPATH` 経由で子プロセスへ注入する sitecustomize を用意する."""
    directory = tmp_path_factory.mktemp("cli-help-probe")
    (directory / "sitecustomize.py").write_text(_PROBE_SOURCE, encoding="utf-8")
    return directory


def _script_path(script_name: str) -> Path:
    """pytest を動かしている環境の console script 実体を返す."""
    bin_dir = Path(sys.executable).parent
    candidate = bin_dir / script_name
    if candidate.exists():
        return candidate
    windows_candidate = bin_dir / f"{script_name}.exe"
    if windows_candidate.exists():
        return windows_candidate
    raise AssertionError(f"console script が見つからない: {candidate}. `uv sync` で entry point を再生成する必要がある")


def test_console_scripts_are_registered() -> None:
    """パラメタ化の母集合が空でないことを保証する（全件 skip の空振りを防ぐ）."""
    assert CONSOLE_SCRIPTS
    assert all(name.startswith("yt-") for name in CONSOLE_SCRIPTS)


@pytest.mark.parametrize("script_name", sorted(CONSOLE_SCRIPTS))
def test_cli_help_needs_no_config_credentials_or_api_client(
    script_name: str,
    probe_dir: Path,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    probe_output = tmp_path / "guarded-calls.json"

    env = {key: value for key, value in os.environ.items() if key not in _STRIPPED_ENV_KEYS}
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONPATH": str(probe_dir),
            _PROBE_OUTPUT_ENV: str(probe_output),
            # `op read` による 1Password 経由の secret 解決を止める（CLAUDE.md のテスト既定）
            "YOUTUBE_AUTOMATION_DISABLE_OP_READ": "1",
        }
    )

    try:
        result = subprocess.run(
            [str(_script_path(script_name)), "--help"],
            capture_output=True,
            text=True,
            timeout=_HELP_TIMEOUT_SECONDS,
            cwd=home,
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{script_name} --help が {_HELP_TIMEOUT_SECONDS} 秒以内に終了しなかった")

    assert result.returncode == 0, f"{script_name} --help が exit {result.returncode}: {result.stderr[-500:]}"
    assert f"usage: {script_name}" in result.stdout, (
        f"{script_name} --help の usage が console script 名と一致しない: {result.stdout[:200]}"
    )

    assert probe_output.exists(), f"{script_name} で sitecustomize プローブが動作しなかった"
    guarded_calls = json.loads(probe_output.read_text(encoding="utf-8"))
    assert guarded_calls == [], (
        f"{script_name} --help が引数解析より前に設定解決 / 認証 / API client 生成を呼んだ: {guarded_calls}"
    )

    written = sorted(path.relative_to(home).as_posix() for path in home.rglob("*"))
    assert written == [], f"{script_name} --help が隔離 HOME へ書き込んだ: {written[:10]}"
