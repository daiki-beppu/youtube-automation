# Cloudflare R2 事実調査（無料枠・ライフサイクル・resumable 転送・Terraform provider）

Issue: #3294（親: #3293「ADR: クラウド移譲アーキテクチャの原則」の入力）
調査日: 2026-08-07
一次情報のみ: developers.cloudflare.com / rclone.org（rclone 公式 docs ソース）/ docs.aws.amazon.com / cloudflare/terraform-provider-cloudflare 公式 docs（Terraform Registry の生成元）

## 結論

**1 コレクション中間物 9.7GB（master-mix.wav 1.5GB + Master.mp4 7.8GB）を前提とした無料枠内運用の成立条件:**

R2 のストレージ無料枠は Standard クラス 10 GB-month/月で、「日次ピークストレージの 30 日平均」で算定される（毎月リセット）。つまり課金対象は *サイズ × 滞留日数* であり、成立条件は次の不等式に集約される。

```text
Σ (中間物サイズ GB × 滞留日数) / 30 ≤ 10 GB-month
9.7GB/コレクションなら:  滞留日数 d × 月間コレクション数 n ≤ 約 30
```

- **常置は成立しない（余裕ゼロ）**: 9.7GB を 30 日置き続けると 9.7 GB-month で枠の 97%。2 コレクション同時常置（19.4 GB-month）で即超過。
- **「短期滞留 + 自動削除」なら余裕で成立**: prefix 単位の lifecycle 削除ルールで、例えば 3 日保持なら月 10 コレクション、7 日保持なら月 4 コレクションまで無料枠内。中間物中継（アップロード → 別マシンでダウンロード → 削除）という用途なら滞留は 1〜2 日で足り、実質無制限に近い。
- **オペレーション枠は誤差**: 9.7GB を 100MiB part で multipart アップロードしても Class A 約 100 回/コレクション（無料枠 100 万回/月）。ダウンロードは Class B（1,000 万回/月）。**DeleteObject / AbortMultipartUpload は無料**なので掃除にコストは掛からない。
- **egress は 0 円**: R2 から直接ダウンロードする限り（S3 API / Workers API / r2.dev 経由）egress 課金はない。中間物の取り出しに転送量コストは発生しない。
- **運用上の必須条件**:
  1. バケットは Standard のまま使う。Infrequent Access は**無料枠の対象外**なので、コスト削減のつもりで IA transition を設定すると逆に課金される。
  2. 中間物 prefix に対する削除ルール（`delete_objects_transition`）と、未完了 multipart の abort ルール（`abort_multipart_uploads_transition`）を lifecycle に設定する。未完了 multipart の part もストレージ消費にカウントされる（デフォルトでは 7 日で自動 abort）。
  3. Master.mp4 7.8GB は単発 PUT の上限（5 GiB、実質 4.995 GiB）を超えるため **multipart upload が必須**。master-mix.wav 1.5GB は単発 PUT 可能だが、resume 不可（失敗時全再送）なので multipart に寄せるのが安全。
  4. 「不完全なファイルを後工程へ渡さない」は R2 の強整合性 + multipart の原子性（CompleteMultipartUpload 成功まで一切見えない）で土台が保証される。その上で、全ファイルの検証後に完了マーカー（マニフェスト）を最後に PUT する設計にする（詳細は §4）。

以下、調査項目ごとの事実と出典。

## 1. 無料枠の正確な内訳

出典: <https://developers.cloudflare.com/r2/pricing/>

| 項目 | 無料枠（毎月） | 超過時（Standard） |
| --- | --- | --- |
| ストレージ | 10 GB-month | $0.015 / GB-month |
| Class A オペレーション | 100 万リクエスト | $4.50 / 100 万 |
| Class B オペレーション | 1,000 万リクエスト | $0.36 / 100 万 |
| egress（データ転送出） | 無料（上限記載なし） | 無料 |

