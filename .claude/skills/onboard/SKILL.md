---
name: onboard
description: "Use when GCP / OAuth まわりの API 設定を新規にセットアップしたい、または既存セットアップを再診断したいとき。「オンボーディング」「セットアップして」「API 設定して」「環境構築」「gcloud 設定」「OAuth 設定」「`/onboard`」など。AI が `yt-doctor` で状態を診断し、次に必要な 1 アクションだけを案内する wizard。新規チャンネル開設時はもちろん、別 PC への引っ越し、ADC 切れ、`client_secrets.json` の作り直しなど、API 設定だけを再整備したいときの単独入口としても使う。"
---

## Overview

このスキルは **AI が指揮を取る API 設定 wizard** である。`yt-doctor --json` を都度叩いて状態を取得し、`summary.next_check_id` が指す未完了 check に対して **1 ステップだけ** 進行する。

利用者は GCP / OAuth に不慣れな前提。AI ができる作業は AI が直接 Bash で実行し、AI にできない 3 ステップ (後述) だけ利用者に依頼する。

### カテゴリ別チェック構成

`yt-doctor` は診断を 4 カテゴリで段階表示する:

| カテゴリ | 内容 |
|---------|------|
| `api` | gcloud CLI・GCP プロジェクト・Billing・APIs・ADC・IAM・.env・OAuth 認証（11 check） |
| `channel` | config/channel/ のロード可能性（1 check） |
| `data` | /wf-new の入力モード判定データ（analytics_report / benchmark_data）（2 check） |
| `upload` | upload 必須 scope 充足・channel_id 設定済み（1 check） |

全 check 緑 = stale ではない analytics mode / benchmark fallback mode / minimal mode のいずれかで `/wf-new` が走り出せ、かつ動画アップロードまで通る状態。

## 起動時のチェック

1. `yt-doctor --json` を Bash で実行し、結果を読む
2. `summary.next_check_id` が `null` なら「全 check 緑です。`/onboard` は完了済みです」と報告して終了
3. `null` でないなら、その check に対応する手順 (§Steps) に進む
4. 1 ステップ完了したら、必ず `yt-doctor --json` を再実行して進捗確認してから次の `next_check_id` に移る

## AI が絶対に Bash で叩かないコマンド

以下は PKCE フローが Claude Code (非対話セッション) では完結しないため、AI が直接実行してはならない。必ず **[HUMAN STEP]** として利用者に依頼する:

- `gcloud auth login`
- `gcloud auth application-default login`

これらを AI が呼ぶと「認可コードを渡しても新しい URL が出る」無限ループに陥る (詳細: PKCE の `code_verifier` が同一プロセスでしか保持できないため)。

加えて、**OAuth クライアント ID 作成** (Google Cloud Console GUI 操作) は gcloud / Terraform に該当 API が存在しないため、これも `[HUMAN STEP]` で依頼する。

## [HUMAN STEP] の書き方

利用者に手動操作を依頼するときは、必ず以下の形式で投げて停止する:

```
> [HUMAN STEP]
> あなたのターミナルで以下を実行してください:
>   gcloud auth login
> 完了したら "done" と返してください。
```

利用者が "done" と返すまで、次の Bash ツール呼び出しはしない。返ってきたら `yt-doctor --json` を再実行して結果を確認する。

## Steps (check id ごとの対応手順)

各 step は `yt-doctor` の check id にマップする。AI は `next_check_id` の値を見て該当 step に飛ぶ。

### `gcloud` — gcloud CLI 未インストール

macOS なら以下を案内 (AI が Bash で叩いてもよい):

```
brew install --cask google-cloud-sdk
```

その他 OS は https://cloud.google.com/sdk/docs/install を案内。

### `gcloud_account` — gcloud 未ログイン

**[HUMAN STEP]** で依頼:

```
> あなたのターミナルで以下を実行してください:
>   gcloud auth login
> ブラウザでログインしてください。完了したら "done" と返してください。
```

### `gcp_project` — GCP プロジェクト未確定

利用者に既存流用か新規作成か聞く:

- 既存流用: project ID を聞いて `gcloud config set project <project-id>` と `gcloud auth application-default set-quota-project <project-id>` を実行（`.env` への `GOOGLE_CLOUD_PROJECT` 書き込みは不要 — project_id は ADC quota project から自動解決される）
- 新規作成: project ID を聞いて (英数字・ハイフン、6-30 文字、グローバルユニーク) AI が以下を実行:

