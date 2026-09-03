# fal 上の MiniMax H3 Max / H3 Max Turbo image-to-video モデル仕様調査

- 調査日: 2026-09-03
- 価格取得日: 2026-09-03
- 対象エンドポイント: `minimax/h3-max/image-to-video`、`minimax/h3-max-turbo/image-to-video`（比較対象として `minimax/h3/image-to-video` と両者の `text-to-video`）
- 調査方法: ログイン不要の一次情報のみを閲覧した。fal のモデルページ・`/api` タブ・OpenAPI schema、fal 公式 docs / blog / ランディングページ、MiniMax 公式（platform.minimax.io の API リファレンス、GitHub `MiniMax-AI/MiniMax-H3` README、Hugging Face モデルカード、diffusers 公式 docs）、OpenRouter のモデルページ。アカウント作成、API 呼び出し、サンプル動画のダウンロードは行っていない
- 関連 issue: #4894（本チケット）、#4892（wayfinder map）
- 比較ユースケース: 1 枚の `main.png/jpg` を始点・終点に指定し、16:9 または 9:16、8 秒、音声不要のループ背景を 1 本生成する

## ステータスの読み方

- **確認済み**: 2026-09-03 にログイン不要の一次情報で確認できた
- **不明**: 公開一次情報に記載がなく、アカウントを作っても確認できる保証がない
- **要アカウント確認**: fal アカウントと `FAL_KEY` で実生成しないと確定できない（USD 5 の実測比較の中で確認する項目）

一次情報の層を区別する。**fal schema** は OpenAPI（機械契約）、**fal 文書** はモデルページ・docs・blog・ランディングページ、**MiniMax 公式** は platform.minimax.io / GitHub / HF / diffusers docs。diffusers docs はオープンウェイト版 H3 の実装契約であり、fal がホストする post-trained 版 H3 Max / Turbo の挙動と一致する保証はないため、H3 Max 固有の確定には使わず「基盤モデルの性質」として引く。

## 結論

