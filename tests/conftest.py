"""
pytest 設定 - モノレポ用テスト環境設定

テスト実行時に CHANNEL_DIR を 8bah チャンネルに向ける。
（8bah = デフォルトテストチャンネル）
"""
import os
from pathlib import Path

import pytest

# automation/tests/ からリポジトリルートまでの相対パス
# 独立リポジトリ: config/ が直下にある
# モノレポ: channels/8bah/ 配下にある
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHANNEL_DIR = (
    _REPO_ROOT
    if (_REPO_ROOT / 'config' / 'channel_config.json').exists()
    else _REPO_ROOT / 'channels' / '8bah'
)


@pytest.fixture(autouse=True, scope='session')
def set_channel_dir():
    """テストセッション全体で CHANNEL_DIR を設定する"""
    os.environ.setdefault('CHANNEL_DIR', str(_CHANNEL_DIR))
    yield
