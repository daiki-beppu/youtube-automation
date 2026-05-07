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
    # USD→JPY レートはテストでは固定値にしてネットワーク依存を外す
    os.environ.setdefault("JPY_PER_USD", "160")
    yield


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """新 loader (utils.config) のシングルトン state を各テスト前後でリセット."""
    from youtube_automation.utils.config import reset as reset_config

    reset_config()
    yield
    reset_config()


@pytest.fixture(autouse=True)
def _isolate_cost_tracker_writes(tmp_path_factory, monkeypatch):
    """sample_channel fixture への cost_tracker 書き込みを構造的に隔離する。

    `cost_tracker.log_generation` は `<channel_dir>/data/{image,video,audio}_costs.json` に
    append する設計のため、CHANNEL_DIR を sample_channel fixture に向けたまま
    pytest を実行すると lyria 系等のテスト経由で `tests/fixtures/sample_channel/data/`
    配下が毎回上書きされる。`git checkout` の単発 revert では durable に解決できないため、
    `_log_path` 解決を一時ディレクトリへリダイレクトし fixture を不可触に保つ。

    `tmp_channel` fixture などテスト側で CHANNEL_DIR を tmp_path に上書きする場合は
    元の解決パス（テスト固有 tmp_path 配下）を尊重し、テストの read 側 helper との
    整合を維持する。
    """
    from youtube_automation.utils import cost_tracker as _ct

    isolated_dir = tmp_path_factory.mktemp("cost_tracker_isolated")

    def _isolated_log_path(category):
        try:
            from youtube_automation.utils.config import channel_dir as _channel_dir

            current = _channel_dir()
        except Exception:
            return isolated_dir / _ct._LOG_FILENAMES[category]
        if current == _CHANNEL_DIR:
            return isolated_dir / _ct._LOG_FILENAMES[category]
        return current / "data" / _ct._LOG_FILENAMES[category]

    monkeypatch.setattr("youtube_automation.utils.cost_tracker._log_path", _isolated_log_path)