| # | 質問 | 判定 | 要旨 |
|---|---|---|---|
| 1 | 同一画像を `image_url` / `end_image_url` に渡す keyframe ループ | **要アカウント確認** | 2 枚指定の first-to-last keyframe 生成自体は **確認済み**（fal schema・fal 文書・MiniMax 公式）。「同一画像で first = last」の挙動は一次情報に記載なし。基盤モデル（diffusers）では first は canvas へ **stretch**、last は **cover-crop** されるため、入力比が canvas 比（1344×768 = 1.75）とずれると first と last が厳密に同一にならない |
| 2 | アスペクト比・9:16・768P 実寸 | 16:9 実寸 **確認済み**、9:16 出力 **確認済み（文書）/ 実寸 不明** | i2v の出力比は **入力画像に従う**（fal schema に明記）。T2V の対応比は 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16。16:9 は **1344×768 @ 24 fps**。9:16 の実寸は公開値なし。基盤モデルは「短辺 768・32 の倍数」なので 768×1344 と **推定** |
| 3 | 音声トラック | **確認済み（音声は常に付く）** / 無音指定 **不明（schema に無い）** | 「Every generation comes back with synchronized audio」。基盤モデルは 32 kHz ステレオを映像と同時生成。schema に音声 on/off パラメータは無く、`strip_audio` 相当の後処理が必須 |
| 4 | fps・コーデック・ビットレート | fps **確認済み（24）**、コンテナ **確認済み（video/mp4）**、コーデック・ビットレート **不明** | 24 fps は fal 文書と MiniMax 公式で一致。出力は `content_type: video/mp4`。H.264 / H.265 の別と平均ビットレートは記載なし。ページのサンプル（5 秒・768P）は 3,601,950 bytes ≈ 5.8 Mbps（音声込み、**推定**） |
| 5 | `prompt_expansion_mode` の書き換えと無効化 | 動作 **確認済み（部分）**、抑制系プロンプトの既知報告 **不明**、無効化 **不明** | Max / Turbo schema は **必須**フィールドで、例示値は `balanced`（約 1 秒）/ `quality`（最大約 30 秒）のみ。`enum` は無い。fal ランディングは `fast` にも言及するが Max / Turbo の schema には無い。無効化オプションは無い（無印 h3 のみ nullable）。expansion は「integrated_multimodal_description / overall_soundscape / non_diegetic_music」構造へ書き換え、**音の指示を追加する**。静止カメラの抑制が崩れる報告は一次情報に無い |
| 6 | `duration` 8 の受理 | **確認済み（schema）** / 実受理 **要アカウント確認** | `integer`、`minimum: 5`、`maximum: 15`、`enum` なし。MiniMax 公式でも H3-Max は「5–15 秒、整数」。基盤モデルは 24 fps × 8 s = 192 フレームで、VAE の `17n+5` 格子（n=11）に**ちょうど乗る** |
| 7 | `seed` 再現性 / `enable_safety_checker=false` | seed **確認済み（fal 一般則）/ 本 endpoint では不明**、safety checker false の影響 **不明** | fal の共通引数 docs は「同じ seed + 同じ入力 = 同じ結果」。ただし prompt expansion（LLM 書き換え）が seed の管轄外なら再現は保証されない（記載なし）。safety checker の docs は画像向け（NSFW を黒画像に置換）で、動画 endpoint での false 時の挙動は記載なし |
| 8 | Max と Turbo の差の公称 | 価格 **確認済み**、品質差・速度差の公称 **不明** | 説明文は両者で**完全に同一**、schema も title まで同一（`TurboImageToVideoHailuo03Input`）。差は価格（768P: Max 0.08 / Turbo 0.04 USD/s、9/7 まで 75% off で 0.02 / 0.01）とページのサンプル `timings.inference`（Max 2.77 s / Turbo 1.68 s、各 1 件）のみ。fal blog は Max のみ発表（5 秒を約 3 秒、公式 H3 endpoint の約 35 倍）。Turbo 単独の発表文書は見つからない |

## 詳細

### 1. keyframe: 同一画像を first / last に渡したときの挙動

- **確認済み**: fal schema の `end_image_url` は「Optional URL of the image to use as the last frame, for first-to-last keyframe generation.」（Max / Turbo / 無印 h3 で同文）。fal ランディングも「Give H3 Max an opening frame and, if you want, a closing one, and it animates the whole journey between them.」
- **確認済み**: MiniMax 公式（GitHub README / HF モデルカード）の `H3-Base-FL2VA` は「Two image inputs: First-and-last-frame-to-video generation」。platform.minimax.io の V2 API も `role: first_frame` / `last_frame`（各 1 枚まで）を持つ
- **不明**: 「同一画像を両方に渡す」ケースは fal・MiniMax いずれの一次情報にも記載がない。Veo の `last_frame` と意味は同じ（終端フレームの拘束）だが、同一画像で継ぎ目が閉じるかは実測事項
- **参考（基盤モデル、diffusers docs）**: `image` は「*stretched* onto the target canvas, which by default is derived from its own aspect ratio」、`last_image` は「is the follower of the two and is cover-cropped onto the canvas」。canvas は短辺 768・32 の倍数で、`canvas_max_pixels` 既定 1,032,192（= 1344×768）。16:9 入力（1.778）に対し canvas 比は 1.75 なので、**同一画像でも first は引き伸ばし・last は切り抜きとなり、厳密には同一フレームにならない**（差は約 1.6%）。fal 側が同じ前処理かは **不明**
- 設計への含意: 実測比較では `main.png` を **1344×768（または 768×1344）にあらかじめリサイズ**して渡す条件を 1 本加えると、この前処理差を切り分けられる

### 2. アスペクト比・9:16・768P の実寸

