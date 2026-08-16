# OpenRouter 経由と現行 AI 呼び出しのコスト比較

- 調査日: 2026-08-16
- 価格取得日: 2026-08-16
- 対象通貨: USD（税、為替、保存・転送費は含めない）
- 調査方法: ログイン不要の公式ドキュメント、公式モデルページ、現行リポジトリだけを確認した。OpenRouter アカウント作成、credit 購入、課金、実 API 呼び出しは行っていない
- 判定対象: OpenRouter を新しい中継 provider として導入すること。OpenRouter 上の安価なモデルが Vertex AI からも同額で直接使える場合、モデル変更の余地はあっても OpenRouter の採用理由には数えない

## ステータスの読み方

- **確認済み**: 2026-08-16 にログイン不要の一次情報または現行リポジトリで確認できた
- **不明**: 公開一次情報に記載がなく、推測で補わない
- **要アカウント確認**: dashboard、購入画面、利用 tier などログイン後にしか確定できない
- **採用**: 机上比較だけでも現行経路より明確な総合優位がある
- **試験導入**: 最低要件と価格優位は確認できたが、別 issue で品質・請求・運用を少額検証する必要がある
- **見送り**: 同一モデルでは安くならない、または安価な代替を OpenRouter で選ぶ固有の利点がない

## 結論

**9 用途すべてで OpenRouter 導入を見送る。** 同一モデル中継は公開モデル単価が直 API と同じで、credit 購入時に 5.5%（最低 USD 0.80）の fee が加わる。安価な Gemini / Veo 代替はあるが、Google Cloud の公開価格にも同じモデル・同じ単価があり、既存の Vertex AI + Application Default Credentials（ADC）を維持したままモデルだけ比較できる。OpenRouter を挟むと新しい API キー、provider routing、別の rate limit、データ取り扱い確認が増える。

OpenRouter は inference price に markup を載せないと説明しているため、「OpenRouter 表示単価」と「OpenRouter credit の実効取得費」を分けて扱う。以下の式で `P` はモデル表示単価による推論費、`P × 1.055` は最低購入額の影響を無視した credit 購入 fee 込み概算である。BYOK も月 100 万リクエスト超は同一 model/provider cost の 5% fee がかかる。

## 対象と最低要件

| 用途 | 現行呼び出し箇所・モデル | 最低要件 | OpenRouter の代替可否 |
|---|---|---|---|
| コメント返信生成 | `src/youtube_automation/application/comments/generator.py:87` / `comments.generator.model`（config 必須） | 日本語テキスト入力・出力、現行 JSON decode 契約 | **代替モデルあり**: config のモデルが OpenRouter 掲載モデルなら同一モデル中継も可能。安価候補は `google/gemini-3.1-flash-lite` |
| 競合サムネイル分析 | `src/youtube_automation/commands/analytics/benchmark_collector.py:786` / `gemini-3.5-flash` | 画像入力、JSON 構造化出力、複数画像の比較 | **代替モデルあり**: `google/gemini-3.1-flash-lite`。`google/gemini-3.5-flash` の同一モデル中継も可能 |
| サムネイル検査 | `src/youtube_automation/commands/thumbnail/thumbnail_check.py:157` / `gemini-3.5-flash` | 画像入力、JSON 構造化出力、日本語指摘 | **代替モデルあり**: `google/gemini-3.1-flash-lite`。同一モデル中継も可能 |
| 動画解析 | `src/youtube_automation/infrastructure/media/video_analyzer.py:97` / skill-config `model` | 動画入力、時間軸を含む JSON 構造化出力 | **代替モデルあり**: `google/gemini-3.1-flash-lite` は video input を公開仕様で確認。同一モデル可否は config 値による |
| 画像生成（既定 provider） | `src/youtube_automation/infrastructure/media/image_provider/gemini.py:74` / `gemini-3.1-flash-image` | text-to-image、画像参照 edit、16:9、1K 以上 | **代替モデルあり**: 同一モデル中継に加え `google/gemini-3.1-flash-lite-image` が 1K、14 aspect ratios、編集・複数画像合成に対応 |
| 画像生成（OpenAI provider） | `src/youtube_automation/infrastructure/media/image_provider/openai.py:98` / `gpt-image-2` | generation/edit、参照画像、16:9、high quality | **同一モデル中継**: `openai/gpt-image-2` は利用可能。安価な別画像モデルはあるが、品質互換は未実測 |
| ループ動画（Veo） | `src/youtube_automation/infrastructure/media/veo_generator.py:172` / `veo-3.1-fast-generate-001` | 同一画像の first/last frame、8 秒、1080p、16:9、音声不要 | **同一モデル中継**: `google/veo-3.1-fast` は first/last frame と 1080p に対応。Veo 3.1 Lite は安いが、公開モデル説明から last-frame 固定を確認できず要件充足代替は **代替なし** |
| ループ動画（Omni） | `src/youtube_automation/infrastructure/media/omni_generator.py:22` / `gemini-omni-flash-preview` | image-to-video、16:9、動画出力、URI/inline delivery | **代替モデルあり**: 同一 Omni model は公開 catalog で確認できない。Veo は画像→動画の機能代替だが Interactions / Files API 互換ではない |
| 楽曲生成 | `src/youtube_automation/infrastructure/media/lyria_client.py` / `lyria-3-pro-preview`・`lyria-3-clip-preview` | text/image-to-music、vocal/instrumental、歌詞、最大約 184 秒または 30 秒の MP3 | **代替なし**: OpenRouter の audio/TTS は音声入出力・読み上げであり、公開 catalog から Lyria 3 または同等の music-generation endpoint を確認できない |

