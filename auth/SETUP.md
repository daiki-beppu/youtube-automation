# 🔐 YouTube Data API OAuth 2.0 セットアップガイド

YouTube 自動アップロードシステム用の認証設定手順です。

## 📋 前提条件
- Googleアカウント（YouTubeチャンネル所有者）
- Python 3.5+ + 必要ライブラリがインストール済み

## 💳 課金体系の変更について（2026 年〜）

2026 年以降、Google Cloud の新規アカウントは **前払い（プリペイド）制のみ** に変更され、従来の **$300 無料クレジットは Google AI Studio の API キー経由では利用不可** になった。

本リポジトリは YouTube Data API（無料枠で十分）に加えて、Gemini / Veo / Lyria など有料 API を利用する。**新規 GCP アカウントの場合、$300 クレジットは Vertex AI 経由でのみ消費可能** なため、以下の選択肢となる:

| パターン | 推奨度 | 方式 |
|---------|-------|------|
| 既存の Google アカウント / GCP プロジェクトを流用 | ⭐⭐⭐ 最簡単 | AI Studio モード（従来通り）|
| 新規 GCP アカウント + $300 クレジット活用 | ⭐⭐ 推奨 | Vertex AI モード（後述）|
| 新規アカウントで AI Studio モード | — | 前払いで入金必要 |

YouTube Data API / Analytics API は OAuth 認証で動作し、この変更の影響を受けない。

## 🚀 セットアップ手順

### Step 1: Google Cloud Console プロジェクト作成
1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 新しいプロジェクトを作成（例: "your-youtube-automation"）
3. プロジェクトを選択

### Step 2: YouTube Data API v3 有効化
1. 「APIとサービス」→「ライブラリ」
2. "YouTube Data API v3" を検索
3. 「有効にする」をクリック

### Step 3: OAuth 2.0 認証情報作成
1. 「APIとサービス」→「認証情報」
2. 「認証情報を作成」→「OAuth クライアント ID」
3. 「デスクトップアプリケーション」を選択
4. 名前を入力（例: "YouTube Auto Uploader"）
5. 「作成」をクリック

### Step 4: client_secrets.json ダウンロード
1. 作成された認証情報の「ダウンロード」ボタンをクリック
2. ダウンロードされたJSONファイルを `client_secrets.json` にリネーム
3. **チャンネルディレクトリの `auth/` 配下** (例: `~/02-yt/<channel>/auth/client_secrets.json`) に配置

> 検索順:
> 1. `CLIENT_SECRETS_DIR` 環境変数で指定されたディレクトリ
> 2. `<channel_dir>/auth/client_secrets.json` (推奨)
> 3. `<channel_dir>/automation/auth/client_secrets.json` (submodule 互換フォールバック)

### Step 5: 認証テスト実行

`yt-channel-status` などの CLI を初回実行すると OAuth フローが立ち上がります:

```bash
yt-channel-status
```

## 📁 ファイル構成
```
<channel_dir>/auth/
├── client_secrets.json          # OAuth 2.0認証情報（要作成・gitignore）
└── token.json                   # 認証トークン（自動生成・gitignore）
```

## ⚠️ セキュリティ注意事項

### 重要ファイル
- `client_secrets.json`: **絶対に公開しない**
- `token.json`: **絶対に公開しない**

### .gitignore 設定確認
```gitignore
# YouTube API認証ファイル
auth/client_secrets.json
auth/token.json
```

## 🌐 Vertex AI モードを使う場合（任意）

新規 GCP アカウントの $300 クレジットで Gemini / Veo を動かす場合、または GCP プロジェクトと AI 利用を一体化したい場合は Vertex AI モードを有効化する。

### 追加セットアップ手順

1. **Vertex AI API を有効化**
   Google Cloud Console で「APIとサービス」→「ライブラリ」→ `Vertex AI API` を検索して有効化。

2. **Application Default Credentials (ADC) の準備**
   ```bash
   gcloud auth application-default login
   gcloud config set project <your-gcp-project-id>
   ```

3. **IAM ロールの確認**
   認証したアカウントに最低 `roles/aiplatform.user` が付与されていること（プロジェクトオーナーなら付与済み）。

4. **環境変数で Vertex AI モードに切替**
   `.env` またはシェルに以下を設定:
   ```bash
   GOOGLE_GENAI_USE_VERTEXAI=true
   GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
   GOOGLE_CLOUD_LOCATION=us-central1   # 任意（デフォルト: us-central1）
   ```

5. **動作確認**
   ```bash
   uv run yt-generate-image --prompt "a gentle watercolor forest" --output /tmp/test.png -y
   ```

### 対応状況

| API | AI Studio モード | Vertex AI モード |
|-----|-----------------|------------------|
| Gemini 画像生成（サムネイル等）| ✅ | ✅ |
| Gemini 画像分析（ベンチマーク）| ✅ | ✅ |
| Veo 動画生成（ループ動画/ショート）| ✅ | ✅ |
| Lyria 音楽生成 | ✅ | ⚠️ Model Garden の提供状況次第。**Lyria を使う場合は AI Studio モード推奨** |

Lyria を使う場合で Vertex AI モードに切り替えているとき、音楽生成ステップだけ `GOOGLE_GENAI_USE_VERTEXAI=false` で実行するか、シェル別で環境変数を分ける運用を推奨。

## 🔧 トラブルシューティング

### エラー: "client_secrets.json が見つかりません"
→ Step 4 を確認。ファイルが正しい場所に配置されているか確認

### エラー: "Access blocked: This app's request is invalid"
→ OAuth同意画面の設定が必要。Google Cloud Console で設定

### エラー: "The OAuth client was not found"
→ client_secrets.json の内容が正しいか確認

### ブラウザが開かない
→ ファイアウォール設定を確認。ポート接続が許可されているか確認

### Vertex AI モードで `GOOGLE_CLOUD_PROJECT が必須です` エラー
→ `.env` に `GOOGLE_CLOUD_PROJECT=<project-id>` を設定。

### Vertex AI モードで `Permission denied` / 認証エラー
→ `gcloud auth application-default login` を実行し、認証済みアカウントに `roles/aiplatform.user` 以上が付与されているか確認

## 💡 使用後の確認事項
認証が成功すると以下が表示されます：
```
✅ OAuth 2.0 認証成功
💾 認証トークン保存完了
✅ YouTube Data API サービス接続成功  
✅ API接続テスト成功
📺 チャンネル名: Your Channel Name
👥 登録者数: XX
🎉 認証・接続テスト完了！YouTube自動アップロードの準備ができました。
```

## 📞 サポート
問題が発生した場合は、エラーメッセージを確認して上記のトラブルシューティングを参照してください。