```bash
gcloud projects create <project-id> --name="<project-id>"
gcloud config set project <project-id>
gcloud auth application-default set-quota-project <project-id>
```

### `billing_linked` — billing 未紐付け

AI が以下を順に実行:

1. `gcloud beta billing accounts list --format=json` で利用可能 billing account を取得
2. `open: true` のものだけを表で利用者に提示し、どれを使うか選ばせる
3. 選択された ID で:

```bash
gcloud beta billing projects link <project-id> --billing-account=<billing-id>
```

billing account が 1 つも無い利用者には、Console URL (`https://console.cloud.google.com/billing`) を提示して billing account 自体の作成を依頼。

### `apis_enabled` — 必須 API 未有効

AI が以下を直接実行:

```bash
gcloud services enable youtube.googleapis.com youtubeanalytics.googleapis.com aiplatform.googleapis.com generativelanguage.googleapis.com --project=<project-id>
```

billing 未紐付けで失敗する場合は `billing_linked` に戻る。

### `adc` — Application Default Credentials 未設定

**[HUMAN STEP]** で依頼:

```
> あなたのターミナルで以下を実行してください:
>   gcloud auth application-default login
> ブラウザでログインしてください。完了したら "done" と返してください。
```

### `adc_quota_project` — ADC quota project 不一致

AI が以下を直接実行:

```bash
gcloud auth application-default set-quota-project <project-id>
```

### `iam_aiplatform_user` — Vertex AI 権限未付与

AI が以下を直接実行 (active アカウントは `gcloud auth list` で取得):

```bash
gcloud projects add-iam-policy-binding <project-id> \
  --member=user:<active-account> \
  --role=roles/aiplatform.user \
  --condition=None \
  --quiet
```

### `env_file` — `.env` 未生成または不足キー

AI が `<channel_dir>/.env` に以下を書き込む (既存値は保持):

```
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_LOCATION=us-central1
```

`us-central1` はデフォルト。利用者が別リージョンを希望すれば差し替える。`GOOGLE_CLOUD_PROJECT` は ADC quota project から自動解決されるため通常は書き込み不要（明示したい場合のみ任意 override として追加）。

### `client_secrets` — OAuth クライアント秘密ファイル未配置

**[HUMAN STEP]** で依頼 (`yt-doctor` の `next_action.url` をそのまま使う):

```
> [HUMAN STEP]
> OAuth クライアント ID は Google Cloud Console でしか作成できません。
>
> 以下の URL を開いてください:
>   https://console.cloud.google.com/apis/credentials?project=<project-id>
>
> 手順:
>   1. 「+ 認証情報を作成」→「OAuth クライアント ID」
>   2. (初回のみ)「OAuth 同意画面の設定」を求められたら、ユーザータイプ「外部」を選んで
>      アプリ名と連絡先メールだけ入力して保存。テストユーザーに自分のメールを追加する
>   3. アプリの種類: 「デスクトップアプリ」を選択
>   4. 作成後、JSON をダウンロードして以下のパスに配置:
>      <channel_dir>/auth/client_secrets.json
>
> 完了したら "done" と返してください。
```

利用者が "done" と返したら `yt-doctor --json` で `client_secrets` が `ok` になるか確認。なっていなければエラー詳細を見せてリトライ。

### `oauth_token` — OAuth トークン未取得

AI が以下を Bash で直接実行 (loopback redirect 方式なので別プロセスでも完結する):

```bash
yt-channel-status
```

初回はブラウザが開いて認証が走る。完了すると `<channel_dir>/auth/token.json` が生成される。

---

## channel カテゴリ

### `channel_config` — チャンネル設定未ロード

`yt-doctor` の `next_action.instructions` を確認:

- **`/channel-new` 案内** (config/channel/ ディレクトリ未存在): 新規チャンネルの場合は `/channel-new` を実行して設定を作成する
- **`/channel-import` 案内** (ディレクトリ存在・ロード失敗): 既存チャンネルの config を持ち込む場合は `/channel-import` を実行して設定を修復する

AI は `yt-doctor` の `message` に含まれるエラー詳細をそのまま利用者に示し、どちらのルートかを確認してから案内する。

---

## data カテゴリ

