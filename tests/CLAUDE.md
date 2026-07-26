# tests

- `tests/conftest.py` が `src/` を sys.path に追加し `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向ける
- `_reset_config_singleton` autouse fixture が各テスト前後で `configuration.reset()` を呼ぶ。追加の実行スコープ状態が必要なテストは、生成した `YouTubeClients` インスタンスを直接 reset／再生成すること
- フィクスチャ JSON は新構造（`config/channel/*.json`）で配置
