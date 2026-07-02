# ライブ配信のデフォルトを 24/7 連続配信に変更

## Status

accepted (2026-06-24)。

## Context

ライブ配信は Vultr VPS 上の systemd + ffmpeg で運用している。従来は `RuntimeMaxSec=11h` + `RestartSec=1h`（11 時間配信 → 1 時間休憩）のサイクルで、YouTube が 12 時間超のライブをアーカイブしない制約への対策として設計されていた。日次稼働 22h（91.7%）、月 2 アーカイブ/日。

運用を続けた結果、アーカイブを事後に参照する場面がなく、視聴者にとっては配信の途切れ（1 時間の空白）のほうがデメリットが大きいと判断した。

## Decision

1. **デフォルトを 24/7 連続配信（`RuntimeMaxSec` なし）にする。** アーカイブは生成されなくなるが、配信の中断がなくなる
2. **Terraform 変数 `stream_hours`（default=0）と `break_hours`（default=0）を導入する。** 0 は「無制限」を意味し、24/7 モードを表す。休憩モードが必要な場合は `stream_hours=11, break_hours=1` のように設定する
3. **設定の置き場所は Terraform 変数のみ。** VPS 上での手動変更は `terraform apply` で上書きされる前提（single source of truth）
4. **systemd unit テンプレートの条件分岐**: `stream_hours > 0` のとき `RuntimeMaxSec` を出力、`break_hours > 0` のとき `RestartSec=Xh` else `RestartSec=10s`（クラッシュ時の再起動間隔）。`Restart=always` は常に出力
5. **Python 定数を更新**: `THEORETICAL_HOURS_PER_DAY=24`、`ARCHIVES_EXPECTED=False`（boolean）。稼働率計算は `ARCHIVES_EXPECTED=False` のとき従来のアーカイブ数ベース計算をスキップ
6. **ヘルスチェックの `idle` 状態分類は残す。** 休憩モード時に正しく動作するために必要で、24/7 モードでは到達しないだけ

## Considered Options

- **アーカイブ維持 + ダウンタイム最小化（`RestartSec=5s`）**: 実質 24/7 に見せつつアーカイブも確保できるが、数秒とはいえ配信断が 1 日 2 回発生し、ffmpeg の再起動で RTMP セッションが切れるため YouTube 側にも新ストリームとして認識される。アーカイブを使わないなら無意味な中断
- **VPS 上の設定ファイルで上書き可能にする**: SSH で即座に変更可能だが、Terraform state と乖離する。`terraform apply` で意図せず上書きされるリスク
- **`streaming_mode` enum + `stream_hours` + `break_hours` の 3 変数**: 意図が明示的だが、`mode=continuous` と `stream_hours=11` が共存する矛盾状態を許してしまう。2 変数のほうが状態空間が小さく壊れにくい

## Consequences

- 帯域使用量が月 ~1.16 TB → ~1.27 TB に増加（2 TB クォータの 63%、80% 閾値以内）
- アーカイブが生成されなくなるため、過去のライブ内容の事後確認は不可
- `yt-stream-bandwidth --report` の稼働率レポートがアーカイブ数ベースから変更される
- streaming スキル（SKILL.md）を 24/7 デフォルト前提に書き換える