OpenRouter の structured outputs は対応モデルで JSON Schema を使え、`require_parameters: true` で非対応 provider を除外できる。ただし各現行 schema と応答品質の互換は実生成なしでは確認できない。動画理解の候補は URL 入力例が公開されているが、現行のローカル動画 upload、長尺上限、token 数は別途確認が必要である。

## 代表ユースケースによる価格正規化

すべて 2026-08-16 取得。トークン単価は 100 万 token 当たり。OpenRouter の表示単価が直 API と同じ場合でも、credit 購入 fee は表の金額に含めず「さらに概算 5.5%」と記す。画像・動画 token 数が入力内容に依存して公開情報だけで固定できない場合は、金額を捏造せず換算式を残す。

| 用途・固定単位 | 現行 | OpenRouter 候補 | 換算・限界 |
|---|---|---|---|
| コメント返信 1 件（入力 1,000、出力 300 tokens） | config model が必須で実値不在のため **換算不能**。仮に Gemini 3.5 Flash なら `1000×1.50/1M + 300×9/1M = USD 0.0042` | Gemini 3.1 Flash Lite: `1000×0.25/1M + 300×1.50/1M = USD 0.00070`、credit fee 前 | 候補は約 83% 安いが、Vertex AI 直でも同じ USD 0.25 / 1.50。OpenRouter 固有の差額ではない |
| 競合サムネイル分析 1 枚（画像 token `I` + text 1,000、出力 500） | Gemini 3.5 Flash: `(I+1000)×1.50/1M + 500×9/1M` | Gemini 3.1 Flash Lite: `(I+1000)×0.25/1M + 500×1.50/1M`、credit fee 前 | `I` は画像 token 化に依存するため **換算不能**。同一 `I` なら候補の単価は低いが Vertex 直にも同額候補あり |
| サムネイル検査 1 枚（画像 token `I` + text 1,000、出力 500） | Gemini 3.5 Flash: `(I+1000)×1.50/1M + 500×9/1M` | Gemini 3.1 Flash Lite: `(I+1000)×0.25/1M + 500×1.50/1M`、credit fee 前 | `I` が未確定で **換算不能**。JSON の品質・fail-closed 契約も未実測 |
| 動画解析 10 分（動画 token `V` + text 1,000、出力 1,000） | skill-config model が実行時決定のため **換算不能**。Gemini 3.5 Flash なら `(V+1000)×1.50/1M + 1000×9/1M` | Gemini 3.1 Flash Lite: `(V+1000)×0.25/1M + 1000×1.50/1M`、credit fee 前 | frame sampling と `V`、OpenRouter の local file delivery が未確定。Vertex 直の同額候補を先に比較できる |
| Gemini 画像 1 枚（1K、入力画像なし） | Gemini 3.1 Flash Image: image output **USD 0.067** + text input | 同一モデルは同額表示 + credit fee。Flash Lite Image は **USD 0.034** + text input + credit fee | `1120×60/1M = 0.0672`、Lite は `1120×30/1M = 0.0336`。Lite は Vertex 直も USD 0.034 なので OpenRouter は安くない |
| GPT Image 2 画像 1 枚（1536×864、high、16:9） | 画像 output は USD 30 / 1M image tokens、入力は text USD 5 / 1M・image USD 8 / 1M。固定出力 token 数が公式モデルページだけでは得られず **換算不能** | OpenRouter 公式の同条件実例は **USD 0.13** + 入力分、さらに credit fee | OpenRouter は OpenAI 1 provider へ直接転送するため価格裁定なし。入力画像数・prompt で総額は変動 |
| Veo ループ動画 1 本（8 秒、1080p、音声なし） | Veo 3.1 Fast: `8×0.10 =` **USD 0.80** | OpenRouter は同一 model を掲載するが landing page は `from` 表示で、1080p・無音の組合せ単価を公開 HTML から確定できず **換算不能** | OpenRouter の Video Models endpoint は SKU を返すが、実 API 呼び出しをしない本調査では取得していない。直 API より安い根拠はない |
| Omni ループ動画 1 本（公開単価に合わせ 8 秒、720p） | `5792 tokens/s × 8 × USD 17.50/1M = USD 0.81088`（公式説明の概算 USD 0.10 / 秒なら **約 USD 0.80**） | 同一 Omni model は確認できず **換算不能**。Veo Fast は別 API・別生成物 | 現行実装は duration を送らないため、8 秒は比較用仮定。実際の応答尺と請求は **要アカウント確認** |
| Lyria 楽曲 1 本（Pro 最大約 184 秒）/ preview 30 秒 | Pro **USD 0.08 / full song**、Clip **USD 0.04 / 30 秒** | 要件を満たす music model が公開 catalog にないため **換算不能** | TTS の秒・文字単価を音楽へ流用しない。現行単価が既に低く、OpenRouter 比較対象がない |

