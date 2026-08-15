# AI 動画生成サービス比較調査（Veo 3.1 基準）

- 調査日: 2026-08-10
- 価格取得日: 2026-08-10
- 対象通貨: 各公式ページの表示通貨（USD / JPY）。税は明記がある場合を除き含めない
- 調査方法: 公開されている公式サイト、公式ドキュメント、利用規約のみを閲覧した。アカウント作成、有料契約、クレジット購入、実生成は行っていない
- 比較ユースケース: 1 枚の `main.png/jpg` を始点・終点に指定し、16:9、8 秒、1080p、音声不要のループ背景を 1 本生成する

## ステータスの読み方

- **確認済み**: 2026-08-10 にログイン不要の一次情報または現行リポジトリで確認できた
- **不明**: 公開一次情報に記載がなく、アカウントを作っても確認できる保証がない
- **要アカウント確認**: 購入画面、ダッシュボード、生成 UI などログイン後の確認が必要

本稿の `seedance2.ai` は、2026-08-10 時点で `seevio.ai` へリダイレクトされる第三者サービスを指す。ByteDance Seed の公式モデル、BytePlus、Dreamina とは別主体として扱う。

## 結論

| 対象 | 判定 | Veo 3.1 に対する結論 | 次アクション |
|---|---|---|---|
| 現行 Google Veo 3.1 Fast | **採用** | **確認済み**: 現行実装は 8 秒・1080p の first/last-frame I2V を直接 API で実行でき、正規化単価は USD 0.80。今回の机上比較では置換する根拠がない | **確認済み**: 現行構成を維持する。価格またはモデル廃止告知時に再評価する |
| BytePlus ModelArk / Seedance 2.0 | **試験導入** | **確認済み**: 公式 API、first/last frame、参照動画、無音指定があり統合可能。8 秒・1080p の公開式による概算は USD 2.99 で Veo Fast の約 3.7 倍だが、参照制御は補完候補になる | **確認済み**: 課金承認を得た別 Issue で、同一静止画・プロンプト・尺による品質、継ぎ目、再試行率、実請求額を比較する。承認前は実生成しない |
| Magnific（formerly Freepik） | **見送り** | **確認済み**: API と複数動画モデルはあるが、同条件の正確なクレジット数が公開表だけでは確定せず、Veo/Seedance 等への集約レイヤーを追加する利点を定量化できない | **要アカウント確認**: 契約前に API ダッシュボードで Veo 3.1 Fast の 8 秒・1080p I2V のクレジット数、レート制限、透かしを確認し、直接 API より安い場合のみ再評価する |
| seedance2.ai → Seevio | **見送り** | **確認済み**: Seevio 独自 API はあるが、ByteDance 公式サービスではない。8 秒・1080p は 240 credits と算出できても credits の購入単価と法人主体を公開情報で確定できず、公式 BytePlus より供給網が不透明 | **要アカウント確認**: 法人名・所在地、モデル再販権、credit pack の実価格、上流障害時の SLA を書面で確認できるまでは利用しない |
| Dreamina / CapCut | **見送り** | **確認済み**: 公式の消費者向け生成 UI と出力権の規約は確認できるが、公開 API、同条件の価格、動画透かし条件を確定できず自動化要件を満たさない | **要アカウント確認**: 対象地域の購入画面で Seedance の credit 消費・商用追加条件・動画透かしを確認する。API が必要なら Dreamina UI ではなく BytePlus を評価する |

## 同一軸比較

