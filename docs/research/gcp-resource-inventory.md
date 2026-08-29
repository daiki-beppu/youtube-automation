# GCP 実リソース棚卸しと `infra/terraform/gcp/` 定義の差分 (#4715)

調査日: 2026-08-29 / 調査方法: **読み取り専用の gcloud コマンドのみ**（変更系コマンドは一切実行していない）。
調査アカウント: `beppu.engineer@gmail.com`（プロジェクト owner）。gcloud のアクティブ設定は別プロジェクト（`life-video-digest`）を向いていたため、全コマンドに `--project yt-channels-automation` を明示して実行した。

地図: #4714 / 前提 ADR: ADR-0010（単一プロジェクト統合）・ADR-0024（IaC = Terraform）。

## 1. 実リソース一覧（gcloud 実測）

### プロジェクト（`gcloud projects describe yt-channels-automation`）

| 項目 | 値 |
|---|---|
| projectId | `yt-channels-automation` |
| projectNumber | `585604716899` |
| name | `yt-channels-automation` |
| lifecycleState | `ACTIVE` |
| createTime | 2026-06-16T02:29:14Z |
| 親（org / folder） | **なし**（describe 出力に parent フィールドなし = スタンドアロン個人プロジェクト） |

### Billing（`gcloud billing projects describe` / `gcloud billing accounts describe`）

| 項目 | 値 |
|---|---|
| billingEnabled | `true` |
| billingAccount | `billingAccounts/01FBD5-B3258B-498671` |
| アカウント表示名 | `youtube-automation`（通貨 JPY、open、組織親なし） |

### 有効化済み API（`gcloud services list --enabled`、計 31 件）

Terraform 定義の 5 API は **すべて有効**:

- `youtube.googleapis.com`
- `youtubeanalytics.googleapis.com`
- `aiplatform.googleapis.com`
- `generativelanguage.googleapis.com`
- `storage.googleapis.com`

Terraform 定義外で有効な API（26 件）:

| 分類 | API |
|---|---|
| 明示有効化とみられる（用途あり） | `youtubereporting.googleapis.com`, `calendar-json.googleapis.com`, `drive.googleapis.com`, `forms.googleapis.com`, `sheets.googleapis.com` |
| BigQuery ファミリー（プロジェクト作成時の既定バンドル、または console 操作での連鎖有効化とみられる） | `bigquery.googleapis.com`, `bigqueryconnection.googleapis.com`, `bigquerydatapolicy.googleapis.com`, `bigquerydatatransfer.googleapis.com`, `bigquerymigration.googleapis.com`, `bigqueryreservation.googleapis.com`, `bigquerystorage.googleapis.com`, `analyticshub.googleapis.com`, `dataform.googleapis.com`, `dataplex.googleapis.com` |
| 新規プロジェクトの既定有効化バンドルとみられる | `cloudapis.googleapis.com`, `servicemanagement.googleapis.com`, `serviceusage.googleapis.com`, `logging.googleapis.com`, `monitoring.googleapis.com`, `cloudtrace.googleapis.com`, `telemetry.googleapis.com`, `datastore.googleapis.com`, `sql-component.googleapis.com`, `storage-api.googleapis.com`, `storage-component.googleapis.com` |

> 「既定バンドル」の分類は一般的な新規プロジェクトの挙動からの推定。確定させるには Console の有効化履歴（Activity ログ）確認が必要。

### IAM バインディング（`gcloud projects get-iam-policy`、全 3 件）

| role | member |
|---|---|
| `roles/owner` | `user:beppu.engineer@gmail.com` |
| `roles/aiplatform.user` | `user:beppu.engineer@gmail.com` |
| `roles/aiplatform.serviceAgent` | `serviceAccount:service-585604716899@gcp-sa-aiplatform.iam.gserviceaccount.com`（Vertex AI 有効化時に自動付与されるサービスエージェント） |

### その他のプロジェクト内リソース

