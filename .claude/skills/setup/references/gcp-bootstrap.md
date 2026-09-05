# GCP / Vertex AI ブートストラップ

新チャンネル用の GCP プロジェクト + API + 認証情報を用意するためのリファレンス。
`/setup --tool` の doctor wizard が正規入口であり、この文書は手動 script ルートを選ぶ場合の補助資料とする。

通常の OAuth 手順は同じ setup owner の [`tool.md`](tool.md) が正本。このリファレンスは **上級者向け代替ルートを明示的に選ぶときの判断材料** に絞ってある。

## 意思決定: どのルートで立ち上げるか

```
┌─ 既存 GCP プロジェクトをそのまま流用したい?
│  ├─ Yes → bootstrap.sh、--create なし
│  └─ No → bootstrap.sh、--create 付き
```

- **正規ルート** (`/setup --tool`): doctor wizard が診断、承認、GCP / OAuth / ADC bootstrap を一貫して所有する。
- **手動 script** (`.claude/skills/setup/references/gcp-bootstrap.sh`): 最速。gcloud を順次叩くだけの冪等シェル。

## 実行コマンド

### bootstrap.sh

チャンネルリポジトリから実行する場合（yt-skills sync 配布後のパスを使う）:

```bash
SKILL_REF="$(git rev-parse --show-toplevel)/.claude/skills/setup/references"

# 新規作成 (Billing account を渡す)
bash "$SKILL_REF/gcp-bootstrap.sh" \
  --create \
  --billing-account <BILLING_ACCOUNT_ID> \
  <PROJECT_ID>

# 既存流用
bash "$SKILL_REF/gcp-bootstrap.sh" <PROJECT_ID>
```

冪等なので何度再実行しても安全。ドライランは `--dry-run`。

## 残る手動ステップ: OAuth クライアント ID

スクリプト実行後も **Google Auth Platform での Branding / Audience / Clients 設定は Console での手動作業として残る**（gcloud 未サポート）。

スクリプト実行後に出力される URL を開き:
1. 左メニューで **Google Auth Platform** を開く
2. **Branding** でアプリ名、ユーザーサポートメール、デベロッパー連絡先を入力して保存
3. **Audience** で User type は **External**、Publishing status は **Testing** のまま保存し、**Test users** に OAuth 認証でログインする Google アカウントを追加
   - ここを忘れると、初回認証で `403 access_denied` になる
4. **Clients** → **Create client** を開き、Application type **Desktop app** を選ぶ
5. 名前を入力（推奨: `<channel-name> Desktop Client`）→ 作成
6. 作成した client を開き、**Client secrets** → **Add secret** で secret を発行
7. **Client secrets > Download JSON** を押して Downloads に保存し、`done` と返す
8. `uv run yt-doctor --fix-client-secrets` を実行して、ダウンロードした JSON をチャンネルリポジトリの `auth/client_secrets.json` へ配置
9. `uv run yt-doctor --json` を実行し、`client_secrets` が `ok` になることを確認

client secret を見失った場合は、**Clients** → 対象 client → **Client secrets** → **Add secret** で新しい secret を発行し、**Download JSON** から再取得して同じ手順を実行する。

## 前提チェック

実行前に確認すべき点:

- [ ] `gcloud` コマンドがインストール済み
- [ ] `gcloud auth login` 済み（`gcloud auth list` で ACTIVE な account がある）
- [ ] 新規作成する場合: Billing Account に対する `roles/billing.user` 以上
- [ ] 新規作成する場合: Organization or 個人アカウントでのプロジェクト作成権限

## 失敗時のリカバリ

| 症状 | 対処 |
|------|------|
| `billingEnabled` エラーで API 有効化失敗 | `--billing-account` を付けて再実行。Console で billing 紐付けを直接確認 |
| `Permission denied` / IAM 付与で 403 | 別アカウントでログインしているケース。`gcloud auth list` で ACTIVE を確認 |
| プロジェクト作成上限エラー | 不要 project を削除、または緩和申請 |
| ADC の quota project がズレている | `gcloud auth application-default set-quota-project <id>` |

OAuth の正規 wizard と失敗時の再診断は [`tool.md`](tool.md) を参照。
