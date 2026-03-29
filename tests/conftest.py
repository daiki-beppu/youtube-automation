"""
pytest 設定 - テスト環境設定

テスト実行時に CHANNEL_DIR をテスト用フィクスチャに向ける。
"""
import os
from pathlib import Path

import pytest

# テスト用フィクスチャディレクトリ
_CHANNEL_DIR = Path(__file__).resolve().parent / 'fixtures' / 'sample_channel'


@pytest.fixture(autouse=True, scope='session')
def set_channel_dir():
    """テストセッション全体で CHANNEL_DIR を設定する"""
    os.environ.setdefault('CHANNEL_DIR', str(_CHANNEL_DIR))
    yield