| 種別 | 実測結果 |
|---|---|
| ユーザー作成サービスアカウント | **0 件**（`gcloud iam service-accounts list`） |
| API キー | **0 件**（`gcloud services api-keys list`） |
| GCS バケット | `youtube-automation-tfstate`（ASIA-NORTHEAST1）の **1 件のみ**。`infra/terraform/bootstrap/` スタックの管理下（ローカル tfstate 実在、serial 1、project 属性も `yt-channels-automation` を確認） |
| ADC quota project | `yt-channels-automation`（`application_default_credentials.json` の `quota_project_id`。ADR-0010 と一致） |

### OAuth クライアント — gcloud では読めない（Console 確認が必要）

- `gcloud iam oauth-clients list --location=global` → **0 件**。ただしこれは Workforce Identity Federation 用の OAuth クライアントであり、Google Auth Platform（旧 OAuth 同意画面）の Desktop クライアントとは**別物**。
- `gcloud iap oauth-brands list` → `iap.googleapis.com` が未有効のためエラー（有効化はしていない）。かつ IAP OAuth Admin API 自体が 2026-03-19 に恒久シャットダウン済みの deprecated API。
- 結論: **Google Auth Platform の Branding / Audience（テストユーザー）/ Clients 一覧（クライアント数・チャンネル対応）は gcloud で棚卸し不可。Console（`https://console.cloud.google.com/apis/credentials?project=yt-channels-automation`）での目視確認が必要。** これは #4714 の現状調査「API 非提供のため IaC 化不可」とも整合する。

## 2. `infra/terraform/gcp/` 定義と実態の差分表

前提の重要事実: **`infra/terraform/gcp/` は一度も apply されていない**。メインチェックアウトに `terraform.tfstate` も `terraform.tfvars` も存在せず（backend ブロックなし = ローカル state のみのため、state が無い = 未適用）、**定義済みリソースはすべて Terraform 管理外**。一方 `infra/terraform/bootstrap/` は apply 済み（ローカル state あり）。

| Terraform 定義（アドレス） | 定義内容 | 実態 | 差分 / 状態 |
|---|---|---|---|
| `google_project.this[0]`（`create_project=true` 時のみ） | project 作成、`deletion_policy = "DELETE"` | プロジェクト実在（2026-06-16 作成、gcloud/console 手動作成とみられる） | **state になし**。`create_project=false` 運用なら data source 参照で import 不要 |
| `data.google_project.this[0]`（`create_project=false` 時） | 既存参照 | 同上 | data source のため差分なし（apply すれば読めるはず） |
| `google_project_service.apis["youtube.googleapis.com"]` ほか計 5 | API 有効化 ×5、`disable_on_destroy=false` | 5 件とも有効 | **設定値は一致するが state 管理外** → import 対象 |
| （定義なし） | — | 上記以外の 26 API が有効 | **Terraform 定義外**。`var.apis` は柔軟なので、実運用で使う `youtubereporting` / `sheets` / `drive` / `calendar-json` / `forms` を tfvars で足すか、定義外のまま容認するかの判断が必要（既定バンドル系は定義不要） |
| `google_project_iam_member.aiplatform_user` | `roles/aiplatform.user` → `user:${var.adc_email}` | `user:beppu.engineer@gmail.com` に付与済み | **設定値は一致するが state 管理外** → import 対象 |
| （定義なし） | — | `roles/owner`（本人）、`roles/aiplatform.serviceAgent`（自動付与） | 定義外だが問題なし。`google_project_iam_member` は非権威的（additive）なので共存できる |
| （定義なし・bootstrap スタック側） | `google_storage_bucket.tfstate` | `youtube-automation-tfstate` バケット実在 | **bootstrap のローカル state で管理済み**（gcp スタックの管理外で正しい）。ただし state 自体がローカルのみ（意図的・循環依存回避、#4714 参照） |
| billing 紐付け（`google_project.this` の `billing_account` 属性） | `var.billing_account` | `01FBD5-B3258B-498671` に紐付け済み | `create_project=false` なら Terraform 管理外のまま（実害なし）。managed 化するなら tfvars に実値が必要 |