- **確認済み**: Max / Turbo の i2v schema に `aspect_ratio` は無い。`image_url` の説明が出力比の決まり方を明記する。「Optional URL of the image to use as the first frame. When provided, the output aspect ratio follows this image. When omitted, the request is handled as text-to-video (16:9 by default).」
- **確認済み**: 同 endpoint の t2v schema は `aspect_ratio` enum `21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16`（既定 16:9）を持つ。fal ランディング FAQ も「text to video covers 21:9, 16:9, 4:3, 1:1, 3:4, and 9:16. On image to video the output follows the aspect ratio of the image you pass in.」
- **確認済み（MiniMax 公式）**: V2 API の `ratio` は `adaptive / 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16`。i2v では「aspect ratio is determined by the input image and `ratio` is always `adaptive`」。入力画像の制約は幅・高さ [256, 5760] px、比 (w/h) [0.4, 2.5]。9:16（0.5625）は範囲内
- **確認済み（OpenRouter）**: `minimax/hailuo-3-max` は「768p and 480p」「21:9, 16:9, 4:3, 1:1, 3:4, 9:16」「5–15 second clips」「first/last frame」と記載
- **確認済み**: 768P の 16:9 実寸は **1344×768 @ 24 fps**（fal ランディング FAQ「At 16:9 that is 1344x768 at 24 FPS.」、diffusers docs「the trained 1344x768」）
- **不明（推定あり）**: 9:16 の実寸は公開値なし。MiniMax 公式「The shorter side is set to 768 pixels by default」と diffusers「A 768 pixel short edge ... multiples of 32」から **768×1344** と推定。任意比では canvas が 32 の倍数に丸められるため、入力比と出力比がわずかにずれ得る
- **要アカウント確認**: 9:16 入力で実際に 768×1344 が返るか、480P の実寸（記載なし。短辺 480 と推定）

### 3. 音声

- **確認済み（音声は常に付く）**: fal ランディング「Every generation comes back with synchronized audio」「Each run returns a clip of up to 15 seconds with synchronized audio」。fal blog「natively synchronized audio and video」。MiniMax 公式 README「Output audio | 32 kHz stereo」。diffusers docs「video and audio come out of the same denoising loop」で、映像と音声は分離不能に同時生成
- **確認済み（無音指定は無い）**: Max / Turbo の i2v / t2v schema に音声の on/off に相当するパラメータは存在しない（プロパティは `prompt / duration / resolution / seed / enable_safety_checker / sync_mode / prompt_expansion_mode / image_url / end_image_url` の 9 個）。MiniMax V2 API にも音声トグルは無い
- **確認済み**: prompt expansion の出力例は `overall_soundscape:` / `non_diegetic_music:` セクションを含み、**expansion 自体が音の指示を補う**。「無音」をプロンプトで指示しても expansion で環境音が足され得る（実測事項）
- 設計への含意: `strip_audio`（`-an`）は必須。Veo 経路と同じ後処理で吸収できる

### 4. fps・コーデック・ビットレート

- **確認済み**: 24 fps（fal ランディング FAQ、MiniMax README「Output frame rate | 24 FPS」、diffusers「24 fps, 5 to 15 seconds」「the fixed 24 fps」）
- **確認済み**: 出力は `video/mp4`。Max ページのサンプル応答は `"content_type": "video/mp4", "file_size": 3601950`（`_minimax-h3.mp4`）、Turbo ページは `file_size: 8277609`、Max t2v `/api` は `file_size: 6463396`
- **不明**: 映像コーデック（H.264 / H.265）、音声コーデック、ビットレート帯。fal・MiniMax いずれも記載なし。MiniMax V2 API が**入力**として受け付ける動画は H.264 / H.265 だが、出力側の記載ではない
- **推定**: Max ページのサンプル（リクエスト例は `duration: 5`、expanded prompt は 00:05.000 で終了）から 3,601,950 bytes / 5 s ≈ **5.8 Mbps**（音声込み）。Turbo サンプルは尺不明のため換算しない
- **要アカウント確認**: 実生成物の `ffprobe`（codec_name / bit_rate / pix_fmt / 音声 codec）。次アクションとしてページ掲載サンプル URL の ffprobe でも代替できる（本調査ではダウンロードを行っていない）
- **参考（基盤モデル）**: フレーム数は `17n+5` に切り上げ。5 秒指定 = 120 → 124 フレーム（≈ 5.17 s）、8 秒 = 192 = 17×11+5 でちょうど。fal が返す尺が指定秒に丸められるかは **不明**

