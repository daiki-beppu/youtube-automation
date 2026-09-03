# fal.ai queue API の契約調査（MiniMax H3 Max / H3 Max Turbo image-to-video）

- 調査日: 2026-09-03
- 価格取得日: 2026-09-03
- 対象通貨: USD（fal 公式ページの表示通貨。税は含めない）
- 調査方法: fal 公式ドキュメント（`fal.ai/docs`、旧 `docs.fal.ai` は 308 で同所へリダイレクト）、公式 OpenAPI schema（`fal.ai/api/openapi/queue/openapi.json?endpoint_id=...`）、公式モデルページ、公式 Python クライアント `fal-ai/fal` の `fal_client` ソースのみを閲覧した。アカウント作成、API キー発行、有料 API 呼び出し、実生成は行っていない
- 対象 issue: #4893（wayfinder map #4892 の research チケット）
- 目的: `requests` 直叩きで `https://queue.fal.run` を呼ぶ `fal_client.py` を書くために、認証・画像入力・queue ライフサイクル・出力・料金・エラーの 6 点を確定する

## ステータスの読み方

- **確認済み**: 2026-09-03 にログイン不要の一次情報（公式 docs / OpenAPI schema / 公式クライアントのソース）で確認できた
- **不明**: 公開一次情報に記載がなく、アカウントを作っても確認できる保証がない
- **要アカウント確認**: ダッシュボード、実 API 呼び出し、実生成などログイン後の確認が必要

fal の docs は `fal.ai/docs/documentation/...` 配下の `.md` を直接取得できる（`https://fal.ai/docs/llms.txt` が索引）。本稿の引用はその `.md` 原文から取った。

## 結論

| # | 質問 | 判定 | 結論 | `fal_client.py` への含意 |
|---|---|---|---|---|
| 1 | 認証 | **確認済み** | ヘッダは `Authorization: Key $FAL_KEY`（`Bearer` ではない）。キーは `https://fal.ai/dashboard/keys` で発行、scope は **API** で足りる。環境変数の慣例は `FAL_KEY`（公式クライアントは `FAL_KEY_ID` + `FAL_KEY_SECRET` → `Key <id>:<secret>` も受ける） | `_SECRET_REFS` に `FAL_KEY` を追加し、ヘッダは `f"Key {key}"` 固定 |
| 2 | 画像入力 | **確認済み（受理）/ 不明（上限）** | `image_url` / `end_image_url` は data URI（base64）を受ける。ただし公式 docs は「数 KB を超えるファイルには推奨しない」と明記し、CDN アップロードを推奨。data URI の明示的な上限バイト数は **不明**。アップロードは `POST https://rest.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3` → `{upload_url, file_url}` → `PUT upload_url` の 2 段。署名 URL の寿命は **不明** | `main.png`（MB 級）は data URI ではなく storage upload で `file_url` を得てから submit する。アップロード直後に PUT する前提で実装し、署名 URL は使い回さない |
| 3 | queue ライフサイクル | **確認済み（形）/ 要アカウント確認（保持期間）** | submit は `{request_id, response_url, status_url, cancel_url, queue_position}`。status は `IN_QUEUE` / `IN_PROGRESS` / `COMPLETED` の 3 値のみで **失敗専用の状態はない**（`COMPLETED` + `error` / `error_type`）。`?logs=1` でログ配列。cancel は `PUT .../cancel` で 202 / 400 / 404。結果の保持は「完了後およそ 1 時間（10 KB 以上の結果はおよそ 6 分）」と webhook docs に記載。queue の result endpoint そのものの保持期間の明文は無い | resume は「完了後 1 時間以内に result を取りに行けること」を上限に設計する。`COMPLETED` を受けたら即 result 取得 → 即動画ダウンロード。`error_type` の有無で成否を判定する |
| 4 | 出力 | **確認済み（形）/ 要アカウント確認（既定寿命）** | `video: {url, content_type, file_name, file_size}` + `expanded_prompt` + `timings`。URL は `https://v3.fal.media/...` / `https://v3b.fal.media/...` で **既定は公開 URL**。寿命は FAQ が「既定で少なくとも 7 日」、Platform Headers が「アカウント設定（未設定なら forever）」と記述が揺れる。`sync_mode: true` は「CDN URL ではなく base64 で返す」のみで、上限・タイムアウトは **不明**。fps / 音声有無は schema に無く **不明** | result 取得後すぐに動画をダウンロードし、URL を永続参照にしない。`sync_mode` は使わない（保持が短くなる方向に働く）。fps / 音声は実生成後に ffprobe で確定する |
| 5 | 料金・制限 | **確認済み** | 「生成に成功した出力にのみ課金」「5xx は課金なし」「キュー待ち時間は無料」「422 でも GPU 時間を使っていれば課金され得る」。プリペイド credits（購入後 365 日で失効）。同時実行は新規アカウント **2**、購入額で最大 **40** まで自動増、超過分は queue で待つ（reject されない）。RPM 型のレート制限の記載は無し。プロモは Max / Turbo の image-to-video・text-to-video の 4 ページとも「75% off、**9 月 7 日**まで」（年は明記されず、2026 と解釈）。768P 通常単価は Max USD 0.08/s、Turbo USD 0.04/s | 予算・cost tracker は **通常単価**で持つ（プロモは調査日から 4 日で終了）。8 秒 768P = Turbo 0.32 / Max 0.64（プロモ中 0.08 / 0.16）。同時実行 2 でも loop 生成は直列なので十分 |
| 6 | エラー | **確認済み（2 形式）** | モデル側の validation error は `{"detail": [{loc, msg, type, url, ctx?, input?}]}`（422）。インフラ側の request error は `{"detail": "<string>", "error_type": "<code>"}` + `X-Fal-Error-Type` ヘッダ（5xx 系、499）。429 は `concurrent_requests_limit` type + `X-Fal-needs-retry: 1`。判別は `detail` が list か str か、`type` / `error_type` を見る。docs 自身が「全 endpoint がまだこの構造に揃っていない」と警告 | `detail` の型で分岐し、機械判定は `type` / `error_type` のみに依存する。`msg` は表示用。401 / 403 の body 形は **不明**なので status code だけで `ConfigError` 相当に落とす |