- **GB-month の算定方式**: 「日毎のピークストレージを課金期間（30 日）で平均」する。1 GB を 30 日間置き続けると 1 GB-month。すなわち滞留日数が短ければ消費 GB-month は比例して小さくなる。
- **無料枠は Standard ストレージのみ**: 「The free tier only applies to Standard storage, and does not apply to Infrequent Access storage.」
- **egress がゼロになる条件**: R2 から直接 egress する場合（Workers API・S3 API・r2.dev ドメイン経由を含む）は無料。R2 に他の従量課金サービスを接続した場合はそちら側の課金が発生し得る。
- **オペレーション分類**（pricing ページの列挙をそのまま転記）:
  - Class A: ListBuckets, PutBucket, ListObjects, PutObject, CopyObject, CompleteMultipartUpload, CreateMultipartUpload, LifecycleStorageTierTransition, ListMultipartUploads, UploadPart, UploadPartCopy, ListParts, PutBucketEncryption, PutBucketCors, PutBucketLifecycleConfiguration
  - Class B: HeadBucket, HeadObject, GetObject, UsageSummary, GetBucketEncryption, GetBucketLocation, GetBucketCors, GetBucketLifecycleConfiguration
  - **無料**: DeleteObject, DeleteBucket, AbortMultipartUpload
- 課金単位は切り上げ（例: 1.1 GB → 2 GB として請求）。

## 2. ライフサイクルルール

出典: <https://developers.cloudflare.com/r2/buckets/object-lifecycles/>、<https://github.com/cloudflare/terraform-provider-cloudflare/blob/main/docs/resources/r2_bucket_lifecycle.md>

- **prefix 別の自動削除: 可能**。ルール作成時に適用対象 prefix を指定できる（コレクション単位の prefix 切りと相性が良い）。
- **アクション**: (a) オブジェクト削除（expire）、(b) 未完了 multipart upload の abort、(c) Standard → Infrequent Access への transition の 3 種。
- **最小粒度**:
  - S3 API（`PutBucketLifecycleConfiguration`）は `Days`（日）単位、または `Date` 指定。
  - Cloudflare ネイティブ API / Terraform（`cloudflare_r2_bucket_lifecycle`）の Age 条件は `max_age` を**秒単位**で指定する。
  - ただし実行は日次バッチ相当で、「オブジェクトは通常 `x-amz-expiration` の値から 24 時間以内に削除される」。秒単位の即時削除を期待してはならない。
- **設定方法**: ダッシュボード / `wrangler r2 bucket lifecycle` / S3 API `PutBucketLifecycleConfiguration`（`GetBucketLifecycleConfiguration`, `DeleteBucketLifecycle` も実装済み）/ Terraform `cloudflare_r2_bucket_lifecycle`。
- **上限**: 1 バケット 1,000 ルール。
- **未完了 multipart のデフォルト**: 「Incomplete multipart uploads are automatically aborted after 7 days by default」（lifecycle ルールで変更可能）。出典: <https://developers.cloudflare.com/r2/objects/multipart-objects/>

## 3. 中断再開可能な転送（S3 互換 multipart upload）

### R2 側の仕様と制約

出典: <https://developers.cloudflare.com/r2/objects/multipart-objects/>（Upload objects ページ）、<https://developers.cloudflare.com/r2/platform/limits/>、<https://developers.cloudflare.com/r2/api/s3/api/>

- part サイズ: 最小 5 MiB（最終 part を除く）、最大 5 GiB。最大 10,000 parts。multipart での最大オブジェクト 5 TiB（実質 4.995 TiB）。
- 単発 PUT の上限は 5 GiB（実質 4.995 GiB）。**7.8GB の Master.mp4 は multipart 必須**。
- **R2 固有の制約: 「All parts except the last must be the same size」**（最終 part 以外は同一サイズ必須。AWS S3 にはない制約。主要ツールは同一 chunk サイズで送るため通常は問題にならないが、可変 part サイズを使う独自実装は非互換）。
- R2 公式の比較表で multipart は「Resumable: Yes — only failed parts need to be retried」、単発 PUT は「No — must restart the entire upload」と明記。
- **R2 固有の挙動**: 「UploadPart: Uploading to the same part number replaces the previous part. If a subsequent upload to the same part fails, the original part is lost and must be re-uploaded.」（同一 part 番号への再送は置換であり、置換失敗時は元 part も失われる）
- S3 仕様として（R2 も同一 API）: upload ID に有効期限はなく、明示的に Complete / Abort するまで part を時間をかけて追加できる。`ListParts` でアップロード済み part を列挙でき、これがプロセス跨ぎ再開の土台になる。出典: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html>（「Pause and resume object uploads – You can upload object parts over time. After you initiate a multipart upload, there is no expiry」）

