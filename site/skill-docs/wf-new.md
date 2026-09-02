## 何ができるか

新しい collection の企画を立ち上げ、サムネイルと音楽プロンプトが揃った制作開始状態まで導くスキルです。通常は企画や生成結果を確認しながら 1 件ずつ開始します。複数企画の順次立ち上げ、公開後処理までの自動継続、定期実行の設定も同じ入口から選べます。

| mode | すること | 主な成果物 |
|---|---|---|
| フラグなし | 1 件の企画を選び、新規 collection を初期化 | `collections/planning/<id>/workflow-state.json` と制作素材 |
| `--auto` | 状態を毎段再評価し、公開後処理まで継続 | `.automation-run/history.json` |
| `--batch` | 複数企画を manifest 順に 1 件ずつ開始 | `reports/wf-new-batches/<batch-id>/` |
| `--schedule` | 定期実行の設定・確認・停止 | `config/channel/workflow.json` と scheduler 登録 |

## 新しい collection を 1 件始めたいとき

```
/wf-new
```

未完了の postmortem を先に振り返り、analytics、競合ベンチマーク、またはユーザー入力から企画候補を作ります。企画とサムネイルを承認すると collection が初期化され、音楽制作へ渡せるところまで進みます。初回制作では、任意のパイロット検証を済ませたかも確認します。

## 制作から公開後処理まで続けたいとき

```
/wf-new --auto
```

active collection の実成果物と `workflow-state.json` を一段ごとに突合し、必要な子スキルだけを呼びます。完了済みの工程は再実行せず、ログイン、CAPTCHA、承認など人の操作が必要な地点では自動突破せずに停止します。外部公開はチャンネル設定で明示的に許可されている場合だけ行います。

## 複数の企画をまとめて立ち上げたいとき

```
/wf-new --batch --count 3
/wf-new --batch --resume <batch-id>
```

`--count <N>` で 2 件以上の企画を比較・承認し、manifest の順番で 1 件ずつ collection を開始します。途中で止まった batch は `--resume <batch-id>` で、ledger と実成果物を照合して最初の未完了企画から再開します。後続企画を並列に進めないため、失敗した 1 件を直してから安全に続行できます。

## 定期実行を設定・確認したいとき

```
/wf-new --schedule
```

実行する工程と環境の能力から cloud / local の配置を判定し、設定差分と scheduler の plan を表示してから登録します。曜日や時刻、外部公開の許可は推測せず確認します。同じ入口で現在の登録状況の確認や無効化も依頼できます。

## つまずいたら

- **channel config がなくて止まる** — 新規チャンネルは `/setup --channel`、既存チャンネルの取り込みは `/setup --import` を先に実行してください
- **企画候補が出ない** — analytics とベンチマークが無い場合は、テーマ・ジャンル・雰囲気の入力が必要です。競合データを使うなら `/channel-research --benchmark` を先に実行します
- **`--auto` が blocked になる** — 承認、Suno のログイン / CAPTCHA、または外部公開設定など、人が判断すべき停止点です。表示された resume action を満たして同じコマンドを再実行してください
- **`--batch` の途中で止まる** — 完了済み collection を手で作り直さず、原因を解消して `--resume <batch-id>` で ledger から再開してください
- **`--schedule` が登録できない** — 既存 backend の重複、OAuth、または local Scheduled Task の利用可否を確認してください。別 backend へ勝手に切り替えることはありません
