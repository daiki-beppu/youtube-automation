---
name: onboard
description: Use when GCP / OAuth まわりの API 設定を新規にセットアップしたい、または既存セットアップを再診断したいとき。「オンボーディング」「セットアップして」「API 設定して」「環境構築」「gcloud 設定」「OAuth 設定」「`/onboard`」など。AI が `yt-doctor` で状態を診断し、次に必要な 1 アクションだけを案内する wizard。新規チャンネル開設時はもちろん、別 PC への引っ越し、ADC 切れ、`client_secrets.json` の作り直しなど、API 設定だけを再整備したいときの単独入口としても使う。
---

## Overview

このスキルは **AI が指揮を取る API 設定 wizard** である。`yt-doctor --json` を都度叩いて状態を取得し、`summary.next_check_id` が指す未完了 check に対して **1 ステップだけ** 進行する。

利用者は GCP / OAuth に不慣れな前提。AI ができる作業は AI が直接 Bash で実行し、AI にできない 3 ステップ (後述) だけ利用者に依頼する。

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

- 既存流用: project ID を聞いて `.env` の `GOOGLE_CLOUD_PROJECT` に書き込む
- 新規作成: project ID を聞いて (英数字・ハイフン、6-30 文字、グローバルユニーク) AI が以下を実行:

```bash
gcloud projects create <project-id> --name="<project-id>"
```

その後 `gcloud config set project <project-id>` も実行し、`.env` にも反映する。

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
GOOGLE_CLOUD_PROJECT=<project-id>
GOOGLE_CLOUD_LOCATION=us-central1
```

`us-central1` はデフォルト。利用者が別リージョンを希望すれば差し替える。

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

## 完了時

`yt-doctor --json` で `summary.next_check_id` が `null` (全 check 緑) になったら:

```
✓ オンボーディング完了。次は `/channel-new` か `/channel-setup` に進めます。
```

を表示して終了。

## 関連スキル

- `/channel-new`: 新規チャンネルリポジトリ作成 + 競合発掘 (`/onboard` 完了後に実行)
- `/channel-setup`: config 生成 (`/onboard` 完了後に実行、Step 6 は `/onboard` 完了済みなら skip)
