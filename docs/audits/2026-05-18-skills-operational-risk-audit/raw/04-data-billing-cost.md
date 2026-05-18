# 課金 API コスト暴走ガード監査 (Part A-2 / dig.part-a2-billing-cost)

**調査日**: 2026-05-18
**スコープ**: 失敗→自動リトライ→quota 焼き切り / 無限ループ生成 / 想定外の高単価モデル選択 — の 3 軸に絞った金銭被害リスク
**前提除外**: PR #367 で実施済の汎用化・整合性観点は再検出しない
**対象**: `.claude/skills/**` (35 skill) + `src/youtube_automation/**` 実装

---

## 1. severity 別サマリー

| severity | 件数 | 内訳 |
|---|---|---|
| **P0** (1 回で 100 USD 超 / 無限ループ) | **0** | — |
| **P1** (高単価モデル選択 / quota 数千〜数万 unit 焼き) | **3** | F-1 / F-2 / F-3 |
| **P2** (リトライ設計のリスク / バッチ上限のなさ) | **3** | F-4 / F-5 / F-6 |
| **P3** (ドキュメント / 観測性) | **3** | F-7 / F-8 / F-9 |

P0 該当はゼロ。Veo / Lyria 等の生成系は **明示的なユーザー確認プロンプト**（`-y` / `--yes` フラグ）と **試行回数キャップ**（Gemini=3 / Lyria=4 / 動画アップ=5）が一通り入っており、現状で「1 回 100 USD 超を焼く穴」は確認できなかった。リスクは P1 以下の「条件付き」案件に集中する。

---

## 2. 課金 API × skill マッピング表

凡例: ◎=本命呼び出し / ○=補助呼び出し / △=条件付き / 課金=月額固定 or 従量

| skill | Veo (動画/秒) | Gemini (text+vision) | Lyria (音楽/song) | OpenAI Image | YouTube Data v3 (10k unit/day) | YouTube Analytics (別 quota) | Vultr VPS (月額+帯域) | 備考 |
|---|---|---|---|---|---|---|---|---|
| loop-video | ◎ | — | — | — | — | — | — | 1 ジョブ = 8 秒動画 1 本 |
| lyria | — | — | ◎ | — | — | — | — | N セグメント (N = ⌈(target_min + padding) × 60 / 184⌉) |
| thumbnail | — | ◎ (画像生成) | — | △ (provider 切替) | — | — | — | provider=gemini default |
| video-analyze | — | ◎ (動画解析) | — | — | — | — | — | --top N で件数指定 |
| video-description | — | ◎ (テキスト生成) | — | — | — | — | — | text-only |
| metadata-audit | — | — | — | — | ○ | — | — | videos.list 1 unit/件 |
| benchmark | — | △ (サムネ分析、`--no-thumbnails` で off) | — | — | ◎ | — | — | search/playlist/videos.list |
| discover-competitors | — | — | — | — | ◎ (660 unit/run) | — | — | search.list × keywords |
| video-upload | — | — | — | — | ◎ (1,600 unit/upload) | — | — | resumable upload |
| analytics-collect | — | — | — | — | ○ (動画 listing) | ◎ | — | reports.query 多発 |
| analytics-analyze | — | — | — | — | — | — | — | ローカル分析のみ |
| analytics-report | — | — | — | — | — | — | — | ローカル表示のみ |
| comments-reply | — | — | — | — | ◎ (commentThreads.list + comments.insert) | — | — | dry-run 既定 |
| channel-status | — | — | — | — | ○ | — | — | channels.list mine |
| channel-import | — | — | — | — | ○ | — | — | branding pull |
| channel-setup | — | — | — | — | ○ | — | — | branding push |
| collection-ideate | — | △ (preview 画像生成) | — | △ | — | — | — | thumbnail provider に委譲 |
| streaming | — | — | — | — | △ (archive 件数確認) | — | ◎ | $10/月 + 2TB/月 |
| postmortem / alignment-check / channel-research / channel-direction / audience-persona / viewer-voice / viewing-scene / thumbnail-compare / playlist / wf-* | — | — | — | — | △〜○ | △ | — | 既存 JSON の再利用が中心 |

---

## 3. 観点別の詳細所見

### 3.1 課金 API 呼び出し点棚卸し（観点 4.1）