## 用途別判定

| 用途 | 判定 | 価格・非価格を合わせた理由 | 次アクション |
|---|---|---|---|
| コメント返信生成 | **見送り** | 現行 model が config 依存で差額を確定できない。Flash Lite は安いが Vertex AI 直にも同額で、OpenRouter API キーと fee を増やす理由がない | 実績 model と token 数を `analysis` cost log で確認後、必要なら Vertex 直の Flash Lite 品質比較を別 issue 化 |
| 競合サムネイル分析 | **見送り** | 同一 Gemini 3.5 Flash は同額 + fee。Flash Lite は安いが Vertex 直でも同額で、画像比較と JSON 品質は未実測 | OpenRouter ではなく現行 ADC 経路の model-only A/B を候補にする |
| サムネイル検査 | **見送り** | 同上。検査漏れは制作 gate を弱めるため、机上単価だけで置換できない | 保存済み画像と期待 JSON によるオフライン評価を別 issue で設計する |
| 動画解析 | **見送り** | 動画 token 数、local upload、時間軸 JSON の互換が不明。安価候補は Vertex 直にもある | 現行 cost log から 10 分当たり実 token / USD を先に取得する |
| 画像生成（Gemini） | **見送り** | 同一モデル中継は同額 + fee。Lite は約半額だが Vertex 直で同額、ADC と既存 retry/response 契約を維持できる | 品質を比較するなら Vertex 直 `gemini-3.1-flash-lite-image` を別 issue で試験導入する |
| 画像生成（OpenAI） | **見送り** | OpenRouter も単一 OpenAI provider への転送で価格裁定がない。新 key と中継障害面だけ増える | 現行 OpenAI provider を維持。別モデル比較は provider seam で独立評価する |
| ループ動画（Veo） | **見送り** | 同一 Google Vertex backend で、OpenRouter の 1080p 無音価格優位を確認できない。video generation は ZDR 対象外 | 現行 ADC + operation recovery を維持。Lite の last-frame 対応が公式化されたら Vertex 直で再評価する |
| ループ動画（Omni） | **見送り** | exact model relay なし。Veo 代替は API・delivery・生成特性が異なり、同条件で安いと確定できない | Omni の実尺・実請求を取得できる運用データが揃ってから比較する |
| 楽曲生成 | **見送り** | OpenRouter に最低要件を満たす music model を確認できず、現行 Lyria は Pro USD 0.08 / 曲と安い | Lyria を維持。OpenRouter が music output と同等制御を公式掲載した時だけ再調査する |

## 非価格要因

| 論点 | 現行 | OpenRouter 導入時の差分 |
|---|---|---|
| 認証・secret | Google 系は Vertex AI + ADC。OpenAI 画像だけ既存 secret resolver を使う | `OPENROUTER_API_KEY` の発行・保管・rotation と `infrastructure/secrets.py::_SECRET_REFS` 登録が必要。既存 ADC 統一規約から逸脱する |
| provider 制御 | project / location / model をコードと config で明示 | 既定 routing は価格・安定性等で endpoint を選び fallback する。再現性には provider pin、`require_parameters`、fallback policy が必要 |
| レート制限 | Google Cloud quota と OpenAI usage tier。Lyria は公開仕様で base model 当たり 10 requests/min | OpenRouter 自身と upstream provider の両方を考慮する。公開 FAQ の free model 上限は 50 requests/day、USD 10 以上の credits 購入後は 1,000/day。paid model の実上限は account / provider 状態を含み **要アカウント確認** |
| 障害面 | SDK / direct endpoint と provider の二者 | OpenRouter の 402（credits）、429（rate limit）、503（eligible provider なし）と upstream failure が追加される。fallback は便利だが model/provider の固定性と引き換え |
| データ取り扱い | Vertex AI / OpenAI の現行契約で直接処理 | OpenRouter 自身は prompt / completion を既定で保存しないと説明する一方、各 provider の保持・学習 policy は endpoint ごとに異なる。data collection / ZDR filter が必要 |
| ZDR | 現行 provider 契約に従う | OpenRouter は unknown policy を保守的に retain/train 扱いできる。ただし video generation は asynchronous retrieval のため ZDR 非対応と明記されている |
| 費用記録 | `cost_tracker.py` の category / unit と provider 応答を現行フローで記録 | model slug、OpenRouter usage cost、credit fee を区別する必要がある。既存月次 log と単純比較できるかは **不明** |