### ツール別の resume 対応状況

| ツール | 転送中の part 単位リトライ | プロセス中断後の自動 resume | 手動 resume の道 |
| --- | --- | --- | --- |
| rclone | あり | **なし**（再実行はファイル先頭から） | `--s3-leave-parts-on-error` で part を残し手動リカバリ |
| aws CLI（高レベル `aws s3 cp`） | あり | **なし**（文書化されていない） | `aws s3api upload-part` 等の低レベルコマンドで自作 |
| boto3（`upload_file` / `upload_fileobj`) | あり | **なし** | 低レベル API（`create_multipart_upload` / `upload_part` / `list_parts` / `complete_multipart_upload`）で自作 |

- **rclone**: `--s3-upload-cutoff`（最大 5 GiB）超で multipart に切替、`--s3-chunk-size` × `--s3-upload-concurrency` で並列転送。中断後の再開機能は S3 backend ドキュメントにも FAQ にも存在しない。`--s3-leave-parts-on-error`（既定 false）は失敗時の abort を抑止して「leaving all successfully uploaded parts on S3 for manual recovery」とするフラグで、「It should be set to true for resuming uploads across different sessions」とあるが、再開処理自体を rclone が自動では行わない（放置 part はストレージを消費する警告つき）。出典: <https://rclone.org/s3/>
  - R2 向け設定は `provider = Cloudflare`、rclone v1.59 以上、object 権限のみのトークンでは `no_check_bucket = true`。part 1 回 = Class A 1 オペレーションのため、「multipart は単発 PutObject の 3 倍以上のオペレーションを消費する」。出典: <https://developers.cloudflare.com/r2/examples/rclone/>
- **aws CLI**: `multipart_threshold`（既定 8MB）/ `multipart_chunksize` で自動 multipart。プロセス跨ぎの resume は設定項目・ドキュメントに存在しない。出典: <https://docs.aws.amazon.com/cli/latest/topic/s3-config.html>。低レベル `aws s3api create-multipart-upload / upload-part / list-parts / complete-multipart-upload` は個別に呼べるため手動再開は可能。出典: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html>
- **boto3**: マネージド転送はプロセス内の part リトライのみで、跨ぎ resume 機能はない。Cloudflare 公式は数 GB 級について「`upload_fileobj` は Python の GIL がボトルネック」とし、低レベル multipart API + `ThreadPoolExecutor`（最大 10 workers 目安）を推奨。出典: <https://developers.cloudflare.com/r2/examples/aws/boto3/>
- R2 は S3 API の region として `auto` を用いる（空値と `us-east-1` は alias）。endpoint は `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`。出典: <https://developers.cloudflare.com/r2/api/s3/api/>、<https://developers.cloudflare.com/r2/examples/aws/aws-cli/>

## 4. 完全性検証（ETag / checksum / 完了マーカー設計）

### ETag と multipart の関係

出典: <https://developers.cloudflare.com/r2/objects/multipart-objects/>

- 単発 PUT の ETag はオブジェクトの MD5。
- multipart の ETag は「各 part のバイナリ MD5 を連結したものの MD5 + `-` + part 数」（例: `f77dc0eecdebcd774a2a22cb393ad2ff-2`）。**ローカルファイル全体の MD5 とは一致しない**。part サイズが既知なら同じ計算をローカルで再現して照合できる。

### checksum による検証手段

出典: <https://developers.cloudflare.com/r2/api/s3/api/>（Checksum Types 表・各 API の Feature 列）

- R2 の checksum 対応（2026-07-31 更新時点の対応表）:
  - CRC-64/NVME（CRC64NVME）: FULL_OBJECT のみ ✅
  - CRC-32 / CRC-32C / SHA-1 / SHA-256: COMPOSITE のみ ✅（full-object ❌）
  - `PutObject` / `CreateMultipartUpload` の `x-amz-checksum-algorithm` ヘッダは ❌（未実装）
  - `PutObject` / `UploadPart` / `CreateMultipartUpload` の `Content-MD5` は ✅（サーバー側で MD5 検証される）
