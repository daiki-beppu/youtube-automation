# 24時間ライブ配信を始める

完成した BGM 動画を、Vultr の VPS から YouTube Live へ24時間連続で配信できます。`/streaming` skill に依頼すると、Terraform による VPS の作成、動画の転送、配信サービスの起動までを一つの手順で進められます。

通常の動画投稿に加えて、作業用 BGM をいつでも聴けるライブ枠を運用したいときに使います。配信プロセスは VPS 上で自律動作するため、手元の PC を起動し続ける必要はありません。

## できること

- ローカルの MP4 を YouTube Live へ24時間連続配信する
- Terraform で Vultr VPS とファイアウォールを再現可能な形で管理する
- 配信停止などの異常と復旧を監視し、Discord へ通知する
- 必要に応じて、11時間配信・1時間休止のサイクルへ切り替える

## 始める前に

少なくとも次のものを準備します。

- **Vultr アカウントと API キー**: VPS の作成と削除に使います。VPS が存在する間は利用料金が発生します。
- **Terraform 1.15.x**: VPS、ファイアウォール、配信サービスを構築します。
- **配信する MP4**: YouTube Live へ流す完成済み動画を、ローカルの絶対パスで指定します。
- **YouTube のストリームキー**: リポジトリへ書かず、1Password または環境変数から渡します。
- **GCS backend と Google Cloud の ADC**: Terraform state の保存に使います。
- **SSH 鍵と ssh-agent**: Terraform が構築した VPS へ接続するために使います。

詳しい前提条件と設定値は [`infra/terraform/streaming/README.md`](../infra/terraform/streaming/README.md) にまとまっています。ストリームキーや API キーなどの secret を `terraform.tfvars` へ書かないでください。

## `/streaming` で始める

チャンネルリポジトリで、配信したい動画と希望する運用を伝えて `/streaming` skill を呼び出します。

```text
/streaming この動画を24時間ライブ配信したい
```

skill は前提条件を確認し、`infra/terraform/streaming/` の設定準備から `terraform plan`、`terraform apply`、配信状態の確認までを案内します。複数チャンネルを運用している場合はチャンネルごとに Terraform workspace を分け、選択中の workspace と plan の対象が一致していることを確認してから適用します。

`terraform apply` により、VPS 作成、OS の準備、動画アップロード、systemd サービスの起動までが実行されます。適用後は YouTube Studio と VPS のサービス状態の両方で、意図したライブ枠へ映像が届いていることを確認してください。

## 配信を見守る

配信サービスはデフォルトで24時間連続運転し、異常終了時には自動再起動します。停止や通知の切り分けが必要になったら、もう一度 `/streaming` を呼び出して状況を伝えてください。

```text
/streaming ライブ配信が止まったので確認したい
```

状態の分類、Discord 通知、再起動検知の詳しい確認方法は [streaming healthcheck 運用手順書](streaming-healthcheck.md) を参照してください。

長期間配信を休止するときは、VPS の課金を止めるため Terraform でリソースを破棄します。実行前に、対象の Terraform workspace と削除対象が意図したチャンネルのものか確認してください。

ライブチャットへの自動返信を試す場合は、実験的機能の[ライブチャット自動返信ガイド](live-chat-reply.md)を参照してください。
