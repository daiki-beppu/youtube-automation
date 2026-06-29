# Onboarding

`youtube-channels-automation` は **複数の BGM 系 YouTube チャンネルを 1 人で運営するためのツールキット**である。本書は **下流チャンネルリポジトリの運営者** を一次読者とし、`/channel-new` から始まる新規開設フロー → 1 コレクション完成 → 継続運用までの動線をまとめる。

> 本リポジトリそのものを編集する開発者向けのメモは末尾の §6「付録: 開発者向け」に置く。

---

## 1. このリポジトリは何か

**ツールキット**: BGM チャンネル運営に必要な CLI 群（`yt-*`）+ Claude Code スキル（`/wf-new` `/analytics-analyze` 等）+ 共通運営方針テンプレ（`.claude/CLAUDE.md`）を 1 つの Python パッケージにまとめたもの。

**運営者がやること**: 自分の YouTube チャンネル用の独立リポジトリを作り、本パッケージを `uv add` でインストール → `yt-skills sync` でスキルと運営方針を取り込む → Claude Code 上で `/channel-new` `/wf-new` `/wf-next` を回す。**コードを書く必要はない**（本リポジトリを編集したい場合は §6）。

**できること** / **できないこと**:

| ✅ できること | ❌ できないこと |
|---|---|
| YouTube Analytics 収集と CTR / engagement 分析 | チャンネルそのものの開設（YouTube 管理画面の操作） |
| AI 音楽生成（Lyria API / Suno UI） | Suno の楽曲生成自体（UI 操作は人手） |
| 画像生成（Gemini / OpenAI）と Veo 動画化 | YouTube アルゴリズムの保証 |
| サムネ + メタデータ + 多言語ローカライズ一括アップロード | 各チャンネル固有の運営判断（ターゲット層・トーン等は `.claude/CLAUDE.local.md` 側） |
| ベンチマーク競合の自動収集・コメント分析 | 非 BGM チャンネル（実況・解説・ゲーム系、現状未対応） |

---

## 2. Prerequisites + インストール

### 2.1 Prerequisites

