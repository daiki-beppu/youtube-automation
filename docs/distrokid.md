# 楽曲を DistroKid 配信向けに準備する

YouTube 用に制作したコレクションの楽曲を、DistroKid から音楽配信サービスへ届けるための素材として再利用できます。`/distrokid-helper` skill に依頼すると、完成済みの MP3 を配信用に整理し、Chrome 拡張へ受け渡すところまでを一つの流れで進められます。

automation が担当するのはローカルでの成果物生成と受け渡しです。DistroKid Web のフォーム入力とアップロードは `distrokid-helper` Chrome 拡張、または手作業で行います。

## できること

- `02-Individual-music/*.mp3` から `30-distrokid/` に配信用の成果物一式を生成する
- 1アルバム35曲の上限に合わせて楽曲を disc に分け、各 disc へ MP3 をコピーする
- 分割計画の `spec.json`、各 disc の `release.json` と `metadata.md`、アップロード手順の `README.md` を用意する
- 配信専用の 3000×3000 JPEG ジャケットを新規生成する
- ローカルサーバーから Chrome 拡張へメタデータを渡し、Web フォームへの転記を支援する

## 始める前に

対象コレクションに完成済みの `02-Individual-music/*.mp3` が必要です。また、チャンネル設定の optional ファイル `config/channel/distrokid.json` で DistroKid 連携を有効にし、配信アーティスト名を設定します。ジャケット生成には `/thumbnail` で使う画像生成設定も必要です。

`config/channel/distrokid.json` には songwriter の本名などの個人情報（PII）が含まれる場合があります。公開リポジトリへ誤って含めないよう、リポジトリの公開範囲と `.gitignore` の運用を確認してから記入してください。songwriter を設定しない場合は、DistroKid Web で曲ごとに手入力します。

Chrome 拡張を使う場合は、先に[Chrome 拡張インストールガイド](chrome-extension-install-guide.md)に沿って `distrokid-helper` を導入してください。詳しい前提条件と設定値は [`/distrokid-helper` skill](/skills/distrokid-helper) が正本です。

## `/distrokid-helper` で準備する

チャンネルリポジトリで、対象のコレクションを伝えて `/distrokid-helper` skill を呼び出します。

```text
/distrokid-helper <collection>
```

skill は MP3 の確認、disc 分割の計画、アルバム名の確認、成果物の生成、ジャケット作成、最終検証を順に案内します。36曲以上のコレクションは、各アルバムが35曲以内になるよう複数の disc へ均等に分割されます。

完了すると `30-distrokid/` に、機械可読な `spec.json`、disc ごとの MP3 と `release.json`、手動転記にも使える `metadata.md`、全体の `README.md`、3000×3000 の `cover_art_3000.jpg` が揃います。生成後はタイトル、曲順、アーティスト名、ジャケットを確認してください。

## DistroKid Web へ受け渡す

成果物の検証後、skill は次のローカルサーバーを起動して Chrome 拡張へデータを渡します。

```text
uv run yt-collection-serve
```

Chrome 拡張は localhost からコレクションと disc のメタデータを読み、DistroKid Web フォームへの転記とファイル選択を支援します。automation や `/distrokid-helper` が DistroKid Web への投稿を完了するわけではありません。Web 側では入力内容を確認し、利用者自身でアップロードを完了してください。

Chrome 拡張を利用できない場合は、各 disc の `metadata.md` を見ながらフォームへ手動で転記できます。作業が終わったら、起動したローカルサーバーを停止します。

## 配信内容を調整する

disc 数や1枚あたりの曲数、アルバム名、リリース日は準備の途中で調整できます。曲数の多いコレクションで分割結果を変えたい場合や、検証でタイトルの重複が見つかった場合は、`/distrokid-helper` に希望を伝えて再調整してください。

ジャケットは YouTube 用画像の流用ではなく、配信用の正方形画像として新規生成します。再生成や既存成果物の上書きには確認が必要なため、詳細なコマンドや判断基準は [`/distrokid-helper` skill](/skills/distrokid-helper) を参照してください。
