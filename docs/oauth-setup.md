# GCP / YouTube API セットアップ

`/setup --tool` で GCP / OAuth / ADC と動画アップロードの前提を整えるための**運営者向け正本**。

> [!IMPORTANT]
> この手順は先に [`ツール導入`](tool-setup.md) を完了していることを前提とする。

skill / CLI ごとの実効 scope と read-only token の設計は [`oauth-scopes.md`](oauth-scopes.md) を参照。
ツール/API 設定後のチャンネル開設と日常運用は [`ONBOARDING.md`](../ONBOARDING.md) を参照。

## 推奨ルート: `/setup --tool` で GCP / ADC / OAuth を完了する

### 3. GCP / ADC / OAuth を完了する

setup は project 選択、Billing 紐付け、必要 API の有効化、ADC quota project、IAM、Reporting job を診断順に進める。外部の GCP 状態を変える前には、対象 project・account・実行コマンドを表示して承認を求める。

認証 CLI は setup 自身が対話 session で起動する。利用者がターミナルへ別途コマンドをコピーして実行する必要はない。

> [!IMPORTANT]
> **[HUMAN STEP]** ブラウザが開いたら、利用者本人が Google ログイン、アカウント選択、OAuth 同意を完了する。password・認可コード・token・client secret をチャットへ貼らない。

Google Auth Platform の GUI は API で自動化できないため、setup が Console URL を示したときだけ次を行う。

> [!IMPORTANT]
> **[HUMAN STEP]**
> 1. **Branding** でアプリ名、ユーザーサポートメール、デベロッパー連絡先を保存する。
> 2. **Audience** は External / Testing とし、OAuth に使う Google アカウントを Test users に追加する。
> 3. **Clients** で Desktop app client を作成する。
> 4. Client secrets で secret を追加し、**Download JSON** で保存してから setup に `done` と返す。

`done` の後は setup が次を実行し、ダウンロード済み JSON を `auth/client_secrets.json` へ配置して再診断する。

```bash
uv run yt-doctor --fix-client-secrets
uv run yt-doctor --apply --json
```

### 4. 完了を確認する

`uv run yt-doctor --apply --json` の `apply.stop_reason` が `completed` となり、次がすべて確認できれば `/setup --tool` は完了である。

- automation CLI と同期済み skill が利用できる
- GCP / OAuth / ADC の認証が通る
- 動画アップロードに必要な OAuth scope と `channel_id` が揃う

`analytics_report` の stale fail だけが残る場合は後続 skill が解消するため、ほかの check がすべて `ok` なら完了としてよい。チャンネル固有の config、TTP、persona、branding はこの手順では作らない。新規チャンネルでは次に **`/setup --channel`** を実行する。

## 上級者向け代替ルートと参照情報

推奨ルートを使わず既存 GCP project を手動管理したい場合に限り、以下の bootstrap / Terraform を使う。`client_secrets.json` の解決順、Vertex AI の project / location 解決、セキュリティ、トラブルシューティングもこの後に記載する。これらの経路は廃止しないが、初回利用者の標準手順ではない。

### ルート A: `gcp-bootstrap.sh`（gcloud 半自動化・最速）

チャンネル単位で気軽に立ち上げたいケース。1 コマンドでプロジェクト作成〜API 有効化〜IAM・ADC quota project 設定まで完結する。冪等なので再実行しても安全。

```bash
# 最小 (既存プロジェクト流用)
.claude/skills/setup/references/gcp-bootstrap.sh my-existing-project

# 新規プロジェクト作成 + Billing 紐付け
.claude/skills/setup/references/gcp-bootstrap.sh \
  --create \
  --billing-account 012345-6789AB-CDEF01 \
  my-new-yt-channel
```

主なオプション:

| オプション | 意味 |
|-----------|------|
| `--create` | プロジェクトが存在しなければ作成 |
| `--billing-account ID` | Billing account を紐付け（Vertex AI に必須） |
| `--adc-email EMAIL` | `aiplatform.user` 付与先アカウント（既定: `gcloud config account`） |
| `--skip-adc` | `gcloud auth application-default login` を省略 |
| `--dry-run` | 変更せずプレビュー |

