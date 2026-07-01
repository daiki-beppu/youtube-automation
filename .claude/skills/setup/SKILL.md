---
name: setup
description: "Use when YouTube automation のツール導入と GCP / OAuth まわりの API 設定を新規にセットアップしたい、または既存セットアップを再診断したいとき。「セットアップして」「ツール入れて」「環境構築」「API 設定して」「gcloud 設定」「OAuth 設定」「`/setup`」「旧 `/onboard`」など。AI が `yt-doctor` で状態を診断し、次に必要な 1 アクションだけを案内する wizard。"
---

## Overview

このスキルは **AI が指揮を取るツール・API 設定 wizard** である。automation CLI 導入後は `uv run yt-doctor --json` を都度叩いて状態を取得し、`summary.next_check_id` が指す未完了 check に対して **1 ステップだけ** 進行する。

責務は「automation ツールが動き、API 認証とアップロード前提が通る状態」まで。新規チャンネルの TTP 対象確認、config 生成、ペルソナ、branding は `/channel-new` が担当する。

利用者は GCP / OAuth に不慣れな前提。AI ができる作業は AI が直接 Bash で実行し、AI にできない 3 ステップ (後述) だけ利用者に依頼する。

### カテゴリ別チェック構成

`yt-doctor` は診断を 5 カテゴリで段階表示する:

| カテゴリ | 内容 |
|---------|------|
| `bootstrap` | ffmpeg / ffprobe / uv / pyproject.toml / automation パッケージ / `yt-skills sync`（6 check） |
| `api` | gcloud CLI・GCP プロジェクト・Billing・APIs・ADC・IAM・.env・OAuth 認証（11 check） |
| `channel` | config/channel/ のロード可能性（1 check）。fail 時は `/channel-new` または `/channel-import` を案内するだけ |
| `data` | `/wf-new` の入力モード判定データ（analytics_report / benchmark_data / ttp_wf_new_readiness）。minimal mode / benchmark fallback mode は setup のブロッカーにしない。承認済み TTP がある場合だけ `/channel-setup` benchmark 反映完了を確認する |
| `upload` | upload 必須 scope 充足・channel_id 設定済み（1 check） |

setup の完了条件は、ツール、API 認証、アップロード前提が揃った状態。`data` カテゴリは `/wf-new` の入力モード確認用で、stale analytics report 以外は新規チャンネル初回制作を止めない。新規チャンネル作成は次に `/channel-new` を実行する。

## 起動時のチェック

空フォルダでは `yt-doctor` がまだ存在しないため、最初に automation CLI を導入する:

1. `uv` が無ければ `uv` step を案内する
2. `pyproject.toml` が無ければ `uv init` を Bash で実行する
3. `pyproject.toml` に `youtube-channels-automation` 依存が無ければ `uv add git+https://github.com/daiki-beppu/youtube-automation.git` を Bash で実行する
4. `uv run yt-skills sync --asset skills --force` / `uv run yt-skills sync --asset claude-md` / `uv run yt-skills sync --asset auth-template` を Bash で実行する
5. `uv run yt-setup-dirs` を Bash で実行し、OAuth クライアント JSON の配置先 `auth/` など setup に必要な最小ディレクトリを作成する
6. `uv run yt-doctor --json` を Bash で実行し、結果を読む
7. `summary.next_check_id` が `null` なら「全 check 緑です。`/setup` は完了済みです」と報告して終了
8. `null` でないなら、その check に対応する手順 (§Steps) に進む
9. 1 ステップ完了したら、必ず `uv run yt-doctor --json` を再実行して進捗確認してから次の `next_check_id` に移る

`/setup` は `uv run yt-setup-dirs` で `auth/`, `collections/`, `data/`, `docs/channel/personas/`, `docs/benchmarks/`, `research/` を冪等に作成する。`/setup` では `config/channel/*.json` を生成しない。新規チャンネルの config、TTP メモ、ペルソナ、branding は引き続き `/channel-new` の責務。

## AI が絶対に Bash で叩かないコマンド

以下は PKCE フローが Claude Code (非対話セッション) では完結しないため、AI が直接実行してはならない。必ず **[HUMAN STEP]** として利用者に依頼する:

- `gcloud auth login`
- `gcloud auth application-default login`

これらを AI が呼ぶと「認可コードを渡しても新しい URL が出る」無限ループに陥る (詳細: PKCE の `code_verifier` が同一プロセスでしか保持できないため)。

加えて、**Google Auth Platform の Branding / Audience / Clients 設定と `client_secrets.json` 配置** (Google Cloud Console GUI 操作) は gcloud / Terraform に該当 API が存在しないため、これも `[HUMAN STEP]` で依頼する。

## [HUMAN STEP] の書き方