| 比較項目 | Veo 3.1 Fast（現行） | BytePlus / Seedance 2.0 | Magnific | seedance2.ai → Seevio | Dreamina / CapCut |
|---|---|---|---|---|---|
| 運営主体・公式性 | **確認済み**: Google Cloud が Google の Veo を直接提供 | **確認済み**: BytePlus Pte. Ltd. の ModelArk が ByteDance Seed の Seedance を提供する公式企業向け経路 | **確認済み**: Magnific（formerly Freepik）の公式サービス。動画モデル自体は Google、ByteDance、Kling 等の外部モデルを含む集約型 | **確認済み**: `seedance2.ai` は Seevio へ移行済み。サイト運営名は Seevio だが法人名・所在地は **不明**。ByteDance 公式とは確認できない | **確認済み**: Dreamina の米国規約上は TikTok USDS Joint Venture LLC、商取引等に TT Commerce & Global Services が関与。地域別主体は規約により異なる |
| 対応モデル | **確認済み**: `veo-3.1-fast-generate-001`（現行設定） | **確認済み**: `dreamina-seedance-2-0-260128`、Fast 等。1080p 比較は標準 Seedance 2.0 | **確認済み**: Veo 3.1、Seedance 2.x、Kling 等の複数モデル。モデルごとに仕様・credits が異なる | **確認済み**: 独自 API 表記の `seedance-2-0`、Fast、Mini、2.5。上流提供契約・実際の推論事業者は **不明** | **確認済み**: 製品ページ上で Seedance 2.x、Veo 3.1 等を選択可能。地域・時期で表示モデルが変わる |
| 生成方式 | **確認済み**: T2V、I2V、first/last frame、参照画像 | **確認済み**: T2V、I2V first/last、画像・動画・音声の multimodal reference | **確認済み**: T2V、I2V、start/end frame、モデル依存の参照入力 | **確認済み**: T2V、I2V first/last、reference-to-video（画像・動画・音声）を API 文書に記載 | **確認済み**: 公開製品ページで T2V / I2V。first/last frame と参照動画の対象モデル別条件は **要アカウント確認** |
| 最大解像度・尺 | **確認済み**: Fast は最大 1080p、4 / 6 / 8 秒。標準は 4K 出力も対応 | **確認済み**: Seedance 2.0 は 1080p。正確な最大尺は API のモデル・入力条件に依存し、同ページの公開値だけでは **不明** | **確認済み**: video nodes はモデル依存で 720p / 1080p、2–10 秒。Veo API は 4K、4–8 秒も記載 | **確認済み**: Seedance 2.0 はモデルにより最大 4K、4–15 秒。Fast / Mini を含むモデル別上限は異なる | **要アカウント確認**: 選択モデルごとの最大解像度・最大尺は生成 UI 内で確認が必要 |
| 音声 | **確認済み**: Veo 3.1 は音声あり/なしを価格区分。現行フローは音声不要で後処理でも除去 | **確認済み**: `generate_audio` / `audio` 指定でネイティブ音声または無音を選択可能 | **確認済み**: 対応可否は選択モデル依存。Veo 3.1 API は optional audio | **確認済み**: API に `generate_audio` がある | **要アカウント確認**: モデル別の音声生成可否と credit 加算は UI 確認が必要 |
| ループ用途 | **確認済み**: 同一画像を first/last frame に渡す現行実装。生成後に音声除去と smooth 処理を行う | **確認済み**: first/last frame があり技術上適合。継ぎ目品質は未実測のため **要アカウント確認** | **確認済み**: start/end frame 対応モデルがあり技術上適合。モデル別の継ぎ目品質は **要アカウント確認** | **確認済み**: API は 2 枚で first/last frame を指定可能。実品質と上流安定性は **要アカウント確認** | **要アカウント確認**: 同一 first/last frame を確実に固定できるモデル・UI 条件と継ぎ目品質を確認する必要がある |
| API・認証・自動化 | **確認済み**: Vertex AI SDK / Google Cloud ADC。現行コードで非同期生成を自動化済み | **確認済み**: 非同期 REST API、Bearer API key、task polling。AP Southeast endpoint | **確認済み**: 非同期 REST API、polling / webhook、`x-magnific-api-key`。API key 作成にはアカウントが必要 | **確認済み**: `api.seevio.ai` の非同期 REST、polling / webhook、Bearer key。test/live key の発行は **要アカウント確認** | **不明**: Dreamina 消費者サービスの公開生成 API は公式ページで確認できない。規約は automated scripts による interaction を禁じるためブラウザ自動化は不採用 |
| 商用利用・生成物の権利 | **確認済み**: Google は生成出力の新規 IP に所有権を主張しない。利用者は Google Cloud 条件・適用法を順守する | **確認済み**: BytePlus は当事者間で output の所有権を主張せず customer data と扱う。利用者が権利・適法性を負う | **確認済み**: paid plan は Commercial AI license。入力・生成動画の権利を利用者が保持すると公式ページに記載 | **確認済み**: Seevio 規約は生成物を利用者所有、個人・商用利用可と記載。ただしモデル提供者側の追加条件は **不明** | **要アカウント確認**: 米国規約では順守を条件に Input / Output を利用者所有とする一方、規約本文の生成例は画像で、動画機能や商用目的には追加条件が適用され得る |
| 透かし・来歴 | **確認済み**: C2PA をサポート。可視透かしの有無は公開モデル仕様では **不明** | **確認済み**: API に watermark boolean。生成 credential / watermark / metadata の不正除去は AUP で禁止 | **確認済み**: pricing に metadata export & lineage。動画の可視透かしは **要アカウント確認** | **確認済み**: API に `watermark` boolean。実際に無透かしが契約プランで許可される条件は **要アカウント確認** | **確認済み**: Safety Guide はダウンロード画像の可視 AI watermark を明記。動画の透かし条件は **不明** |
| 地域制限 | **確認済み**: 現行 Fast model は `us-central1` で利用。Google Cloud の契約・輸出管理に従う | **確認済み**: 公開 API は `ap-southeast` endpoint。利用可能国の完全な一覧は **不明** | **確認済み**: pricing は regional restrictions が適用されると明記。対象国一覧は **不明** | **不明**: 利用可能地域、データ処理地域、輸出規制対象国の公開一覧を確認できない | **確認済み**: 規約は地域でサービス・機能・言語が異なり、全地域提供を保証しない。日本での個別機能提供は **要アカウント確認** |