完了時に Google Auth Platform 手動設定用の Console URL が表示されるので、Branding / Audience / Clients を設定し、`client_secrets.json` を配置する（[Google Auth Platform 手動設定](#google-auth-platform-手動設定) 参照）。

### ルート B: `infra/terraform/gcp`（宣言的 IaC・本命）

Organization 配下で統制したい、複数プロジェクトを tfstate 管理したい、将来的に変更履歴を残したいケース。

```bash
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# → project_id, adc_email, billing_account を編集

# apply
cd ../../..
.claude/skills/setup/references/gcp-terraform-apply.sh
```

`terraform.tfvars` の必須キーは `project_id` / `adc_email`。新規作成時は `billing_account` も必要（既存流用なら `create_project = false` にして不要）。

詳細は [`infra/terraform/gcp/README.md`](../infra/terraform/gcp/README.md) を参照。

ルート A / B では `client_secrets.json` の手動配置を行う。次節はその手動経路向けであり、推奨のルート 0 は `/setup` の Download JSON → `done` → `yt-doctor --fix-client-secrets` → JSON 再診断を使う。

---

## Google Auth Platform 手動設定

`gcloud` / Terraform いずれも Google Auth Platform の Branding / Audience / Clients 設定には対応していないため、ここは Console での手動作業が必要:

1. スクリプト / terraform 出力に表示された URL を開く
   - 形式: `https://console.cloud.google.com/apis/credentials?project=<PROJECT_ID>`
2. 左メニューで **Google Auth Platform** を開く
3. **Branding** でアプリ名、ユーザーサポートメール、デベロッパー連絡先を入力して保存
   - 推奨アプリ名: `<channel-name> YouTube Automation`
4. **Audience** で User type は **External**、Publishing status は **Testing** のまま保存し、**Test users** に OAuth 認証でログインする Google アカウントを追加
   - ここを忘れると、初回認証で `403 access_denied` になる
5. **Clients** → **Create client** を開き、Application type **Desktop app** を選ぶ
6. 名前を入力（推奨: `<channel-name> Desktop Client`）→ 作成
7. 作成した client を開き、**Client secrets** → **Add secret** で新しい secret を発行
8. チャンネルリポジトリの `auth/client_secrets.template.json` をコピーし、`client_id` / `project_id` / `client_secret` を転記して `client_secrets.json` として保存
   - テンプレートは `yt-skills sync --asset auth-template` で配布される（canonical source は `src/youtube_automation/infrastructure/resources/auth/client_secrets.template.json`）
9. `client_secrets.json` を **チャンネルリポジトリの `auth/` 配下**に配置
   - 推奨パス: `<channel_dir>/auth/client_secrets.json`

新 UI では client 作成後の secret 再表示に依存しない。secret が必要なときは、**Clients** → 対象 client → **Client secrets** → **Add secret** で新しい secret を発行し、テンプレートへ転記する。

`yt-channel-status` などの初回認証で `403 access_denied` が出る場合は、**Audience > Test users** にログイン中の Google アカウントが登録されているか確認し、`<channel_dir>/auth/token.json` を削除してから再実行する。

---

## <a id="client-secrets-resolution"></a>`client_secrets.json` の解決順

実装は `infrastructure/auth/youtube.py::client_secrets_file_candidates()` および `resolve_client_secrets_location()`。

`CLIENT_SECRETS_DIR` が設定されている場合は **明示 override** として扱い、そのディレクトリの `client_secrets.json` **のみ**を検査する。未配置でも他の候補や 1Password へ fallback しない。

`CLIENT_SECRETS_DIR` 未設定時は、次の順にファイルを探索する:

1. `<channel_dir>/auth/client_secrets.json`（推奨）
2. `<channel_dir>/automation/auth/client_secrets.json`（submodule 互換フォールバック）
3. `<workspace_root>/auth/client_secrets.json`
   - `channel_dir` が workspace 配下のチャンネルとして解決できる場合のみ候補に加わる
4. `<main_worktree_root>/auth/client_secrets.json`
   - git worktree では gitignore された `auth/` が複製されないため、main 作業ツリー側の実体を最後のフォールバックとして参照する（#1721）

いずれのファイルも存在しない場合は、1Password / `CLIENT_SECRETS_JSON` による secret fallback を試みる。

実行時 OAuth は secret fallback の内容を一時ファイル化して Google OAuth ライブラリへ渡す。`yt-doctor` は read-only 診断のため、fallback をメモリ上で JSON 構造だけ検査し、secret ファイルを書き出さない。

---

## 動作確認

```bash
# YouTube OAuth 初回認証（ブラウザ起動）
yt-channel-status

# Vertex AI での画像生成
uv run yt-generate-image --prompt "a gentle watercolor forest" --output /tmp/test.png -y
```

両方成功すれば完了。

## ファイル構成

```
<channel_dir>/
└── auth/
    ├── client_secrets.json          # OAuth 2.0 認証情報（要作成・gitignore）
    ├── token.json                   # 認証トークン（自動生成・gitignore）
    └── token.readonly.json          # read-only 系用トークン（任意。`uv run yt-oauth --readonly` で発行・gitignore）
```

read-only 系 skill（analytics / benchmark / channel-status 等）は `token.readonly.json`
（write scope を含まない）を優先使用し、未発行時は warning 付きで `token.json` に
フォールバックする。詳細と skill × scope 対応表は [`oauth-scopes.md`](oauth-scopes.md)。

---

## Vertex AI の project / location 解決

project ID は ADC quota project (`gcloud auth application-default set-quota-project <PROJECT_ID>`) を標準とする。明示 override が必要な実行だけ `GOOGLE_CLOUD_PROJECT=<id>` を process env で渡す。

アプリ側 (`create_genai_client()`) は `utils/google_cloud_project.resolve_project_id()` を介して process env → ADC の順で project ID を解決し、常に `vertexai=True` で初期化する。location は Gemini / Veo / Lyria の用途別にアプリが決定し、利用者は設定しない。

### 対応 API

Vertex AI で以下を利用する。`aiplatform.googleapis.com` が有効化されていれば追加設定不要。

| API | 用途 |
|-----|------|
| Gemini 画像生成 | サムネイル等 |
| Gemini 画像分析 | ベンチマーク / 競合調査 |
| Veo 動画生成 | ループ動画 / ショート |
| Lyria 3 音楽生成（`lyria-3-pro-preview` / `lyria-3-clip-preview`）| 楽曲生成（[公式ドキュメント](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/lyria/lyria-3)） |

---

## セキュリティ注意事項

- `auth/client_secrets.json`: **絶対に公開しない**（gitignore 済み）
- `auth/token.json` / `auth/token.readonly.json`: **絶対に公開しない**（gitignore 済み）
- `infra/terraform/gcp/terraform.tfvars`: **絶対に公開しない**（gitignore 済み）

---

## トラブルシューティング

### bootstrap/terraform 共通

#### `Permission denied` / 認証エラー
`gcloud auth application-default login` で ADC を更新。必要なら quota project を固定:
```bash
gcloud auth application-default set-quota-project <project-id>
```

#### `roles/aiplatform.user` 付与でエラー
IAM 付与権限がない。Organization / Project オーナー権限を持つアカウントで実行すること。

#### プロジェクト作成上限に達した
GCP のプロジェクト作成は 1 アカウントあたり上限あり（初期は少ない）。不要プロジェクトを削除するか、上限緩和申請。

#### `billingEnabled` エラー（Vertex AI / aiplatform 有効化時）
Billing account が紐付いていない。`--billing-account` を渡して再実行するか、Console で紐付け。

### bootstrap 固有

#### `project-id が複数指定されました`
位置引数として project-id を渡せるのは 1 つだけ。フラグの前後を確認。

### terraform 固有

#### `already exists but is not managed by this terraform configuration`
プロジェクト ID がグローバルで衝突している。`project_id` を別名に変えるか、`create_project = false` で既存流用。

#### `Error 400: ... not enabled for billing`
`aiplatform.googleapis.com` には Billing が必須。`billing_account` を正しく指定。

### YouTube OAuth 固有

#### `client_secrets.json が見つかりません`
[Google Auth Platform 手動設定](#google-auth-platform-手動設定) と [`client_secrets.json` の解決順](#client-secrets-resolution) を確認。ファイル配置先を見直す。

#### `Access blocked: This app's request is invalid`
Google Auth Platform の設定が不足している。**Branding** の連絡先、**Audience > Test users**、**Clients** の Desktop app client を確認する。

#### `The OAuth client was not found`
`client_secrets.json` の内容が壊れている。**Clients** で対象 client を開き、必要なら **Add secret** で新しい secret を発行して `client_secrets.json` を作り直す。

#### ブラウザが開かない
ファイアウォール設定 / ポート接続を確認。