利用者に手動操作を依頼するときは、必ず以下の形式で投げて停止する:

```
> [HUMAN STEP]
> あなたのターミナルで以下を実行してください:
>   gcloud auth login
> 完了したら "done" と返してください。
```

利用者が "done" と返すまで、次の Bash ツール呼び出しはしない。返ってきたら `uv run yt-doctor --json` を再実行して結果を確認する。

## Steps (check id ごとの対応手順)

各 step は `yt-doctor` の check id にマップする。AI は `next_check_id` の値を見て該当 step に飛ぶ。

### bootstrap カテゴリ

#### `ffmpeg` / `ffprobe` — 動画生成ツール未インストール

`yt-doctor` の `next_action.instructions` をそのまま案内する。macOS なら以下を案内してよい:

```bash
brew install ffmpeg
```

#### `uv` — uv 未インストール

利用者の OS に合わせて uv のインストール手順を案内する。公式手順は https://docs.astral.sh/uv/getting-started/installation/ を参照する。

#### `uv_project` — `pyproject.toml` 未作成

AI が以下を直接実行:

```bash
uv init
```

#### `automation_package` — automation パッケージ未導入

AI が以下を直接実行:

```bash
uv add git+https://github.com/daiki-beppu/youtube-automation.git
```

#### `skills_synced` — スキル未展開

`yt-doctor` の `next_action` に従う。

- `next_action.kind == "ai-exec"` の場合は `next_action.cmd` をそのまま Bash で実行する
- `next_action.kind == "human"` の場合は `next_action.instructions` を **[HUMAN STEP]** として利用者に依頼する

初回展開や同梱 skill 不足時は以下を実行する:

```bash
uv run yt-skills sync --asset skills --force
uv run yt-skills sync --asset claude-md
uv run yt-skills sync --asset auth-template
uv run yt-setup-dirs
```

旧 `/onboard` が残存している場合は、通常の `--force` sync では削除されないため、`yt-doctor` の `next_action.cmd` に従って以下を実行する:

```bash
uv run yt-skills sync --asset skills --force --prune --yes
```

`.agents/skills` が `.claude/skills` を指す symlink になっていない warning の場合は、`next_action.instructions` の内容を手動手順として案内する。実行または手動作業の完了後は、必ず `uv run yt-doctor --json` を再実行して `skills_synced` の状態を確認する。

### api カテゴリ

#### `gcloud` — gcloud CLI 未インストール

macOS なら以下を案内 (AI が Bash で叩いてもよい):

```bash
brew install --cask google-cloud-sdk
```

その他 OS は https://cloud.google.com/sdk/docs/install を案内。

#### `gcloud_account` — gcloud 未ログイン

**[HUMAN STEP]** で依頼:

```
> あなたのターミナルで以下を実行してください:
>   gcloud auth login
> ブラウザでログインしてください。完了したら "done" と返してください。
```

#### `gcp_project` — GCP プロジェクト未確定

利用者に既存流用か新規作成か聞く:

- 既存流用: project ID を聞いて `gcloud config set project <project-id>` と `gcloud auth application-default set-quota-project <project-id>` を実行（`.env` への `GOOGLE_CLOUD_PROJECT` 書き込みは不要。project_id は ADC quota project から自動解決される）
- 新規作成: チャンネル情報から推奨 project ID と表示名を生成し、利用者に提示して承認またはカスタム入力を求める

新規作成時の推奨値:

- チャンネル名: `config/channel/meta.json` の `channel.name` が存在すればそれを使う。未設定の場合は `<channel_dir>` のベースネームを title case 化して使う (例: `lofi-beats` -> `Lofi Beats`)
- project ID: `yt-{channel-slug}`。`channel-slug` はチャンネル名を kebab-case 化し、英小文字・数字・ハイフン以外をハイフンに置換、連続ハイフンを 1 個に畳み、先頭末尾のハイフンを削る
- project ID は GCP 制約に合わせて 6-30 文字、英小文字開始、英小文字/数字/ハイフン終端に収める。30 文字を超える場合は `yt-` を含めて 30 文字以内に truncate し、短すぎる/空になる場合はカスタム入力を求める
- project 表示名 (`--name`): `{チャンネル名} YouTube` (例: `Lo-Fi Beats YouTube`)

利用者には「推奨 project ID は `<suggested-project-id>`、表示名は `<channel-name> YouTube`。この ID で作成してよいか、またはカスタム project ID を入力してください」と確認する。project ID はグローバルユニークなので、作成失敗時は別 ID を聞いてリトライする。

承認またはカスタム入力で project ID が決まったら、AI が以下を実行:

```bash
gcloud projects create <project-id> --name="<channel-name> YouTube"
gcloud config set project <project-id>
gcloud auth application-default set-quota-project <project-id>
```