## 詳細

### 1. 認証

| 項目 | 判定 | 内容 | 出典 |
|---|---|---|---|
| ヘッダ形式 | **確認済み** | 公式 curl 例はすべて `-H "Authorization: Key $FAL_KEY"`。OpenAPI の `securitySchemes.apiKeyAuth` は `type: apiKey, in: header, name: Authorization, description: "Fal Key"` | [Get Your API Key](https://fal.ai/docs/documentation/setting-up/authentication/index.md)、[OpenAPI (turbo)](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3-max-turbo/image-to-video) |
| 公式クライアントの実装 | **確認済み** | `AuthCredentials(scheme="Key", token=...)` → `header_value = f"{scheme} {token}"`。`FAL_KEY` が無ければ `FAL_KEY_ID` + `FAL_KEY_SECRET` を `Key <id>:<secret>` に組む。無ければ「No credentials found. Set FAL_KEY (or FAL_KEY_ID/FAL_KEY_SECRET) or login via `fal auth login`.」 | [fal_client/auth.py](https://github.com/fal-ai/fal/blob/main/projects/fal_client/src/fal_client/auth.py) |
| キー発行場所 | **確認済み** | `https://fal.ai/dashboard/keys` で **Create Key**。「Copy the key immediately. You will not be able to see it again」 | 同上 authentication |
| scope | **確認済み** | **API**（Model APIs と自前 endpoint の呼び出し + API-scoped Platform APIs）/ **ADMIN**（API + CLI・deploy・admin Platform APIs）。「If you're not sure which to choose, start with **API** scope」 | 同上 |
| 環境変数 | **確認済み** | `FAL_KEY`。「The fal client libraries read your key automatically from the `FAL_KEY` environment variable」。キーはアカウント（team）に紐づき、個人に紐づかない | 同上 |
| 取り扱い | **確認済み** | FAQ: クライアント側コードに露出させず、サーバー側から呼ぶ。本リポジトリでは `os.environ` → `op read` の既存解決順に載せればよい | [FAQ](https://fal.ai/docs/documentation/model-apis/faq.md) |
| 一時トークン | **確認済み（Model API には無し）** | Model API 呼び出し用の JWT / 一時トークンの記述は無い。`POST https://rest.fal.ai/storage/auth/token?storage_type=fal-cdn-v3` は **CDN の非公開ファイル読み取り用 Bearer トークン**（最長 30 日）で、queue 呼び出しには使わない | [File Access Controls](https://fal.ai/docs/documentation/model-apis/file-access-controls.md) |

### 2. 画像入力（`image_url` / `end_image_url`）

| 項目 | 判定 | 内容 | 出典 |
|---|---|---|---|
| schema 上の型 | **確認済み** | `image_url` / `end_image_url` は `anyOf: [string, null]`、`format` 指定なし。説明は「Optional URL of the image to use as the first frame. When provided, the output aspect ratio follows this image. When omitted, the request is handled as text-to-video (16:9 by default).」/「Optional URL of the image to use as the last frame, for first-to-last keyframe generation.」。Max と Turbo の input schema は同一（title も同じ `TurboImageToVideoHailuo03Input`） | OpenAPI（turbo / [max](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3-max/image-to-video)） |
| data URI の受理 | **確認済み** | モデルの API ページ「Files」節: 「Some attributes in the API accept file URLs as input. Whenever that's the case you can pass your own URL or a Base64 data URI.」「You can pass a Base64 data URI as a file input. The API will handle the file decoding for you. Keep in mind that for large files, this alternative although convenient can impact the request performance.」 | [H3 Max API](https://fal.ai/models/minimax/h3-max/image-to-video/api)、[H3 Max Turbo API](https://fal.ai/models/minimax/h3-max-turbo/image-to-video/api) |
| data URI の推奨上限 | **確認済み（推奨）/ 不明（強制上限）** | fal CDN docs: 「Data URIs embed the entire file in the request payload. This inflates the request size significantly, slows down transmission, and is not recommended for files larger than a few KB. Use CDN uploads or external URLs instead.」また「Some models also accept **data URIs** ... but URLs are the universal format that works with every model.」バイト数の強制上限（request body 上限）は記載なし | [fal CDN](https://fal.ai/docs/documentation/model-apis/fal-cdn.md) |
| 受理フォーマット | **確認済み** | モデルページの playground が `jpg, jpeg, png, webp, gif, avif` を受ける。画像の最大バイト数・最小/最大解像度は schema・ページとも記載なし（**不明**）。汎用の `file_too_large` エラーは `ctx.max_size`（バイト）を返す | モデルページ、[Model Errors](https://fal.ai/docs/documentation/model-apis/errors.md) |
| storage upload（REST） | **確認済み** | 2 段: (1) `POST https://rest.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3` に `Authorization: Key $FAL_KEY`、`Content-Type: application/json`、body `{"file_name": "input.png", "content_type": "image/png"}` → 応答 `{upload_url, file_url}`; (2) `PUT $upload_url` に `Content-Type: image/png` で bytes を送る。以後 `file_url` を `image_url` に渡す。`initiate` に `X-Fal-Object-Lifecycle-Preference` を付けると保持期間 / ACL を指定できる | [File Access Controls](https://fal.ai/docs/documentation/model-apis/file-access-controls.md)（cURL 例） |
| 公式クライアントの経路 | **確認済み** | `fal_client` は既定で `POST https://v3.fal.media/files/upload`（`/storage/auth/token` の Bearer トークンで認証、応答 `access_url`）を使い、失敗時に `POST https://rest.fal.ai/storage/upload/initiate?storage_type=gcs` → `PUT upload_url` にフォールバックする。100 MB 超は multipart（10 MB chunk） | [fal_client/client.py](https://github.com/fal-ai/fal/blob/main/projects/fal_client/src/fal_client/client.py) |
| 署名 URL の寿命 | **不明** | `upload_url` の有効期限は docs・クライアントとも明記なし | — |
| アップロード済み入力の保持 | **確認済み** | 「Files you upload as inputs via `fal_client.upload_file` are also stored on the CDN. Both input uploads and output media are subject to the same retention controls.」 | [Data Retention & Storage](https://fal.ai/docs/documentation/model-apis/media-expiration.md) |
| 外部 URL | **確認済み** | S3 / GCS / R2 の presigned URL は使える。`Authorization` ヘッダが必要な private URL は使えない（`file_download_error`, 422） | fal CDN、Model Errors |

### 3. queue ライフサイクル

| 項目 | 判定 | 内容 | 出典 |
|---|---|---|---|
| endpoint | **確認済み** | `servers: https://queue.fal.run`。`POST /minimax/h3-max-turbo/image-to-video`（submit）、`GET .../requests/{request_id}/status?logs=1`、`GET .../requests/{request_id}`（result）、`PUT .../requests/{request_id}/cancel`。SSE は `GET .../requests/{request_id}/status/stream?logs=1` | OpenAPI、[Asynchronous Inference](https://fal.ai/docs/documentation/model-apis/inference/queue.md) |
| submit 応答 | **確認済み** | `QueueStatus`: `status`, `request_id`（必須）, `response_url`, `status_url`, `cancel_url`, `queue_position`, `logs`, `metrics`。docs の例では `response_url` が `.../requests/<id>/response` で終わる一方、OpenAPI の result path は `/requests/{request_id}`（公式クライアントも後者を組む）。**submit が返した URL をそのまま使う**のが安全 | 同上、fal_client `from_request_id` |
| status の値 | **確認済み** | `enum: ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"]` のみ。`COMPLETED` は「Result is stored and available for retrieval, or sent to your webhook.」で、失敗時も `COMPLETED` になり `error`（人間向け）と `error_type`（機械向け）が付く。公式クライアントも未知の status で `ValueError` | OpenAPI、queue docs、fal_client `_parse_status` |
| logs / metrics | **確認済み** | `?logs=1` で `logs: [{message, timestamp}]`。`metrics.inference_time`（秒、`COMPLETED` 時）。`queue_position` は `IN_QUEUE` 時のみ | queue docs |
| result 取得 | **確認済み** | `GET response_url` → `H3MaxTurboImageToVideoOutput`。公式クライアントの `get()` は `COMPLETED` を確認後に `response_url` を GET し、HTTP エラーなら `FalClientHTTPError` | OpenAPI、fal_client |
| cancel | **確認済み** | `IN_QUEUE` なら即削除。`IN_PROGRESS` なら runner にシグナルを送るが「The request may still complete if the app does not handle cancellation.」応答: `202 {"status":"CANCELLATION_REQUESTED"}` / `400 {"status":"ALREADY_COMPLETED"}` / `404 {"status":"NOT_FOUND"}`。OpenAPI は `{"success": boolean}` と記載しており docs と揺れる。`IN_PROGRESS` cancel 時の課金有無は **不明** | queue docs、OpenAPI |
| request_id の保存 | **確認済み** | 「Store the `request_id` if you need to check status or retrieve results later, even from a different process.」 | queue docs |
| 結果の保持期間 | **確認済み（webhook 文脈）/ 要アカウント確認（queue endpoint の実挙動）** | webhook docs: 「the delivery is retried with increasing backoff until the stored result expires — about 1 hour after the request completes, or about 6 minutes for results of 10 KB or more」「you can usually still retrieve the result from the queue while it is retained — results larger than 1 MB, and results for requests with payload storage disabled, are only available until the stored result expires.」queue docs 側に保持期間の明文は無い。request payload（JSON の入出力）は別系統で **30 日**保存（`X-Fal-Store-IO: 0` で無効化）され、ダッシュボードの履歴を支える。「1 MB 以下かつ payload 保存有効なら 30 日間 result endpoint から取れる」と読めるが明文ではない | [Webhooks](https://fal.ai/docs/documentation/model-apis/inference/webhooks.md)、[Data Retention & Storage](https://fal.ai/docs/documentation/model-apis/media-expiration.md) |
| 自動リトライ | **確認済み** | runner 失敗（503 / 504 / 接続エラー）は最大 10 回自動で再キュー。429（同時実行超過）も queue 側で待って再試行。`X-Fal-No-Retry: 1` で無効化。`start_timeout` / `X-Fal-Request-Timeout` は「処理開始までの絶対期限」で、超過は 504 + `X-Fal-Request-Timeout-Type: user` | queue docs、[Reliability](https://fal.ai/docs/documentation/model-apis/inference/reliability.md)、[Platform Headers](https://fal.ai/docs/documentation/model-apis/common-parameters.md) |
| webhook | **確認済み（今回は不採用）** | `?fal_webhook=<url>` で完了時 POST。payload は `{request_id, gateway_request_id, status: "OK"|"ERROR", payload, error?, payload_error?}`。公開 HTTPS endpoint が必要でローカル CLI には不向き | Webhooks |

### 4. 出力

| 項目 | 判定 | 内容 | 出典 |
|---|---|---|---|
| result の形 | **確認済み** | `video: File`（必須）、`expanded_prompt: string|null`（「Null when prompt expansion was disabled, left the prompt unchanged, or was performed internally by MiniMax's hosted API」）、`timings: {inference: number, ...}|null`。`File` は `url`（必須）, `content_type`, `file_name`, `file_size`（バイト） | OpenAPI |
| URL のドメイン・公開性 | **確認済み** | queue docs: 「All media URLs in responses (`https://v3.fal.media/...`) are publicly accessible and subject to your media expiration settings. Download files you need to keep before they expire.」FAQ: `https://v3b.fal.media/...` は「anyone with the URL can access the file until it expires」。`initial_acl` で非公開化できる | queue docs、FAQ、File Access Controls |
| URL の既定寿命 | **確認済み（下限）/ 要アカウント確認（実際の既定値）** | FAQ: 「Generated media files ... are stored on the fal CDN and available for **at least 7 days** by default.」Platform Headers の `X-Fal-Object-Lifecycle-Preference` 既定: 「Your account setting (forever and publicly readable if not configured)」。Data Retention の表は「Configurable」。3 箇所で表現が揺れるため、実値はダッシュボードのアカウント設定で確認する。「Expired files are permanently deleted and cannot be recovered.」 | FAQ、Platform Headers、Data Retention |
| 寿命の明示指定 | **確認済み** | submit 時に `X-Fal-Object-Lifecycle-Preference: {"expiration_duration_seconds": 3600}`（`null` で無期限）。同ヘッダで `initial_acl` も指定可 | Data Retention |
| `sync_mode` | **確認済み（意味）/ 不明（制限）** | schema: 「Return the generated video as base64 instead of a CDN URL.」既定 `false`。base64 の上限サイズ・タイムアウトの記載なし。数 MB の動画を base64 で返すと result が「10 KB 以上」「1 MB 超」の保持短縮条件に該当する | OpenAPI、Webhooks |
| fps / 音声 | **不明** | schema・モデルページとも fps と音声トラックの有無を記載しない。モデルページの例は `video/mp4`、file_size 8,277,609 B（Turbo）/ 約 3.6 MB（Max）。#4892 の「H3 はネイティブ音声を持つ」は fal のこの 2 endpoint では確認できなかった | モデルページ |
| 商用利用 | **確認済み** | 両モデルページに「Commercial use」バッジ。FAQ: 「Most models on fal are available for commercial use and are marked with a `Commercial use` badge」 | モデルページ、FAQ |

### 5. 料金・制限

| 項目 | 判定 | 内容 | 出典 |
|---|---|---|---|
| 課金対象 | **確認済み** | 「You pay only for successful outputs, and you are never charged for server errors or time spent waiting in the queue.」「Server errors are never billed. If a request fails with an HTTP 500 or higher status code, no charge is incurred.」FAQ: 「Client-side errors like invalid inputs (HTTP 422) may still be charged if a runner spent GPU time processing the request before the error was detected.」cold start も無料 | [Pricing](https://fal.ai/docs/documentation/model-apis/pricing.md)、FAQ |
| 課金タイミング | **確認済み（出力ベース）/ 不明（明文）** | 「billed based on the output you generate」= 実質完了時。submit 時点で引き落とす旨の記述は無い。safety checker で弾かれた場合の扱いは **不明** | Pricing |
| 支払いモデル | **確認済み** | プリペイド credits。購入 credits は 365 日で失効。残高が lock threshold を下回るとアカウントが lock され API が reject される | Pricing、FAQ |
| 単価（H3 Max i2v） | **確認済み** | 「Video costs **$0.0125** per second at **480p**, **$0.02** per second at **768p**. Note: these are promotional launch rates, 75% off for a limited time. The discount ends September 7, after which 480p is $0.05/second and 768p is $0.08/second.」 | [H3 Max i2v](https://fal.ai/models/minimax/h3-max/image-to-video) |
| 単価（H3 Max Turbo i2v） | **確認済み** | 「Video costs **$0.00625** per second at **480p**, **$0.01** per second at **768p**. ... The discount ends September 7, after which 480p is $0.025/second and 768p is $0.04/second.」 | [H3 Max Turbo i2v](https://fal.ai/models/minimax/h3-max-turbo/image-to-video) |
| プロモの範囲 | **確認済み** | Max / Turbo の image-to-video と text-to-video の 4 ページすべてに同じ 75% off・9 月 7 日の文言。年は未記載。ページの非表示フィールド `billingMessage` には「50% off ... ends September 1」という古い文言が残っており、表示テキスト（`pricingInfoOverride`）が現行 | 上記 + [Turbo t2v](https://fal.ai/models/minimax/h3-max-turbo/text-to-video)、[Max t2v](https://fal.ai/models/minimax/h3-max/text-to-video) |
| 8 秒・768P の換算 | **確認済み** | Turbo: プロモ USD 0.08 / 通常 USD 0.32。Max: プロモ USD 0.16 / 通常 USD 0.64。参考: Veo 3.1 Fast 1080p は USD 0.80（[2026-07-24 調査](2026-07-24-ai-video-generation-services.md)）。`prompt_expansion_mode: quality` の追加課金の記載は無い | 上記 |
| 単価 API | **確認済み（存在）/ 要アカウント確認（応答）** | `GET https://api.fal.ai/v1/models/pricing?endpoint_id=<id>` に `Authorization: Key` で単価と billing unit を返す。cost tracker の価格表を機械取得する候補 | Pricing |
| 同時実行 | **確認済み** | 「Every new account starts with a concurrency limit of **2** concurrent requests. ... Self-serve limits scale up to **40**」。`IN_QUEUE` は上限に数えない。「Requests are never dropped due to concurrency limits.」高負荷モデルには endpoint 別の上限が追加され得る | [Concurrency Limits](https://fal.ai/docs/documentation/model-apis/concurrency-limits.md) |
| レート制限（RPM 等） | **不明** | FAQ「Is there a rate limit?」の回答は同時実行上限のみ。RPM / RPD 型の制限は記載なし | FAQ |
| 429 の形 | **確認済み** | 「a `429` response with the `concurrent_requests_limit` type indicates you have hit your concurrency limit. The response includes an `X-Fal-needs-retry: 1` header. You should retry with exponential backoff」（生 HTTP、主に `fal.run` 直叩き時。queue 経由は server 側で待つ） | Concurrency Limits |

### 6. エラー

| 項目 | 判定 | 内容 | 出典 |
|---|---|---|---|
| モデル側 validation error | **確認済み** | body は `{"detail": [ {loc, msg, type, url, ctx?, input?} ]}`。`loc` は `["body", "<field>"]`、`type` は `image_too_large` などの機械可読文字列（Pydantic 標準の `string_type` / `int_parsing` / `enum` 等も素通し）。「treat any `type` not listed on this page as a non-retryable `422` validation error」「Client code should not parse and rely on the msg field.」 | [Model Errors](https://fal.ai/docs/documentation/model-apis/errors.md) |
| 揃っていない旨の警告 | **確認済み** | 「Some APIs are still being migrated to this error structure. Not all endpoints strictly follow the format documented below yet.」 | 同上 |
| インフラ側 request error | **確認済み** | body は flat: `{"detail": "Request timed out", "error_type": "request_timeout"}` + `X-Fal-Error-Type` ヘッダ。type 一覧: `request_timeout`(504) `startup_timeout`(504) `runner_scheduling_failure`(503) `runner_connection_timeout`(503) `runner_disconnected`(503) `runner_connection_refused`(503) `runner_connection_error`(503) `runner_incomplete_response`(502) `runner_server_error`(500) `client_disconnected`(499) `client_cancelled`(499) `bad_request`(400) `internal_error`(500) | [Request Error Types](https://fal.ai/docs/documentation/model-apis/request-errors.md) |
| status での失敗判定 | **確認済み** | `COMPLETED` の `error_type` に上記 type が入る。「The `error_type` is also available in queue status responses for failed requests」 | 同上、queue docs |
| リトライ判断 | **確認済み** | `X-Fal-Needs-Retry` ヘッダと `type` / `error_type` で判断。runner / timeout 系は一時的で再試行に値し、`client_*` / `bad_request` は再試行しない | Model Errors、Request Error Types |
| 公式クライアントの判別 | **確認済み** | `_raise_for_status`: body が dict なら `detail`（str でも list でもそのまま message に）と `error_type` を取り、無ければ `x-fal-error-type` ヘッダ。`RETRY_CODES = [408, 409, 429]`、`INGRESS_ERROR_CODES = [502, 503, 504]`（`x-fal-request-id` ヘッダが無い 5xx を ingress 起因と判定） | fal_client/client.py |
| 401 / 403 の body | **不明** | 認証失敗時の body 形は docs に記載なし | — |
| webhook の ERROR | **確認済み** | `status: "ERROR"`, `error: "Invalid status code: 422"`, `payload.detail: [...]` の形で validation error が入る | Webhooks |

## 現行設計（#4892）への影響

- **認証ヘッダは `Key`**: `Authorization: Key <FAL_KEY>`。`Bearer` を使うと認証されない。`infrastructure/secrets.py::_SECRET_REFS` に `FAL_KEY` を追加し、`op read` フォールバックに載せる
- **data URI は使わない**: 受理はされるが公式が「数 KB 超は非推奨」。`main.png` / `main.jpg` は MB 級なので `rest.fal.ai/storage/upload/initiate` → `PUT` の 2 段で `file_url` を得てから submit する（HTTP 2 往復の追加）。first = last なので同一画像を 1 回だけアップロードし、`image_url` と `end_image_url` に同じ `file_url` を渡す。アップロード時に `X-Fal-Object-Lifecycle-Preference: {"expiration_duration_seconds": 86400}` を付けて入力画像が CDN に長期公開されないようにする
- **失敗専用 status が無い**: `COMPLETED` を受けたら `error_type` の有無で成否を分ける。`IN_QUEUE` / `IN_PROGRESS` / `COMPLETED` 以外が来たら想定外として `YouTubeAPIError` 系ではなく fal 用ドメイン例外で落とす
- **request_id の保持は「完了後およそ 1 時間」を上限に置く**: webhook docs の記述が唯一の一次情報。resume（`minimax_video_task_store` 同型の store）は「submit 済み・未完了」の再ポーリングには使えるが、完了から 1 時間以上経った request_id は失効扱いにして再生成に回す。`COMPLETED` 検知 → result 取得 → 動画ダウンロードを同一プロセスで連続実行し、result JSON を保存して URL だけに頼らない。30 日の payload 保存経由で救えるかは **要アカウント確認**
- **`sync_mode` は使わない**: base64 化で result が 10 KB / 1 MB 閾値を超え、保持がむしろ短くなる。CDN URL 経由でダウンロードする
- **出力 URL は既定で公開**: 承認前の生成物を長く公開 URL に残さないよう、submit 時にも `X-Fal-Object-Lifecycle-Preference` で短い `expiration_duration_seconds` を指定するか、ダウンロード後に Platform API で payload / CDN ファイルを削除する（後者は要アカウント確認）
- **submit が返す URL を使う**: docs の例（`.../response`）と OpenAPI（`/requests/{id}`）で result URL の表記が揺れるため、`response_url` / `status_url` / `cancel_url` を保存してそのまま叩く。store には `request_id` に加えてこれら 3 URL を保存する
- **422 は課金され得る**: prompt 長（1〜50,000 文字）、`duration` 5〜15、`resolution` 480P / 768P、`prompt_expansion_mode` の値をクライアント側で事前検証してから submit する。`enable_safety_checker` 起因の失敗も課金対象になり得るので、実測比較の予算 USD 5 に失敗分の余白を持つ
- **料金は通常単価で持つ**: 9 月 7 日でプロモが終わるため、cost tracker と比較表は 768P の Max USD 0.08/s、Turbo USD 0.04/s を正とし、プロモ単価は注記に留める。単価は `GET https://api.fal.ai/v1/models/pricing?endpoint_id=...` で取れるが、応答形の確認にはキーが要る
- **同時実行 2 は問題にならない**: loop 生成は直列。ただし 9:16 ショートと 16:9 を並列に回す将来設計でも、超過分は queue で待つだけで reject されない
- **fps / 音声は実測で確定**: 768P → 1080p アップスケール位置と音声除去の要否は、実生成した mp4 を ffprobe してから決める（#4892「Not yet specified」の 1 項目はこの調査では埋まらない）
- **エラー文言の扱い**: `detail` は list（validation）と str（request error）の 2 形。ログ・例外文言には `type` / `error_type` と HTTP status のみを載せ、`input`（送った URL や prompt を含む）は含めない（`minimax_client` と同じ流儀）

## 一次情報

### fal 公式ドキュメント（`fal.ai/docs`）

- [Get Your API Key](https://fal.ai/docs/documentation/setting-up/authentication/index.md): `Authorization: Key $FAL_KEY`、`FAL_KEY`、キー発行場所、scope
- [Asynchronous Inference](https://fal.ai/docs/documentation/model-apis/inference/queue.md): queue endpoint、status 3 値、`error` / `error_type`、cancel の応答、`request_id` の保存、自動リトライ、`start_timeout`
- [Webhooks](https://fal.ai/docs/documentation/model-apis/inference/webhooks.md): 結果保持「約 1 時間 / 10 KB 以上は約 6 分」「1 MB 超と payload 保存無効は保持期限まで」、ERROR payload
- [Reliability](https://fal.ai/docs/documentation/model-apis/inference/reliability.md): 429 の queue 側リトライ、5xx 非課金
- [Synchronous Inference](https://fal.ai/docs/documentation/model-apis/inference/synchronous.md): `fal.run` 直叩きと `subscribe` の違い、request error の body
- [fal CDN](https://fal.ai/docs/documentation/model-apis/fal-cdn.md): data URI の受理と「数 KB 超は非推奨」、CDN URL 形式、公開性、multipart
- [Data Retention & Storage](https://fal.ai/docs/documentation/model-apis/media-expiration.md): `X-Fal-Object-Lifecycle-Preference`、payload 30 日、`X-Fal-Store-IO`、削除 API
- [File Access Controls](https://fal.ai/docs/documentation/model-apis/file-access-controls.md): `POST https://rest.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3` → `PUT upload_url` の cURL 例、CDN Bearer トークン、署名 URL
- [Platform Headers](https://fal.ai/docs/documentation/model-apis/common-parameters.md): 各ヘッダの既定値（lifecycle 既定「forever」、`X-Fal-Store-IO` 既定 30 日、`X-Fal-Request-Timeout`、`X-Fal-No-Retry`）
- [Model Errors](https://fal.ai/docs/documentation/model-apis/errors.md): `detail` 配列の構造、`type` 一覧、`X-Fal-Needs-Retry`、移行中の警告
- [Request Error Types](https://fal.ai/docs/documentation/model-apis/request-errors.md): flat `detail` + `error_type`、`X-Fal-Error-Type`、type と status code の対応表
- [Concurrency Limits](https://fal.ai/docs/documentation/model-apis/concurrency-limits.md): 新規 2 → 最大 40、queue 待ち、429 `concurrent_requests_limit`
- [Pricing](https://fal.ai/docs/documentation/model-apis/pricing.md): 出力課金、5xx・キュー待ち無料、プリペイド、単価 API
- [FAQ](https://fal.ai/docs/documentation/model-apis/faq.md): 422 課金の可能性、media「少なくとも 7 日」、URL の公開性、credits 失効、Commercial use バッジ
- [Documentation Index (llms.txt)](https://fal.ai/docs/llms.txt): 各 `.md` の索引

### OpenAPI schema・モデルページ

- [Queue OpenAPI: minimax/h3-max-turbo/image-to-video](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3-max-turbo/image-to-video): servers、securitySchemes、4 path、`QueueStatus`、input / output / `File` schema
- [Queue OpenAPI: minimax/h3-max/image-to-video](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=minimax/h3-max/image-to-video): 同上（input schema は Turbo と同一）
- [H3 Max (Image to Video)](https://fal.ai/models/minimax/h3-max/image-to-video) / [API](https://fal.ai/models/minimax/h3-max/image-to-video/api): 単価・プロモ文言、data URI の「Files」節、受理フォーマット
- [H3 Max Turbo (Image to Video)](https://fal.ai/models/minimax/h3-max-turbo/image-to-video) / [API](https://fal.ai/models/minimax/h3-max-turbo/image-to-video/api): 同上
- [H3 Max (Text to Video)](https://fal.ai/models/minimax/h3-max/text-to-video) / [H3 Max Turbo (Text to Video)](https://fal.ai/models/minimax/h3-max-turbo/text-to-video): プロモ範囲の確認のみ

### 公式クライアントのソース（fal-ai/fal）

- [fal_client/auth.py](https://github.com/fal-ai/fal/blob/main/projects/fal_client/src/fal_client/auth.py): `AuthCredentials("Key", ...)`、`FAL_KEY` / `FAL_KEY_ID` + `FAL_KEY_SECRET`
- [fal_client/client.py](https://github.com/fal-ai/fal/blob/main/projects/fal_client/src/fal_client/client.py): `REST_URL = "https://rest.fal.ai"`、`CDN_URL = "https://v3.fal.media"`、`_upload_via_storage`、`_parse_status`、`_raise_for_status`、`RETRY_CODES`

## 未確認事項

- **要アカウント確認**: queue の result endpoint が `request_id` で結果を返し続ける実際の期間（webhook docs の「約 1 時間 / 約 6 分」が queue にも適用されるか、payload 保存 30 日で延びるか）。実測比較の際に、完了後 1 時間・2 時間・翌日に `GET response_url` を叩いて確認する
- **要アカウント確認**: 出力 CDN URL の既定寿命の実値（アカウント設定。docs は「少なくとも 7 日」と「forever」で揺れる）
- **要アカウント確認**: `GET https://api.fal.ai/v1/models/pricing?endpoint_id=...` の応答形と、プロモ期間中に返る単価がプロモ値か通常値か
- **要アカウント確認**: `IN_PROGRESS` 中に cancel した場合と、safety checker で弾かれた場合の課金
- **要アカウント確認**: 出力 mp4 の fps・音声トラックの有無（ffprobe）
- **不明**: data URI / 入力画像の強制上限バイト数、最小・最大解像度、`upload_url` の有効期限
- **不明**: `sync_mode: true` 時の応答サイズ上限とタイムアウト
- **不明**: 401 / 403 の body 形、RPM 型のレート制限、`prompt_expansion_mode: quality` の追加課金

以上は未確認のまま実装仕様に固定せず、実測比較（予算 USD 5）の中で確認項目として消化する。