| 呼び出し点 | ファイル | 1 skill 実行の最悪リクエスト数 |
|---|---|---|
| Veo 3.1 動画生成 | `src/youtube_automation/utils/veo_generator.py:47` (`generate_videos`) | **1 ジョブ** = 8 秒 (`veo_generator.py:23 MAX_POLL_SEC=600`)。skill 1 回 = 1 動画 |
| Veo operations.get poll | `veo_generator.py:76` | 5 秒 × 最大 120 回 = 最大 120 poll/ジョブ。poll は無料 (Long-running operation の get) |
| Lyria interactions | `src/youtube_automation/utils/lyria_client.py:139` | **N セグメント** (skill_config の `duration_padding_min=3` + `audio.target_duration_min`)。90 分マスター = 30 セグメント |
| Lyria リトライ | `src/youtube_automation/scripts/generate_lyria_master.py:143` | セグメントあたり最大 **`max_retries + 1` = 4 回**（既定）。失敗ループは `wait_sec = min(30, 10 * attempt)` で挟む |
| Gemini Image (Nano Banana) | `src/youtube_automation/utils/image_provider/gemini.py:64` | 1 thumbnail = 最大 **3 試行**（`RETRY_MAX=3`）。SAFETY/RECITATION は即時 fail（リトライしない、good） |
| Gemini Text/Video | `populate_scene_phrases.py:74` / `video_analyzer.py:79` | 1 動画あたり 1 リクエスト + `delay_sec=10`。`video_analyze.py:255` で APIError は failures に積み次へ（**リトライしない、good**） |
| Gemini benchmark サムネ分析 | `benchmark_collector.py:580` | 動画 × チャンネル数。`scan_recent=50` × `min_views=10000` 通過分のみ。`delay_sec=5` |
| OpenAI Images | `src/youtube_automation/utils/image_provider/openai.py:89-103` | 1 thumbnail = 最大 **3 試行**。`batch=1` default。`quality=high` default ← P1 リスク |
| YouTube Data search.list | `competitor_discovery.py:48` / `streaming/archive_counter.py:64` | search.list = **100 unit/call**。discover-competitors は `keywords × per_keyword_results`、streaming archive-check は月内ページング |
| YouTube Data upload | `upload_core.py:74` (videos().insert) | 1 upload = **1,600 unit**。MAX_RETRY_ATTEMPTS=5（5xx のみ）`upload_policy.py:13` |
| YouTube Data benchmark | `benchmark_collector.py:111` / `162` / `196` | channels.list (1 unit) + playlistItems.list (1 unit) × ページ + videos.list (1 unit) × ⌈scan_recent/50⌉。default scan_recent=50 → 3 API call/channel |
| Analytics reports.query | 各 Mixin（`channel_analytics.py:68` 他多数） | Analytics は別 quota（720 req/min 標準）。`strategic_analytics.py:416` で **ThreadPoolExecutor(max_workers=8)** 並列実行 |
| Vultr bandwidth | `streaming/vultr_bandwidth.py:41` | 月次レポート/閾値チェックで 1 call。Vultr API 自体は無料 |
| Vultr VPS | `infra/terraform/streaming/variables.tf:22` (`vc2-1c-2gb`) | **$10/月固定 + 2TB 帯域**。`terraform destroy` 必須 |

### 3.2 単価・quota の前提情報（観点 4.2）

`.env`/`docs/`/`README` を grep 済み。**ハードコード単価は撤廃済み**（`composition.py:174` のコメント「PRICING フォールバックは撤廃済み」 / `cost_tracker.py:9-10` 「Issue #132 で `estimated_cost_usd` は新規エントリで `null` 固定」）。

