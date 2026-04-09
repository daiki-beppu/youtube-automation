# youtube-channels-automation

YouTube チャンネル運営を自動化するツールキット。git+https インストール（推奨）またはサブモジュール（後方互換）でチャンネルリポジトリに導入する。

## アーキテクチャ

```
youtube-channels-automation/         # ← このリポジトリ
├── pyproject.toml                   # hatchling / [project.scripts] entry points
├── src/
│   └── youtube_automation/
│       ├── utils/                   # コアライブラリ（設定, API, 分析, アップロード）
│       ├── agents/                  # アップロードエージェント（Auto/Collection/Short）
│       ├── auth/                    # OAuth 2.0 認証（YouTubeOAuthHandler）
│       ├── scripts/                 # CLI スクリプト（analytics, upload, AI 生成）
│       ├── cli/                     # ユーザー向け CLI ツール (yt-skills)
│       └── templates/               # 説明文 Markdown テンプレート
├── .claude/skills/                  # Claude Code スキル群（yt-skills sync で配布）
├── tests/                           # pytest テストスイート
├── scripts/*.sh                     # シェルスクリプト（generate_master.sh 等）
└── auth/client_secrets.json         # (gitignored) ローカル開発用 OAuth 認証情報
```

downstream のチャンネルリポジトリ:

```
channel-repo/                  # チャンネル固有リポジトリ
├── config/
│   ├── channel_config.json    # チャンネル設定（唯一の設定ソース）
│   └── localizations.json     # 多言語テンプレート
├── auth/                      # チャンネル固有 OAuth 認証
│   ├── client_secrets.json
│   └── token.json
├── .claude/skills/            # yt-skills sync で展開
└── collections/               # コンテンツ成果物（音源, 動画, サムネイル）
```

## 主要モジュール

| モジュール | 責務 |
|-----------|------|
| `youtube_automation.utils.channel_config` | `channel_config.json` のシングルトンローダー・バリデーション |
| `youtube_automation.utils.youtube_service` | YouTube API サービスファクトリ（ServiceRegistry） |
| `youtube_automation.utils.upload_core` | 再開可能アップロード・サムネイル圧縮の共通コア |
| `youtube_automation.utils.exceptions` | ドメイン固有例外（ConfigError, YouTubeAPIError 等） |
| `youtube_automation.utils.collection_paths` | コレクションディレクトリ構造の解決 |
| `youtube_automation.utils.metadata_generator` | タイトル・説明文・タグ・ローカライゼーション自動生成 |
| `youtube_automation.utils.analytics_collector` | Analytics API データ収集（Mixin 構成） |
| `youtube_automation.utils.analytics_analyzer` | CTR・エンゲージメント分析 |
| `youtube_automation.auth.oauth_handler` | OAuth 2.0 トークン管理・リフレッシュ |
| `youtube_automation.cli.skills_sync` | `yt-skills` コマンド本体 |

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

### Import 規約
- パッケージ内コードは必ず `from youtube_automation.xxx import ...` の fully-qualified import を使用
- ルート直下の `scripts/` にはシェルスクリプト（`.sh`）のみ配置。Python shim は廃止済み

### テスト
- `tests/conftest.py` が `src/` を sys.path に追加し `CHANNEL_DIR` をフィクスチャに向ける
- `ChannelConfig.reset()` / `ServiceRegistry.reset()` でシングルトンをリセット
- `tests/fixtures/sample_channel/` にテストデータを配置

### パッケージング
- ビルドバックエンド: hatchling (`[build-system]` 参照)
- パッケージレイアウト: `src/youtube_automation/` (PyPA src layout)
- `.claude/skills/` は `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_skills/` に同梱され、`yt-skills sync` で配布される
- 新しい CLI スクリプトを追加するときは `pyproject.toml` の `[project.scripts]` にも entry point を登録すること
- バージョン bump は `pyproject.toml` `version` と `src/youtube_automation/__init__.py` の `__version__` の両方

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は **絶対にコミットしない**
- API キーは環境変数経由（`.env` または 1Password CLI）
- OAuth スコープは必要最小限に制限
