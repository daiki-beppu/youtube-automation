# Onboarding

新しく `youtube-channels-automation` を触る人向けの到達点別ガイド。
README が「何を提供しているか」を説明するのに対し、本書は **何を順番にやれば動くか** を示す。
各セクションの末尾には、より詳細な参照先（`README.md` / `auth/SETUP.md` / `docs/`）へのリンクを置く。

---

## 1. このリポジトリでできること / できないこと

### できること

- YouTube Analytics データの定期収集と CTR / engagement 分析
- AI による音楽生成（Lyria / Suno プロンプト生成）、画像生成（Gemini / OpenAI）、動画生成（Veo + FFmpeg）
- 動画・サムネイル・メタデータ・多言語ローカライゼーションの一括アップロード
- ベンチマーク競合チャンネルのデータ収集・コメント分析・サムネイル相関分析
- Claude Code スキル（`.claude/skills/`）の wheel 同梱配布（`yt-skills sync`）

### できないこと

- 各チャンネル固有のディレクトリ作成・config 生成・OAuth 初期化（本リポジトリは **ツールキット** であり、運用は **下流チャンネルリポジトリ** で行う）
- YouTube チャンネルそのものの開設（GCP / YouTube 側の管理画面操作は別）
- マスター音源の自動人手生成（Suno は人手 UI 経由、Lyria は API 経由で生成される — `/suno` と `/lyria` で経路が分かれる）

---

## 2. Prerequisites

