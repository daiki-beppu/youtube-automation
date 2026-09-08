# GCP / YouTube API セットアップ

`/setup --tool` で GCP / OAuth / ADC と動画アップロードの前提を整えるための**運営者向け正本**。

> [!IMPORTANT]
> この手順は先に [`ツール導入`](tool-setup.md) を完了していることを前提とする。

skill / CLI ごとの実効 scope と read-only token の設計は [`oauth-scopes.md`](oauth-scopes.md) を参照。
ツール/API 設定後のチャンネル開設と日常運用は [`ONBOARDING.md`](../ONBOARDING.md) を参照。

## 推奨ルート: `/setup --tool`

### 5. GCP / ADC / OAuth を完了する

setup は GCP / ADC / OAuth / Reporting job を診断順に確認する。project / billing / API / IAM の不足は、後述の GCP 層の正本へ誘導する。GCP 層を Terraform で整えてから setup を再実行し、ADC / OAuth のローカル認証を進める。

認証 CLI は setup 自身が対話 session で起動する。利用者がターミナルへ別途コマンドをコピーして実行する必要はない。

> [!IMPORTANT]
> **[HUMAN STEP]** ブラウザが開いたら、利用者本人が Google ログイン、アカウント選択、OAuth 同意を完了する。password・認可コード・token・client secret をチャットへ貼らない。