### 5. `prompt_expansion_mode`

- **確認済み（schema）**: Max / Turbo では `required: ["prompt", "prompt_expansion_mode"]` で **必須**。`default: "balanced"`、`examples: ["balanced", "quality"]`、**`enum` なし**（型は string）。説明「'balanced' returns in about a second. 'quality' spends up to ~30s on a richer prompt.」
- **確認済み（差分）**: 無印 `minimax/h3/image-to-video` は `anyOf: [string, null]`・任意で、例示値に `fast` を含む（「'fast' returns in about a second. 'balanced' picks per request. 'quality' spends up to ~30s」）。fal ランディング FAQ も H3 Max について「fast returns in about a second and quality can spend up to 30 seconds on the rewrite alone」と 3 モードを述べるが、**Max / Turbo の schema には `fast` が無い**。`enum` が無いので `fast` を送っても schema 上は拒否されないが、受理・挙動は **要アカウント確認**
- **不明（無効化）**: expansion を無効にするパラメータは Max / Turbo schema に無い。出力 `expanded_prompt` の説明「Null when prompt expansion was disabled, left the prompt unchanged, or was performed internally by MiniMax's hosted API.」は無効化経路の存在を示唆するが、本 endpoint での指定方法は文書化されていない。無印 h3 の `null` 指定が無効化に当たるかも記載なし
- **確認済み（書き換えの形）**: ページ掲載の `expanded_prompt` は「For the target video, at 0.00 seconds into the target video, (from [Shot 1]) is fully referenced.\n\nintegrated_multimodal_description: [Shot 1] ... overall_soundscape: ... non_diegetic_music: N/A」という定型構造へ書き換える。タイムコード付きの動作記述と音の指示が追加される
- **不明（抑制系プロンプトの崩れ）**: 「Locked camera, static composition」のような抑制指示が expansion で崩される既知の報告は fal・MiniMax の一次情報に無い。fal ランディングは「Camera moves you can direct」「The camera stays locked on the subject」と追従性を主張するのみ。fal の推奨は「leave prompt expansion on balanced」
- 設計への含意: 比較条件の balanced / quality に加え、`expanded_prompt` を必ず保存して静止指示が残っているかを目視の前に機械確認する

### 6. `duration` 8 の受理

- **確認済み（schema）**: `duration` は `type: integer`、`default: 5`、`minimum: 5`、`maximum: 15`、`enum` なし。8 は範囲内
- **確認済み（MiniMax 公式）**: `MiniMax-H3-Max` は「5–15s（4 seconds not supported）、integer values only」。`MiniMax-H3` は 4–15
- **確認済み（OpenRouter）**: 「5–15 second clips」
- **要アカウント確認**: 8 が実際に受理され、返る尺が 8.00 s か（基盤モデルの `17n+5` 格子では 192 フレーム = 8.00 s でちょうど乗るため、丸め誤差は出ない見込み）
- 価格への含意: 768P・8 秒は Max USD 0.64（promo 0.16）、Turbo USD 0.32（promo 0.08）。Veo Fast 1080p の USD 0.80 に対し、通常価格でも Max 80% / Turbo 40%

### 7. `seed` と `enable_safety_checker`

