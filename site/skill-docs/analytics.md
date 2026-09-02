## 何ができるか

YouTube Analytics のデータ収集から分析、レポート表示までを、成果物の鮮度を見ながら進めるスキルです。フラグなしなら収集 → 分析 → 表示を順番に判定し、完了済みの工程は再実行しません。日々の数値確認だけでなく、伸びなかった公開済み動画の原因整理にも使えます。

| mode | すること | 主な成果物・表示 |
|---|---|---|
| `--collect` | YouTube の統計を収集 | `data/analytics_data_*.json` |
| `--analyze` | 収集データから傾向・勝ちパターンを分析 | `reports/analysis_*.json` / `.html`、`data/insights.jsonl` |
| `--report` | 検証済みの最新分析レポートを表示 | 最新の分析 JSON / HTML |
| `--flop` | 公開済み動画の失速要因を検証 | collection 内の `postmortem.md`、insights |
| `--status` | 登録者数・再生回数・collection 一覧を表示 | チャット内のチャンネル統計 |

## データ更新からレポート確認までまとめて進めたいとき

```
/analytics
```

collect → analyze → report を状態判定つきで実行します。鮮度内の収集・分析結果は再利用するため、定期的な振り返りにも、途中失敗後の再開にも向いています。

## 一工程だけ実行したいとき

```
/analytics --collect
/analytics --analyze
/analytics --report
```

`--collect` は通常の統計収集、`--analyze` は収集済みデータの比較・傾向分析、`--report` は最新レポートの表示だけを行います。mode は排他的なので、一度に指定するのは 1 つだけです。

## 伸びなかった動画を振り返りたいとき

```
/analytics --flop <video_id>
/analytics --flop <collection>
/analytics --flop --since 30
```

動画 ID または collection を指定して、症状の定量化、仮説の検証、学びの記録まで進めます。対象を省略した場合、`--since <N>` で公開後 N 日以内の動画に候補を絞れます。改善策そのものは実行せず、次に試す内容を postmortem と insights に残します。

## チャンネルの現在値をすぐ見たいとき

```
/analytics --status
```

登録者数、総再生回数、公開動画数と collection 一覧を表示します。制作工程の進捗ではなく YouTube 上の統計を確認したいときに使います。

## つまずいたら

- **config を読めず止まる** — 新規チャンネルは `/setup --channel`、既存チャンネルの取り込みは `/setup --import` を先に実行してください
- **`--analyze` が入力不足で止まる** — 先に `/analytics --collect` で最新データを収集してください
- **`--report` で表示できるレポートがない** — `/analytics --analyze` を実行し、同日付の検証済み JSON / HTML ペアを作ってください
- **`--flop` で collection を特定できない** — collection 名を明示するか、対象動画を記録した `upload_tracking.json` を整備してください
- **複数の mode を指定して止まる** — `--collect` などの mode は 1 回に 1 つだけ指定してください
