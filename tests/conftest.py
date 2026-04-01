"""
pytest 設定 - テスト環境設定

テスト実行時に CHANNEL_DIR をテスト用フィクスチャに向ける。
"""
import os
import sys
from pathlib import Path

import pytest

# scripts/ ディレクトリをインポートパスに追加
_AUTOMATION_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _AUTOMATION_DIR / 'scripts'
for _p in (str(_AUTOMATION_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# テスト用フィクスチャディレクトリ
_CHANNEL_DIR = Path(__file__).resolve().parent / 'fixtures' / 'sample_channel'


@pytest.fixture(autouse=True, scope='session')
def set_channel_dir():
    """テストセッション全体で CHANNEL_DIR を設定する"""
    os.environ.setdefault('CHANNEL_DIR', str(_CHANNEL_DIR))
    yield