`/wf-new` は内部で `/collection-ideate` を呼び、analytics レポートとベンチマークデータの有無で入力モードを選ぶ。analytics / benchmark が未生成でも `/wf-new` は minimal mode で開始できるため、本カテゴリは中断条件ではなく開始モードの説明として扱う。

### `analytics_report` — analytics レポート状態

`yt-doctor` が `ok` を返す場合:

- `reports/analysis_*.md` があり、最新 `data/analytics_data_*.json` より古くない → analytics mode
- 無いが `data/benchmark_*.json` がある → benchmark fallback mode
- どちらも無い → minimal mode

`reports/analysis_*.md` が最新 `data/analytics_data_*.json` より古い場合は `fail`。`yt-doctor` の `next_action.instructions` に従い、`/analytics-analyze`（必要なら先に `/analytics-collect`）を案内する。

利用者が analytics mode の精度を明示的に求めた場合だけ、`/analytics-collect` → `/analytics-analyze` を案内する。`/analytics-analyze` は AI 推論コストが発生するため AI が自動実行しない。

### `benchmark_data` — ベンチマークデータ状態

`yt-doctor` が `ok` を返す場合:

- fresh `reports/analysis_*.md` がある → benchmark の有無に関係なく analytics mode。benchmark が無い場合も `/collection-ideate` 側が `/benchmark` の鮮度確認・必要時更新を扱う
- `reports/analysis_*.md` が無く、`data/benchmark_*.json` がある → benchmark fallback mode の入力として使える
- `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも無い → minimal mode で開始できる

利用者がベンチマーク込みの初回企画を明示的に求めた場合だけ `/benchmark` を案内する。analytics mode では `/collection-ideate` 側が `/benchmark` の鮮度確認・必要時更新を扱う。

---

## upload カテゴリ

### `upload_ready` — アップロード可能状態未達

`yt-doctor` の `message` に含まれる事由を確認する:

#### scope 不足の場合

**[HUMAN STEP]** で依頼:

```
> [HUMAN STEP]
> OAuth token に upload 必須 scope が不足しています。以下の手順で再認証してください:
>   1. <channel_dir>/auth/token.json を削除
>   2. yt-channel-status を実行してブラウザ認証
>   3. OAuth 同意画面で youtube / youtube.force-ssl scope を含むアカウントを選択
> 完了したら "done" と返してください。
```

#### channel_id 未設定の場合

AI が以下を確認・案内:

1. `yt-channel-status` を Bash で実行してチャンネル ID を取得
2. 取得した ID を `config/channel/meta.json` の `channel.channel_id` に書き込む

---

## 完了時

`yt-doctor --json` で `summary.next_check_id` が `null` (全 check 緑) になったら:

```
✓ オンボーディング完了。
  - /wf-new が即中断せず企画フェーズから走り出せる状態です
  - 動画アップロードに必要な OAuth scope と channel_id が揃っています
  次は /wf-new で新しいコレクションの企画を始めましょう。
```

を表示して終了。

## 関連スキル

- `/channel-new`: 新規チャンネルリポジトリ作成 + 競合発掘 (`channel_config` fail 時に実行)
- `/channel-import`: 既存チャンネル設定の取り込み (`channel_config` fail・既存 config ありの場合)
- `/analytics-collect`: YouTube Analytics データ収集（analytics mode の精度が必要なときに案内）
- `/analytics-analyze`: Analytics データ分析・レポート生成（analytics mode の精度が必要なときに案内）
- `/benchmark`: ベンチマークデータ生成（benchmark fallback mode の入力が必要なときに案内）
- `/wf-new`: 新規コレクション制作開始 (`/onboard` 完了後に実行)
- `/channel-setup`: config 生成 (`/onboard` 完了後に実行、Step 6 は `/onboard` 完了済みなら skip)

## 上級者向け: terraform ルート

複数チャンネルを横断管理したい / 別 PC へ引っ越したい / GCP 側の drift を検出したい場合は `infra/terraform/gcp/` の README を参照。tfstate で構成管理できる代わりに `terraform.tfvars` 編集の 1 ステップが増える。

AI が tfvars を Write して `.claude/skills/channel-setup/references/gcp-terraform-apply.sh --auto-approve` を Bash で叩けば自動化可能。OAuth クライアント ID の手動配置は両ルート共通。