- **確認済み（fal 一般則）**: fal「Common Model Arguments」docs は seed について「The same seed with the same inputs produces the same result.」。schema の説明は「Random seed. A random seed is selected when omitted.」
- **不明（本 endpoint）**: 同 docs は画像生成向けの共通引数の説明で、動画 endpoint・prompt expansion（LLM 書き換え）を含めた再現性は記載なし。expansion が seed の管轄外なら、同じ seed でも `expanded_prompt` が変わり結果が変わり得る。**要アカウント確認**（同 seed で 2 回生成し `expanded_prompt` と出力を比較）
- **参考（基盤モデル）**: diffusers「two runs from the same generator state return the same video and soundtrack」。モデル自体は決定的
- **確認済み（fal 一般則）**: `enable_safety_checker` は「If set to true, the safety checker will be enabled.」（既定 true）。fal docs では画像について NSFW 分類器で検出し、「replaced with a black image of the same dimensions」・`has_nsfw_concepts` を返すと説明。「Not all models support disabling this feature」
- **不明（動画 endpoint）**: 本 endpoint の出力 schema に `has_nsfw_concepts` は無い。false にした場合に何が変わるか（入力画像 / プロンプトの事前判定が外れるのか、出力のフレーム検査が外れるのか）は記載なし。fal の Trust & Safety ページは OpenAI omni moderation API によるモデレーションと NSFW ポリシーを述べるが、パラメータとの関係は書いていない
- 設計への含意: ループ背景（風景・抽象）では誤検知の可能性は低い。既定 true のまま運用し、false は実測で誤ブロックが出たときの逃げ道として設定可能にしておく程度でよい

### 8. Max と Turbo の差の公称

- **確認済み（同一の説明文）**: 両モデルページの説明は「fal's H3 Max [Turbo] is a post-trained variant of MiniMax H3, tuned for stronger prompt adherence and better aesthetics while co-optimized with our custom inference stack for higher throughput with no compromises on output quality」で、名称以外同一
- **確認済み（同一 schema）**: i2v の Input / Output schema は `H3MaxImageToVideoInput` / `H3MaxTurboImageToVideoInput` の名前差のみで、内部 title は両方 `TurboImageToVideoHailuo03Input` / `TurboImageToVideoHailuo03Output`
- **確認済み（価格）**: 768P は Max USD 0.08/s、Turbo USD 0.04/s。480P は Max 0.05 / Turbo 0.025。「promotional launch rates, 75% off for a limited time. The discount ends September 7」で、それまで Max 0.02 / 0.0125、Turbo 0.01 / 0.00625（Turbo t2v ページは `$0,00625` と表記揺れ）。fal blog（8/26）と PR（9/1）は「50% off for the first week」「$0.04 per second」と述べており、**割引率と表記が文書間で一致しない**。モデルページの 75% を現在値とみなす
- **確認済み（Max の速度公称）**: 「A 5-second clip at 768p renders in under 3 seconds」「roughly 35x the throughput of the official MiniMax H3 endpoint」「on average 15x faster than models of comparable quality」「timings.inference ... roughly 2.5 seconds for a 5-second 768p generation ... a 15-second clip takes around 15 seconds」
- **確認済み（サンプル値）**: ページ掲載の 1 件ずつの `timings.inference` は Max 2.765 s、Turbo 1.676 s（i2v）、Turbo t2v 1.552 s。統計値ではない
- **確認済み（品質公称は Max のみ）**: Design Arena i2v Elo 1,341、Artificial Analysis「Image-to-Video with Audio」Elo 1,201 ± 11（2,177 samples）。fal ランディングは「It is listed there under its internal name, MiniMax H3 Turbo (768p)」と述べ、**"Turbo" が H3 Max の内部名でもある**ことを示す。`h3-max-turbo` endpoint がこの内部名と同一物か、さらに蒸留・削減した別物かは **不明**
- **不明**: Turbo 単独の発表・blog・品質ベンチマーク。Max / Turbo の公称レイテンシ差
- 設計への含意: 「Turbo を既定、Max を品質フォールバック」の二段構えは公開情報では裏づけられない。実測比較で同一 `main.png`・同一 seed・同一 expansion mode で両方を回し、`timings.inference` と目視で差を見るのが唯一の判定手段

