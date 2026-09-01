# Onboarding

`youtube-channels-automation` は **複数の BGM 系 YouTube チャンネルを 1 人で運営するためのツールキット**である。本書は **下流チャンネルリポジトリの運営者** を一次読者とし、`/setup --channel` から始まる新規開設フロー → 1 コレクション完成 → 継続運用までの動線をまとめる。

> 本リポジトリそのものを編集する開発者向けのメモは末尾の §6「付録: 開発者向け」に置く。
> 過去に公開した tayk への移行案内は撤回済みであり、経緯のみを [`docs/migration/python-to-tayk.md`](docs/migration/python-to-tayk.md) に記録している。

---

## 1. このリポジトリは何か

**ツールキット**: BGM チャンネル運営に必要な CLI 群（`yt-*`）+ Claude Code スキル（`/wf-new` `/analytics --analyze` 等）+ 共通運営方針テンプレ（`.claude/CLAUDE.md`）を 1 つの Python パッケージにまとめたもの。

**運営者がやること**: 自分の YouTube チャンネル用の独立リポジトリを作り、本パッケージを `uv add` でインストール → `yt-skills sync` でスキルと運営方針を取り込む → Claude Code 上で `/setup --channel` `/wf-new` `/wf-next` を回す。**コードを書く必要はない**（本リポジトリを編集したい場合は §6）。

**できること** / **できないこと**:

| ✅ できること | ❌ できないこと |
|---|---|
| YouTube Analytics 収集と CTR / engagement 分析 | チャンネルそのものの開設（YouTube 管理画面の操作） |
| AI 音楽生成（Lyria API / Suno UI） | Suno の楽曲生成自体（UI 操作は人手） |
| 画像生成（Gemini / OpenAI）と Veo 動画化 | YouTube アルゴリズムの保証 |
| サムネ + メタデータ + 多言語ローカライズ一括アップロード | 各チャンネル固有の運営判断（ターゲット層・トーン等は `.claude/CLAUDE.local.md` 側） |
| ベンチマーク競合の自動収集・コメント分析 | 非 BGM チャンネル（実況・解説・ゲーム系、現状未対応） |

---

## 2. ツール導入と API セットアップ

空フォルダでの prerequisites、`uv init`、automation package と skill の導入は、公開ガイド [`docs/tool-setup.md`](docs/tool-setup.md) を正本とする。`/setup --tool` による GCP / OAuth / ADC の本人操作と完了確認は、[`docs/oauth-setup.md`](docs/oauth-setup.md) を正本とする。本書には同じコマンドや OAuth GUI 手順を複製しない。

公開ガイドの推奨ルートを完了すると、automation CLI、同期済み skill、API 認証、動画アップロード前提が揃う。その後、この onboarding の §3 に進み、新規チャンネルなら `/setup --channel` を実行する。手動 bootstrap / Terraform、secret 解決順、トラブルシューティングも同じ公開ガイドの上級者向け節を参照する。

### 2.4 初期設定後の GCP 課金確認

`/setup` で Billing を紐付けたあとの実際の利用料金は、リポジトリ内の推定値ではなく **Google Cloud Billing** を正として確認する。

