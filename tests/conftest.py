"""
pytest 設定 - テスト環境設定

テスト実行時に CHANNEL_DIR をテスト用フィクスチャに向ける。
新 loader (`youtube_automation.utils.config`) のシングルトンを各テスト前後で
リセットするため、autouse function-scope fixture を提供する。
"""

import os
import sys
from pathlib import Path

import pytest

# editable install されていない場合に備えて src/ を sys.path に追加
_AUTOMATION_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _AUTOMATION_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# テスト用フィクスチャディレクトリ
_CHANNEL_DIR = Path(__file__).resolve().parent / "fixtures" / "sample_channel"


@pytest.fixture(autouse=True, scope="session")
def set_channel_dir():
    """テストセッション全体で CHANNEL_DIR を設定する"""
    os.environ.setdefault("CHANNEL_DIR", str(_CHANNEL_DIR))
    yield


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """新 loader (utils.config) のシングルトン state を各テスト前後でリセット."""
    from youtube_automation.utils.config import reset as reset_config

    reset_config()
    yield
    reset_config()