## #4892 の設計前提への影響

- **9:16 ショートは成立見込み**: i2v の出力比は入力画像追従で、9:16 は基盤モデル・MiniMax 公式・OpenRouter が対応比に含める。ただし実寸（768×1344 推定）は未公開で、要実測
- **同一画像 first = last は「意味はあるが同一性は非保証」**: keyframe 拘束としては Veo と同型。基盤モデルの前処理差（stretch / cover-crop）により、入力を canvas 実寸に合わせないと last が厳密に一致しない可能性がある。`main.png` を 1344×768 / 768×1344 に整えて渡す前処理を候補に入れる
- **音声は常に付く**: `strip_audio` 必須。expansion が音の指示を足すため、プロンプトでの無音指示は当てにしない
- **8 秒は受理見込み**: schema・MiniMax 公式とも 5–15 の整数。フレーム格子上もちょうど
- **prompt_expansion_mode は必須送信**: 省略不可。`balanced` / `quality` 以外（`fast`、無効化）は Max / Turbo で未文書化。`expanded_prompt` を必ず保存する
- **Max ↔ Turbo は config 1 行切替で問題ない**: schema 完全同一。差の根拠は価格のみで、品質差は実測でしか出ない
- **768P → 1080p アップスケール**: 16:9 は 1344×768 → 1920×1080（1.43 倍）。9:16 は 768×1344 → 1080×1920 と推定
- **fps 24 は Veo 経路と同じ**: `smooth_loop` / compression の前提は変えなくてよい。コーデックは未確定なので再エンコードを前提にする
- **価格**: 9/7 で promo 終了。通常価格で 768P・8 秒は Max 0.64 / Turbo 0.32 USD。cost tracker には通常価格を載せ、promo は載せない

## 一次情報

### fal（schema）

- [OpenAPI: minimax/h3-max/image-to-video](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3-max/image-to-video): 入出力 schema、`image_url` の出力比説明、`prompt_expansion_mode` 必須、`duration` 5–15
- [OpenAPI: minimax/h3-max-turbo/image-to-video](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3-max-turbo/image-to-video): Max と名前以外同一
- [OpenAPI: minimax/h3/image-to-video](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3/image-to-video): 無印。`resolution` に 2K / 4K、`prompt_expansion_mode` に `fast`、nullable
- [OpenAPI: minimax/h3-max/text-to-video](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3-max/text-to-video) / [h3-max-turbo/text-to-video](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3-max-turbo/text-to-video): `aspect_ratio` enum（21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16）

### fal（モデルページ・docs・blog）

