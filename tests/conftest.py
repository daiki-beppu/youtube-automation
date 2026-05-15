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


def _prepare_isolated_channel_dir() -> None:
    """`CHANNEL_DIR` を tmp 配下の sample_channel コピーに向ける。

    既存 env 上書きがあれば尊重する（setdefault 相当）。
    tmp dir は `atexit` で session 終了時に削除する。
    """
    if os.environ.get("CHANNEL_DIR"):
        return

    tmp_root = Path(tempfile.mkdtemp(prefix="yt-automation-tests-"))
    atexit.register(shutil.rmtree, tmp_root, ignore_errors=True)

    isolated = tmp_root / "sample_channel"
    shutil.copytree(_FIXTURE_CHANNEL_DIR, isolated)
    os.environ["CHANNEL_DIR"] = str(isolated)


_prepare_isolated_channel_dir()


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """新 loader (utils.config) のシングルトン state を各テスト前後でリセット."""
    from youtube_automation.utils.config import reset as reset_config

    reset_config()
    yield
    reset_config()
