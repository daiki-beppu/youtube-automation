"""
pytest 設定 - テスト環境設定

テスト実行時に CHANNEL_DIR をテスト用フィクスチャに向ける。
"""
import os
import sys
from pathlib import Path

import pytest

# editable install されていない場合に備えて src/ を sys.path に追加
_AUTOMATION_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _AUTOMATION_DIR / 'src'
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# テスト用フィクスチャディレクトリ
_CHANNEL_DIR = Path(__file__).resolve().parent / 'fixtures' / 'sample_channel'


@pytest.fixture(autouse=True, scope='session')
def set_channel_dir():
    """テストセッション全体で CHANNEL_DIR を設定する"""
    os.environ.setdefault('CHANNEL_DIR', str(_CHANNEL_DIR))
    yield
