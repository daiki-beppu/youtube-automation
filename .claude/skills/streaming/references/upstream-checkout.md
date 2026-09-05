# Terraform 資産と実行場所の確定

`/streaming` と `/reply --live` の操作前に実行する。Terraform モジュールと README は [youtube-automation 上流リポジトリ](https://github.com/daiki-beppu/youtube-automation) の checkout が所有する。wheel / `yt-skills sync` は `infra/terraform/streaming/` を配布しない。

既存の運用 checkout の絶対パスを `AUTOMATION_ROOT`、対象チャンネルの絶対パスを `CHANNEL_DIR` として確定する。上流内で実行中ならその checkout をそのまま使う。所在が不明なら運用者に既存 checkout を確認する。未取得なら、GitHub アクセスを確認し `gh repo clone daiki-beppu/youtube-automation <取得先>` で取得する場所を示して停止する。下流の `/automation --update` だけではこの前提は解消しない。

値を確定した後、次の存在確認を行う。欠損時は不足パスを報告し、上流 checkout の取得・修復が済むまで Terraform、認証、外部 API 操作へ進まない。

```bash
: "${AUTOMATION_ROOT:?上流 checkout の絶対パスを設定してください}"
: "${CHANNEL_DIR:?対象チャンネルの絶対パスを設定してください}"
AUTOMATION_ROOT=$(cd "$AUTOMATION_ROOT" && pwd -P) || exit 1
CHANNEL_DIR=$(cd "$CHANNEL_DIR" && pwd -P) || exit 1
export AUTOMATION_ROOT CHANNEL_DIR
export TF_DIR="$AUTOMATION_ROOT/infra/terraform/streaming"
for asset in main.tf variables.tf versions.tf outputs.tf cloud-init.yaml README.md; do
  if [ ! -f "$TF_DIR/$asset" ]; then
    printf 'STOP: 上流 Terraform 資産がありません: %s\n' "$TF_DIR/$asset" >&2
    exit 1
  fi
done
for helper in select_channel.sh deploy_live_chat.sh; do
  if [ ! -f "$AUTOMATION_ROOT/.claude/skills/streaming/references/$helper" ]; then
    printf 'STOP: 上流 helper がありません: %s\n' "$helper" >&2
    exit 1
  fi
done
cd "$AUTOMATION_ROOT" || exit 1
```

以降の Terraform と配備 helper はこの上流 root で実行する。既存 helper の `--tf-dir "$TF_DIR"` で対象を明示できる。チャンネルの設定・認証・動画のパスは `CHANNEL_DIR` を基準とする絶対パスで渡す。チャンネル用 CLI はチャンネル root で実行し、Terraform 操作前に上流 root へ戻る。

`$TF_DIR/README.md` を読み、既存 backend と workspace を照合してから運用する。新しい checkout を既存 VPS の運用に使う場合も README に従って元の backend へ接続する。`.terraform/`、tfstate、tfvars、秘密ファイルを下流や別 checkout へコピーしない。