## 8 秒・1080p の価格正規化

画像 1 枚を入力する I2V、16:9、8 秒、1080p、音声なしを基準とする。品質・成功率・再生成回数は含まない。

| 対象 | 公開価格・credit 条件（2026-08-10） | 8 秒・1080p 1 本 | 換算根拠・限界 |
|---|---|---|---|
| Veo 3.1 Fast | **確認済み**: USD 0.10 / 秒（video-only 1080p）。音声付きは USD 0.12 / 秒 | **確認済み**: **USD 0.80** = 8 × 0.10 | **確認済み**: Vertex AI の秒単価。税、保存・転送料、失敗後の再生成は除外 |
| BytePlus Seedance 2.0 | **確認済み**: 画像入力を含む「input without video」は USD 7.7 / 1M tokens。推定 token 式は `(input video duration + output duration) × width × height × fps / 1024` | **確認済み（公開式による概算）**: **USD 2.99**。`8 × 1920 × 1080 × 24 / 1024 = 388,800 tokens`、`0.3888 × 7.7 = 2.99376` | **確認済み**: 24 fps は Seedance の公開計算例に合わせた前提。公式文書も token 数を estimate としており、実請求は出力 token 数による。入力動画なし、成功生成のみ課金 |
| Magnific | **確認済み**: 日本向け年払い表示は Premium JPY 1,950/月相当・240K credits/年、Premium+ JPY 4,875/月相当・600K/年、Pro JPY 31,650/月相当・4M/年（VAT・地方税別）。例: Seedance 2.0 1080p は 5,600 credits / 4 秒 | **要アカウント確認**: **換算不能** | **確認済み**: 8 秒指定時の同モデルの credit 数、API と UI の同一料金、追加 credit 単価が公開表から確定しない。年額を単純に credits で割るとプラン内の他機能価値を誤配分するため換算しない |
| seedance2.ai → Seevio | **確認済み**: Seedance 2.0 1080p は動画入力なし 30 credits / 秒、動画入力ありは入力+出力時間に対し 20 credits / 秒 | **確認済み（credits）**: **240 credits** = 8 × 30。法定通貨額は **要アカウント確認** | **確認済み**: 公開ページに credit 消費はあるが、ログアウト状態で plan / credit pack の金額と換算率を確定できない。画像は「動画入力なし」に分類 |
| Dreamina / CapCut | **確認済み**: 無料 credits と有料 subscription の存在は公式ページ・規約に記載 | **要アカウント確認**: **換算不能** | **要アカウント確認**: 地域別購入画面の価格、Seedance 2.x の 1080p・8 秒 credit 消費、失敗時返還条件が公開ページだけでは確定しない |

比較上、公開情報だけで金額まで正規化できたのは Veo 3.1 Fast と BytePlus である。BytePlus の USD 2.99 は実請求額ではなく公式式による推定なので、予算化には課金承認後の請求ログ確認が必要となる。

## 現行フローとの対応

現行の `.claude/skills/thumbnail/config.default.yaml::loop` は `veo-3.1-fast-generate-001`、1080p、8 秒を選び、`src/youtube_automation/infrastructure/media/veo_generator.py` は同じ静止画を first frame と last frame に渡す。生成後は音声を除去し、`loop-video` 側の後処理で smooth 処理を行う。

| 必須契約 | Veo 3.1 | BytePlus | Magnific | Seevio | Dreamina |
|---|---|---|---|---|---|
| 静止画 I2V | **確認済み** | **確認済み** | **確認済み** | **確認済み** | **確認済み** |
| 同一 first / last frame | **確認済み** | **確認済み** | **確認済み（対応モデルのみ）** | **確認済み** | **要アカウント確認** |
| 8 秒 | **確認済み** | **確認済み** | **確認済み（対応モデルのみ）** | **確認済み（API 例）** | **要アカウント確認** |
| 1080p | **確認済み** | **確認済み** | **確認済み（対応モデルのみ）** | **確認済み（Seedance 2.0）** | **要アカウント確認** |
| API で無人実行 | **確認済み** | **確認済み** | **確認済み** | **確認済み** | **不明（公開 API なし）** |
| 商用 YouTube 利用の公開根拠 | **確認済み（Cloud 規約）** | **確認済み（ModelArk 規約）** | **確認済み（paid plan）** | **確認済み（Seevio 自身の規約のみ。上流条件は不明）** | **要アカウント確認（追加商用条件の可能性）** |

