"""
pytest 設定 - モノレポ用テスト環境設定

テスト実行時に CHANNEL_DIR を 8bah チャンネルに向ける。
（8bah = デフォルトテストチャンネル）
"""
import os
from pathlib import Path

import pytest

# automation/tests/ から channels/8bah/ までの相対パス
_CHANNEL_DIR = Path(__file__).resolve().parents[2] / 'channels' / '8bah'


@pytest.fixture(autouse=True, scope='session')
def set_channel_dir():
    """テストセッション全体で CHANNEL_DIR を設定する"""
    os.environ.setdefault('CHANNEL_DIR', str(_CHANNEL_DIR))
    yield