#### `billing_linked` — billing 未紐付け

AI が以下を順に実行:

1. `gcloud beta billing accounts list --format=json` で利用可能 billing account を取得
2. `open: true` のものだけを表で利用者に提示し、どれを使うか選ばせる
3. 選択された ID で:

```bash
gcloud beta billing projects link <project-id> --billing-account=<billing-id>
```

billing account が 1 つも無い利用者には、Console URL (`https://console.cloud.google.com/billing`) を提示して billing account 自体の作成を依頼。

#### `apis_enabled` — 必須 API 未有効

AI が以下を直接実行:

```bash
gcloud services enable youtube.googleapis.com youtubeanalytics.googleapis.com aiplatform.googleapis.com generativelanguage.googleapis.com --project=<project-id>
```

billing 未紐付けで失敗する場合は `billing_linked` に戻る。

#### `adc` — Application Default Credentials 未設定

**[HUMAN STEP]** で依頼:

```
> あなたのターミナルで以下を実行してください:
>   gcloud auth application-default login
> ブラウザでログインしてください。完了したら "done" と返してください。
```

#### `adc_quota_project` — ADC quota project 不一致

AI が以下を直接実行:

```bash
gcloud auth application-default set-quota-project <project-id>
```

#### `iam_aiplatform_user` — Vertex AI 権限未付与

AI が以下を直接実行 (active アカウントは `gcloud auth list` で取得):

```bash
gcloud projects add-iam-policy-binding <project-id> \
  --member=user:<active-account> \
  --role=roles/aiplatform.user \
  --condition=None \
  --quiet
```

#### `env_file` — `.env` 未生成または不足キー

AI が `<channel_dir>/.env` に以下を書き込む (既存値は保持):

```
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_LOCATION=us-central1
```

`us-central1` はデフォルト。利用者が別リージョンを希望すれば差し替える。`GOOGLE_CLOUD_PROJECT` は ADC quota project から自動解決されるため通常は書き込み不要（明示したい場合のみ任意 override として追加）。

#### `client_secrets` — OAuth クライアント秘密ファイル未配置

**[HUMAN STEP]** で依頼 (`yt-doctor` の `next_action.url` をそのまま使う):

HUMAN STEP を出す前に、`gcp_project` と同じルールでチャンネル名を解決し、以下の推奨名をメッセージに含める:

- Google Auth Platform > Branding のアプリ名: `{チャンネル名} YouTube Automation` (例: `Lo-Fi Beats YouTube Automation`)
- OAuth クライアント ID 名: `{チャンネル名} Desktop Client` (例: `Lo-Fi Beats Desktop Client`)

```
> [HUMAN STEP]
> OAuth クライアント ID は Google Cloud Console でしか作成できません。
>
> 以下の URL を開いてください:
>   https://console.cloud.google.com/apis/credentials?project=<project-id>
>
> 推奨入力値:
>   - Google Auth Platform > Branding のアプリ名: <channel-name> YouTube Automation
>   - OAuth クライアント ID 名: <channel-name> Desktop Client
>
> 手順:
>   1. 左メニューで「Google Auth Platform」を開く
>   2. 「Branding」でアプリ名に上記の推奨アプリ名を入力し、ユーザーサポートメールと
>      デベロッパー連絡先には自分の Google アカウントを入れて保存
>   3. 「Audience」で User type は「External」、Publishing status は「Testing」のまま、
>      「Test users」に OAuth 認証でログインする Google アカウントを追加
>      （未追加だと初回認証が 403 access_denied で止まります）
>   4. 「Clients」→「Create client」で Application type「Desktop app」を選び、
>      名前には上記の推奨 OAuth クライアント ID 名を入力
>   5. 作成した client を開き、「Client secrets」→「Add secret」で新しい secret を発行
>   6. auth/client_secrets.template.json をコピーし、client_id / project_id / client_secret を転記して、以下のパスに配置:
>      <channel_dir>/auth/client_secrets.json
>
> 完了したら "done" と返してください。
```

利用者が "done" と返したら `uv run yt-doctor --json` で `client_secrets` が `ok` になるか確認。なっていなければエラー詳細を見せてリトライ。

#### `oauth_token` — OAuth トークン未取得

AI が以下を Bash で直接実行 (loopback redirect 方式なので別プロセスでも完結する):

```bash
uv run yt-channel-status
```

初回はブラウザが開いて認証が走る。完了すると `<channel_dir>/auth/token.json` が生成される。

### channel カテゴリ

#### `channel_config` — チャンネル設定未ロード

`yt-doctor` の `next_action.instructions` を確認:

- **`/channel-new` 案内** (config/channel/ ディレクトリ未存在): 新規チャンネルの場合は `/channel-new` を実行して設定を作成する
- **`/channel-import` 案内** (ディレクトリ存在・ロード失敗): 既存チャンネルの config を持ち込む場合は `/channel-import` を実行して設定を修復する