Google Auth Platform の設定が必要なら、setup が対話 session で [OAuth client wizard](#google-auth-platform-手動設定) を起動する。利用者は wizard の入力とブラウザ操作を行い、完了後に setup が `uv run yt-doctor --apply --json` で再診断する。

### 6. 完了を確認する

`uv run yt-doctor --apply --json` の `apply.stop_reason` が `completed` となり、次がすべて確認できれば `/setup --tool` は完了である。

- automation CLI と同期済み skill が利用できる
- GCP / OAuth / ADC の認証が通る
- 動画アップロードに必要な OAuth scope と `channel_id` が揃う

`analytics_report` の stale fail だけが残る場合は後続 skill が解消するため、ほかの check がすべて `ok` なら完了としてよい。チャンネル固有の config、TTP、persona、branding はこの手順では作らない。新規チャンネルでは次に **`/setup --channel`** を実行する。

## 上級者向け代替ルートと参照情報

### GCP 層（project / billing / API / IAM）

first-party の共有 GCP 構成は、上流の [`infra/terraform/gcp/README.md`](../infra/terraform/gcp/README.md) を正本として Terraform で管理する。`yt-doctor` は GCP 層の検証と正本への誘導のみを行い、project / billing / API / IAM を変更しない。

external user は上流リポジトリを clone し、同じ README に従って自分の tfvars で apply する。Terraform 資産は下流チャンネルリポジトリへ配布しない。GCP 層の構築・変更・トラブルシューティングは上流 README、OAuth の本人操作と secret 解決順は本ガイドを参照する。

---

## Google Auth Platform 手動設定

### 操作画面を動画で確認する

初回の「開始」からアプリ情報・外部ユーザー・連絡先の保存、Test users の登録、Desktop app の作成と JSON ダウンロードまでを、日本語ナレーション・字幕付きで確認できる（約 2 分 10 秒）。画面確認日: **2026-09-08**。黄色い枠の「非表示」パネルは、メールアドレスや認証情報を隠すために動画編集で加えたもの。Google Cloud の画面には表示されない。

<video controls playsinline preload="none" width="1920" height="1080" style="display:block;width:100%;max-width:100%;height:auto;aspect-ratio:16/9" title="Google Auth Platform の設定画面と JSON ダウンロード" aria-label="Google Auth Platform の設定画面と JSON ダウンロード" poster="/media/oauth-guide/poster.jpg">
  <source src="/media/oauth-guide/oauth-guide.mp4" type="video/mp4" />
  <track kind="captions" src="/media/oauth-guide/oauth-guide.ja.vtt" srclang="ja" label="日本語" default />
  動画を再生できない場合は、この下の文章手順を参照してください。
</video>

[動画を直接開く](https://youtube-automation-release-notes.pages.dev/media/oauth-guide/oauth-guide.mp4) · [日本語字幕](https://youtube-automation-release-notes.pages.dev/media/oauth-guide/oauth-guide.ja.vtt)

動画は専用デモ環境で初期設定・テストユーザー登録・クライアント作成を実際に保存した操作例。補足の追加シークレットは、同日に別のデモクライアントで撮影した **Add secret → JSON ダウンロードの実操作**を示す。撮り直した初期設定とは別環境であることを動画の見出しにも表示する。デモの Audience は **Testing** のままで、**In production への切替は未完了**。Console にアプリ構成未完了の警告が出ているため、切替完了の例としては扱わない。実運用では下記の手順で不足するアプリ情報を確認して切り替える。JSON の配置・再診断と本人の OAuth 同意は、本文と wizard に戻って進める。

音声合成: Irodori-TTS。フリー素材キャラクター「つくよみちゃん」が無料公開している音声データ、[つくよみちゃんコーパス（CV.夢前黎）](https://tyc.rei-yumesaki.net/material/corpus/)を使用。BGM は本動画用のオリジナル曲。動画は視聴用の教材であり、音声素材としての二次利用は許可していない。

### 文章で操作を確認する

Console 操作の正本は [OAuth client wizard](../.claude/skills/setup/references/oauth-client-wizard.sh)。チャンネルリポジトリのルートで起動する:

```bash
bash .claude/skills/setup/references/oauth-client-wizard.sh
```

1. 前提確認: チャンネル名と project ID を解決し、配置済みなら終了する。
2. Branding: プロジェクト共通の固定名 `YouTube Automation` を設定する（初回のみ）。
3. Audience: External / **In production** に切り替え、unverified 警告は「詳細」からアプリへの移動を選んで続行する（初回のみ）。
4. Clients: チャンネルごとの Desktop client を用意する。
5. Secret: Download JSON の候補を確認し、doctor が `auth/client_secrets.json` に配置する。
6. 再診断: `client_secrets: ok` を確認する。`oauth_token` 取得は wizard の範囲外。

Branding / Audience が未完了の既存プロジェクトも「初めて」の経路を使う。すでに秘密ファイルが配置済みなら wizard は変更せず終了するため、既存プロジェクトの Audience 切替は wizard 内の該当 stage を参照する。
切替直後に VPS の `token_streaming` 4 チャンネル分だけ先回り再認証し、その他は自然失効に任せる。再認証は本人操作であり wizard の範囲外。

---

## <a id="client-secrets-resolution"></a>`client_secrets.json` の解決順

実装は `infrastructure/auth/youtube.py::client_secrets_file_candidates()` および `resolve_client_secrets_location()`。

`CLIENT_SECRETS_DIR` が設定されている場合は **明示 override** として扱い、そのディレクトリの `client_secrets.json` **のみ**を検査する。未配置でも他の候補や 1Password へ fallback しない。

`CLIENT_SECRETS_DIR` 未設定時は、次の順にファイルを探索する:

1. `<channel_dir>/auth/client_secrets.json`（推奨）
2. `<channel_dir>/automation/auth/client_secrets.json`（submodule 互換フォールバック）
3. `<main_worktree_root>/auth/client_secrets.json`
   - git worktree では gitignore された `auth/` が複製されないため、main 作業ツリー側の実体を最後のフォールバックとして参照する（#1721）

いずれのファイルも存在しない場合は、1Password / `CLIENT_SECRETS_JSON` による secret fallback を試みる。

実行時 OAuth は secret fallback の内容を一時ファイル化して Google OAuth ライブラリへ渡す。`yt-doctor` は read-only 診断のため、fallback をメモリ上で JSON 構造だけ検査し、secret ファイルを書き出さない。

---

## 動作確認

Claude デスクトップアプリの同じチャットへ、次を貼る。

```text
セットアップの動作確認をしてください。
1. `yt-channel-status` で YouTube OAuth の初回認証を確認してください。ブラウザでの Google ログインや同意が必要になったら、そこで止めて私に操作を依頼してください。
2. `uv run yt-generate-image --prompt "a gentle watercolor forest" --output /tmp/test.png -y` で Vertex AI の画像生成を確認してください。
3. secret や token の内容は表示せず、各確認の成否と、失敗時に次に必要な操作だけを日本語で要約してください。
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

### YouTube OAuth 固有

#### `client_secrets.json が見つかりません`
[Google Auth Platform 手動設定](#google-auth-platform-手動設定) と [`client_secrets.json` の解決順](#client-secrets-resolution) を確認。ファイル配置先を見直す。

#### `Access blocked: This app's request is invalid`
Google Auth Platform の設定が不足している。**Branding** の連絡先、**Audience > Test users**、**Clients** の Desktop app client を確認する。

#### `The OAuth client was not found`
`client_secrets.json` の内容を検査し、再発行が必要なら既存ファイルを安全に退避して [OAuth client wizard](#google-auth-platform-手動設定) を使う。

#### ブラウザが開かない
ファイアウォール設定 / ポート接続を確認。
