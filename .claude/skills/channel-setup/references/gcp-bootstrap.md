# GCP / Vertex AI ブートストラップ

新チャンネル用の GCP プロジェクト + API + 認証情報を用意するためのリファレンス。
`/channel-new` / `/channel-setup` から共通参照する。

上流リポジトリ (`daiki-beppu/youtube-automation`、PyPI 配布名は `youtube-channels-automation`) の `auth/SETUP.md` と `infra/terraform/gcp/README.md` が詳細版。このリファレンスは **スキルが実行するときの判断材料** に絞ってある。

## 意思決定: どのルートで立ち上げるか

```
┌─ 既存 GCP プロジェクトをそのまま流用したい?
│  ├─ Yes → ルート A (bootstrap.sh、--create なし)
│  └─ No
│     ├─ tfstate で構成管理したい or Organization 統制必須?
│     │  ├─ Yes → ルート B (terraform)
│     │  └─ No → ルート A (bootstrap.sh、--create 付き)
```

- **ルート A** (`.claude/skills/channel-setup/references/gcp-bootstrap.sh`): 最速。gcloud を順次叩くだけの冪等シェル。
- **ルート B** (`infra/terraform/gcp/`): 宣言的 IaC。複数環境・多人数運用向け。

## 実行コマンド

### ルート A: bootstrap.sh

チャンネルリポジトリから実行する場合（yt-skills sync 配布後のパスを使う）:

```bash
SKILL_REF="$(git rev-parse --show-toplevel)/.claude/skills/channel-setup/references"

# 新規作成 (Billing account を渡す)
bash "$SKILL_REF/gcp-bootstrap.sh" \
  --create \
  --billing-account <BILLING_ACCOUNT_ID> \
  <PROJECT_ID>

# 既存流用
bash "$SKILL_REF/gcp-bootstrap.sh" <PROJECT_ID>
```

冪等なので何度再実行しても安全。ドライランは `--dry-run`。

### ルート B: terraform

```bash
SKILL_REF="$(git rev-parse --show-toplevel)/.claude/skills/channel-setup/references"

# tfvars を用意 (初回のみ)
cp "$SKILL_REF/terraform-gcp/terraform.tfvars.example" \
   "$SKILL_REF/terraform-gcp/terraform.tfvars"
# → project_id, adc_email, billing_account を編集

bash "$SKILL_REF/gcp-terraform-apply.sh" \
  --tf-dir "$SKILL_REF/terraform-gcp"
```

`gcp-terraform-apply.sh` が `terraform init && apply` → `.env` への値反映までラップする。

automation リポジトリ側では `infra/terraform/gcp/` を canonical ディレクトリとして利用できる。

## 残る手動ステップ: OAuth クライアント ID

いずれのルートでも **Google Auth Platform での Branding / Audience / Clients 設定と `client_secrets.json` 配置は Console での手動作業として残る**（gcloud / Terraform 双方未サポート）。

スクリプト実行後に出力される URL を開き:
1. 左メニューで **Google Auth Platform** を開く
2. **Branding** でアプリ名、ユーザーサポートメール、デベロッパー連絡先を入力して保存
3. **Audience** で User type は **External**、Publishing status は **Testing** のまま保存し、**Test users** に OAuth 認証でログインする Google アカウントを追加
   - ここを忘れると、初回認証で `403 access_denied` になる
4. **Clients** → **Create client** を開き、Application type **Desktop app** を選ぶ
5. 名前を入力（推奨: `<channel-name> Desktop Client`）→ 作成
6. 作成直後に表示される client secret を控えるか JSON をダウンロード
7. `client_secrets.json` にリネームし、**チャンネルリポジトリの `auth/client_secrets.json`** に配置

作成直後の画面を閉じて client secret を見失った場合は、**Clients** → 対象 client → **Client secrets** → **Add secret** で新しい secret を発行し、JSON を再ダウンロードする。JSON ダウンロードが表示されない場合は `auth/client_secrets_template.json` をコピーし、`client_id` / `project_id` / `client_secret` を手入力して `client_secrets.json` として保存する。

## 前提チェック

実行前に確認すべき点:

- [ ] `gcloud` コマンドがインストール済み
- [ ] `gcloud auth login` 済み（`gcloud auth list` で ACTIVE な account がある）
- [ ] 新規作成する場合: Billing Account に対する `roles/billing.user` 以上
- [ ] 新規作成する場合: Organization or 個人アカウントでのプロジェクト作成権限

terraform ルートの場合は追加で:
- [ ] `terraform` >= 1.5
- [ ] `jq`
- [ ] `gcloud auth application-default login` で ADC も取得済み

## 失敗時のリカバリ

| 症状 | 対処 |
|------|------|
| `billingEnabled` エラーで API 有効化失敗 | `--billing-account` を付けて再実行。Console で billing 紐付けを直接確認 |
| `Permission denied` / IAM 付与で 403 | 別アカウントでログインしているケース。`gcloud auth list` で ACTIVE を確認 |
| プロジェクト作成上限エラー | 不要 project を削除、または緩和申請 |
| ADC の quota project がズレている | `gcloud auth application-default set-quota-project <id>` |
| tfstate が壊れた | `terraform.tfstate*` を削除して `terraform import` からやり直すか、bootstrap.sh ルートに切替 |

その他詳細は上流の `auth/SETUP.md` の「トラブルシューティング」節。
