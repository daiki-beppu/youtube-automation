# Cloud Run（Cloud Run Jobs）の適性調査

- 対象 issue: [#3295](https://github.com/daiki-beppu/youtube-automation/issues/3295)（親: #3293「ADR: 実行基盤の選定」の入力）
- 調査日: 2026-08-07
- 一次情報のみ（cloud.google.com / docs.cloud.google.com の公式ドキュメント・料金ページ。R2 側の転送費は developers.cloudflare.com、Claude Code の Vertex 対応は code.claude.com 公式ドキュメント）
- 料金・上限はすべて調査日時点の記載値。GCP の docs は `cloud.google.com/run/docs/...` から `docs.cloud.google.com/...` へ 301 リダイレクトされるため、出典はリダイレクト先で表記する

## 総合サマリ

バッチ制作ランの実行基盤としての適性は**高い**。Jobs はコンテナを「exit code 0 で終わるまで実行する」だけの契約で、タスクタイムアウトは最大 168 時間、ADC・Terraform・単一 GCP プロジェクト構成（ADR-0010）にそのまま乗る。週次運用なら compute はほぼ無料枠内。主要な注意点は 4 つ:

1. **一時ディスク（ephemeral disk）はまだ Preview**。GA まではデフォルトの in-memory filesystem（メモリを食う）で 32 GiB メモリ構成にするか、Preview 依存を受け入れるかの二択
2. **R2 への動画 push は GCP の internet egress 課金**（$0.12/GiB）。日次運用ではこれが compute と並ぶ主要コスト
3. **多重起動防止の組込み機構はない**。Cloud Scheduler は at-least-once（稀に複数回発火）で、アプリ側の冪等化 / lease が必須
4. **CPU は最大 8 vCPU**。重量レジームを 1 ラン内で縦にスケールする余地はここまで

---

## 共通評価軸

### 1. 料金体系と無料枠

**事実**

- Jobs の料金（Tier 1 リージョン・デフォルト消費モデル）: CPU **$0.000018/vCPU-秒**、メモリ **$0.000002/GiB-秒**。無料枠は月 **240,000 vCPU-秒 + 450,000 GiB-秒**（billing account 単位で合算、毎月リセット、Tier 1 価格での spending based discount として適用）[^run-pricing]
- 東京（asia-northeast1）は Tier 1 リージョン[^run-pricing]
- Services（request-based billing）は CPU $0.000024/vCPU-秒（active）+ リクエスト $0.40/100 万件、無料枠 180,000 vCPU-秒 / 360,000 GiB-秒 / 200 万リクエスト[^run-pricing]
- Ephemeral Disk: **$0.000109589/GiB-時**（デフォルト。プロビジョンしたサイズ全体 × インスタンス存続時間で課金）[^run-pricing][^ephemeral-disk]
- アウトバウンド internet 転送は Premium Network Service Tier 固定で、無料枠は「北米宛 1 GiB/月」。GCP 全体の networking 料金に従う[^run-pricing]（単価は軸 4）
- インバウンド転送は無料（"No charge for inbound data transfer"）[^vpc-pricing]

**試算（想定負荷への当てはめ。出典の単価からの自前計算）**

| シナリオ | 構成 | compute 費（無料枠適用前） |
|---|---|---|
| 重量レジーム 1 ラン | 8 vCPU / 32 GiB / 1 時間 | CPU $0.52 + RAM $0.23 ≈ **$0.75** + disk 10 GiB×1h ≈ $0.001 |
| 軽量レジーム 1 ラン | 2 vCPU / 8 GiB / 10 分 | ≈ **$0.03** |
| 週次×重量（月 4–5 ラン） | 同上 | CPU は無料枠内、RAM が枠をわずかに超過し **月 $0〜0.3 程度** |
| 日次×重量（月 30 ラン） | 同上 | 無料枠超過分で **月 ≈ $17**（CPU $11 + RAM $6） |

**含意**: 週次運用なら compute はほぼ無料。日次でも compute は $20/月 未満で、支配項はむしろ egress（軸 4）。時間課金は「ランが動いた秒数だけ」なので、アイドル費ゼロという性質は間欠バッチと相性が良い。

### 2. 実行時間上限

**事実**

- Jobs のタスクタイムアウト: デフォルト 10 分、**最大 168 時間（7 日）**（GPU 使用時は最大 1 時間）。リトライ有効時は 1 attempt ごとに適用[^task-timeout][^quotas]
- job execution 自体に明示のタイムアウトはない（全タスク完了で終了）[^task-timeout]
- Services のリクエストタイムアウト: デフォルト 5 分、**最大 60 分**[^request-timeout]
- Jobs の上限: 1 execution あたり最大 10,000 タスク、同時 running execution は 1,000/プロジェクト/リージョン[^quotas]

**含意**: 重量レジーム（エフェクト・スペクトラムで大幅増）でも 7 日上限は事実上無制限。Services の 60 分では ffmpeg 実エンコードを受けきれないため、**制作ランは Jobs 一択**。

### 3. 一時ディスク容量と IO

**事実**

- デフォルトのファイルシステムは **in-memory**。「書き込みはインスタンスのメモリを消費する」と明記され、メモリ超過はインスタンスクラッシュになる[^container-contract]
- メモリ上限は **32 GiB**（8 vCPU 時に 4〜32 GiB。in-memory 書き込み込みで 32 GiB が天井）[^memory-limits][^quotas]
- **Ephemeral disk volume（Preview）**: 最小 10Gi、デフォルト quota は **10 GB/インスタンス・100 GB/プロジェクト/リージョン**（初回利用時に自動付与、引き上げ申請可）。gen2 実行環境のみ（Jobs は既定で gen2）。ext4 で自動プロビジョン・インスタンス固有鍵で暗号化・終了時に完全削除。対応リージョン限定だが料金ページのリージョンタブに東京（asia-northeast1）が含まれる[^ephemeral-disk][^run-pricing]
- ephemeral disk へ大量データをダウンロードして遅い場合は Direct VPC の有効化が推奨されている[^ephemeral-disk]
- Cloud Storage FUSE volume mount もあるが、書き込みステージングはメモリを消費（streaming writes でファイルあたり約 64 MiB、大きなファイルはメモリ上限に制約される）、POSIX 非完全・file locking なし[^gcs-fuse]

**含意**: 9.7 GB 級の中間物の置き場は 2 案。(a) **32 GiB メモリ構成 + in-memory**: GA 機能のみで成立するが、ラン全時間にわたり 32 GiB ぶんのメモリ課金を払う（それでも 1 時間 $0.23）。(b) **ephemeral disk 10 GiB**: 課金は 1 時間 $0.001 と無視できるが **Preview 依存**で、9.7 GB に対して default quota 10 GB はぎりぎり（quota 引き上げ申請で余裕を確保したい）。GCS FUSE は ffmpeg のランダム I/O・大容量書き込みに不適で、本用途では候補外。

### 4. R2 との転送

**事実**

- pull（R2 → Cloud Run）: GCP 側のインバウンドは無料[^vpc-pricing]。R2 側の egress も無料（"There are no charges for egress bandwidth for any storage class"）[^r2-pricing]
- push（Cloud Run → R2）: GCP の internet egress（Premium Tier 固定[^run-pricing]）として課金。単価は宛先が北米/欧州/アジア（韓国・インドネシア除く）で **$0.12/GiB（月 0〜1 TiB 帯）**、最初の 1 GiB/月（北米宛）のみ無料[^vpc-pricing]
- 帯域の保証値は公表されていない。ephemeral disk のドキュメントに「大量ダウンロードが遅ければ Direct VPC を有効化」という性能ガイダンスがある[^ephemeral-disk]

**試算**: 1 ランあたり動画 push 5 GB（≈4.7 GiB）とすると、週次で月 ≈ $2.3、日次で月 ≈ $17。音源 pull（数百 MB〜数 GB）は双方向とも無料。

**含意**: **egress が Cloud Run 採用時の従量コストの主要因**。ただしこれは GCP 共通の internet egress であり Cloud Run 固有の不利ではない（GCE でも同額）。R2 を成果物ストアとして維持する前提なら、日次運用時に compute と同オーダーの egress 費を織り込む。

### 5. CPU 性能と ffmpeg 適性

**事実**

- 最大 **8 vCPU / 32 GiB**[^cpu-limits][^memory-limits]
- CPU プラットフォーム（世代・機種）の指定・公表はない[^cpu-limits]
- コンテナ実行形式は **linux/amd64 のみ**（"Cloud Run specifically supports the Linux x86_64 ABI format"）[^container-contract]
- GPU（NVIDIA L4 等）は提供されているが本件では不要[^run-pricing]

**含意**: 軽量レジーム（静止画ループ 2 時間尺で 1〜2 分）は小さい構成で十分。重量レジームは 8 vCPU が縦の天井で、それ以上は Jobs のタスク分割（曲単位など）で水平に逃がす設計になる。ハードウェア世代が固定できないため、エンコード時間の再現性は保証されない点は留意。

### 6. スケジュール実行

**事実**

- Cloud Scheduler が `https://run.googleapis.com/v2/projects/.../jobs/JOB:run` へ OAuth トークン付き POST で Jobs を起動する。実行側 service account に `roles/run.invoker` が必要。Console の Trigger タブ / gcloud / Terraform（`google_cloud_scheduler_job`）で構成できる[^jobs-schedule]
- Cloud Scheduler は **at-least-once 保証**: 「稀に単一スケジュールに対しジョブが複数回実行され得る」ため「ターゲットは冪等であるべき」と明記。`X-CloudScheduler-ScheduleTime` ヘッダで元のスケジュール時刻を識別できる[^scheduler-overview]
- Cloud Run 側に同一 job の並行 execution を禁止する組込み設定はない（running executions の上限は 1,000/プロジェクト/リージョンという quota のみ）[^quotas]
- 料金: **3 ジョブ/月まで無料**（billing account 単位）、以降 $0.10/ジョブ/月。課金はジョブ定義単位で実行回数には依らない[^scheduler-pricing]

**含意**: 週次〜日次の cron はほぼ無料で組める。ただし**多重起動防止は自前**: 制作ランを冪等にする（実行前に R2/GCS 上の lease オブジェクトを取る、または Jobs API で running execution の有無を確認して skip する）実装が前提になる。週次〜日次の粒度なら lease の実装コストは小さい。

### 7. secret 管理

**事実**

- Secret Manager の秘密情報は **環境変数**（インスタンス起動時に解決。`latest` でなく version pin 推奨）または **volume mount**（読み取り時に常に最新版を fetch。rotation 向き）として Jobs に注入できる。実行 service account に `roles/secretmanager.secretAccessor` が必要[^jobs-secrets]
- 料金: active secret version 6 個まで無料、以降 $0.06/version/月。アクセス 10,000 回/月まで無料、以降 $0.03/10,000 回[^sm-pricing]

**含意**: 本プロジェクトのシークレット解決順（`os.environ` → `op read` → `ConfigError`）と**無変更で噛み合う**。Secret Manager → 環境変数注入にすれば `infrastructure/secrets.py` は第一段の `os.environ` で解決し、`op read` はローカル専用のフォールバックとしてそのまま残せる。1Password を SoT とし Secret Manager へは Terraform 等で同期する住み分けが自然。本チャンネル数・シークレット数なら実質無料。

### 8. コンテナ可搬性

**事実**

- Jobs のコンテナ契約は「正常終了で exit code 0、失敗で非 0。リクエストを待ち受けない」のみ。PORT 待受は Services のみの要件[^container-contract]
- gen2 実行環境は「full Linux compatibility」（gVisor サンドボックスなし）[^container-contract]
- イメージは Artifact Registry 推奨。Docker Hub / GitHub Container Registry の**公開**イメージは直接デプロイ可（最大 1 時間キャッシュ）、外部私設レジストリは Artifact Registry remote repository 経由。remote/外部経由はレイヤ 9.9 GB 制限。イメージサイズ自体の直接制限はない[^deploying]

**含意**: ffmpeg + uv + Python パッケージ入りの汎用 OCI イメージをそのまま持ち込める。制約は **linux/amd64 のみ**という点だけで、Apple Silicon からは `docker buildx --platform linux/amd64` でのクロスビルドが必要。イメージを基盤非依存に保てば、Cloud Run 固有部分は Terraform の薄い層に閉じる。

### 9. AI エージェント実行適性

**事実**

- Cloud Run の workload は attached service account + メタデータサーバ経由の ADC で、鍵ファイルなしに Google Cloud API（Vertex AI 含む）へ認証できる。`GOOGLE_APPLICATION_CREDENTIALS` の設定はむしろ非推奨で、user-managed service account の構成が推奨[^service-identity]
- Claude Code は `CLAUDE_CODE_USE_VERTEX=1` + `CLOUD_ML_REGION` + `ANTHROPIC_VERTEX_PROJECT_ID` の環境変数で Vertex AI（Agent Platform）経由に構成でき、認証は「標準の Google Cloud 認証」（ADC チェーン）を使う[^cc-vertex]
- Claude Code は `claude -p`（headless / 非対話）でスクリプト・CI から実行でき、成功で exit code 0 / 失敗で非 0 を返す。CI 用の `--bare` モードもある[^cc-headless]
- Jobs のタスクタイムアウトは最大 168 時間（軸 2）で、長時間のエージェントループも収まる[^task-timeout]

**含意**: 「制作ランの中で Claude Code / Codex CLI を headless 実行する」構成は Jobs 上で素直に成立する。特に **Vertex 経由なら API キーの secret 注入すら不要**（ADC で完結）で、既存の「AI 系は ADC 認証のため op 取得不要」という規約とそのまま連続する。exit code 契約は `claude -p` の終了コード仕様と一致し、失敗時は Jobs のリトライに乗せられる。対話的な承認ゲートはクラウドに持ち込めないため、AFK 前提のステップに限定する（これは基盤共通の制約）。

### 10. ベンダーロックイン度

**事実**

- アプリ本体は標準 OCI コンテナ + exit code 契約のみで、Cloud Run 固有の SDK・ランタイム改変は不要[^container-contract]
- 基盤固有になる層: Scheduler / Jobs / Secret Manager / IAM の Terraform 資源定義、ephemeral disk 等の volume 設定[^jobs-schedule][^jobs-secrets][^ephemeral-disk]
- ephemeral disk は Preview（Pre-GA Offerings Terms 適用）[^ephemeral-disk]

**含意**: ロックインは薄い。コンテナは他基盤のバッチ実行（Fly Machines、ECS/Fargate、GitHub Actions 等）へ改変なしで移せて、撤退コストは Terraform 資源の書き換えと secret 注入経路の差し替えに閉じる。リスクとして残るのは (1) Preview 機能（ephemeral disk）の仕様変更・GA 遅延、(2) 移行時に egress 費の性質が基盤ごとに変わる点のみ。

---

## この基盤に固有の論点

### Jobs と Services の使い分け

公式の位置づけがそのまま答えになる。Jobs は「仕事を実行して終了するコード（"performs work (a job) and quits when the work is done"）」向けで、ユースケースとして Script or tool / Array job / **Scheduled job** / AI workloads（batch inferencing）が明記されている[^what-is]。Services は HTTP リクエスト駆動でタイムアウト最大 60 分[^request-timeout]、Worker pools は Kafka/Pub/Sub consumer のような常駐 pull 型向け[^what-is]。**バッチ制作ランは Jobs が自然**であり、Services を挟む理由はない。

### 既存構成（ADR-0010・ADC・Terraform）との整合

- 単一 GCP プロジェクト構成にそのまま追加できる。Jobs / Scheduler / Secret Manager はすべて既存の Terraform google provider の資源（`google_cloud_run_v2_job` / `google_cloud_scheduler_job` はドキュメントの構成手段として明記[^jobs-schedule]）
- 認証は service identity + ADC で、Vertex AI（Lyria / Gemini）呼び出しと同一プロジェクト・同一 IAM 管理に収まる[^service-identity]
- 新規に増える運用面は「コンテナイメージのビルドと Artifact Registry への push」のみ（Artifact Registry には独自の無料枠があり、超過分は課金[^run-pricing]）

### GPU 不要の確認

GPU は L4 / RTX Pro 6000 が提供されるが[^run-pricing]、GPU 付き Jobs はタスクタイムアウトが 1 時間に制限される[^task-timeout]。ffmpeg CPU エンコード前提の本プロジェクトは GPU を使わないことで 168 時間タイムアウトと低い課金レートを維持できる。

---

## 出典

[^run-pricing]: Cloud Run pricing — https://cloud.google.com/run/pricing
[^vpc-pricing]: Network pricing（internet data transfer / inbound 無料 / Premium Tier 単価）— https://cloud.google.com/vpc/network-pricing
[^task-timeout]: Configure task timeout for jobs — https://docs.cloud.google.com/run/docs/configuring/task-timeout
[^request-timeout]: Configure request timeout for services — https://docs.cloud.google.com/run/docs/configuring/request-timeout
[^container-contract]: Container runtime contract — https://docs.cloud.google.com/run/docs/container-contract
[^memory-limits]: Configure memory limits — https://docs.cloud.google.com/run/docs/configuring/services/memory-limits
[^cpu-limits]: Configure CPU limits — https://docs.cloud.google.com/run/docs/configuring/services/cpu
[^ephemeral-disk]: Configure an ephemeral disk for Cloud Run jobs（Preview）— https://docs.cloud.google.com/run/docs/configuring/jobs/ephemeral-disk
[^gcs-fuse]: Configure Cloud Storage volume mounts for jobs — https://docs.cloud.google.com/run/docs/configuring/jobs/cloud-storage-volume-mounts
[^quotas]: Cloud Run quotas and limits — https://docs.cloud.google.com/run/quotas
[^what-is]: What is Cloud Run — https://docs.cloud.google.com/run/docs/overview/what-is-cloud-run
[^jobs-schedule]: Execute jobs on a schedule — https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule
[^scheduler-overview]: Cloud Scheduler overview（at-least-once / 冪等性）— https://docs.cloud.google.com/scheduler/docs/overview
[^scheduler-pricing]: Cloud Scheduler pricing — https://cloud.google.com/scheduler/pricing
[^jobs-secrets]: Configure secrets for jobs — https://docs.cloud.google.com/run/docs/configuring/jobs/secrets
[^sm-pricing]: Secret Manager pricing — https://cloud.google.com/secret-manager/pricing
[^deploying]: Deploying container images — https://docs.cloud.google.com/run/docs/deploying
[^service-identity]: Service identity（ADC / メタデータサーバ）— https://docs.cloud.google.com/run/docs/securing/service-identity
[^r2-pricing]: Cloudflare R2 pricing（egress 無料）— https://developers.cloudflare.com/r2/pricing/
[^cc-vertex]: Claude Code on Google Cloud's Agent Platform (Vertex AI) — https://code.claude.com/docs/en/google-vertex-ai
[^cc-headless]: Run Claude Code programmatically（`claude -p`）— https://code.claude.com/docs/en/headless
