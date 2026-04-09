# 🔐 YouTube Data API OAuth 2.0 セットアップガイド

YouTube 自動アップロードシステム用の認証設定手順です。

## 📋 前提条件
- Googleアカウント（YouTubeチャンネル所有者）
- Python 3.5+ + 必要ライブラリがインストール済み

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

## 🔧 トラブルシューティング

### エラー: "client_secrets.json が見つかりません"
→ Step 4 を確認。ファイルが正しい場所に配置されているか確認

### エラー: "Access blocked: This app's request is invalid"
→ OAuth同意画面の設定が必要。Google Cloud Console で設定

### エラー: "The OAuth client was not found"
→ client_secrets.json の内容が正しいか確認

### ブラウザが開かない
→ ファイアウォール設定を確認。ポート接続が許可されているか確認

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