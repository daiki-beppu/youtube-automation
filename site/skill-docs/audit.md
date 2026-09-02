## 何ができるか

制作物の整合性、動画本体、公開後メタデータ、運用の価値ループをまとめて点検するスキルです。フラグなしでは 4 監査を順に状態判定し、保存済みレポートを再利用しながら不足している監査だけを進めます。監査は問題を発見して次の作業を示すところまでで、公開情報や制作物を勝手に修正しません。

| mode | すること | 主な成果物・表示 |
|---|---|---|
| `--alignment` | 音楽ムード・サムネイル・タイトルの整合性を監査 | `docs/plans/alignment-audit.json` / `.html` |
| `--video` | 競合または自チャンネルの動画本体を解析 | `data/video_analysis/*`、`reports/video_analysis/*` |
| `--metadata` | ローカル記録と YouTube 上のメタデータを照合 | チャット内の差分一覧 |
| `--value-loop` | シーン定義から指標還流までの運用ループを点検 | チャット内の 4 工程診断 |

## 4 つの監査をまとめて実行したいとき

```
/audit
```

alignment → video → metadata → value-loop の順に進めます。保存される alignment / video の成果物は完了後に skip され、表示型の metadata / value-loop はその都度最新状態を診断します。

## 音楽・サムネ・タイトルの一貫性を確認したいとき

```
/audit --alignment
```

collection ごとに音楽プロンプト、サムネイル、タイトルを照合し、整合性マトリクスと改善候補を作ります。creative constraints があればチャンネル固有の基準も判定根拠に加えますが、不在だけでは停止しません。

## 動画の構成を解析したいとき

```
/audit --video
```

ベンチマーク上位動画、自チャンネルの collection、単発 URL のいずれかを選び、映像・音声・展開を解析します。既存の有効な解析結果は再利用するため、対象を増やしたい場合は source や collection を明示してください。

## 公開後メタデータのずれを見つけたいとき

```
/audit --metadata
```

ローカルの description・workflow state と YouTube 側の snippet・localizations を照合します。差分は表示しますが修正は行わないので、確認後に `/video --describe` や公開工程へ戻れます。

## 運用が学びを次の制作へ戻せているか確認したいとき

```
/audit --value-loop
```

視聴シーン定義、制作制約への翻訳、公開前ゲート、公開後指標の還流という 4 工程を読み取り専用で診断します。一部の成果物がなくても残りの工程を最後まで確認し、不足箇所を次のアクションとして示します。

## つまずいたら

- **チャンネル設定がなくて止まる** — 新規チャンネルは `/setup --channel`、既存チャンネルは `/setup --import` を実行してください
- **`--alignment` の入力が足りない** — thumbnail、音楽プロンプト、description の対象成果物を先に生成してください
- **`--video` の対象を決められない** — benchmark の競合名、own collection、または動画 URL のどれを解析するか指定してください
- **`--metadata` に監査対象がない** — 公開済み collection の検証済み description と `upload_tracking.json` を確認してください
- **監査で FAIL が出る** — FAIL は監査自体の失敗ではありません。表示された担当スキルへ戻って修正し、同じ mode で再監査してください
