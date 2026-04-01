# youtube-channels-automation

YouTube チャンネル運営を自動化するツールキット。各チャンネルリポジトリの `automation/` にサブモジュールとして組み込んで使用する。

## アーキテクチャ

```
channel-repo/                  # チャンネル固有リポジトリ
├── config/
│   ├── channel_config.json    # チャンネル設定（唯一の設定ソース）
│   └── localizations.json     # 多言語テンプレート
├── automation/                # ← このリポジトリ（サブモジュール）
│   ├── agents/                # アップロードエージェント（Auto/Collection/Short）
│   ├── auth/                  # OAuth 2.0 認証（YouTubeOAuthHandler）
│   ├── scripts/               # CLI スクリプト（analytics, upload, AI 生成）
│   ├── utils/                 # コアライブラリ（設定, API, 分析, アップロード）
│   ├── templates/             # 説明文 Markdown テンプレート
│   └── tests/                 # pytest テストスイート
└── collections/               # コンテンツ成果物（音源, 動画, サムネイル）
```

## 主要モジュール

| モジュール | 責務 |
|-----------|------|
| `utils/channel_config.py` | `channel_config.json` のシングルトンローダー・バリデーション |
| `utils/youtube_service.py` | YouTube API サービスファクトリ（ServiceRegistry） |
| `utils/upload_core.py` | 再開可能アップロード・サムネイル圧縮の共通コア |
| `utils/exceptions.py` | ドメイン固有例外（ConfigError, YouTubeAPIError 等） |
| `utils/collection_paths.py` | コレクションディレクトリ構造の解決 |
| `utils/metadata_generator.py` | タイトル・説明文・タグ・ローカライゼーション自動生成 |
| `utils/analytics_collector.py` | Analytics API データ収集（Mixin 構成） |
| `utils/analytics_analyzer.py` | CTR・エンゲージメント分析 |
| `auth/oauth_handler.py` | OAuth 2.0 トークン管理・リフレッシュ |

## 開発規約

### Python
- Python 3.11+
- リンター: ruff（E, F, I, W）
- 行長: 120 文字
- テスト: pytest
- パッケージマネージャ: uv

### エラーハンドリング
- `utils/exceptions.py` のドメイン例外を使用すること
- 生の `Exception` / `KeyError` を catch しない — `ConfigError`, `YouTubeAPIError` 等を使う
- API 呼び出しには適切なリトライ・タイムアウトを設定

### 設定
- チャンネル固有値は必ず `ChannelConfig` 経由で参照
- ハードコーディング禁止 — `channel_config.json` に集約
- 新しい設定キーを追加する場合は `ChannelConfig._validate()` にも必須/任意を定義

### テスト
- `tests/conftest.py` が `CHANNEL_DIR` をフィクスチャに向ける
- `ChannelConfig.reset()` / `ServiceRegistry.reset()` でシングルトンをリセット
- `tests/fixtures/sample_channel/` にテストデータを配置

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は **絶対にコミットしない**
- API キーは環境変数経由（`.env` または 1Password CLI）
- OAuth スコープは必要最小限に制限