| 項目 | バージョン | 用途 |
|---|---|---|
| Python | 3.11+ | パッケージランタイム |
| [uv](https://docs.astral.sh/uv/) | 最新 | 仮想環境 / 依存解決 |
| [FFmpeg](https://ffmpeg.org/) | 最新 | 動画合成 |
| Google Cloud SDK (`gcloud`) | 最新 | Vertex AI / OAuth クライアント作成 |
| [1Password CLI (`op`)](https://developer.1password.com/docs/cli/) | 任意 | シークレットをディスクに書かずに使う |
| [Nix](https://nixos.org/) | 任意 | `flake.nix` で開発環境を再現 |

OS は macOS / Linux を想定。Windows は WSL2 を推奨。

---

## 3. インストール

### 3-A. 下流チャンネルリポジトリで使う（推奨）

```bash
uv add git+https://github.com/daiki-beppu/youtube-channels-automation
# 特定タグ固定
uv add "git+https://github.com/daiki-beppu/youtube-channels-automation@v1.1.0"
```

インストールすると `yt-*` 系 CLI が PATH に入る（`yt-skills` / `yt-analytics` / `yt-upload-collection` 等）。完全な一覧は `pyproject.toml` の `[project.scripts]` を参照。

### 3-B. 本リポジトリを直接編集（開発者向け）

```bash
git clone git@github.com:daiki-beppu/youtube-channels-automation.git
cd youtube-channels-automation
uv sync --extra dev --extra veo
```

> **リネーム時の注意**: リポジトリ／ディレクトリをリネームしたら `.venv` を作り直す（`rm -rf .venv && uv sync`）。`.venv/bin/*` の shebang に旧パスが残ったままだと `bad interpreter` で落ちる。

詳細: [`README.md`](README.md#quick-start)、[`docs/migration-submodule-to-uv.md`](docs/migration-submodule-to-uv.md)

---

## 4. OAuth セットアップ

YouTube Data API v3 を呼ぶには OAuth 2.0 クライアントが必要。詳細は [`auth/SETUP.md`](auth/SETUP.md) を参照。最速経路は次の 2 つ:

- **`scripts/gcp-bootstrap.sh`** — `gcloud` で GCP プロジェクト作成〜 API 有効化〜 `.env` 書き出しまで半自動化（冪等）
- **`infra/terraform/gcp/`** — Terraform で同じ構成を IaC 管理

OAuth クライアント ID 作成だけは Google Cloud Console で手動クリックが残る。
作成した `client_secrets.json` は **下流チャンネルリポジトリの** `auth/client_secrets.json` に配置する（本リポジトリには置かない）。

---

## 5. 最小 config の作り方

下流チャンネルリポジトリ側で、責務別 7 ファイルに分割した `config/channel/*.json` を用意する（v2.0.0 以降）:

| ファイル | 責務 |
|---|---|
| `meta.json` | `channel` / `youtube_channel` |
| `content.json` | `genre` / `tags` / `descriptions` / `title` |
| `youtube.json` | `youtube` / `music_engine` / `content_model` |
| `analytics.json` | `analytics` / `benchmark` (optional) |
| `playlists.json` | `playlists` (optional) |
| `workflow.json` | (optional, 拡張用 reserved) |
| `audio.json` | `audio` (optional) |

サンプルは [`examples/channel_config.example/`](examples/channel_config.example/)（7 ファイル）と [`examples/localizations.example.json`](examples/localizations.example.json) を参照。

v1.x からの移行は [`docs/migration/v2-config-split.md`](docs/migration/v2-config-split.md) と `uv run yt-config-migrate migrate --apply`。

---

## 6. `yt-skills sync` でスキルを配布

Claude Code スキル群（`.claude/skills/`）は本リポジトリの wheel に同梱されており、下流チャンネルリポジトリ側で同期して使う:

```bash
yt-skills list                 # 同梱スキル一覧
yt-skills sync                 # ./.claude/skills/ にコピー
yt-skills sync --symlink       # 開発時はシンボリックリンク
yt-skills diff                 # 同梱版とローカルの差分
yt-skills sync --force         # 既存ファイルを上書き
```

スキルを編集する場合は、本リポジトリ側の `.claude/skills/` を直接編集して PR を出す。下流側で書き換えても次回 `sync` で上書きされる。

---

## 7. 開発者向け

- **テスト**: `uv run pytest`
- **Lint**: `uv run ruff check .`
- **設定アクセス**: チャンネル固有値は `from youtube_automation.utils.config import load_config` 経由で取得する。ハードコーディング禁止。詳細は [`CLAUDE.md`](CLAUDE.md) の「開発規約」節
- **新規 CLI**: `yt-*` プレフィックスを必ず付け、`pyproject.toml` の `[project.scripts]` に entry point を登録する
- **テストフィクスチャ**: `tests/conftest.py` が `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向ける。新スキーマ（`config/channel/*.json`）で配置する
- **takt + GitHub issue 経由の開発フロー**: ブランチ手作業ではなく、`takt-issue` スキルで issue → worktree → PR を統一手順化する（`CLAUDE.md` の「開発ワークフロー」節）

---

## 8. トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| `yt-*` が `bad interpreter` で起動しない | リポジトリ／ディレクトリをリネームした直後によく起きる。`rm -rf .venv && uv sync` で復旧（`uv sync` 単独では shebang が更新されない） |
| `ConfigError: missing key ...` | `config/channel/*.json` に必須キーが不足。`utils/config/loader.py::_REQUIRED_KEYS_BY_SECTION` を参照して該当 JSON を埋める |
| `op read` が失敗する | `op signin` でサインインしているか確認。CLI 取得経路は `utils/secrets.py` の `_SECRET_REFS`（デフォルト: `op://Personal/YouTube_OAuth_Client_Secrets/credential`） |
| `yt-skills sync` がスキルを上書きしない | `--force` を付ける（既存ファイルがあるとデフォルトでスキップ） |
| Vertex AI 呼び出しで `PERMISSION_DENIED` | `GOOGLE_CLOUD_PROJECT` を確認し、`auth/SETUP.md` の IAM ロール付与節を再実行 |
| アップロードが `quotaExceeded` で止まる | YouTube Data API の日次クォータ消費上限。翌日に再開するか、別 GCP プロジェクトに切り替える |

詳細なエラー定義は [`src/youtube_automation/utils/exceptions.py`](src/youtube_automation/utils/exceptions.py) を参照。