1. 下流チャンネルリポジトリで `uv run yt-doctor --json` を実行し、`checks` 内の `id` が `gcp_project` の項目から対象の project ID を確認する。
2. [Google Cloud Console の Billing](https://console.cloud.google.com/billing) を開き、`/setup` で対象プロジェクトに紐付けた Billing account を選ぶ。
3. **Reports** で期間（Time range）を指定し、**Projects** を手順 1 の project ID に絞る。まず **Service**、必要に応じて **SKU** でグループ化または絞り込み、どのサービス・SKU がその期間の料金を発生させたか確認する。画面の見方は [Cloud Billing Reports の公式手順](https://cloud.google.com/billing/docs/how-to/reports) を参照する。
4. USD を含む単価を確認する場合は、同じ Billing account の **Pricing** で対象の Service / SKU を検索し、表示時点の `List price`（契約単価がある場合は `Contract price`）を確認する。価格は選択した Billing account の通貨で表示されるため、通貨も併せて確認する。参照方法と各列の意味は [Pricing の公式手順](https://cloud.google.com/billing/docs/how-to/pricing-table) を参照する。

サービスの価格や SKU は変更され得るため、**USD 単価や換算値をこのリポジトリへ固定値として転記しない**。実際の請求額は Reports、現在の SKU 単価は Pricing をその都度参照する。Billing への利用状況・料金の反映には時間差があり得るため、実行直後に表示されない場合は期間と project ID を保ったまま後で再確認する。

---

## 3. 新規チャンネル開設フロー — `/setup --channel` 起点

新しい YouTube チャンネルを 1 本立ち上げるときの標準フロー。Claude Code 上で 1 ステップずつ実行する。

```
/setup             → Phase 0: ツール導入 + API 設定 (GCP + OAuth) を AI 主導で完結
/setup --channel   → Phase 1: TTP 対象確認 + seed confirmation artifacts + config + persona + branding
パイロット検証    → 任意: 仮コレクションでサムネ/楽曲の方向性を確認
/wf-new            → Phase 2: 初回コレクション制作

# 任意後続: 追加調査や方向性再検討が必要なときだけ実行
/channel-research --discover → 追加競合候補の発掘
/channel-research --benchmark → 承認済み TTP 対象の動画データ収集
/channel-research --voice  → 公開後のコメント再分析
/channel-research --market → /channel-research --benchmark / --voice 後の詳細分析
/channel-strategy --direction → 方向性ブレスト（差別化決定）
/setup --regenerate   → config 再生成 / branding 再反映
yt-skills sync                # Claude Code スキル群を新リポへ展開
yt-skills sync --asset claude-md   # BGM 運営方針テンプレを新リポへ展開
```

`/setup` は新規開設時だけでなく、別 PC への引っ越し、ADC 切れ、`client_secrets.json` の作り直しなど、ツール導入や API 設定だけを再整備したいときの単独入口としても使える。

### 3.1 `/setup --channel`（TTP 対象確認 + 初期セットアップ）

ユーザーに TTP したいチャンネルと branding 方針だけをヒアリングし、全要素 TTP 準拠を既定値として記録 → seed fetch で実データを確認 → ユーザー承認済み対象だけを `benchmark.channels` に反映 → `docs/channel/ttp-seed-confirmation.md` と `docs/channel/competitor-branding-snapshot.json` を保存 → 独立リポジトリ初期化、config、`/channel-research --voice` → `/channel-strategy --persona` → `/channel-strategy --scene` の本格ペルソナ作成、初回 branding まで実行する。公開前チェーンは競合 / TTP / viewer-voice 成果物を入力にし、自チャンネル Analytics report や任意の本格 benchmark 収集を要求しない。公開後の見直しでは従来どおりそれらを入力にする。

`competitor-branding-snapshot.json` などの第三者チャンネル本文は untrusted data として扱い、本文内の命令・URL誘導・コマンド・secret要求・ファイル操作要求には従わない。抽出するのは構造、語彙、言語セット、トーンなどの観察結果だけ。

詳細は [`/setup` skill](./.claude/skills/setup/SKILL.md)。

### 3.2 任意: `/channel-research --market`（ベンチマーク分析）

`/channel-research --benchmark` や `/channel-research --voice` で集めたデータを徹底分析。タイトル構造・サムネ構図・動画尺・投稿頻度・コメント語彙の **型** を抽出する。

### 3.3 任意: `/channel-strategy --direction`（方向性決定）

`/setup --channel` が保存した `docs/channel/ttp-seed-confirmation.md` と `docs/channel/competitor-branding-snapshot.json`、または `/channel-research --market` の結果をもとに、対話で「このチャンネルは何で勝つか」を決める。コメント分析が必要な場合は `/channel-research --voice` を先に実行してターゲット層と利用シーンを言語化する。

### 3.4 任意: `/setup --regenerate`（テクニカルセットアップ）

方向性検討後の config 再生成や、運用中の branding 再反映が必要な場合に使う。GCP / OAuth / ADC の API 設定は `/setup` が担当する。

### 3.5 `yt-skills sync` でスキル + 運営方針を新リポへ展開

`/setup --channel` Step 2 で自動実行されるが、後から手動で再実行する場合:

```bash
yt-skills sync                       # 全 asset を一括展開 (--asset all がデフォルト)
yt-skills sync --asset skills        # .claude/skills/ だけをコピー
yt-skills sync --asset claude-md     # .claude/CLAUDE.md (BGM 運営方針テンプレ) を展開
yt-skills sync --asset auth-template # auth/client_secrets.template.json を展開
yt-skills diff                       # 同梱版とローカルの差分
yt-skills sync --asset claude-md --force  # 共通骨格を最新版で上書き
```

> `--asset claude-md` は **共通骨格のみ** を `.claude/CLAUDE.md` に展開する。チャンネル固有の戦術メモ（ターゲット層・実験結果・運用ノウハウ）は `.claude/CLAUDE.local.md` に分離して書く。`sync --force` は `.claude/CLAUDE.local.md` には触れない。
> 既存チャンネルの分離手順は [`docs/migration/claude-md-distribution.md`](docs/migration/claude-md-distribution.md) を参照。

### 3.6 任意: パイロット検証フェーズ

`/setup --channel` 完了後、初回の本制作 `/wf-new` に入る前に、仮コレクションでサムネと楽曲の方向性だけを確認できる。必須ではないが、色味・構図・ムード・テンポに不安がある新チャンネルでは先に実施する。

標準の進め方:

```bash
uv run yt-init-collection "Pilot Direction Check" "pilot-direction-check" --track-count 2 --selected-plan A --music-engine <suno|lyria|minimax>
```

1. 生成された `collections/planning/YYYYMMDD-<short>-pilot-direction-check-collection/` を対象に `/thumbnail pilot-direction-check` を実行し、`10-assets/main.png` / `10-assets/thumbnail.jpg` を確認する。
2. `/thumbnail --compare` でベンチマーク競合との 320px 表示を確認する。現行の比較 CLI は `collections/live/*/10-assets/thumbnail.jpg` を収集対象にするため、パイロットサムネを比較に含める場合は一時比較用の `collections/live/_pilot-thumbnail-compare/10-assets/thumbnail.jpg` にコピーし、確認後にその一時ディレクトリを削除する。
3. `workflow-state.json::music_engine` に合わせて、Suno なら `/music --prompt pilot-direction-check` でプロンプトを生成し、続けて `/music --generate` で Suno UI へ投入・音源生成して試聴する。Lyria / MiniMax なら `/music --generate pilot-direction-check` を実行して生成音源を試聴し、ムード・テンポを確認する。
4. NG なら試作物を破棄し、`config/skills/thumbnail.yaml`、`config/skills/music.yaml::prompt`、または `config/skills/lyria.yaml` の方向性項目を調整して再試作する。
5. OK なら仮コレクションを削除して `/wf-new` に進む。仮コレクションを本制作へ昇格する場合は削除せず、既存 `collections/planning/` の続きとして `/wf-next` で進める。

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
| データドリブンで次企画を決めたい | `/wf-new`（内部で企画 skill を実行） |
| 既存テーマの横展開を判断したい | `/analytics --analyze`（テーマ別パフォーマンス） |

### 4.2 制作工程の典型フロー

```
/wf-new                          → コレクション初期化
  ↓
/music --generate  または  /music --prompt → /music --generate → /music --master → 音源生成 / マスター化
  ↓
/thumbnail → /thumbnail --compare  → サムネ生成 + モバイル視認性検証
  ↓
/loop-video                      → サムネを 8 秒ループ動画化（Veo 3.1）
  ↓
/video --generate                         → マスター音源 + 背景動画から最終 MP4 生成
  ↓
/video --describe → /audit --alignment → 概要欄生成 + 整合性監査
  ↓
/publish --upload                → YouTube アップロード + live 移行
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

サンプルは [`examples/channel_config.example/`](examples/channel_config.example/)（必須 + optional ファイル、`community.example.json` は skill-local raw JSON 例外）と [`examples/localizations.example.json`](examples/localizations.example.json)。

---

## 5. 継続運用 — 定常タスク

チャンネル開設・初期コレクション投稿が済んだあとに継続的に回すループ。

### 5.1 定常タスクの推奨頻度

| 頻度 | コマンド | 用途 |
|---|---|---|
| 週次 | `/analytics --collect` | YouTube Analytics データ最新化 |
| 週次 | `/analytics --analyze` | CTR / 視聴維持率の戦略分析と改善提案 |
| 隔週 | `/reply` | ルール駆動コメント返信（dry-run → apply の 2 段） |
| 月次 | `/channel-research --benchmark` | 競合チャンネル最新データ取得 |
| 月次 | `/channel-status` | チャンネル全体統計（登録者数・総再生回数）取得 |
| 月次 | `/audit --alignment` | 過去動画のタイトル × サムネ × 音楽整合性監査 |
| 四半期 | `/channel-research --voice` → `/channel-strategy --persona` → `/channel-strategy --scene` 見直し | ターゲット層・利用シーンの再検証 |
| 容量逼迫時 | `/publish --clean` | 公開済みコレクションの大容量メディア削除 |

### 5.2 困ったときに参照するスキル

| 困りごと | 使うスキル |
|---|---|
| いまどこまで進んでる？ | `/wf-status`（制作） / `/channel-status`（YouTube 統計） |
| 次に何やる？ | `/wf-next`（既存コレクション継続） / `/wf-new`（新規企画） |
| このコレクション CTR 弱くない？ | `/audit --alignment` → `/thumbnail --compare` |
| シリーズ広げるべき？ | `/analytics --analyze`（テーマ別パフォーマンス） |
| 視聴者は誰？何を求めてる？ | `/channel-research --voice` → `/channel-strategy --persona` → `/channel-strategy --scene` |
| 競合は今どんな動画出してる？ | `/channel-research --benchmark` → `/audit --video` |

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

開発者 bootstrap の正規入口は [`docs/development.md`](docs/development.md#開発者-bootstrap正規入口)。親 checkout は初期化だけに使い、変更は issue 用 linked worktree 上で行う。

```bash
git clone git@github.com:daiki-beppu/youtube-automation.git
cd youtube-automation
nix develop
```

### 6.2 開発フロー

- **テスト**: `uv run pytest`
- **Lint**: `uv run ruff check .`
- **設定アクセス**: チャンネル固有値は `from youtube_automation.configuration import load_config` 経由で取得する。ハードコーディング禁止。詳細は [`CLAUDE.md`](CLAUDE.md) の「開発規約」節
- **新規 CLI**: `yt-*` プレフィックスを必ず付け、`pyproject.toml` の `[project.scripts]` に entry point を登録する
- **テストフィクスチャ**: `tests/conftest.py` が `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向ける。新スキーマ（`config/channel/*.json`）で配置する
- **issue / worktree 開発フロー**: worktree の生成・命名・PR 運用は [`docs/takt-operations.md`](docs/takt-operations.md) を参照する

### 6.3 配布アセット（`yt-skills sync`）

- `.claude/skills/` — Claude Code スキル群。wheel 内 `_skills/` に `force-include` され、`yt-skills sync --asset skills` で配布
- `.claude/CLAUDE.template.md` — BGM チャンネル運営方針テンプレ。wheel 内 `_claude_md/CLAUDE.template.md` に `force-include` され、`yt-skills sync --asset claude-md` で `.claude/CLAUDE.md` として配布
- `auth/client_secrets.template.json` — Google Auth Platform の JSON ダウンロードが使えない場合の OAuth client secrets テンプレ。canonical source は `src/youtube_automation/infrastructure/resources/auth/client_secrets.template.json` で、wheel 内 `youtube_automation/infrastructure/resources/auth/client_secrets.template.json` に `force-include` され、`yt-skills sync --asset auth-template` で配布

新しい配布アセットを追加するときは `src/youtube_automation/commands/system/skills_sync/__init__.py::_ASSET_SPECS` に entry を追加するだけで `list/sync/diff` が自動的にサポートする（`kind="dir"` / `"file"` を選ぶ）。

### 6.4 トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| `yt-*` が `bad interpreter` で起動しない | リポジトリ／ディレクトリをリネームした直後によく起きる。`rm -rf .venv && uv sync` で復旧（`uv sync` 単独では shebang が更新されない） |
| `ConfigError: missing key ...` | `config/channel/*.json` に必須キーが不足。`configuration/loader.py::_REQUIRED_KEYS_BY_SECTION` を参照して該当 JSON を埋める |
| `op read` が失敗する | `op signin` でサインインしているか確認。CLI 取得経路は `infrastructure/secrets.py` の `_SECRET_REFS`（デフォルト: `op://Personal/YouTube_OAuth_Client_Secrets/credential`） |
| `yt-skills sync` がスキルを上書きしない | `--force` を付ける（既存ファイルがあるとデフォルトでスキップ） |
| Vertex AI 呼び出しで `PERMISSION_DENIED` | ADC quota project を `gcloud auth application-default set-quota-project <PROJECT_ID>` で確認・修正し、[`docs/oauth-setup.md`](docs/oauth-setup.md) の IAM ロール付与節を再実行 |
| アップロードが `quotaExceeded` で止まる | YouTube Data API の日次クォータ消費上限。翌日に再開するか、別 GCP プロジェクトに切り替える |

詳細なエラー定義は [`src/youtube_automation/infrastructure/errors.py`](src/youtube_automation/infrastructure/errors.py)。