AI は config をここで生成しない。`yt-setup-dirs` で setup 用ディレクトリが作成済みでも `config/channel/*.json` は未生成で正常な中間状態として扱う。`yt-doctor` の `message` に含まれるエラー詳細をそのまま利用者に示し、どちらのルートかを確認してから案内する。

### data カテゴリ

#### `analytics_report` — `/wf-new` 入力モード状態

`reports/analysis_*.md` が存在しないこと自体は setup のブロッカーにしない。`yt-doctor` の message に表示される入力モードを確認する:

- `reports/analysis_*.md` が存在し、stale ではない → analytics mode
- `reports/analysis_*.md` が無く、`data/benchmark_*.json` がある → benchmark fallback mode
- `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも無い → minimal mode

ただし `reports/analysis_*.md` が最新 `data/analytics_data_*.json` より古い場合は stale report として fail になる。fallback せず、`/analytics-analyze` 再実行を案内する。

#### `benchmark_data` — ベンチマークデータ状態

benchmark の有無は analytics report の有無より優先しない:

- fresh `reports/analysis_*.md` がある → benchmark の有無に関係なく analytics mode
- `reports/analysis_*.md` が無く、`data/benchmark_*.json` がある → benchmark fallback mode
- `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも無い → minimal mode

minimal mode / benchmark fallback mode は新規チャンネル初回制作を始めるための許容状態であり、setup の完了を止めない。

#### `ttp_wf_new_readiness` — 承認済み TTP の `/channel-setup` benchmark 反映状態

`benchmark.channels` に承認済み TTP 対象がある場合だけ、初回 `/wf-new` 前に `/channel-setup` の benchmark 反映が完了しているか確認する。`yt-doctor` の `message` に `/channel-setup benchmark 反映未完了` が含まれる場合は、以下を案内する:

- `/channel-setup` の benchmark 反映ステップを再実行する
- `data/benchmark_*.json`、`docs/benchmarks/*.md`、`data/thumbnail_compare/benchmark/` の参照画像を揃える
- `config/skills/thumbnail.yaml::reference_images.default` に `data/thumbnail_compare/benchmark/...` の相対パスを転記する
- 完了後に `uv run yt-doctor --json` を再実行し、`ttp_wf_new_readiness` が ok になることを確認する

`benchmark.channels` 未設定の場合は minimal mode として扱われるため、setup の完了を止めない。

### upload カテゴリ

#### `upload_ready` — アップロード可能状態未達

`yt-doctor` の `message` に含まれる事由を確認する。

scope 不足の場合は **[HUMAN STEP]** で依頼:

```
> [HUMAN STEP]
> OAuth token に upload 必須 scope が不足しています。以下の手順で再認証してください:
>   1. <channel_dir>/auth/token.json を削除
>   2. uv run yt-channel-status を実行してブラウザ認証
>   3. OAuth 同意画面で youtube / youtube.force-ssl scope を含むアカウントを選択
> 完了したら "done" と返してください。
```

channel_id 未設定の場合は AI が以下を確認・案内:

1. `uv run yt-channel-status` を Bash で実行してチャンネル ID を取得
2. 取得した ID を `config/channel/meta.json` の `channel.channel_id` に書き込む

## 完了時

`uv run yt-doctor --json` で `summary.next_check_id` が `null` (全 check 緑) になったら:

```
✓ setup 完了。
  - automation ツールと同期済みスキルが利用できます
  - GCP / OAuth / ADC の API 認証が通ります
  - 動画アップロードに必要な OAuth scope と channel_id が揃っています
  新規チャンネルを作る場合は、次に /channel-new を実行してください。
```

を表示して終了。

## 関連スキル

- `/channel-new`: 新規チャンネルの TTP 対象確認、config 生成、ペルソナ、branding (`channel_config` fail・新規チャンネルの場合)
- `/channel-import`: 既存チャンネル設定の取り込み (`channel_config` fail・既存 config ありの場合)
- `/channel-status`: OAuth token 生成とチャンネル ID 確認
- `/wf-new`: config 作成後の新規コレクション制作開始

## 上級者向け: terraform ルート

複数チャンネルを横断管理したい / 別 PC へ引っ越したい / GCP 側の drift を検出したい場合は `infra/terraform/gcp/` の README を参照。tfstate で構成管理できる代わりに `terraform.tfvars` 編集の 1 ステップが増える。

AI が tfvars を Write して `.claude/skills/channel-setup/references/gcp-terraform-apply.sh --auto-approve` を Bash で叩けば自動化可能。Google Auth Platform の Branding / Audience Test users / Clients 設定と `client_secrets.json` 配置は両ルート共通。
