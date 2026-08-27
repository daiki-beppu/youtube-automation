# ライブチャット自動返信を試す

24時間ライブ配信のチャットへ、Codex が新着メッセージを判定して返信する常駐 daemon を追加できます。この機能は公開コメントを自動投稿する**実験的機能**です。制約と停止方法を理解し、まずは監視できる状態で試してください。

## 何ができるか

配信 VPS 上の `live-chat-reply.service` がアクティブな YouTube Live を待ち受け、返信対象と判断した新着テキストへチャンネルの persona に沿った返答を投稿します。映像を送る `youtube-stream.service` とは独立しているため、返信 daemon の停止や再起動で配信本体は止まりません。

## 前提条件

利用には、次の環境と認証が必要です。

- `/streaming` で構築し、`youtube-stream.service` が動作している配信 VPS
- `youtube.force-ssl` scope を許可した YouTube OAuth の client secrets と token
- 返信の判定・生成に使う Codex CLI と、そのログイン情報
- 認証 JSON を安全に VPS へ渡すための 1Password CLI と、有効な session

秘密情報はリポジトリや `terraform.tfvars` へ保存しません。VPS への配備要件と opt-out は [`infra/terraform/streaming/README.md`](../infra/terraform/streaming/README.md#ライブチャット自動返信opt-in) を参照してください。

## 始め方

チャンネルリポジトリで、ライブ配信が動作していることを確認してから `/reply --live` を呼びます。

```text
/reply --live ライブチャットの自動返信を始めたい
```

skill が前提条件、認証、Terraform の変更内容を確認し、外部投稿を始める直前に明示的な承認を求めます。詳しい実行手順と確認項目は [`/reply --live` の live mode](../.claude/skills/reply/references/live.md) を正として参照してください。

## 実験的である理由と制約

返信は外部へ即時公開され、daemon からは投稿後に取り消せません。Codex の判断にも誤りがあり得るため、導入直後は YouTube Studio と daemon のログを監視し、意図しない応答があれば停止してください。

過剰な応答を抑えるため、投稿には **1時間あたりの返信数**、**同じ user への連続返信数**、**PT（太平洋時間）基準の日次 quota** の3段階の上限があります。これは安全弁であり、返信内容の正しさを保証するものではありません。

また、有効化には次の二重 opt-in が必要です。片方だけでは daemon は配備されません。

- チャンネル設定の `comments.live_chat.enabled: true`
- Terraform の `enable_live_chat_reply=true`

試用を終える場合は Terraform の `enable_live_chat_reply` を `false` に戻します。返信 daemon と専用の認証ファイルは削除されますが、ライブ配信本体には影響しません。