- [H3 Max (Image to Video) モデルページ](https://fal.ai/models/minimax/h3-max/image-to-video) / [API タブ](https://fal.ai/models/minimax/h3-max/image-to-video/api): 説明文、価格と promo 終了日、サンプル応答（`video/mp4`、`file_size`、`expanded_prompt`、`timings.inference`）
- [H3 Max Turbo (Image to Video) モデルページ](https://fal.ai/models/minimax/h3-max-turbo/image-to-video) / [API タブ](https://fal.ai/models/minimax/h3-max-turbo/image-to-video/api): 同上（Turbo）
- [H3 Max Turbo (Text to Video)](https://fal.ai/models/minimax/h3-max-turbo/text-to-video) / [H3 Max (Text to Video) API](https://fal.ai/models/minimax/h3-max/text-to-video/api): `aspect_ratio` と価格
- [MiniMax H3 (Image to Video)](https://fal.ai/models/minimax/h3/image-to-video): 無印の価格（480p 0.05 / 768p 0.06 / 2K 0.13 / 4K 0.16 USD/s）と「aspect ratio following the input」
- [MiniMax H3 Max ランディング（FAQ）](https://fal.ai/minimax-h3-max): 1344×768 @ 24 fps、i2v は入力比追従、音声常時、速度公称、expansion 3 モード、内部名「MiniMax H3 Turbo (768p)」、「50% off for its first 14 days」
- [MiniMax H3 ランディング](https://fal.ai/minimax-h3): 2K・24 fps・ネイティブステレオ音声・対応比・「First-and-last-frame follows the aspect ratio of the uploaded image」
- [Introducing H3 Max by fal（blog, 2026-08-26）](https://fal.ai/learn/devs/introducing-h3-max-by-fal): post-training 内容、5 秒を約 3 秒、35x、Elo、50% off
- [MiniMax H3 Prompting Guide](https://fal.ai/learn/devs/minimax-h3-prompting-guide) / [MiniMax H3 Explained](https://fal.ai/learn/tools/minimax-h3-explained): 音声常時、i2v 入力比追従。expansion・同一画像・無音指定の記載なし
- [Common Model Arguments](https://fal.ai/docs/documentation/model-apis/model-arguments): seed 再現性の一般則、`enable_safety_checker` の画像向け説明
- [Asynchronous Inference（queue）](https://fal.ai/docs/documentation/model-apis/inference/queue): `queue.fal.run/{model-id}`、`request_id` / `status_url` / `response_url` / `cancel_url`、`IN_QUEUE / IN_PROGRESS / COMPLETED`
- [Data Retention & Storage](https://fal.ai/docs/documentation/model-apis/media-expiration): リクエスト入出力 JSON は既定 30 日保持、生成メディアは `X-Fal-Object-Lifecycle-Preference` で期限指定、`X-Fal-Store-IO: 0` で保存抑止
- [Trust & Safety](https://fal.ai/legal/trust-and-safety): OpenAI omni moderation API、NSFW ポリシー
- [fal Launches H3 Max（PR Newswire, 2026-09-01）](https://www.prnewswire.com/news-releases/fal-launches-h3-max-a-new-post-trained-video-model-with-frontier-quality-and-faster-than-real-time-generation-302866462.html): 速度公称、$0.04/s promo（9/7 まで）、Turbo の言及なし

### MiniMax 公式

- [Create Video Generation Task（V2 / Hailuo-03 API）](https://platform.minimax.io/docs/api-reference/video-generation-v2-create): `MiniMax-H3` / `MiniMax-H3-Max` の仕様表、`ratio`（i2v は常に adaptive）、画像制約（[256, 5760] px、w/h [0.4, 2.5]）、`first_frame` / `last_frame` 各 1 枚
- [Video Generation guide](https://platform.minimax.io/docs/guides/video-generation): H3-Max は 480P / 768P・5–15 秒、first/last-frame は画像 0 / 1 / 2 枚
- [GitHub MiniMax-AI/MiniMax-H3 README](https://github.com/MiniMax-AI/MiniMax-H3): 「Output frame rate | 24 FPS」「Output audio | 32 kHz stereo」「The shorter side is set to 768 pixels by default」、FL2VA の 0 / 1 / 2 枚
- [Hugging Face MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3): 同内容、MiniMax H3 Community License
- [diffusers docs: MiniMax-H3](https://huggingface.co/docs/diffusers/main/en/api/pipelines/minimax_h3): 24 fps 固定、`17n+5` フレーム格子、短辺 768・32 の倍数、`canvas_max_pixels` 1,032,192、`image` は stretch / `last_image` は cover-crop、generator 決定性、映像と音声の同時生成
- [MiniMax H3 発表 blog](https://www.minimax.io/blog/minimax-h3): アーキテクチャ、ネイティブステレオ音声、768p / 2K

### OpenRouter

- [minimax/hailuo-3-max](https://openrouter.ai/minimax/hailuo-3-max): 「768p and 480p」「21:9, 16:9, 4:3, 1:1, 3:4, 9:16」「5–15 second clips」「first-frame or last-frame keyframes」、価格 480p 0.05 / 768p 0.08 USD/s、fal と共同リリース
