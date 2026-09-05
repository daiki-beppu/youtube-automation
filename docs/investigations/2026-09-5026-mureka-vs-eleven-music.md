# Mureka API と Eleven Music API の事実並置（Issue #5026）

wayfinder map #5025 の research ticket。Mureka API（platform.mureka.ai）と Eleven Music API を同じ観点で並置し、後続の 3 判断（載せ替え順序 / 共通基盤の境界 / ボーカル経路）が待っている事実を確定する。**判断はしない。事実と一次情報の URL のみ。**

> 調査日: 2026-09-05（Asia/Tokyo）。Eleven Music 側は `docs/investigations/2026-07-2264-eleven-music-api.md`（2026-07-22 調査）の事実を写し、料金・曲長・vocal 対応だけ 2026-09-05 に公式 docs で再確認した。Mureka の docs は JS 描画（vitepress-openapi）のためブラウザで描画後の本文を読んだ。価格・仕様は変わり得るので、購入・実装時に再確認すること。

## 並置表

| 観点 | Mureka API | Eleven Music API |
|---|---|---|
| Base URL / 認証 | `https://api.mureka.ai`。ヘッダ `Authorization: Bearer <MUREKA_API_KEY>`（HTTP bearer）。[Quickstart](https://platform.mureka.ai/docs/en/quickstart.html) | ヘッダ `xi-api-key`（公式 SDK は `ELEVENLABS_API_KEY`）。2026-07 調査の [API errors](https://elevenlabs.io/docs/eleven-api/resources/errors) / [Music quickstart](https://elevenlabs.io/docs/eleven-api/guides/cookbooks/music) に基づく。現行の compose reference ページ本文にはヘッダ名の記載なし |
| 音源生成 endpoint | vocal: `POST /v1/song/generate`（lyrics to song）、`POST /v1/song/easy-generate`（prompt to song）。instrumental: `POST /v1/instrumental/generate`。結果取得: `GET /v1/song/query/{task_id}`、`GET /v1/instrumental/query/{task_id}`。残高: `GET /v1/account/billing`。[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) / [song/easy-generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-easy-generate.html) / [instrumental/generate](https://platform.mureka.ai/docs/api/operations/post-v1-instrumental-generate.html) / [song/query](https://platform.mureka.ai/docs/api/operations/get-v1-song-query-%7Btask_id%7D.html) / [account/billing](https://platform.mureka.ai/docs/api/operations/get-v1-account-billing.html) | `POST /v1/music`（compose）、`POST /v1/music/stream`、`POST /v1/music/detailed`、`POST /v1/music/detailed/stream`（2026-07-06 追加）、composition plan 作成 endpoint。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) / [Compose detailed](https://elevenlabs.io/docs/api-reference/music/compose-detailed) / [Create composition plan](https://elevenlabs.io/docs/api-reference/music/create-composition-plan) / [Changelog 2026-07-06](https://elevenlabs.io/docs/changelog/2026/7/6) |
| 同期 / 非同期 | **非同期 polling**。generate は task `id` と `status` を返し、query endpoint で polling。`status` は `preparing / queued / running / streaming / succeeded / failed / timeouted / cancelled`。`stream: true` で生成中に `stream_url` を再生できる streaming phase が入る（mureka-o1 は非対応）。stream URL は生成完了後 5 分間有効期間が延長される（[Changelog 2025.10.27](https://platform.mureka.ai/docs/en/changelog.html)）。[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) | **同期**。compose は生成音声 bytes をそのまま返す（`song-id` response header）。stream / detailed stream は SSE。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) / [Changelog 2026-07-06](https://elevenlabs.io/docs/changelog/2026/7/6) |
| レスポンス形（音源） | `choices[]` に `index`, `id`, `url`（形式の明記なし）, `flac_url`（lossless FLAC）, `wav_url`（lossless WAV。2025.12.9 追加）, `stream_url`, `duration`（ms）, `lyrics_sections[]`（`section_type`, `start`, `end`, `lines`）。`url` / `flac_url` / `wav_url` は **30 日間有効**。[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) / [Changelog](https://platform.mureka.ai/docs/en/changelog.html) | 音声 bytes を直接返す。`output_format` は query param。detailed は multipart で `audio` + `composition_plan` + `song_metadata`（title / description / genres / languages / explicit）。`with_timestamps` で単語 timestamps。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) / [Compose detailed](https://elevenlabs.io/docs/api-reference/music/compose-detailed) |
| 出力形式 | `url`（形式の明記なし）+ FLAC + WAV を同時返却。出力形式を request で指定する param はなし。[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) | `output_format` enum: `auto`, `mp3_48000_128/192/240/320`, `mp3_22050_32`, `mp3_24000_48`, `mp3_44100_32/64/96/128/192`, `pcm_8000..48000`, `ulaw_8000`, `alaw_8000`, `opus_48000_32..192`。`auto` は v1=`mp3_44100_128`、v2=`mp3_48000_192`（2026-07 調査）。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) |
| 1 リクエスト最大曲長 | request に曲長 param なし（モデル任せ）。pricing 表の注記: 「Song length not exceeding 5m30s」（Lyrics to song / Prompt to song）、「BGM length not exceeding 4m30s」（BGM = instrumental）。最小長の記載なし。[Pricing](https://platform.mureka.ai/pricing) | `music_length_ms` = 3,000〜600,000 ms（API validation。省略時はモデルが決める）。商品説明は「5 minute duration limit」、capability 概要は「minimum duration of 3 seconds and a maximum duration of 5 minutes」。2026-07 調査と同じ（変更なし）。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) / [API Pricing](https://elevenlabs.io/pricing/api) / [Eleven Music overview](https://elevenlabs.io/docs/overview/capabilities/music) |
| 1 リクエストの出力本数 | `n` = 既定 2、最大 3。**本数分課金**。[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) | 1 request = 1 output。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) |
| モデル名 | song: `auto`, `mureka-7.6`, `mureka-o2`, `mureka-8`, `mureka-9`, `mureka-9.5`（`auto` = 最新の regular model）。instrumental: `auto`, `mureka-7.6`, `mureka-8`, `mureka-9`, `mureka-9.5`（o2 なし）。`mureka-o2` は `vocal_id` / `melody_id` 非対応。リリース日: 9.5=2026.8.28, 9=2026.4.9, 8=2026.3.2, 7.6 と o2=2025.12.9。[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) / [instrumental/generate](https://platform.mureka.ai/docs/api/operations/post-v1-instrumental-generate.html) / [Changelog](https://platform.mureka.ai/docs/en/changelog.html) | `model_id`: `music_v1`（既定）, `music_v2`。v2 は 2026-06-15 に API 提供、UI では v2 が既定で v1 は移行期間中のみ。`MusicPrompt` 形の plan は v1 専用、v2 は chunk-based composition plan。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) / [Changelog 2026-06-15](https://elevenlabs.io/docs/changelog/2026/6/15) / [Eleven Music overview](https://elevenlabs.io/docs/overview/capabilities/music) |
| モデル間の品質・曲長差 | 公式 docs は各版を「The enhanced version of the mureka-N model released」としか記述せず、品質指標・曲長差の数値なし。曲長上限は pricing 表でモデル横断（5m30s / 4m30s）。docs トップの Model Specifications は V7.5 / O1 の説明のみ（更新されていない）。[Changelog](https://platform.mureka.ai/docs/en/changelog.html) / [Docs top](https://platform.mureka.ai/docs/) | v1 / v2 の曲長上限は同じ（3,000〜600,000 ms）。差は plan 形式（v2 は section duration を常に強制、`respect_sections_durations` は v1 のみ）。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) |
| 料金（単価） | 前払い top-up の **曲単位課金**。Lyrics to song: O2 / V8 / V9 = $0.045/song、V7.6 = $0.03/song、9.5 = $0.15/song。Prompt to song: V7.6 / O2 / V8 / V9 = $0.3/song、9.5 = $0.5/song。BGM（instrumental）: V8 / V9 = $0.045/BGM、V7.6 = $0.03/BGM、9.5 = $0.15/BGM。Lyric generation = $0.009/lyric。Stem export = $0.06〜$0.7/song。[Pricing](https://platform.mureka.ai/pricing) | **分単位課金** $0.150/生成分（API Pricing）。plan 月額と含有分: Free/PAYG 3 分、Starter $6 = 40 分、Creator $22 = 147 分、Pro $99 = 660 分、Scale $299 = 1,993 分、Business $990 = 6,600 分。2026-07 調査と同じ（変更なし）。一般 pricing ページ FAQ は「Eleven Music 900 credits per minute」。[API Pricing](https://elevenlabs.io/pricing/api) / [Pricing](https://elevenlabs.io/pricing) |
| 無料枠・最低チャージ | 「TRAIL $10（One-time purchase per account）」が最小。次段は $1,000。「Apply for a Free Trial」導線は Custom Price 欄にあるが条件の記載なし（未確認）。残高は最終 recharge から 12 か月有効、返金不可、先入先出で消費。Web 版会員・クレジットは API に移行不可。[Pricing](https://platform.mureka.ai/pricing) / [FAQ](https://platform.mureka.ai/docs/en/faq.html) | Music API は有料 plan のみ（「The Music API is available for paid subscribers」）。Free の月間生成上限は 11 分・download 不可・帰属表示必須。超過分は PAYG Top Up（前払い、返金不可、12 か月失効。2026-07 調査）。[Eleven Music overview](https://elevenlabs.io/docs/overview/capabilities/music) / [Music Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms) / [Pay As You Go](https://elevenlabs.io/docs/overview/administration/pay-as-you-go) |
| rate limit / 並列 | **並列数は 1 回の購入額で決まる**（累積ではない。$1,000 を 5 回買っても 5 並列）: $10 → 1、$1,000 → 5、$3,000 → 15、$5,000 → 25、$30,000 → 150。「concurrent requests」= 投入から生成完了までの同時タスク数。`GET /v1/account/billing` の `concurrent_request_limit` で確認可。429 は「Rate limit reached」（送信過多）と「Quota exceeded」（残高不足）の 2 種。403 は未対応リージョン。秒間リクエスト数の上限値は docs に記載なし（未確認）。[Pricing](https://platform.mureka.ai/pricing) / [FAQ](https://platform.mureka.ai/docs/en/faq.html) / [Error codes](https://platform.mureka.ai/docs/en/error-codes.html) / [account/billing](https://platform.mureka.ai/docs/api/operations/get-v1-account-billing.html) | Music Terms 表の Concurrency Limits: Free 0、Starter / Creator / Pro 2、Scale / Business 5、Enterprise Music Lite 5、Enterprise Music 10+。月間生成上限（分）: Free 11、Starter 17、Creator 62、Pro 304、Scale 1,100、Business 4,800。月間 download 上限: Starter 30、Creator 250、Pro 500、Scale 1,500、Business 4,000。Last Updated 26 May 2026 で 2026-07 調査から数値変更なし。表に「Inpainting API Access」列が追加（self-serve 全 plan で Yes と表示）。[Music Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms) |
| instrumental 指定 | **別 endpoint**。`POST /v1/instrumental/generate` に `prompt`（≤1,024 文字）または `instrumental_id`（files/upload 由来）。song/generate 側に instrumental flag はない。soundtrack endpoint は「Specify vocals or instrumental in your prompt」。[instrumental/generate](https://platform.mureka.ai/docs/api/operations/post-v1-instrumental-generate.html) / [Pricing](https://platform.mureka.ai/pricing) | **flag**。`force_instrumental: true`（既定 false）で「guarantees that the generated song will be instrumental」。[Compose](https://elevenlabs.io/docs/api-reference/music/compose) |
| vocal の歌詞入力書式 | `lyrics`（必須、**最大 5,000 文字**）に歌詞を渡す。公式 cURL 例は `"[Verse]\n..."` と **`[Verse]` 形式の section tag を含む**。レスポンスの `lyrics_sections[].section_type` の語彙は `intro / verse / pre-chorus / chorus / bridge / break / outro`（2025.6.10 に `breakdown` → `break`）。入力側で受理される tag 文法・tag 無しの扱いは docs に記載なし（未確認）。補助: `prompt`（≤1,024 文字、スタイル指示）、`gender`（`female` / `male`）、`vocal_id`、`reference_id`、`melody_id`。easy-generate は `prompt`（≤2,000 文字）+ `styles[]`（`pop, rock, jazz, r&b, edm, ambient, folk, latin, k-pop, j-pop, house, gospel, lo-fi`）で歌詞は自動生成。[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) / [song/easy-generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-easy-generate.html) / [Changelog](https://platform.mureka.ai/docs/en/changelog.html) | composition plan の section ごとに `lines: string[]`（**section あたり最大 30 行、1 行最大 200 文字**）が歌詞。section 名は `section_name`（1〜100 文字）で自由文字列。quickstart 例は `"[Intro]"` `"[Peak Drop]"` のような bracket 表記を text に使う。prompt 単体でも生成できるが、prompt 内の歌詞書式（section tag 可否）は docs に記載なし（未確認）。prompt 文字数上限は現行 reference ページに記載なし（2026-07 調査時は 4,100 文字）。plan と prompt は排他。[Create composition plan](https://elevenlabs.io/docs/api-reference/music/create-composition-plan) / [Music quickstart](https://elevenlabs.io/docs/eleven-api/guides/cookbooks/music) / [Compose](https://elevenlabs.io/docs/api-reference/music/compose) |
| 日本語歌詞 | FAQ「song generation で対応する言語」に **Japanese を明記**（Chinese, English, Japanese, Korean, Portuguese, Spanish, German, French, Italian, Russian の 10 言語）。changelog 2026.1.5 も vocal で同 10 言語を明記。[FAQ](https://platform.mureka.ai/docs/en/faq.html) / [Changelog](https://platform.mureka.ai/docs/en/changelog.html) | capability 概要に「Multilingual, including English, Spanish, German, Japanese and more」と **Japanese を明記**。[Eleven Music overview](https://elevenlabs.io/docs/overview/capabilities/music) |
| 日本語 prompt | prompt（スタイル指示）の言語に関する記載なし（未確認）。公式例は英語。[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) | composition plan の style 各フィールドは「use English language for best result」。prompt 本体の言語制約の記載なし（未確認）。[Create composition plan](https://elevenlabs.io/docs/api-reference/music/create-composition-plan) |
| 商用利用 | FAQ「All content generated through paid API calls comes with full usage rights and commercial authorization」。詳細は Terms of Service（本調査では未読）。[FAQ](https://platform.mureka.ai/docs/en/faq.html) | plan 別に Streaming / Media / Attribution 条件あり（Free は Streaming 不可・帰属表示必須、Creator 以上で Streaming 可）。2026-07 調査から変更なし。[Music Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms) |
| 失敗時の課金 | docs に記載なし（未確認）。返金は全面不可（FAQ）。[FAQ](https://platform.mureka.ai/docs/en/faq.html) | docs に記載なし（2026-07 調査と同じ、未確認）。`bad_prompt` / `bad_composition_plan` で `prompt_suggestion` を返す。[Music quickstart](https://elevenlabs.io/docs/eleven-api/guides/cookbooks/music) |

## Mureka の課金単位の補足（Pricing ページの注記、判断ではなく転記）

- 「Generate up to 3 songs per time (Default is 2)」— `n` を明示しないと 2 曲分課金される（[Pricing](https://platform.mureka.ai/pricing)、[song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html)）。
- 「Concurrency is based on each individual purchase, not the total」「API calls deduct the balance sequentially, based on the concurrency per purchase」（[Pricing](https://platform.mureka.ai/pricing)）。
- 「Downloading songs is free of charge. However, using the multitrack (stems) feature requires a separate payment」（[FAQ](https://platform.mureka.ai/docs/en/faq.html)）。

## 未確認のまま残った項目

- Mureka `choices[].url` の音声形式（mp3 か否か）— schema に形式の明記なし。
- Mureka 入力歌詞の section tag 文法（受理される tag の一覧、tag 無し歌詞の扱い、tag が日本語表記でよいか）。
- Mureka prompt の日本語可否、秒間 rate limit の数値、失敗 task の課金有無、「Apply for a Free Trial」の条件。
- Mureka の V9.5 beta 価格（第三者記事に「$0.045 beta until 2026-08-28」の記述があるが、公式 pricing ページには 9.5 = $0.15/song のみ。一次情報で未確認）。
- Eleven Music prompt 単体経路での歌詞・section tag の書式、prompt 文字数上限の現行値。
- Eleven Music の失敗生成の課金・返金条件（2026-07 調査から未解決）。

## 後続の判断に効く事実

- 課金単位が異なる: Mureka は曲単位（$0.03〜$0.15/song、`n` 既定 2 で 2 曲分）、Eleven Music は分単位（$0.15/分）+ plan 別の月間生成上限。
- 実行モデルが異なる: Mureka は非同期 task + polling（URL は 30 日有効、FLAC / WAV 同時返却）、Eleven Music は同期で音声 bytes を直接返す。
- 曲長: Mureka は request で指定不可・上限 5m30s（song）/ 4m30s（BGM）、Eleven Music は `music_length_ms` で 3 秒〜10 分（API）を指定可。
- instrumental: Mureka は別 endpoint（`/v1/instrumental/generate`）、Eleven Music は `force_instrumental` flag。
- 歌詞: Mureka は `lyrics` 1 文字列（≤5,000 文字、公式例が `[Verse]` tag 付き）、Eleven Music は composition plan の section 別 `lines[]`（30 行 × 200 文字）。両者とも日本語 vocal 対応を公式に明記。

## 参照した一次情報

Mureka:

- [Quickstart](https://platform.mureka.ai/docs/en/quickstart.html)
- [Docs top（Model Specifications）](https://platform.mureka.ai/docs/)
- [POST /v1/song/generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html)
- [POST /v1/song/easy-generate](https://platform.mureka.ai/docs/api/operations/post-v1-song-easy-generate.html)
- [GET /v1/song/query/{task_id}](https://platform.mureka.ai/docs/api/operations/get-v1-song-query-%7Btask_id%7D.html)
- [POST /v1/instrumental/generate](https://platform.mureka.ai/docs/api/operations/post-v1-instrumental-generate.html)
- [POST /v1/lyrics/generate](https://platform.mureka.ai/docs/api/operations/post-v1-lyrics-generate.html)
- [GET /v1/account/billing](https://platform.mureka.ai/docs/api/operations/get-v1-account-billing.html)
- [Pricing](https://platform.mureka.ai/pricing)
- [FAQ](https://platform.mureka.ai/docs/en/faq.html)
- [Changelog](https://platform.mureka.ai/docs/en/changelog.html)
- [Error codes](https://platform.mureka.ai/docs/en/error-codes.html)

Eleven Music:

- [ElevenAPI Pricing](https://elevenlabs.io/pricing/api)
- [Pricing](https://elevenlabs.io/pricing)
- [Eleven Music Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms)
- [Pay As You Go](https://elevenlabs.io/docs/overview/administration/pay-as-you-go)
- [Eleven Music overview](https://elevenlabs.io/docs/overview/capabilities/music)
- [Compose music API](https://elevenlabs.io/docs/api-reference/music/compose)
- [Compose music with details API](https://elevenlabs.io/docs/api-reference/music/compose-detailed)
- [Create composition plan API](https://elevenlabs.io/docs/api-reference/music/create-composition-plan)
- [Music quickstart](https://elevenlabs.io/docs/eleven-api/guides/cookbooks/music)
- [Changelog 2026-06-15](https://elevenlabs.io/docs/changelog/2026/6/15)
- [Changelog 2026-07-06](https://elevenlabs.io/docs/changelog/2026/7/6)
- [API errors](https://elevenlabs.io/docs/eleven-api/resources/errors)
- 前回調査: `docs/investigations/2026-07-2264-eleven-music-api.md`