## 採用するとした場合の挿入 seam

本 issue では変更しない。将来採用する場合、コメントは `comments.generator.provider`、画像は `image_generation.provider` の既存 factory seam に追加し、API key は `infrastructure/secrets.py::_SECRET_REFS` へ登録する。分析・動画・音楽は現在 provider seam が統一されていないため、各 domain の typed interface を先に定義する必要がある。`cost_tracker.py` では category / unit を維持し、model 名と OpenRouter 表示 cost、credit fee を混同しない。

## 一次情報

以下はすべて 2026-08-16 取得。

### OpenRouter

- [FAQ](https://openrouter.ai/docs/faq): inference price は provider price を markup なしで転送、credit 購入 fee 5.5%（最低 USD 0.80）、BYOK fee、既定ログ方針、free model rate limit
- [Pricing](https://openrouter.ai/pricing): pay-as-you-go fee と provider / model 集約の概要
- [Provider selection](https://openrouter.ai/docs/guides/routing/provider-selection): provider routing、fallback、price / parameter / data policy filter
- [Structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs): JSON Schema と `require_parameters`
- [Provider logging](https://openrouter.ai/docs/guides/privacy/provider-logging/): endpoint ごとの保持・学習 policy
- [Zero Data Retention](https://openrouter.ai/docs/guides/features/zdr): ZDR endpoint filtering と unknown policy の扱い
- [Errors and debugging](https://openrouter.ai/docs/api/reference/errors-and-debugging): 402 / 429 / 503 と `Retry-After`
- [Gemini 3.5 Flash](https://openrouter.ai/google/gemini-3.5-flash/providers): USD 1.50 / 9.00、Google Vertex / AI Studio endpoint
- [Gemini 3.1 Flash Lite](https://openrouter.ai/google/gemini-3.1-flash-lite): multimodal input、USD 0.25 / 1.50
- [Gemini 3.1 Flash Image](https://openrouter.ai/google/gemini-3.1-flash-image): same-model image generation と provider
- [Image generation](https://openrouter.ai/docs/guides/overview/multimodal/image-generation): image API、capability / endpoint price discovery、GPT Image 2 の 1536×864 high 実例 USD 0.13
- [GPT Image 2](https://openrouter.ai/openai/gpt-image-2): same-model relay と provider 数
- [Video generation](https://openrouter.ai/docs/guides/overview/multimodal/video-generation): async API、first/last `frame_images`、resolution、ZDR 非対応
- [Veo 3.1 Fast](https://openrouter.ai/google/veo-3.1-fast): same-model relay、対応機能、`from` price
- [Google model catalog](https://openrouter.ai/google): Flash Lite、image、Veo 各候補。Lyria / Omni の公開掲載有無も同ページを確認

### Google Cloud / Gemini API

- [Vertex AI generative AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing): Gemini 3.5 Flash、3.1 Flash Lite、画像 output、Veo、Lyria、Omni の直接価格
- [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing): `gemini-omni-flash-preview` の入力・動画出力 token 単価と約 USD 0.10 / 秒
- [Lyria 3 model documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/lyria/lyria-3): model ID、出力尺、機能、quota

### OpenAI

- [GPT Image 2 model](https://developers.openai.com/api/docs/models/gpt-image-2): modalities、generation/edit endpoints、rate limits
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing): GPT Image 2 の text / image token 単価

## 未確認事項

- **要アカウント確認**: OpenRouter paid workspace の実 rate limit、credit 購入時の税・決済通貨、model/provider ごとの利用可能地域
- **不明**: OpenRouter 上の 1080p・無音 Veo 3.1 Fast SKU のログアウト状態での確定単価。公開 Video Models API の取得は実 API 呼び出し禁止に合わせて行っていない
- **不明**: `comments.generator.model` と動画解析 skill-config の下流実値、および代表実行の input / output token 数
- **要アカウント確認**: Omni の実出力尺・実 token 数、各 provider の実請求、失敗時返金、OpenRouter fallback 後の請求主体
- **不明**: OpenRouter が Lyria 3 / Omni exact relay または同等 music generation を今後提供する時期
- **要アカウント確認**: ZDR / data collection filter を適用したときに各候補で残る endpoint と、その endpoint 固有 rate limit

未確認事項は採用理由に使わず、アカウント作成・課金・実生成が必要な検証は別 issue に分離する。