- Veo 3.1 / Lyria 3 / Gemini 3.1 / gpt-image-2 の **2026-05 時点の USD 単価は本リポジトリには存在しない**。`thumbnail/config.default.yaml:103-105` で `cost_per_image_usd: null` がコメントアウトされているのみ。実コストは GCP Cloud Console > Billing で確認する設計（`cost_tracker.py:203 _GCP_BILLING_HINT`）。
- **YouTube Data API quota**（2026-05-18 時点で WebFetch せず実装側の引用を採用）:
  - search.list = 100 unit (`discover-competitors/SKILL.md:118`)
  - videos.insert = 1,600 unit (`video-upload/SKILL.md:47` の "API クォータ: 2 × 1,600 = 3,200 ユニット"）
  - その他 list = 1 unit
  - 日次 quota = 10,000 unit（プロジェクト既定）
- **Vultr プラン定数**: `streaming/__init__.py:10-22`
  - MONTHLY_QUOTA_GB = 2048
  - THRESHOLD_RATIO = 0.80（80% で webhook アラート）
  - THEORETICAL_BITRATE_MBPS = 4
- **調査不可項目**: 各生成 API の USD/秒・USD/song・USD/image。WebFetch でも 2026-05 時点の公式単価は流動的なため、推測単価で見積もりは出さない方針とする。代わりに「1 skill 実行で発生するリクエスト数」を §3.4 の表に明示する。

### 3.3 コスト制御ガード（観点 4.3）

| skill / モジュール | dry-run | ユーザー確認 | 上限キャップ | ファイル:行 |
|---|---|---|---|---|
| loop-video | ❌ | ✅ `-y` 未指定で対話 | duration_seconds = 8（API 仕様で固定） | `generate_loop_video.py:91, 141-144` |
| lyria | ❌（CLI 直） | ⚠️ skill 内の Step 3 で人手承認するフロー設計だが、CLI 自体は確認しない | max_retries 既定 3 + 1（`--max-retries`）, segment 数 = `ceil((target+padding)*60/184)`、上限なし | `generate_lyria_master.py:143, 233-237` |
| thumbnail / generate-image | ❌ | ✅ `confirm_cost()` で y/N 確認 | RETRY_MAX = 3 | `composition.py:58-78` / `image_provider/base.py:14` |
| video-analyze | ❌ | ❌ | `--top` で件数指定（default 5）。リトライなし | `video_analyze.py:213-217, 255` |
| benchmark | ❌ | ❌ | `freshness_days=3` で更新スキップ。`--no-thumbnails` で Gemini off。`--playlists` は `--channel` 必須（誤爆防止） | `benchmark_collector.py:1183-1186`, `benchmark/config.default.yaml:11-16` |
| discover-competitors | ❌ | ❌ | keywords × per_keyword_results を CLI 引数で制御。SKILL.md に 660 unit/run と明示 | `discover-competitors/SKILL.md:116-119` |
| video-upload | ✅ `--plan` あり | ❌ | upload_policy MAX_RETRY_ATTEMPTS=5（5xx 限定）, 403 quota 系はリトライしない設計 | `upload_policy.py:13-14` / `upload_core.py:120-128` |
| comments-reply | ✅ `--dry-run` 既定 | ✅ dry-run 経由必須運用 | max_replies_per_run = 20, delay_between_replies_sec = 2.0, history 重複防止 | `config/loader.py:316-317` / `replier.py:113-124, 199-203` |
| analytics-collect | ❌ | ❌ | `freshness 30 分以内ならスキップ`（`analytics-collect/SKILL.md:33-40`）、Analytics は別 quota | — |
| streaming bandwidth | ❌ | ❌ | THRESHOLD_RATIO=0.80 で webhook アラート | `streaming/__init__.py:13` |

**観察**:
- 生成系（Veo / Lyria / Image）は **CLI 起動時に y/N 確認 or `-y` 必須**。Lyria だけは確認プロンプトなし（skill 側 Instructions の Step 3 で人手承認する想定）。
- `cost_tracker.log_generation`（`cost_tracker.py:94`）が画像/動画/音楽の生成 1 件ごとに記録 → `yt-cost-report` CLI で照会可能。**ただし USD 推定はしない**（Issue #132 以降は GCP Billing 側で確認する設計）。

### 3.4 リトライ戦略のコスト影響（観点 4.4）

| 呼び出し | ファイル:行 | 上限 | バックオフ | 評価 |
|---|---|---|---|---|
| Veo 3.1 generate_videos | `veo_generator.py:47` | **1 回**（try-except で False 返却） | — | ✅ safe |
| Veo poll | `veo_generator.py:68-76` | 120 回 (`MAX_POLL_SEC=600 / POLL_INTERVAL_SEC=5`) | 5 秒固定 | ✅ poll は無課金 |
| Lyria generate_music | `lyria_client.py:139` | **1 回**（None 返却） | — | ✅ safe |
| Lyria segment retry | `generate_lyria_master.py:143-147` | 既定 `max_retries=3` → 試行 4 回 | `wait_sec = min(30, 10 * attempt)` | ✅ 上限あり |
| Gemini Image | `image_provider/gemini.py:57-108` | RETRY_MAX=3 | (10, 30, 60) 秒 | ✅ SAFETY/RECITATION は即時 fail |
| Gemini Text/Video | `video_analyzer.py:79` | **0 リトライ**（APIError は failures に積み次へ） | — | ✅ safe |
| Gemini 翻訳 (populate_scene_phrases) | `populate_scene_phrases.py:35-87` | `_RETRY_MAX=3` | (5, 15) 秒 | ✅ |
| OpenAI Image | `image_provider/openai.py:78-132` | RETRY_MAX=3 | (10, 30, 60) 秒 | ✅ ConfigError は fail-fast |
| YouTube Data upload | `upload_core.py:111-128` + `upload_policy.py:39-53` | MAX_RETRY_ATTEMPTS=5 | `2 ** attempt` 秒 | ✅ **403 は retry しない**（quota 焼け防止が効いている） |
| YouTube Data search/list (benchmark) | `benchmark_collector.py:162` | ページング上限なし（`scan_recent` で打ち切り） | — | ⚠️ 後述 F-2 |
| Analytics reports.query | `strategic_analytics.py:286-351` | バッチサイズ 10 × 上位 N 件、エラー時 break | — | ✅ |
| Analytics 並列 | `strategic_analytics.py:416` | `ThreadPoolExecutor(max_workers=8)` | — | ⚠️ 後述 F-3 |
| Vultr bandwidth | `vultr_bandwidth.py:42-46` | **0 リトライ** | — | ✅（Vultr API は無料） |

**まとめ**: 「無限リトライで quota を焼く」パターンは見当たらない。全ての生成系で `RETRY_MAX` / `MAX_RETRY_ATTEMPTS` がコードレベルで定義されている。

### 3.5 モデル選択の固定 / フォールバック（観点 4.5）

| skill / モジュール | 既定モデル | フォールバック挙動 | リスク |
|---|---|---|---|
| Veo (loop-video) | `veo-3.1-fast-generate-001` (`veo_generator.py:15`, `loop-video/config.default.yaml:8`) | `--model` > skill-config > DEFAULT_MODEL。**fast 系を default 採用**（コスト低） | ✅ 安全寄り |
| Lyria | `lyria-3-pro-preview` (`lyria/config.default.yaml:17`) | `--model` > skill-config。`lyria-3-clip-preview`（30秒固定）は preview 用 | ⚠️ pro 既定。preview→pro の切替誤りで song あたり単価差 |
| Gemini Image | `gemini-3.1-flash-image-preview` (`image_provider/config.py:27`) | skill-config の `image_generation.gemini.model` で上書き可 | ✅ flash 既定 |
| Gemini Text | `gemini-2.5-flash` (`benchmark/config.default.yaml:23`, `video-analyze/config.default.yaml:7`) | skill-config 上書き可 | ✅ flash 既定 |
| Gemini 翻訳 | `gemini-2.5-flash-lite` (`populate_scene_phrases.py:33`) | ハードコード | ✅ flash-lite（最安） |
| OpenAI Image | `gpt-image-2` (`image_provider/config.py:150`) | skill-config 上書き可 | ⚠️ **`quality=high` が既定**（`config.py:151`, `thumbnail/config.default.yaml:92`）。low/medium に比べ大幅高単価 → P1 |
| YouTube Reporting | 自動選定 (Reach 系) | `reporting_api.py:65-68` で priorities 順 | ✅ 自動 |

**観察**: 画像/動画系の既定モデルは **fast/flash 系の低単価モデル**で固定されており、設計の意図は明確。唯一 OpenAI の `quality=high` だけが「明示的に高単価設定」になっている（後述 F-1）。

---

## 4. 「1 回の skill 実行で最悪いくらかかるか」概算表

USD 単価は不明（前述）のため、**「最悪リクエスト数」と「焼き切る可能性のある quota」**で表現する。

| skill | リクエスト最大数（1 回実行） | Quota 影響 | 注記 |
|---|---|---|---|
| loop-video | Veo ジョブ **1 本**（8 秒） | Vertex AI billing | poll 120 回は無料。事故っても 1 動画 |
| lyria（90 分マスター） | Lyria 生成 **30 セグメント × max 4 試行 = 120 リクエスト最悪** | Vertex AI billing | 既存 wav は skip（resume） |
| lyria（10 時間ロング） | **200 セグメント × 4 = 800 リクエスト最悪** | Vertex AI billing | 既存 wav skip で復帰可。**target_duration_min × duration_padding_min に上限なし** → F-4 |
| thumbnail | 画像生成 **1 枚 × 3 試行 = 3 リクエスト** | Vertex/OpenAI billing | confirm_cost 必須 |
| video-analyze --top 5 | Gemini **5 動画解析** | Vertex AI billing | リトライなし |
| benchmark（全チャンネル更新） | YouTube Data ~3 unit/channel + Gemini サムネ N 枚 | Data quota: ~30 unit/channel（軽い）/ Gemini billing | サムネ分析を `--no-thumbnails` で off 可 |
| discover-competitors | search.list × keywords (default 3-5) = **660 unit/run** | Data quota の 6.6% | SKILL.md に明示 |
| video-upload (single_release JP+EN) | videos.insert × 2 + thumbnails.set × 2 = **3,200+ unit** | Data quota の 32% | 同日 2 本投稿構成 |
| video-upload + 多言語 collection | 1,600 unit + thumbnails.set | Data quota の 16% | |
| comments-reply --apply --limit 20 | commentThreads.list (1) × videos + comments.insert × 20 | Data quota: **~20-40 unit/run** | dry-run 既定で誤投稿防止 |
| analytics-collect | reports.query 多数 (8 並列) + Data API videos listing | **Analytics quota（別枠 720req/min）** + Data quota 数十 unit | 30 分鮮度キャッシュあり |
| streaming archive-check (月次) | search.list × ⌈月内動画/50⌉ ≈ 2 page × 100 unit = **200 unit** | Data quota | 月 1 回 cron 想定 |
| streaming VPS | — | **Vultr $10/月固定** + 帯域 2TB/月 | terraform destroy 必須 |

---

## 5. Findings（severity 付き、推奨アクション含む）

| # | severity | 内容 | ファイル:行 | 推奨アクション |
|---|---|---|---|---|
| **F-1** | P1 | **OpenAI Image の `quality=high` が既定**。Gemini を default にしているチャンネルで provider 切替時、無自覚に high quality が選ばれる。gpt-image-2 は low/medium/high で単価が階層化されており、`high` は数倍コスト。`thumbnail/config.default.yaml:92` には `# 品質階層: low | medium | high` とコメントがあるが既定が high | `src/youtube_automation/utils/image_provider/config.py:151` / `.claude/skills/thumbnail/config.default.yaml:92` | quality の既定を `medium` に下げる or skill SKILL.md に「provider=openai 時は quality を明示確認」と書く |
| **F-2** | P1 | **benchmark `scan_recent` 上限なし**。skill-config で `scan_recent: 50` が default だが、ユーザーが 1000 に設定するとチャンネルあたり ⌈1000/50⌉=20 page × playlistItems.list = 20 unit、videos.list 20 batch = 20 unit。10 チャンネル × `--force` で **400+ unit**。Gemini サムネ分析が走ると更にスケール（min_views で間引かれるが）。skill-config では値域 validate なし | `src/youtube_automation/scripts/benchmark_collector.py:135-178` / `.claude/skills/benchmark/config.default.yaml:11` | `scan_recent` に上限 validate（例: max 200）を追加 or SKILL.md に「scan_recent を上げる際の quota 計算式」を明記 |
| **F-3** | P1 | **Lyria の segment 数に上限がない**。`audio.target_duration_min` を 600（10 時間）にすると ⌈600+3*60/184⌉ = **196 セグメント** × max_retries+1 = **最大 784 Lyria API call**。Vertex AI の Lyria クォータ（プロジェクト単位）が枯渇する可能性 + 課金が線形に増える。skill 側の Step 3 で人手承認するフロー設計だが、CLI 単体（`yt-generate-lyria-master`）は confirm prompt を持たない | `src/youtube_automation/scripts/generate_lyria_master.py:68-79` / `lyria_client.py:139` | CLI に「N セグメント生成しますがよろしいですか？」の `-y` 確認を追加、または上限 segment 数を skill-config で明示（例: `max_segments: 60`）。SKILL.md `Step 4` の注意点に追記 |
| **F-4** | P2 | **Analytics の ThreadPoolExecutor が `max_workers=8` 固定**。1 チャンネル数百本動画があると 8 並列で reports.query を叩き、Analytics quota（720 req/min）を**最悪 8 秒で 100 req 消費**。Analytics は Data quota とは別枠で安全弁が緩い。エラー時は worker 単位で degrade するため致命傷にはならないが、quota 枯渇で **後続 skill が all-fail する連鎖**は起きうる | `src/youtube_automation/utils/strategic_analytics.py:25, 416` | `max_workers` を skill-config で可変化 + 既定を 4 に下げる、または `time.sleep(0.1)` で per-worker rate limit を入れる |
| **F-5** | P2 | **Veo `MAX_POLL_SEC=600` でタイムアウトしても Vertex 側でジョブが走り続ける可能性**。タイムアウトで `return False` する（`veo_generator.py:71`）が、Vertex AI 側のオペレーションを cancel するコードはない（`client.operations.cancel` 等は呼ばれていない）。Veo ジョブは生成完了まで課金されるため、Python 側が早期 return しても料金は発生 | `src/youtube_automation/utils/veo_generator.py:67-71` | (a) タイムアウト時に `client.operations.cancel(operation)` を呼ぶ、または (b) MAX_POLL_SEC をもっと長く取る（Veo 3.1 fast は通常 1-3 分で完了するため、現状 10 分でも実害は小さい）。少なくとも SKILL.md に「タイムアウトでもジョブは継続課金される」と書く |
| **F-6** | P2 | **`generate_lyria_master.py:145` の retry バックオフが上限 30 秒**。`min(30, 10 * attempt)` で attempt=3 でも 30 秒。Vertex AI Lyria が 429 を返すケースで 30 秒待機 × max_retries=3 = 90 秒で全試行を消費し、後続セグメントも同じ高負荷状況で 429 を引き続け失敗 → 中断。コストではなく**運用効率の問題**で、リトライ全消費後に手動再実行する場合、再実行ごとに「直前まで成功」分は skip されるためコスト二重課金は起きない。だが大量リトライが quota を更に焼く | `src/youtube_automation/scripts/generate_lyria_master.py:144-147` | バックオフを `min(120, 30 * 2 ** attempt)` 程度に拡大、または 429 専用の長めウェイトを入れる |
| **F-7** | P3 | **`cost_tracker.estimated_cost_usd` が常に null**（Issue #132 設計）。`yt-cost-report` で件数は集計できるが **金額は出ない**。GCP Cloud Console > Billing を見ないとコスト実態が把握できず、暴走検出が遅れる | `src/youtube_automation/utils/cost_tracker.py:9-20, 117-119` | 「GCP Billing アラート」を SKILL.md レベルで案内する（streaming に 80% アラートが入っているのと同じパターン）。`yt-cost-report` 出力末尾に GCP Billing URL を表示 |
| **F-8** | P3 | **streaming archive_counter が `search.list` を使う**。search.list = 100 unit/call。月の動画 60 本 → 2 page × 100 = 200 unit/run。毎月の cron + 都度確認で月 1,000 unit 程度を消費。SKILL.md は「`yt-stream-archive-check` でアーカイブ件数確認」と書くだけで quota 影響は無記載 | `src/youtube_automation/utils/streaming/archive_counter.py:55, 64` / `.claude/skills/streaming/SKILL.md:30, 39` | `playlistItems.list`（1 unit）+ クライアント側日付フィルタに置き換える、または SKILL.md に quota 影響を追記 |
| **F-9** | P3 | **`collection_uploader.py:451` の `while True: schedule.run_pending(); time.sleep(60)` 常駐スケジューラ**。`run_automated_schedule` が呼ばれた場合のみ走る。「事故で常駐させ続けて quota を毎日 1,600 × N 単位で消費」というシナリオはあるが、明示的に手動起動する設計のため P3 | `src/youtube_automation/agents/collection_uploader.py:440-457` | SKILL.md / README で「`run_automated_schedule` は手動運用用途。CI で常駐させない」と注記 |

---

## 6. 注意点・残リスク

1. **「無限ループ生成」リスクはコードレベルでは検出されず**。Lyria の `target_duration_min` 上限なし（F-3）が最も「設定値次第で線形にコスト膨張」する箇所。
2. `cost_tracker` は USD 算出を放棄しているため、**「いくら使ったか」を Python 側で観測できない**。Issue #132 設計上の意図的選択だが、暴走検出能力は GCP Billing に完全依存。
3. **Vultr streaming は固定 $10/月 + 帯域従量**で、Python 側のコード経路で暴走するシナリオは無い。むしろ「`terraform destroy` し忘れ」が現実的な金銭リスクで、SKILL.md §5 に明記済み（P2 とは扱わない）。
4. PR #367 (汎用化・整合性) でカバー済とされる「ハードコード単価」「PRICING テーブル」系の残骸は今回再検出しないルールに従い除外したが、`composition.py:174` の「PRICING フォールバックは撤廃済み」コメントが残っており、現行コードは null 設計に統一されていることを確認した。

---

## 7. 調査不可項目と理由

| 項目 | 理由 |
|---|---|
| Veo 3.1 fast/standard/lite の 2026-05 単価 (USD/秒) | リポジトリ内に単価情報なし（Issue #132 で撤廃）。WebFetch は GCP 公式ページが時系列で変動するため、推測単価で見積もりを出すと誤情報になるので回避 |
| Lyria 3 Pro / Clip の単価 (USD/song) | 同上 |
| Gemini 3.1 flash-image / 2.5 flash の単価 | 同上 |
| gpt-image-2 quality 別単価 | 同上 |
| Vultr 帯域超過時の単価（$/GB） | `streaming/README.md` 参照（本タスク範囲外） |
| YouTube Data API の有償拡張枠 | 標準 quota（10k/日）想定で、拡張申請は別フロー |
| 「1 skill 実行で最悪何 USD」 | 単価が取れないため算出不可。代わりに §4 でリクエスト数で表現 |

---

## 8. 推奨アクション（severity 付き、優先度順）

| 優先度 | 対応 | 関連 Finding | 工数感 |
|---|---|---|---|
| P1 | OpenAI Image の `quality` 既定を `medium` に下げる、または SKILL.md に明示警告を追加 | F-1 | XS |
| P1 | `benchmark.scan_recent` に上限 validate（例: max 200）+ SKILL.md に quota 計算式追記 | F-2 | S |
| P1 | `yt-generate-lyria-master` に segment 数の確認プロンプト（`-y` 未指定時）と segment 数上限（skill-config）を追加 | F-3 | S |
| P2 | Analytics の `_MAX_WORKERS=8` を skill-config で可変化 + 既定を 4 に | F-4 | S |
| P2 | Veo タイムアウト時の `operations.cancel` 呼び出し、または SKILL.md に「タイムアウト後も課金継続」を明示 | F-5 | M |
| P2 | Lyria リトライバックオフを `min(120, 30 * 2 ** attempt)` に拡大 | F-6 | XS |
| P3 | `yt-cost-report` 出力末尾に GCP Billing アラート URL / 設定手順を案内 | F-7 | XS |
| P3 | streaming archive_counter を search.list → playlistItems.list に置換、または SKILL.md に quota 注記 | F-8 | M |
| P3 | `collection_uploader.run_automated_schedule` の常駐運用注意を SKILL.md / README に追記 | F-9 | XS |

---

## 9. 監査スコープと根拠

- **コード読み取り対象**: `src/youtube_automation/{utils,scripts,agents,cli}/*.py` のうち課金 API を呼ぶ全ファイル
- **skill 読み取り対象**: `.claude/skills/{loop-video,lyria,thumbnail,video-analyze,benchmark,discover-competitors,video-upload,comments-reply,analytics-collect,streaming}/SKILL.md` + 各 `config.default.yaml`
- **検索手段**: Grep（`while True` / `retry` / `MAX_` / `RETRY_` / `model:` / `cost_per_image_usd` / `MONTHLY_QUOTA_GB` / `maxResults` / `search().list` / `videos().list`）+ Read（実装の確認）
- **コード修正**: なし（読み取り専用）
