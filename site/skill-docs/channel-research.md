## 何ができるか

競合の発見とデータ収集から、市場・視聴者・サムネイルの分析までを一つの入口で進めるスキルです。フラグなしなら benchmark → discover → voice → market を状態判定つきで実行し、鮮度内の成果物は再利用します。調査結果はチャンネル戦略や次の企画へ渡せる JSON / HTML ペアとして残ります。

| mode | すること | 主な成果物 |
|---|---|---|
| `--benchmark` | 登録済み競合の動画データとサムネイルを収集 | `data/benchmark_*.json`、benchmark report |
| `--discover` | キーワード検索から追加競合候補を発掘 | `research/*-discovery.md` / `.csv` |
| `--market` | 市場比較または収集済みデータの横断分析 | `docs/channel-research.json` / `.html` |
| `--voice` | 競合コメントから視聴者の語彙・利用シーンを抽出 | viewer voice report、`data/comments_*.json` |
| `--thumbnail` | 競合サムネイルの上位群・下位群を比較 | thumbnail analysis report |

## チャンネル調査を一通り更新したいとき

```
/channel-research
```

競合データ、追加候補、コメント、横断分析を順に更新します。`--thumbnail` は任意の深掘りなので一括実行には含まれず、必要なときだけ明示して実行します。

## 登録済み競合の最新データを集めたいとき

```
/channel-research --benchmark
```

承認済みベンチマークチャンネルの動画指標とサムネイルを収集し、比較レポートを更新します。鮮度内なら API を呼ばず既存データを使い、収集が必要な場合は API コストを示して確認します。

## 新しい競合候補を探したいとき

```
/channel-research --discover
```

ニッチ、用途、ムードなどの検索語から候補を発掘し、登録前に人が比較できる Markdown / CSV を作ります。候補の採用や設定変更までは自動で行いません。

## 市場の勝ち筋や機会領域を整理したいとき

```
/channel-research --market
```

競合データとコメントが揃っていれば収集済みデータを横断分析し、競合マトリクス、コンテンツ戦略、視聴者インサイト、機会領域をまとめます。新規市場の比較が必要な場合は一次情報を根拠に market comparison を行います。

## 視聴者の言葉や利用シーンを知りたいとき

```
/channel-research --voice
```

競合上位動画のコメントを収集し、感情、没入、利用シーン、要望、言語傾向を分析します。出力は `/channel-strategy --persona` や `/channel-strategy --scene` の根拠になります。

## 競合サムネイルの勝ちパターンを比較したいとき

```
/channel-research --thumbnail
```

再生数による上位群と下位群を同じルーブリックで比較し、構図・配色・文字・視線誘導の差を `/thumbnail` へ渡せる TTP として整理します。サムネイル自体の生成は行いません。

## つまずいたら

- **競合チャンネルが未登録で止まる** — `/setup --channel` の競合設定を完了するか、`/channel-research --discover` で候補を探してください
- **OAuth 認証がなくて収集できない** — `/setup` で YouTube API の認証を完了してください
- **`--market` の入力不足で止まる** — `/channel-research --benchmark` と `/channel-research --voice` を先に実行してください
- **`--thumbnail` で比較数が足りない** — サムネイル取得を有効にした `--benchmark` を再実行し、対応付け可能な動画を 2 件以上用意してください
- **収集前の確認で止まる** — API call が発生するための承認待ちです。表示された対象数とコストを確認して続行してください