- AWS SDK / CLI は 2024-12 以降の版で CRC 系 checksum を既定送信する（`request_checksum_calculation` / `response_checksum_validation`、既定 `WHEN_SUPPORTED`、環境変数 `AWS_REQUEST_CHECKSUM_CALCULATION` / `AWS_RESPONSE_CHECKSUM_VALIDATION`）。必要時のみ送る `WHEN_REQUIRED` に切り替えられる。R2 の対応表にない組合せを SDK が選んだ場合の逃げ道として押さえておく。出典: <https://docs.aws.amazon.com/sdkref/latest/guide/feature-dataintegrity.html>
- rclone は multipart 完了時に `X-Amz-Meta-Md5chksum` メタデータへ元ファイルの MD5 を格納する（multipart ETag では照合できないため）。単発 PUT は `Content-Md5` 付きで送り、アップロード後に HEAD で ETag を照合する。出典: <https://rclone.org/s3/>

### 「不完全なファイルを後工程へ渡さない」ための設計材料

- **R2 は強整合**: 「The effect of an operation will be observed globally, immediately, by all clients」。multipart は「read-after-write consistency continues to apply once all parts have been successfully uploaded」— すなわち **CompleteMultipartUpload が成功するまでオブジェクトは一切見えず、部分状態が読者に露出することはない**。オブジェクトが存在する = 完全にアップロードされた、が API レベルで保証される。出典: <https://developers.cloudflare.com/r2/reference/consistency/>
- 未完了 multipart の part はストレージを消費する（R2 公式の Workers サンプルに「Abort on failure so incomplete uploads do not count against storage」とのコメント。abort しない限りカウントされる）。出典: <https://developers.cloudflare.com/r2/objects/multipart-objects/>
- ベストプラクティス（上記事実からの設計指針）:
  1. データ本体は multipart で送り、Complete 後に `HeadObject` でサイズ・ETag（または `Content-MD5` / メタデータに埋めた checksum）を照合する。
  2. **全ファイルの照合が済んだ後に、最後に完了マーカー（サイズ・checksum 一覧を含むマニフェスト JSON）を単発 PUT する**。単発 PUT は原子的かつ強整合なので、後工程は「マニフェストが存在する = 全中間物が検証済みで揃っている」と判定できる。マーカーを他ファイルより後に書く順序だけが要件。
  3. 後工程はマニフェスト記載のサイズ / checksum と `HeadObject` / ダウンロード後のローカル計算を突き合わせてから使う。`GetObject` / `PutObject` とも conditional（`If-Match` / `If-None-Match` 等）が実装済みなので、マーカーの二重作成防止や読み取り時の世代固定にも使える。
  4. 失敗経路では `AbortMultipartUpload`（無料）を明示的に呼び、取りこぼしは lifecycle の abort ルール（§2）で回収する。

## 5. Terraform 対応（cloudflare provider）

出典: <https://github.com/cloudflare/terraform-provider-cloudflare/blob/main/docs/resources/r2_bucket.md>、<https://github.com/cloudflare/terraform-provider-cloudflare/blob/main/docs/resources/r2_bucket_lifecycle.md>、<https://github.com/cloudflare/terraform-provider-cloudflare/blob/main/docs/resources/api_token.md>（いずれも Terraform Registry 掲載ドキュメントの生成元）。調査時点の最新 provider は v5.23.0（2026-08-05 リリース）。

