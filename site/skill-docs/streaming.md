## 何ができるか

Terraform で Vultr VPS を構築し、YouTube ライブ配信を開始・監視・復旧する運用スキルです。初回構築から動画差し替え、帯域確認、障害調査、VPS の破棄までを案内します。既定は 24/7 連続配信で、アーカイブを残したい場合は 11 時間配信 + 1 時間休止へ切り替えられます。

| mode | すること | 主な確認先 |
|---|---|---|
| 初回構築 | VPS、cloud-init、動画転送、配信開始 | `terraform plan` / `terraform output` |
| 動画差し替え | VPS を作り直さず動画だけ更新 | deploy resource の replace |
| 監視・復旧 | service、帯域、アーカイブ、配信枠を診断 | systemd / Discord / recovery result |
| 破棄 | VPS を削除して課金を止める | `terraform destroy` |

## 24/7 ライブ配信を始めたいとき

```
/streaming
```

Terraform、SSH 鍵と ssh-agent、1Password の Vultr API key・stream key・Discord webhook、operator IP の `/32` CIDR を確認します。`terraform plan` でリソースと動画品質を確認し、明示承認後に apply すると配信が始まります。secret は tfvars に書かず `TF_VAR_*` 環境変数で渡します。

## 配信動画を差し替えたいとき

swap script で plan を確認してから apply します。動画 hash だけが変わる通常ケースでは deploy resource だけが置き換わり、VPS 自体は残ります。24/7 配信中は数秒から数十秒の中断があるため、必要なら告知や休止時間を調整してください。

## 配信停止や帯域を調べたいとき

service status と journal を起点に、stream key、動画破損、SSH、通知を切り分けます。24/7 運用は bandwidth check、11 時間 + 1 時間運用は archive check を使います。ingest が動いているのに active 配信枠だけが消えた場合は、broadcast recovery を必ず dry-run してから復旧します。ライブチャット返信は `/reply --live` の担当です。

## 長期休止して課金を止めたいとき

Vultr API key を再注入し、`terraform destroy` の対象を確認して VPS を破棄します。service の停止だけでは VPS の時間課金は続くため、長期休止では destroy まで完了してください。

## つまずいたら

- **`Permission denied (publickey)`** — `ssh-add -l` を確認し、毎セッション `~/.ssh/yt_stream_key` を ssh-agent へ登録してください。手動の `ssh -i` 成功だけでは provisioner の確認になりません
- **plan が動画品質で止まる** — キーフレーム間隔、ビットレート、H.264 profile を確認して配信向けに再エンコードしてください
- **Discord 通知が来ない** — healthcheck の environment と journal を確認してください。secret が trace に出るため `bash -x` は使いません
- **24/7 なのに archive check が不足を示す** — 日次アーカイブ数は 11 時間 + 1 時間運用だけの指標です。24/7 では service、ingest、broadcast recovery を確認してください
- **VPS が増えそうな plan になる** — workspace とチャンネル別の環境変数を照合し、意図しない instance replace が含まれる場合は apply しないでください