## 一次情報

### Google Cloud / Veo 3.1

- [Veo 3.1 model documentation](https://cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate): 生成方式、解像度、尺、リージョン、C2PA
- [Vertex AI generative AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing): video-only / audio の秒単価
- [Google Cloud Service Specific Terms](https://cloud.google.com/terms/service-terms): Generated Output の知的財産とデータ取扱い

### ByteDance Seed / BytePlus

- [ByteDance Seedance 2.0](https://seed.bytedance.com/en/seedance2_0): モデル開発元と multimodal 機能
- [BytePlus ModelArk model pricing](https://docs.byteplus.com/docs/ModelArk/1099320): model ID、USD / token、token 推定式
- [BytePlus video generation API](https://docs.byteplus.com/en/docs/modelark/1520757): 非同期 task、I2V / reference、音声、watermark
- [BytePlus API key authentication](https://docs.byteplus.com/en/docs/ModelArk/1521309): Bearer API key
- [Specific Terms for BytePlus Video Generation Model Services](https://docs.byteplus.com/en/docs/modelark/Specific_Terms_for_the_BytePlus_Video_Generation_Model_Services): output、customer data、学習利用
- [BytePlus GenAI Acceptable Use Policy](https://docs.byteplus.com/en/docs/legal/acceptable_use_policy_byteplus_genai/): watermark / metadata 等の制限

### Magnific

- [Magnific pricing](https://www.magnific.com/pricing): JPY plan、年間 credits、commercial license、モデル別消費例
- [AI credits and limits](https://www.magnific.com/ai/docs/ai-credits-and-limits): credit 消費条件
- [Video nodes](https://www.magnific.com/ai/docs/video-nodes): start/end frame、参照、解像度、尺
- [Magnific API authentication](https://docs.magnific.com/authentication): API key と rate limit
- [Veo 3.1 image-to-video API](https://docs.magnific.com/api-reference/image-to-video/veo-3-1/overview): 解像度、尺、音声
- [Magnific AI video generator](https://www.magnific.com/ai/video-generator): 商用 license、入力・出力の権利、学習利用

### seedance2.ai / Seevio（第三者サービス自身の情報）

- [Seedance2.ai migration notice](https://seevio.ai/ja/seedance2-ai-migration): `seedance2.ai` から Seevio への移行
- [Seevio pricing](https://seevio.ai/ja/pricing): model / resolution 別 credits
- [Seevio API docs](https://seevio.ai/ja/api-docs): 独自 endpoint、認証、生成方式、watermark
- [Seevio Terms of Service](https://seevio.ai/ja/terms-of-service): サイト運営名、生成物の権利、商用利用
- [Seevio Privacy Policy](https://seevio.ai/ja/privacy-policy): prompts / input / output とモデル学習

これらは Seevio が自ら掲示する一次情報ではあるが、ByteDance との公式提携、モデル再販権、法人登記を裏付ける ByteDance / BytePlus 側資料ではない。

### Dreamina / CapCut

- [Dreamina product page](https://dreamina.capcut.com/productivity): T2V / I2V、利用可能モデル、free credits
- [Dreamina US Terms of Service](https://dreamina.capcut.com/clause/dreamina-terms-of-service?store_region=us): 米国運営主体、地域差、Output の権利、商用追加条件、自動 script 制限
- [Dreamina User Safety Guide](https://dreamina.capcut.com/clause/dreamina-user-safety-guide): AI watermark

## 未確認事項

- **要アカウント確認**: Magnific の 8 秒・1080p・I2V の正確な credits、追加 credits 単価、API rate limit、可視透かし
- **不明**: Seevio の法人名・所在地、ByteDance との契約関係、上流モデルの追加利用条件、処理地域、SLA
- **要アカウント確認**: Seevio の credits 購入単価と、240 credits の法定通貨額
- **要アカウント確認**: Dreamina の地域別価格、モデル別 credits、first/last frame、動画透かし、商用利用の追加条件
- **不明**: Dreamina 消費者サービスの公開生成 API。BytePlus API は別サービスであり Dreamina API とみなしていない
- **要アカウント確認**: BytePlus の実 token 数、実請求額、ループ継ぎ目品質、再試行率

以上は未確認のまま採用判断へ進めず、推測で補完しない。