### モジュール内部の不整合（実態差分とは別の発見）

1. **`terraform.tfvars.example` が未定義変数 `location` を設定している**（`location = "us-central1"`）。`variables.tf` に `location` 変数は存在しない → example をそのままコピーすると undeclared variable の警告になる。
2. **`terraform.tfvars.example` のコメント内 `apis` リストが 4 件しかない**（`storage.googleapis.com` が漏れている）。`variables.tf` の default は 5 件で正。
3. `versions.tf` の配布側ドリフト（正本 `~> 1.15.0` / `~> 7.40` vs 配布側 `>= 1.5` / `>= 5.0, < 7.0`）は #4714 で既知のため本チケットでは再掲のみ。

## 3. import 対象リソースアドレス候補

`create_project = false`（既存流用）で state を作る場合、import が必要なのは以下の 6 リソース:

```bash
cd infra/terraform/gcp
# terraform.tfvars: project_id="yt-channels-automation", create_project=false, adc_email="beppu.engineer@gmail.com"
terraform init

terraform import 'google_project_service.apis["youtube.googleapis.com"]'            yt-channels-automation/youtube.googleapis.com
terraform import 'google_project_service.apis["youtubeanalytics.googleapis.com"]'   yt-channels-automation/youtubeanalytics.googleapis.com
terraform import 'google_project_service.apis["aiplatform.googleapis.com"]'         yt-channels-automation/aiplatform.googleapis.com
terraform import 'google_project_service.apis["generativelanguage.googleapis.com"]' yt-channels-automation/generativelanguage.googleapis.com
terraform import 'google_project_service.apis["storage.googleapis.com"]'            yt-channels-automation/storage.googleapis.com

terraform import 'google_project_iam_member.aiplatform_user' \
  'yt-channels-automation roles/aiplatform.user user:beppu.engineer@gmail.com'
```

`create_project = true`（プロジェクト自体を managed 化）まで踏み込む場合は追加で:

```bash
terraform import 'google_project.this[0]' projects/yt-channels-automation
# tfvars に billing_account = "01FBD5-B3258B-498671" が必要
# 注意: main.tf は deletion_policy = "DELETE" — 単一共有プロジェクト(ADR-0010)を
# managed 化するなら "PREVENT" への変更を検討すべき（destroy 事故で全チャンネル喪失）
```

bootstrap スタックのバケットは既にローカル state 管理下のため import 不要（GCS backend への state 移行は別論点）。

## 4. Console 確認が必要だった項目（gcloud で読めなかったもの）

| 項目 | 理由 |
|---|---|
| Google Auth Platform の Clients 一覧（OAuth クライアント数・チャンネル対応関係） | 公開 API / gcloud コマンド非提供（IAP OAuth Admin API は 2026-03 シャットダウン済み・そもそも用途違い） |
| Google Auth Platform の Branding / Audience（公開ステータス・テストユーザー一覧） | 同上 |
| 定義外 26 API の「既定有効化 vs 手動有効化」の確定 | gcloud の services list は経緯を持たない。Activity ログ or Console で確認 |

## 5. 結論（import 計画・setup skill 再編への含意）

- 実態と Terraform 定義の**設定値レベルの乖離はゼロ**（定義された 5 API と IAM 1 件はすべて実在・一致）。乖離は「**state が存在しない**」という管理状態の一点に集約される。よって import は破壊的変更なしで完了できる見込み。
- プロジェクト本体を managed 化するかは `deletion_policy` の扱いとセットで判断が必要（現定義は `DELETE` で単一共有プロジェクトには危険）。
- OAuth クライアント関連は引き続き手動領域（gcloud でも棚卸し不可を実測で確認）。IaC 化のスコープからは除外し、Console 手順の一本化（#4714 の重複 4 ファイル問題）で扱うのが妥当。
- 実運用で有効化済みの `youtubereporting` / `sheets` / `drive` / `calendar-json` / `forms` を `var.apis` に含めるかは setup skill 再編時の論点（含めるなら import 対象も同数増える）。