| 項目 | バージョン | 用途 |
|---|---|---|
| Python | 3.11+ | パッケージランタイム |
| [uv](https://docs.astral.sh/uv/) | 最新 | 仮想環境 / 依存解決 |
| [FFmpeg](https://ffmpeg.org/) | 最新 | 動画合成 |
| Google Cloud SDK (`gcloud`) | 最新 | Vertex AI / OAuth クライアント作成 |
| Claude Code (claude.ai/code) | 最新 | スキル実行ホスト |
| [1Password CLI (`op`)](https://developer.1password.com/docs/cli/) | 任意 | シークレットをディスクに書かずに使う |
| [Nix](https://nixos.org/) | 任意 | `flake.nix` で開発環境を再現 |

OS は macOS / Linux を想定。Windows は WSL2 を推奨。

### 2.2 下流チャンネルリポジトリでインストール（推奨経路）

各チャンネルリポジトリ側で実行:

```bash
uv add git+https://github.com/daiki-beppu/youtube-channels-automation
# 特定タグ固定
uv add "git+https://github.com/daiki-beppu/youtube-channels-automation@v5.5.0"
```

インストールすると `yt-*` 系 CLI が PATH に入る（`yt-skills` / `yt-analytics` / `yt-upload-collection` 等）。完全な一覧は `pyproject.toml` の `[project.scripts]` を参照。

> **リネーム時の注意**: チャンネルリポジトリのディレクトリをリネームしたら `.venv` を作り直す（`rm -rf .venv && uv sync`）。`.venv/bin/*` の shebang に旧パスが残ると `bad interpreter` で落ちる。

### 2.3 OAuth セットアップ

**Claude Code 上で `/setup` を実行する**。AI が `yt-doctor` でツール導入と API 設定の状態を診断し、GCP プロジェクト作成・API 有効化・IAM 付与・`.env` 書き出し・OAuth クライアント ID 配置まで wizard で誘導する。

`gcloud auth login` / `gcloud auth application-default login` / Google Cloud Console での OAuth クライアント ID 作成の 3 ステップだけは PKCE / GUI 制約で AI 実行不可なため利用者が手動で行うが、それ以外 (プロジェクト作成・billing 紐付け・API 有効化・IAM 付与・トークン取得など) は AI が gcloud を直接 Bash で実行する。

手動で全工程やりたい上級者向けの 2 ルート (bootstrap.sh / Terraform) は [`auth/SETUP.md`](auth/SETUP.md) と `.claude/skills/channel-setup/references/gcp-bootstrap.sh` / `infra/terraform/gcp/` を参照（submodule 利用の場合は `automation/` プレフィックスを追加）。

---

## 3. 新規チャンネル開設フロー — `/channel-new` 起点

新しい YouTube チャンネルを 1 本立ち上げるときの **5 スキル連携**。Claude Code 上で 1 ステップずつ実行する。

```
/setup             → Phase 0: ツール導入 + API 設定 (GCP + OAuth) を AI 主導で完結
/channel-new       → Phase 1: ビジョン共有 + 競合発掘 + 独立リポジトリ作成
/channel-research  → Phase 2: ベンチマーク徹底分析
/channel-direction → Phase 3: 方向性ブレスト（差別化決定）
/channel-setup     → Phase 4: テクニカルセットアップ（config 生成、Step 6 は /setup 完了済みなら skip）
yt-skills sync                # Claude Code スキル群を新リポへ展開
yt-skills sync --asset claude-md   # BGM 運営方針テンプレを新リポへ展開
```

`/setup` は新規開設時だけでなく、別 PC への引っ越し、ADC 切れ、`client_secrets.json` の作り直しなど、ツール導入や API 設定だけを再整備したいときの単独入口としても使える。

### 3.1 `/channel-new`（競合発掘 + リポジトリ作成）

ユーザーにビジョン（ジャンル / 雰囲気 / 仮チャンネル名）をヒアリング → `gh repo create` で独立リポジトリを作成 → `uv add` でパッケージ導入 → `yt-discover-competitors` で 5-10 件の競合チャンネルを発掘 → ベンチマークデータ + コメント収集まで実行する。

詳細は [`/channel-new` skill](./.claude/skills/channel-new/SKILL.md)。

### 3.2 `/channel-research`（ベンチマーク分析）

`/channel-new` で集めたベンチマークデータを徹底分析。タイトル構造・サムネ構図・動画尺・投稿頻度の **型** を抽出する。

### 3.3 `/channel-direction`（方向性決定）

分析結果をもとに、対話で「このチャンネルは何で勝つか」を決める。`/audience-persona` `/viewing-scene` `/viewer-voice` も使ってターゲット層と利用シーンを言語化する。

### 3.4 `/channel-setup`（テクニカルセットアップ）

責務別 `config/channel/*.json` を生成、GCP / Vertex AI ブートストラップ（API 有効化・サービスアカウント作成・ADC 設定・`.env` 書き出し）、認証ファイル配置を AI セッション内で完結させる。

### 3.5 `yt-skills sync` でスキル + 運営方針を新リポへ展開

`/channel-new` Step 2 で自動実行されるが、後から手動で再実行する場合:

```bash
yt-skills sync                       # .claude/skills/ をコピー
yt-skills sync --asset claude-md     # .claude/CLAUDE.md (BGM 運営方針テンプレ) を展開
yt-skills diff                       # 同梱版とローカルの差分
yt-skills sync --asset claude-md --force  # 共通骨格を最新版で上書き
```

> `--asset claude-md` は **共通骨格のみ** を `.claude/CLAUDE.md` に展開する。チャンネル固有の戦術メモ（ターゲット層・実験結果・運用ノウハウ）は `.claude/CLAUDE.local.md` に分離して書く。`sync --force` は `.claude/CLAUDE.local.md` には触れない。
> 既存チャンネルの分離手順は [`docs/migration/claude-md-distribution.md`](docs/migration/claude-md-distribution.md) を参照。

---

## 4. 制作ループ — 1 コレクションを完成まで

新規チャンネルが立ち上がったら、コレクション単位で動画を 1 本ずつ完成させる。

```
/wf-new      → 新規コレクション制作開始（企画選択 → ディレクトリ作成 → 素材準備）
/wf-next     → 既存コレクションを次工程に進める（音源生成 → サムネ → 動画 → メタデータ → アップロード）
/wf-status   → 制作中コレクションの進捗を読み取り（実行はしない）
```

### 4.1 企画選定

| シーン | スキル |
|---|---|
| データドリブンで次企画を決めたい | `/collection-ideate` |
| 既存テーマの横展開を判断したい | `/analytics-analyze`（テーマ別パフォーマンス） |

### 4.2 制作工程の典型フロー

```
/wf-new                          → コレクション初期化
  ↓
/lyria  または  /suno + /masterup → 音源生成 / マスター化
  ↓
/thumbnail → /thumbnail-compare  → サムネ生成 + モバイル視認性検証
  ↓
/loop-video                      → サムネを 8 秒ループ動画化（Veo 3.1）
  ↓
/videoup                         → マスター音源 + 背景動画から最終 MP4 生成
  ↓
/video-description → /alignment-check → 概要欄生成 + 整合性監査
  ↓
/video-upload                    → YouTube アップロード + live 移行
```

`/wf-next` を呼べば現在の進捗を読んで次の必要工程を自動で判定して案内する。

### 4.3 最小 config の構造

下流チャンネルの `config/channel/` は以下の必須 + optional ファイル構造を持つ（v2.0.0 以降の責務別分割）:

| ファイル | 責務 |
|---|---|
| `meta.json` | `channel` / `youtube_channel` |
| `content.json` | `genre` / `tags` / `descriptions` / `title` |
| `youtube.json` | `youtube` / `music_engine` / `content_model` |
| `analytics.json` | `analytics` / `benchmark` (optional) |
| `playlists.json` | `playlists` (optional) |
| `workflow.json` | (optional, 拡張用 reserved) |
| `audio.json` | `audio` (optional) |
| `shorts.json` | `shorts` (optional) |
| `comments.json` | `comments` (optional) |
| `pinned-comment.json` | `pinned_comment` (optional) |
| `distrokid.json` | `distrokid` (optional) |

サンプルは [`examples/channel_config.example/`](examples/channel_config.example/)（必須 + optional ファイル、`community.example.json` は skill-local raw JSON 例外）と [`examples/localizations.example.json`](examples/localizations.example.json)。v1.x からの移行は [`docs/migration/v2-config-split.md`](docs/migration/v2-config-split.md) と `uv run yt-config-migrate migrate --apply`。

---

## 5. 継続運用 — 定常タスク

チャンネル開設・初期コレクション投稿が済んだあとに継続的に回すループ。

### 5.1 定常タスクの推奨頻度

| 頻度 | コマンド | 用途 |
|---|---|---|
| 週次 | `/analytics-collect` | YouTube Analytics データ最新化 |
| 週次 | `/analytics-analyze` | CTR / 視聴維持率の戦略分析と改善提案 |
| 隔週 | `/comments-reply` | ルール駆動コメント返信（dry-run → apply の 2 段） |
| 月次 | `/benchmark` | 競合チャンネル最新データ取得 |
| 月次 | `/channel-status` | チャンネル全体統計（登録者数・総再生回数）取得 |
| 月次 | `/alignment-check` | 過去動画のタイトル × サムネ × 音楽整合性監査 |
| 四半期 | `/audience-persona` + `/viewing-scene` 見直し | ターゲット層・利用シーンの再検証 |
| 容量逼迫時 | `/live-clean` | 公開済みコレクションの大容量メディア削除 |

### 5.2 困ったときに参照するスキル

| 困りごと | 使うスキル |
|---|---|
| いまどこまで進んでる？ | `/wf-status`（制作） / `/channel-status`（YouTube 統計） |
| 次に何やる？ | `/wf-next`（既存コレクション継続） / `/collection-ideate`（新規企画） |
| このコレクション CTR 弱くない？ | `/alignment-check` → `/thumbnail-compare` |
| シリーズ広げるべき？ | `/analytics-analyze`（テーマ別パフォーマンス） |
| 視聴者は誰？何を求めてる？ | `/audience-persona` + `/viewer-voice` + `/viewing-scene` |
| 競合は今どんな動画出してる？ | `/benchmark` → `/video-analyze` |

### 5.3 共通運営方針の更新

upstream で `.claude/CLAUDE.template.md` が更新されたら、各チャンネルリポで以下を実行して取り込む:

```bash
uv add -U git+https://github.com/daiki-beppu/youtube-channels-automation
uv run yt-skills diff --asset claude-md     # 上書きされる差分を確認
uv run yt-skills sync --asset claude-md --force
```

`.claude/CLAUDE.local.md`（個別メモ）は触られない。

---

## 6. 付録: 開発者向け（本リポジトリ側を編集する人）

本リポジトリそのものを編集して PR を出す場合のメモ。下流チャンネル運営者は読む必要はない。

### 6.1 セットアップ

```bash
git clone git@github.com:daiki-beppu/youtube-channels-automation.git
cd youtube-channels-automation
uv sync --extra dev --extra veo
```

### 6.2 開発フロー

- **テスト**: `uv run pytest`
- **Lint**: `uv run ruff check .`
- **設定アクセス**: チャンネル固有値は `from youtube_automation.utils.config import load_config` 経由で取得する。ハードコーディング禁止。詳細は [`CLAUDE.md`](CLAUDE.md) の「開発規約」節
- **新規 CLI**: `yt-*` プレフィックスを必ず付け、`pyproject.toml` の `[project.scripts]` に entry point を登録する
- **テストフィクスチャ**: `tests/conftest.py` が `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向ける。新スキーマ（`config/channel/*.json`）で配置する
- **takt + GitHub issue 経由の開発フロー**: ブランチ手作業ではなく、`takt-issue` スキルで issue → worktree → PR を統一手順化する（`CLAUDE.md` の「開発ワークフロー」節）

### 6.3 配布アセット（`yt-skills sync`）

- `.claude/skills/` — Claude Code スキル群。wheel 内 `_skills/` に `force-include` され、`yt-skills sync --asset skills` で配布
- `.claude/CLAUDE.template.md` — BGM チャンネル運営方針テンプレ。wheel 内 `_claude_md/CLAUDE.template.md` に `force-include` され、`yt-skills sync --asset claude-md` で `.claude/CLAUDE.md` として配布

新しい配布アセットを追加するときは `src/youtube_automation/cli/skills_sync.py::_ASSET_SPECS` に entry を追加するだけで `list/sync/diff` が自動的にサポートする（`kind="dir"` / `"file"` を選ぶ）。

### 6.4 トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| `yt-*` が `bad interpreter` で起動しない | リポジトリ／ディレクトリをリネームした直後によく起きる。`rm -rf .venv && uv sync` で復旧（`uv sync` 単独では shebang が更新されない） |
| `ConfigError: missing key ...` | `config/channel/*.json` に必須キーが不足。`utils/config/loader.py::_REQUIRED_KEYS_BY_SECTION` を参照して該当 JSON を埋める |
| `op read` が失敗する | `op signin` でサインインしているか確認。CLI 取得経路は `utils/secrets.py` の `_SECRET_REFS`（デフォルト: `op://Personal/YouTube_OAuth_Client_Secrets/credential`） |
| `yt-skills sync` がスキルを上書きしない | `--force` を付ける（既存ファイルがあるとデフォルトでスキップ） |
| Vertex AI 呼び出しで `PERMISSION_DENIED` | ADC quota project を `gcloud auth application-default set-quota-project <PROJECT_ID>` で確認・修正し、`auth/SETUP.md` の IAM ロール付与節を再実行 |
| アップロードが `quotaExceeded` で止まる | YouTube Data API の日次クォータ消費上限。翌日に再開するか、別 GCP プロジェクトに切り替える |

詳細なエラー定義は [`src/youtube_automation/utils/exceptions.py`](src/youtube_automation/utils/exceptions.py)。
