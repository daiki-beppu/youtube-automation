## 何ができるか

collection の YouTube サムネイルを、競合の勝ちパターンとチャンネル固有の制作制約に合わせて作るスキルです。通常入口ではテキスト付きの `thumbnail.jpg` と動画背景用の textless `main.png` / `main.jpg` を別々に確定し、候補の承認、320px での視認性確認、制作状態の更新まで進めます。生成後の比較、A/B テスト、勝因の還元、ループ背景作成も同じ入口から一段ずつ実行できます。

| mode | すること | 主な成果物 |
|---|---|---|
| フラグなし | サムネ候補と textless 背景を生成・確定 | `thumbnail.jpg` / `main.png` または `main.jpg` |
| `--compare` | 候補を競合サムネと 320px で比較 | `docs/plans/thumbnail-comparison.md` |
| `--test` | YouTube Studio の A/B テストを設計・記録 | `thumbnail-test-active.json` / `thumbnail-test-history.json` |
| `--iterate` | 公開済み動画の勝因を分析し、次回の生成へ引き継ぐ | `data/thumbnail-iterate/champion.json` ほか |
| `--loop` | textless 背景から短いループ動画を生成 | `10-assets/loop.mp4` |

## 新しいサムネイルを作りたいとき

```
/thumbnail
/thumbnail fiddle playing
```

フラグなしで対象 collection を選び、設定済みの provider と参照画像から候補を作ります。テーマを引数で渡すこともできます。通常は候補ごとに確認を挟み、確定した画像だけを正式名へコピーします。チャンネルが全自動生成を明示設定している場合だけ、確認を省略して自動確定します。

## 小さい表示で競合に負けないか確認したいとき

```
/thumbnail --compare
```

`--compare` は生成済み候補を 320px に縮小し、競合の上位サムネと並べて可読性、コントラスト、被写体の認識しやすさを確認します。通常生成では承認前にこの検証を通してください。音楽・タイトルとの意味的な一致を見る `/audit --alignment` とは役割が異なります。

## Studio の A/B テストを回したいとき

```
/thumbnail --test
```

`--test` は最大 3 案の Test & Compare を設計し、開始時の仮説と終了後の結果を collection に記録します。いま実施中のテストを上書きせず、履歴を残しながら次のテストへ進めるための mode です。

## 伸びたサムネの勝因を次へ使いたいとき

```
/thumbnail --iterate <video-id>
```

`--iterate` は公開済み動画の CTR や比較対象を読み、再利用できる勝ち筋を champion として保存します。通常生成はこの記録を参照してプロンプトへ反映します。分析対象の動画と比較期間を確定できる状態で実行してください。

## 静止画からループ背景を作りたいとき

```
/thumbnail --loop
```

`--loop` は確定済みの textless `main.png` / `main.jpg` を Veo、Gemini Omni Flash、または MiniMax H3 へ渡し、動画本編で繰り返せる `loop.mp4` を作ります。静止画の確定前には実行せず、生成後は継ぎ目と意図しない文字・動きをプレビューしてください。

## つまずいたら

- **候補生成前に止まる** — `config/channel/`、対象 collection、参照画像を確認してください。チャンネル制作制約が未作成でも生成は続けられますが、先に `/channel-strategy --constraints` を実行すると判定基準を揃えられます
- **provider の認証や quota で失敗する** — 自動では別 provider に切り替わりません。ADC、API key、利用上限を直すか、設定で provider を明示変更してから再実行してください
- **`--compare` で不合格になる** — 正式画像へ確定せず、文字量、コントラスト、顔や主役の大きさを直した候補を生成して比較し直してください
- **`--loop` が始まらない** — `main.png` または `main.jpg` が確定済みか、チャンネルで loop-video が有効かを確認してください

