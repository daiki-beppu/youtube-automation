## 何ができるか

チャンネル設定から content model を自動判定し、縦型ショートを生成するスキルです。collection 型では公開済み長尺動画のテイスターを作ってローカライズ・投稿まで進め、release 型では楽曲のサビを切り出した日本語・英語クリップを作ります。利用者が型を選ぶ必要はなく、同じ `/short` から適切な手順へ分岐します。

| mode | すること | 主な成果物 |
|---|---|---|
| フラグなし | collection / release の型に合うショートを生成 | `short-*.mp4` または `short-{jp,en}.mp4` |
| `--thumbnail` | collection 型の 9:16 素材を生成 | `10-assets/short.png` / `short-loop.mp4` |

## 長尺動画から BGM テイスターを作りたいとき

```
/short
```

collection 型では公開済み動画と確定素材から既定 3 本前後の縦型クリップを生成します。区間とクロップをプレビューで承認してから、対応言語の metadata を付けて YouTube へ投稿し、collection state に結果を記録します。API を使う前に投稿計画を確認したい場合は、内部の `yt-upload-shorts --plan` 手順で内容を確認できます。

## 楽曲リリースのサビを切り出したいとき

```
/short
```

release 型では JP / EN の 9:16 動画をローカルで生成します。サビの開始秒と尺は release 設定の値が初期値として提示され、生成前に区間を確認して都度指定できます。設定を書き換えなくてもその場で切り出し位置を変えられ、恒常的な既定値を変えたいときだけ release 設定を直します。プレビュー確認までがこの mode の責務で、現時点では YouTube への投稿は行いません。

## ショート専用の縦素材を作りたいとき

```
/short --thumbnail
```

`--thumbnail` は collection 型だけで使える一段実行です。9:16 の `short.png` を生成・承認し、必要なら縦型の `short-loop.mp4` に動画化します。content model を切り替えるフラグではないため、release 型で指定すると対象外として停止します。

## つまずいたら

- **開始直後に設定エラーになる** — `config/channel/shorts.json` で shorts が有効か、`content_model.type` が `collection` または `release` かを確認してください
- **collection 型で素材が見つからない** — 本編の公開とマスター動画・背景素材の確定が前提です。先に `/publish --upload` または不足している制作工程を完了してください
- **`--thumbnail` が対象外になる** — この mode は collection 型専用です。release 型のショートは本編映像から直接生成します
- **生成に時間がかかる** — ffmpeg 処理は通常 1〜3 分かかります。process の終了と成果物の存在を確認するまで再実行しないでください
