## 何ができるか

collection の MP3 を DistroKid で配信できるアルバム一式に整え、Chrome 拡張へ受け渡すスキルです。35 曲上限に合わせた disc 分割、メタデータ、3000×3000 ジャケットを生成し、検証後に collection server を起動します。DistroKid Web への転記とアップロード自体は拡張で行います。

| mode | すること | 主な成果物 |
|---|---|---|
| plan | MP3 を列挙して disc 分割案を作る | draft `spec.json` |
| build | 確定した仕様から配信用ファイルを組み立てる | disc / `metadata.md` / `README.md` |
| cover | AI 生成した正方形画像をジャケットへ最終化 | `cover_art_3000.jpg` |
| verify / serve | 成果物を検証して拡張へ配信する | `release.json` / localhost server |

## アルバムの分割案を作りたいとき

```
/distrokid-helper
```

対象 collection の MP3、DistroKid 設定、サムネイル設定を確認して plan から順に進めます。曲数が多い場合は disc 数や 1 disc の上限を相談し、重複タイトルは確定前にユニークな名前へ直します。

## 配信用ファイルとジャケットを作りたいとき

確定した `spec.json` から MP3 のコピーとメタデータを生成します。リリース日が決まっていれば初回 build で指定します。ジャケットは既存サムネイルの単純リサイズではなく、ブランド設定を引き継いだ文字なしの正方形画像を新規生成してから 3000×3000 JPEG にします。

## DistroKid へ受け渡したいとき

verify が green になった後、distrokid-helper 用の collection server を起動します。表示された URL を Chrome 拡張が読み、各 disc の `release.json` と音源をフォーム入力に使います。アップロード完了を確認したら server を停止し、workflow state に人間タスクの完了を記録します。

## つまずいたら

- **MP3 がない** — collection に応じて `/music --generate` と `/music --master` を先に完了してください
- **DistroKid が disabled と言われる** — `config/channel/distrokid.json` の有効化と artist 設定が必要です。songwriter は本名を含むため、設定時は案内される PII 運用を確認してください
- **disc が 35 曲を超える** — disc 数を増やすか 1 disc の上限を小さくして plan を作り直してください
- **ジャケットが非正方形** — 中央 crop の候補を確認してから cover をやり直してください。既存ジャケットの上書きには別途確認が必要です
- **拡張で collection が見えない** — single-file server ではなく distrokid 用 server を起動し直し、検出された URL と port を使ってください
