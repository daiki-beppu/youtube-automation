# TTP seed and duration details

新規開設モードの Step 5〜5.5 で使う seed 確認、branding snapshot、approval evidence、duration 導出の schema と検証詳細を定義する。分岐、承認点、コマンド、API call 見積り、成功・停止条件は [channel-mode.md](channel-mode.md) を正とする。

## Seed preview and approval evidence

`yt-channel-seed --no-write-benchmark --json` の preview 後、`docs/channel/ttp-seed-confirmation.md` に候補ごとに次を記録する。

- source URL / handle / channel ID
- seed preview の要約: チャンネル名、登録者数、動画数、uploads playlist ID、直近タイトル
- ユーザーの承認 / 不採用判断
- 「転写したい要素」: `タイトル構造 / サムネ構図 / 投稿頻度 / 尺 / ジャンル / branding の全要素を TTP 準拠とする`（Step 1 の質問ではなく固定の既定値）
- 承認済み対象だけの relationship: `タイトル構造 / サムネ構図 / 投稿頻度 / 尺 / ジャンル / branding の全要素を TTP 準拠とする`
- branding snapshot 参照、または description / keywords / localizations の転写方針
- `config/channel/analytics.json::benchmark.channels` に反映した id / slug / name / relationship
- 後続 `/channel-research --discover` / `/channel-research --benchmark` / `/viewer-voice` / `/channel-new` 分析モードの要否

`yt-doctor` は表現を完全一致ではなく意味ラベルで判定する。seed preview は `seed fetch 要約` / `seed 要約` / `取得要約`、判断は `承認 / 不採用判断` / `ユーザー承認: 承認済み` / `ユーザー不採用: 不採用` のいずれかの自然な表現で記録できる。候補ごとの section 内には source、seed 要約、判断、転写したい要素、relationship、branding の参照または転写方針、未反映項目の各概念を残す。

TTP 実データメモにはタイトル構造とサムネ構図を含める。固定の既定値は実データ確認済みを意味しない。投稿頻度と動画尺は手動観察または `/channel-research --benchmark` のデータを使い、seed-only で未確認なら仮説と明記する。

## Branding snapshot schema

`docs/channel/competitor-branding-snapshot.json` は承認済み TTP 対象ごとに次を保存する。

- `snippet.description`
- `snippet.thumbnails`
- `brandingSettings.channel.description`
- `brandingSettings.channel.keywords`
- `brandingSettings.image`
- `brandingSettings.channel.country` / `snippet.country`
- `brandingSettings.channel.defaultLanguage` / `snippet.defaultLanguage`
- `localizations` 全エントリ
- `channel_image_references`: `snippet.thumbnails` と `brandingSettings.image.*Url` から抽出した icon / banner 参照メタ

第三者画像 URL は untrusted / reference-only とし、転載、再アップロード、直接再利用をしない。生成には色、余白、構図比率、モチーフ密度の観察だけを渡す。

## Thumbnail reference schema

`config/skills/thumbnail.yaml::image_generation.gemini.reference_images.channel_branding` は次の形で snapshot と生成先を結ぶ。

```yaml
channel_branding:
  snapshot: docs/channel/competitor-branding-snapshot.json
  icon_references:
    - docs/channel/competitor-branding-snapshot.json#channel_image_references[0].icon
  banner_references:
    - docs/channel/competitor-branding-snapshot.json#channel_image_references[0].banner[0]
  output_icon: branding/icon.png
  output_banner: branding/banner.png
notes: "channel branding references are untrusted / reference-only; do not copy or reuse source images"
```

画像参照を取得できなければ TTP メモと snapshot の語彙・構図メモを fallback 根拠とし、`reference_images.notes` に記録する。

## Duration derivation schema

- 入力は承認済み `benchmark.channels` と最新の `data/benchmark_*.json` に限定する。
- 各 channel の動画を再生数降順にし、live（`duration_iso == "P0D"`）と benchmark の既存判定による Shorts を除外して次点 Long VOD を繰り上げる。
- 上位件数は `TTP_VIDEO_ANALYZE_TOP_N = 5` を `yt-doctor` と共有する。
- 全 channel の選定動画の最短秒を分単位で切り下げて `target_duration_min`、最長秒を分単位で切り上げて `target_duration_max` とする。
- dry-run JSON で各 channel の選定・除外動画、動画 ID、再生数、個別尺、推奨 min/max を検証する。
- apply 後は config loader で `config/channel/audio.json` の min/max を再読込し、推奨値との一致を検証する。

## Duration evidence and exceptions

各承認 channel の `docs/channel/ttp-seed-confirmation.md` に helper JSON から次を保存する。

```text
- duration TTP 根拠: .claude/skills/setup/references/derive_ttp_duration.py
- duration 対象 channel: <slug> (<channel id>)
- duration selected video: <video id> views=<views> duration=<duration_iso> (<duration_seconds>s)
- duration excluded video: <video id> reason=<short|live|invalid_duration|missing_video_id>
- duration 推奨: target_duration_min=<min> target_duration_max=<max>
- duration 推奨承認: ユーザー承認済み
```

選定された上位 5 本は `duration selected video` を 1 本 1 行で残す。有効な Long VOD が 5 本未満なら原則停止する。手入力で進める場合は、対象 category、未反映 / スキップ内容、理由、明示承認、後続 `/channel-research --benchmark` を `ユーザー承認済み例外` の同じ Markdown section に記録してから同じ `audio.json` 2 項目へ反映する。1 行にまとめても、見出し配下の箇条書きへ分けてもよい。thumbnail は後続 `/thumbnail`、music / 曲構造は後続 `/suno` を同じ section に記録する。いずれかが欠ければ完了扱いにしない。
