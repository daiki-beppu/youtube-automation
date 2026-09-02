# youtube-channels-automation

YouTube チャンネル運営を自動化するツールキット。Analytics データ収集、AI コンテンツ生成、動画アップロード、メタデータ管理をまとめて提供します。

主に、下流のチャンネルリポジトリで制作・公開・分析を継続する運営者と、導入を検討する開発者を対象にしています。セットアップから日々の運営までの手順は [`ONBOARDING.md`](ONBOARDING.md) を参照してください。

> 過去に公開した tayk への移行案内は撤回済みであり、経緯のみを [`docs/migration/python-to-tayk.md`](docs/migration/python-to-tayk.md) に記録しています。

## Features

- YouTube Analytics の収集・分析と競合ベンチマーク
- AI による音楽・動画・画像・メタデータの生成
- 動画、サムネイル、メタデータの公開とプレイリスト管理
- 複数チャンネルの制作ワークフローとローカル dashboard
- 運用者向けの公開リリースノート

機能と skill の全一覧は [`docs/features.md`](docs/features.md) を参照してください。利用できる CLI entry point の正は [`pyproject.toml`](pyproject.toml) の `[project.scripts]` です。

## Prerequisites

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) (動画生成に必要)
- Google Cloud Project (YouTube Data API v3 有効化済み)
- (オプション) [Nix](https://nixos.org/): `flake.nix` で開発環境を再現可能に
- (オプション) [1Password CLI](https://developer.1password.com/docs/cli/): シークレットをディスクに書かずに管理

## Quick Start

### 1. パッケージをインストール

`uv` または `pip` でインストールします。

```bash
uv add git+https://github.com/daiki-beppu/youtube-automation
# または
pip install "git+https://github.com/daiki-beppu/youtube-automation"
```

### 2. チャンネルリポジトリへ配布物を同期

チャンネルリポジトリのルートで実行します。

```bash
yt-skills sync
```

チャンネル作成、OAuth、シークレット、設定、Nix を含む以降の手順は [`ONBOARDING.md`](ONBOARDING.md) に進んでください。

## Documentation

- [`ONBOARDING.md`](ONBOARDING.md) — 導入、API セットアップ、チャンネル開設、日々の運営
- [`docs/architecture.md`](docs/architecture.md) — ツールキットと下流チャンネルリポジトリの構成、設定の責務
- [`docs/features.md`](docs/features.md) — workflow、skill、CLI が提供する機能の一覧
- [`docs/oauth-setup.md`](docs/oauth-setup.md) — OAuth、ADC、シークレットの設定とトラブルシューティング
- [`docs/development.md`](docs/development.md) — 開発環境、テスト、パッケージング、品質ゲート

## License

This project is **source-available**. You may view and study the code for educational and personal purposes, but redistribution, commercial use, and modification are prohibited without prior written permission. See [LICENSE](LICENSE) for full terms.
