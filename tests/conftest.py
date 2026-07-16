"""pytest 設定 - テスト環境設定

テスト実行時に `CHANNEL_DIR` を `tests/fixtures/sample_channel/` を **コピーした**
tmp 配下に向けることで、`cost_tracker` などの実行ログが git 管理下の fixture を
汚染しないようにする（issue #286）。

`CHANNEL_DIR` を確定する処理はモジュールトップで実行する。
session-scope の autouse fixture では、`tests/test_metadata_audit.py` のように
**import 時点** で `channel_dir()` を呼び出すテストの collection phase に間に合わないため。

ユーザが明示的に `CHANNEL_DIR` を指定している場合（例: 別 fixture をデバッグ用に
向ける）はその指定を尊重し、コピー処理をスキップする。

新 loader (`youtube_automation.utils.config`) のシングルトンは各テスト前後で
function-scope の autouse fixture でリセットする。
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# editable install されていない場合に備えて src/ を sys.path に追加
_AUTOMATION_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _AUTOMATION_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# テスト用フィクスチャディレクトリ（git 管理下のオリジナル）
_FIXTURE_CHANNEL_DIR = Path(__file__).resolve().parent / "fixtures" / "sample_channel"
_OP_READ_DISABLED_ENV = "YOUTUBE_AUTOMATION_DISABLE_OP_READ"
_TEST_TMP_PREFIX = "yt-automation-tests-"
# conftest が CHANNEL_DIR を自動設定したことを示すマーカー。
# xdist worker はこれを見て「ユーザー明示指定」と「controller の自動設定の継承」を
# 区別し、後者なら worker 専用のコピーを作り直す（共有 tmp への並行書き込みを防ぐ）。
_ISOLATED_MARKER_ENV = "YOUTUBE_AUTOMATION_TEST_ISOLATED_CHANNEL_DIR"


os.environ.setdefault(_OP_READ_DISABLED_ENV, "1")


def _pid_is_running(pid: int) -> bool:
    """Return whether a process exists without sending it a signal."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cleanup_stale_isolated_channel_dirs() -> None:
    """Remove leftovers from killed pytest runs without touching active runs."""
    system_tmp = Path(tempfile.gettempdir())
    for candidate in system_tmp.glob(f"{_TEST_TMP_PREFIX}*"):
        if not candidate.is_dir() or candidate.is_symlink():
            continue

        suffix = candidate.name.removeprefix(_TEST_TMP_PREFIX)
        pid_text, separator, _ = suffix.partition("-")
        if separator and pid_text.isdigit() and _pid_is_running(int(pid_text)):
            continue

        shutil.rmtree(candidate, ignore_errors=True)


def _prepare_isolated_channel_dir() -> None:
    """`CHANNEL_DIR` を tmp 配下の sample_channel コピーに向ける。

    ユーザーの既存 env 上書きがあれば尊重する（setdefault 相当）。
    ただし pytest-xdist の worker では、controller が自動設定した値
    （`_ISOLATED_MARKER_ENV` 付き）を継承している場合に限り、worker 専用の
    コピーを作り直して並行書き込みの衝突を防ぐ。
    tmp dir は `atexit` で session（worker プロセス）終了時に削除する。
    """
    _cleanup_stale_isolated_channel_dirs()

    if os.environ.get("CHANNEL_DIR"):
        inherited_from_controller = bool(os.environ.get(_ISOLATED_MARKER_ENV) and os.environ.get("PYTEST_XDIST_WORKER"))
        if not inherited_from_controller:
            return

    tmp_root = Path(tempfile.mkdtemp(prefix=f"{_TEST_TMP_PREFIX}{os.getpid()}-"))
    atexit.register(shutil.rmtree, tmp_root, ignore_errors=True)

    isolated = tmp_root / "sample_channel"
    shutil.copytree(_FIXTURE_CHANNEL_DIR, isolated)
    os.environ["CHANNEL_DIR"] = str(isolated)
    os.environ[_ISOLATED_MARKER_ENV] = "1"


_prepare_isolated_channel_dir()


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """新 loader (utils.config) のシングルトン state を各テスト前後でリセット."""
    from youtube_automation.utils.config import reset as reset_config

    reset_config()
    yield
    reset_config()


@pytest.fixture
def no_retry_backoff(monkeypatch):
    """retry backoff の実 sleep を無効化する。

    `execute_with_retry` / `retry_youtube_api` のリトライ経路を通るテストで
    実 backoff（attempt 毎に数秒）を待たないために使う。`time.sleep` を
    グローバルに patch せず、retry モジュールのシームだけを差し替える。
    """
    from youtube_automation.utils import retry as retry_module

    monkeypatch.setattr(retry_module, "_DEFAULT_SLEEP", lambda _seconds: None)
    monkeypatch.setattr(retry_module, "_DEFAULT_JITTER", lambda low, _high: low)