- **バケット作成: `cloudflare_r2_bucket` で対応**。必須: `account_id`, `name`。任意: `location`（apac / eeur / enam / weur / wnam / oc）、`storage_class`（Standard / InfrequentAccess）、`jurisdiction`（default / eu / fedramp / us）。import 対応（`'<account_id>/<bucket_name>/<jurisdiction>'`）。必要権限は「Workers R2 Storage Write」。
- **ライフサイクル: `cloudflare_r2_bucket_lifecycle` で対応**。`rules[]` に `id` / `enabled` / `conditions.prefix` を持ち、`abort_multipart_uploads_transition` / `delete_objects_transition` / `storage_class_transitions` を設定できる。条件は Age 型（`max_age` 秒）と Date 型。**`terraform import` 未対応**（ドキュメント明記）。
- **注意（食い違い）**: developers.cloudflare.com の R2 Terraform example（<https://developers.cloudflare.com/r2/examples/terraform/>）は provider v4 前提で「Cloudflare provider ではバケット管理のみ。CORS や lifecycle は AWS provider が必要」と記載しているが、v5 系の provider には上記のとおり lifecycle リソースが存在する。example ページの記述は v4 時代のもので、v5 では AWS provider へ迂回する必要はない。
- **API token（スコープ限定）**: `cloudflare_api_token` リソースで `policies`（`permission_groups` + `resources`）を絞ったトークンを作成できる。`value` は sensitive な read-only 属性。`expires_on` / `not_before` / `condition.request_ip` に対応。
- **S3 認証情報の導出**（出典: <https://developers.cloudflare.com/r2/api/tokens/>）: R2 の S3 API 用 Access Key ID = API token の `id`、**Secret Access Key = API token `value` の SHA-256 ハッシュ**。したがって Terraform で作ったトークンから `sha256(cloudflare_api_token.x.value)` で S3 認証情報まで IaC 内で導出できる。
- R2 トークンの権限段階: Admin Read & Write / Admin Read only / Object Read & Write / Object Read only。**Object 系は特定バケット集合へのスコープが可能**。Account token（Super Administrator のみ作成可、手動失効まで有効）と User token（作成者の権限を継承し、ユーザー離脱で失効）の 2 系統がある。出典: <https://developers.cloudflare.com/r2/api/tokens/>

## 6. S3 互換 API の非互換点（移行可能性への影響）

出典: <https://developers.cloudflare.com/r2/api/s3/api/>（実装状況の対応表）、<https://developers.cloudflare.com/r2/platform/limits/>

R2 から他の S3 互換ストレージ（本家 S3 含む）へ将来移行する場合、**R2 で使える機能は概ね S3 のサブセット**なので、R2 前提で組んだクライアントコードはそのまま移行しやすい。逆方向（S3 固有機能への依存）が発生しないよう、以下の差分を把握しておく。

- **未実装（R2 に存在しない）**: バケットポリシー / ACL 全般、オブジェクト versioning、Object Lock（リーガルホールド含む）、オブジェクト tagging、S3 イベント通知 API、クロスリージョンレプリケーション、バケットロギング、静的 website ホスティング、Transfer Acceleration、SSE-KMS / SSE-S3 系ヘッダ（**SSE-C は対応**）、`x-amz-request-payer`、inventory / metrics / analytics 設定。
- **ストレージクラスは STANDARD / STANDARD_IA のみ**（Glacier 系のアーカイブ階層なし）。
- **checksum の差分**: full-object checksum は CRC64NVME のみ、SHA-256 等は composite のみ。`x-amz-checksum-algorithm` ヘッダ未実装（§4 参照）。AWS SDK の既定 checksum 送信は `WHEN_REQUIRED` への切替で調整可能。
- **region / endpoint**: region は `auto` 固定（空値・`us-east-1` が alias）。endpoint がアカウント固有 URL のため、移行時は endpoint 差し替えが前提の設計にしておく。
- **R2 固有の追加制約**: multipart の「最終 part 以外は同一サイズ必須」、同一オブジェクトキーへの並行書き込み上限 1 回/秒（超過で HTTP 429）、単発 PUT 上限 4.995 GiB。
- **R2 拡張（使うとロックインになる）**: auto-bucket creation、CopyObject の MERGE metadata directive、Unicode メタデータ拡張など（<https://developers.cloudflare.com/r2/api/s3/extensions/>）。移行可能性を保つなら使用を避ける。
- **互換が確認できているコア**: オブジェクト CRUD（PutObject / GetObject / HeadObject / DeleteObject(s) / CopyObject）、ListObjectsV2、multipart 一式（Create / UploadPart / UploadPartCopy / ListParts / ListMultipartUploads / Complete / Abort）、presigned URL、conditional requests（If-Match 等）、CORS、lifecycle の基本（expire / abort / IA transition）。この範囲に限定して使うのが移行安全域。
