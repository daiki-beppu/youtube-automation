# dig-part-a — ハードコード値検出 & 既存 config 参照漏れ

実行日: 2026-05-18
担当ステップ: dig (2/4) — Part A
対象: `.claude/skills/**` 配下 **35 スキル**（`SKILL.md` 35 件 + `references/**` + `config.default.yaml` 9 件、合計 81 ファイル）
比較対象 (一次情報): `examples/channel_config.example/*.json` 8 ファイル（meta / content / youtube / analytics / playlists / workflow / audio / comments）
方法: Read / Grep / Glob のみ（編集禁止 — `.claude/skills/**` は protected paths）

---

## 1. 概要

| 区分 | 検出件数 | 主な内訳 |
|---|---|---|
| **A-1 数値ハードコード**（しきい値・尺・タイムアウト等） | **14 箇所** | レポート鮮度 30 分（×2 skill）/ Veo 8 秒 / Lyria 184 秒 / API timeout 5+10 秒 / CTR 判定閾値 0.5/0.7/0.9 / video_id 文字数 11 / マスター動画解像度 1920×1080 / 等 |
| **A-2 モデル名・URL ハードコード** | **11 箇所** | `gemini-2.5-flash` ×4 / `veo-3.1-fast-generate-001` ×3 / `lyria-3-pro-preview` ×2 / `gpt-image-2` / `gemini-3.1-flash-image-preview` / `cdn1.suno.ai` ×4 / `discord.com` 正規表現 / `cloud.google.com/sdk` 等 |
| **A-3 パス・ディレクトリ直書き**（`channel_dir()` / `CollectionPaths` を経由していない） | **22 箇所** | `collections/planning/` ×9 / `collections/live/` ×11 / `01-master/` / `02-Individual-music/` / `10-assets/` / `20-documentation/` / `auth/token.json` / `branding/` 等。多くは ガイド／例示用で正当 |
| **A-4 既存 config キーと重複している直書き** | **6 箇所** | `descriptions.perfect_for` の項目数 "4" / `descriptions.hashtags` "5 個" / `tags.base` 件数 "10 個程度" / `tags.themes` "6-10 テーマ" / `audio.target_duration_min/max` 監査文言 / `youtube.category_id="10"` 等 |
| **A-5 raw `json.load` / `yaml.safe_load` で channel config を読んでいる references スクリプト** | **0 箇所**（false positive 1 件） | `channel-setup/references/verification.md:12` の `json.load(open(p))` は **JSON 構文検証**用途で、設定値の消費ではないため対象外 |

**Top 影響度（P1）**: §7 サマリー参照。最も対応価値が高いのは **(1) 30 分鮮度しきい値の skill-config 化**（analytics-collect / analytics-analyze で全く同じ「30 分」が直書き）、**(2) API timeout / Veo duration の skill-config 化**、**(3) `descriptions.perfect_for` 個数や `tags.base` 個数の SKILL.md→config-generation-rules.md 一元化**。

---

## 2. A-1 — 数値ハードコード（しきい値・尺・タイムアウト・リトライ）

### 検出フォーマット
`file:line — 値 / 文脈 → 提案外出し先`

| # | file:line | 値 | 文脈 | 提案外出し先（推測） |
|---|---|---|---|---|
| A1-1 | `.claude/skills/analytics-collect/SKILL.md:36-39` | **30 分** | 「ファイルの更新時刻が **30分以内** → 収集をスキップ」 | `config/skills/analytics-collect.yaml::freshness_minutes`（新規） |
| A1-2 | `.claude/skills/analytics-analyze/SKILL.md:38-39` | **30 分** | 「30分以内に生成されたレポートがあれば分析をスキップ」 | 同上（共通の `analytics.freshness_minutes` を 1 か所に） |
| A1-3 | `.claude/skills/streaming/references/notify.sh:67-68` | **5 秒 / 10 秒** | `curl --connect-timeout 5 --max-time 10` | `config/skills/streaming.yaml::notify.{connect_timeout_sec,max_time_sec}`（要確認・streaming は ops 性が強い） |
| A1-4 | `.claude/skills/streaming/references/healthcheck.sh:79`（SKILL.md 参照） | **5 分間隔 / RuntimeMaxSec=11h / RestartSec=1h** | systemd cron / Terraform 定義由来。SKILL.md L8, L80 で参照 | `infra/terraform/streaming/` の tfvar が Single Source。SKILL.md 側はドキュメントなので **正当**（要確認） |
| A1-5 | `.claude/skills/loop-video/SKILL.md:118` / `loop-video/config.default.yaml:20` | **8 秒** | `veo.duration_seconds: 8`（Veo API 制約） | **既に skill-config 化済み**（OK、追加対応不要） |
| A1-6 | `.claude/skills/lyria/SKILL.md:10,76,94,168` / `lyria/config.default.yaml:8,15` | **184 秒** | Lyria 3 1 リクエスト上限。SKILL.md 4 箇所で直書き | **既に skill-config 化済み**だが、SKILL.md 内の `184` 数値は CLI 計算式 `ceil((target + padding) * 60 / 184)` でも露出。コード側に集約推奨（CLI に定数化） |
| A1-7 | `.claude/skills/lyria/config.default.yaml:28` | **5 秒** | `crossfade_sec: 5`（セグメント間クロスフェード） | skill-config 化済み（OK） |
| A1-8 | `.claude/skills/lyria/SKILL.md:194` | **3** | `--max-retries N` default: 3 | CLI 側 default なので CLI 実装に集約。**要確認**（skill-config からも上書き可能にすべきか） |
| A1-9 | `.claude/skills/postmortem/SKILL.md:71-78` | **0.5 / 0.7 / 0.9 / 0.5 / 0.9 / 0.7** | CTR 判定の比率閾値（赤/黄/薄黄/緑） | `config/skills/postmortem.yaml::thresholds.ratio_vs_median.{red,yellow,light_yellow}`（新規） |
| A1-10 | `.claude/skills/postmortem/SKILL.md:45` | **11 文字** | `<video_id>（11 文字英数 + -_）` | YouTube API 仕様値。**正当**（外出し不要） |
| A1-11 | `.claude/skills/postmortem/SKILL.md:64` | **±10%** | 「全指標が中央値前後（±10%）」 | A1-9 と同セクションに統合（`thresholds.neutral_band_pct`） |
| A1-12 | `.claude/skills/videoup/references/generate_videos.sh:73,148-149,174-175,189,202,212` | **1920×1080 / 384k / 48000 / CRF 18/23 / framerate 1** | ffmpeg コマンドの固定値（解像度・ビットレート・CRF） | `config/skills/videoup.yaml`（新規）に `video.{width,height,audio_bitrate,sample_rate,crf}` セクション。**P2**（チャンネル独自のフォーマットを許容したい場合のみ） |
| A1-13 | `.claude/skills/collection-ideate/config.default.yaml:18,37` | **2 / 0.5** | `session_id_bytes: 2`, `originality.max_similarity: 0.5` | **既に skill-config 化済み**（OK） |
| A1-14 | `.claude/skills/benchmark/config.default.yaml:10,13,16,24` | **50 / 10000 / 3 / 5** | `scan_recent / min_views / freshness_days / delay_sec` | **既に skill-config 化済み**（OK） |
| A1-15 | `.claude/skills/comments-reply/SKILL.md:58` | **100** | `--per-video-limit N` default: 100 | CLI default。`config/channel/comments.json` 側に `per_video_limit` を足すと整合性 ↑（**要確認**） |
| A1-16 | `.claude/skills/discover-competitors/SKILL.md:85-90,116` | **10K / 1M / 30日 / 20 / 660 units** | CLI フラグ既定値の引用 | CLI 側に集約済み。SKILL.md は **ドキュメンテーション** なので **正当**（ただし数値変更時の同期コストあり） |
| A1-17 | `.claude/skills/video-analyze/config.default.yaml:10` | **10** | `delay_sec: 10`（API レート対策） | **既に skill-config 化済み**（OK） |
| A1-18 | `.claude/skills/masterup/config.default.yaml:10,13` | **1.0 / "192k"** | `audio.crossfade_duration / bitrate` | **既に skill-config 化済み**（OK） |
| A1-19 | `.claude/skills/thumbnail/config.default.yaml:101` | **1** | `openai.batch: 1` | **既に skill-config 化済み**（OK） |
| A1-20 | `.claude/skills/analytics-report/SKILL.md:62,104` | **4 / 1200px** | KPI カード枚数 / `max-width: 1200px` | 影響度低。HTML テンプレ側に集約（**P3**） |
| A1-21 | `.claude/skills/wf-next/SKILL.md:41` / `lyria/SKILL.md:201` | **184 秒 / 30〜90 秒** | ガイド文書内の数値 | A1-6 参照（CLI 定数で集約） |
| A1-22 | `.claude/skills/channel-setup/references/verification.md:68-69` | **2048×1152 / 800×800 / 6MB / 4MB** | YouTube バナー・アイコン上限値 | YouTube API 仕様値。**正当**（外出し不要） |

**正味の新規外出し候補（P1）**: A1-1/A1-2（30 分鮮度）、A1-3（streaming notify timeout）、A1-9/A1-11（postmortem CTR 判定閾値）。
**正味の新規外出し候補（P2）**: A1-12（videoup の ffmpeg パラメータ）、A1-15（comments-reply の per-video-limit）。

---

## 3. A-2 — モデル名・API バージョン・エンドポイント URL の直書き

| # | file:line | 値 | 文脈 | 提案外出し先 |
|---|---|---|---|---|
| A2-1 | `.claude/skills/benchmark/SKILL.md:98` / `benchmark/config.default.yaml:23` | `gemini-2.5-flash` | サムネイル分析モデル | **既に skill-config 化済み**（`thumbnail_analysis.model`、OK） |
| A2-2 | `.claude/skills/video-analyze/SKILL.md:58` / `video-analyze/config.default.yaml:7` | `gemini-2.5-flash` | Gemini モデル | **既に skill-config 化済み**（OK） |
| A2-3 | `.claude/skills/wf-new/references/scene_phrases.md:26,41` | `gemini-2.5-flash` | `yt-populate-scene-phrases --model` の既定値ドキュメント | CLI 側 default を引用。**正当**（ドキュメンテーション） |
| A2-4 | `.claude/skills/loop-video/SKILL.md:107,116` / `loop-video/config.default.yaml:8` | `veo-3.1-fast-generate-001` / `veo-3.1-generate-001` / `veo-3.1-lite-generate-preview` | Veo モデル | **既に skill-config 化済み**（OK） |
| A2-5 | `.claude/skills/lyria/SKILL.md:60,85` / `lyria/config.default.yaml:17` | `lyria-3-pro-preview` / `lyria-3-clip-preview` | Lyria モデル | **既に skill-config 化済み**（OK） |
| A2-6 | `.claude/skills/thumbnail/config.default.yaml:18,89` | `gemini-3.1-flash-image-preview` / `gpt-image-2` | Gemini/OpenAI 画像生成モデル | **既に skill-config 化済み**（OK） |
| A2-7 | `.claude/skills/collection-ideate/SKILL.md:139` | `gemini-3.1-flash-image-preview` | コスト見積りの例示文字列 | thumbnail skill-config 経由で取得済み（OK） |
| A2-8 | `.claude/skills/masterup/SKILL.md:22,84,89,174` / `masterup/config.default.yaml:33` | `https://cdn1.suno.ai/{song_id}.mp3` | Suno CDN URL テンプレ | **既に skill-config 化済み**（`suno_download.cdn_url_template`、OK）。ただし SKILL.md 本文側 4 箇所で URL が再露出 → skill-config 値の引用に統一推奨 |
| A2-9 | `.claude/skills/streaming/references/notify.sh:37` | `https://(discord\.com\|discordapp\.com)/api/webhooks/` | Discord 公式ホスト許可リスト（SSRF 防御の正規表現） | セキュリティ上 **正当**（コード側に固定すべき） |
| A2-10 | `.claude/skills/streaming/SKILL.md:51,52` | `op://Personal/YouTube/stream_key` etc. | 1Password アイテムパス | 個人ボルト名は **チャンネル個別設定**。`config/skills/streaming.yaml::onepassword_paths` で外出し可（**P2**、要確認） |
| A2-11 | `.claude/skills/channel-setup/references/gcp-bootstrap.sh:108,239` / `gcp-terraform-apply.sh:38` / `streaming/references/swap_video.sh:62` | `https://cloud.google.com/sdk/docs/install` / `https://developer.hashicorp.com/terraform/install` / `https://console.cloud.google.com/apis/credentials?project=…` | エラーメッセージ内のガイド URL | **正当**（外部公式ドキュメントへの恒久リンク） |
| A2-12 | `.claude/skills/channel-import/SKILL.md:26` / `channel-new/SKILL.md:49` | `git+https://github.com/daiki-beppu/youtube-channels-automation.git` | パッケージインストール URL | 配布元の Single Source。テンプレリポ移行時のみ更新必要（**正当**だが移行検討の影響範囲調査時に拾えるようメモ） |
| A2-13 | `.claude/skills/lyria/config.default.yaml:32-37` | `ambient pads / ethereal choir / cinematic / orchestral / epic / synthesizer` | Lyria NG ワードリスト | **既に skill-config 化済み**（OK） |
| A2-14 | `.claude/skills/suno/config.default.yaml:13` | `heavy metal, aggressive, EDM, dubstep, …` | Suno Exclude Styles | **既に skill-config 化済み**（OK） |

**結論**: A-2 系の新規外出し候補は **A2-8（masterup SKILL.md 本文の URL 4 箇所の引用化）** と **A2-10（streaming の 1Password ボルトパス）** のみ。他はすべて既に skill-config 化済み or 外出し不要。

---

## 4. A-3 — ファイルパス・ディレクトリ名の直書き

検出方針: `collection_paths.CollectionPaths` を経由せず `01-master/` `10-assets/` `20-documentation/` 等を文字列リテラルで参照している箇所、および `config/channel/` や `auth/` を直書きしている箇所。

| # | file:line | 値 | 文脈 | 判定 / 提案 |
|---|---|---|---|---|
| A3-1 | `.claude/skills/videoup/references/generate_videos.sh:23-24,39,49,144` | `01-master/`, `10-assets/`, `loop_normalized.mp4` | ffmpeg コマンドのコレクションパス解決 | bash スクリプトのため `CollectionPaths` 不可。**現状維持で正当**（コード内定数として扱う） |
| A3-2 | `.claude/skills/live-clean/SKILL.md:39,92-100` | `01-master/master.mp3` / `01-master/master-mix.wav` / `01-master/*-Master.mp4` / `02-Individual-music/*.mp3` / `10-assets/loop_normalized.mp4` | 削除対象ファイルの SKILL.md 内列挙 | SKILL.md レベルの仕様文書。Python 実装に Lift する場合は `CollectionPaths` 経由（**P2**） |
| A3-3 | `.claude/skills/lyria/references/worktree_sync.sh:72-104` | `01-master/master.wav` / `01-master/*.mp4` / `10-assets/main.png` / `10-assets/main.jpg` | rsync 元・コピー先指定 | bash スクリプトのため正当。複数 sync 関数で同名繰り返しは命名定数化推奨（**P3**） |
| A3-4 | `.claude/skills/masterup/SKILL.md:64,85,89,135-156` | `02-Individual-music/`, `01-master/` etc. | rsync 命令を含む SKILL.md ガイド文 | SKILL.md は仕様書。**現状維持で正当** |
| A3-5 | `.claude/skills/alignment-check/SKILL.md:41,78-80` | `collections/live/*/10-assets/thumbnail.jpg` 等 | Glob 探索パターン | **正当**（Glob 用パターン文字列） |
| A3-6 | `.claude/skills/wf-status/SKILL.md:22` / `wf-next/SKILL.md:22` / `masterup/SKILL.md:68` / `lyria/SKILL.md:114` / `loop-video/SKILL.md:43` / `videoup/SKILL.md:36` / `collection-ideate/SKILL.md:299` | `collections/planning/` の Glob | コレクション自動検出処理の入口 | 全 7 skill で「collections/planning/」を直書き → Python 化されたヘルパー `collection_paths.find_active_collections()` 等を導入してそこに集約すると将来ディレクトリ変更が 1 か所で済む（**P2**） |
| A3-7 | `.claude/skills/postmortem/SKILL.md:25,46,114,154,168` / `metadata-audit/SKILL.md:8,32` / `live-clean/SKILL.md:8,21,32` / `alignment-check/SKILL.md:26,41` / `video-analyze/SKILL.md:42,87` / `thumbnail-compare/SKILL.md:73` | `collections/live/` の glob | 公開済みコレクションの走査 | A3-6 と同様、`CollectionPaths.glob_live()` 系を導入したい（**P2**） |
| A3-8 | `.claude/skills/channel-setup/SKILL.md:17,56,77,85` / `channel-import/SKILL.md:83-84` / `channel-new/SKILL.md` 多数 | `auth/token.json`, `auth/client_secrets.json` | OAuth トークンパス | `auth.oauth_handler` 内の Path 定数を `auth/` namespace で固定。**正当**（外出し不要） |
| A3-9 | `.claude/skills/lyria/SKILL.md:180,190` / `loop-video/SKILL.md:53` / `thumbnail/SKILL.md:62,70` | `10-assets/main.png` | reference image / 入力画像 | コレクション構造のドキュメント。**正当**（`CollectionPaths.assets_dir / 'main.png'` 相当） |
| A3-10 | `.claude/skills/channel-setup/references/verification.md:68-69,72-83` | `branding/banner.png` / `branding/icon.png` | ブランディング素材生成手順 | Convention。**正当** |
| A3-11 | `.claude/skills/channel-setup/references/verification.md:11` | `config/channel/*.json` | JSON 構文検証 Glob | **正当**（検証用途） |
| A3-12 | `.claude/skills/postmortem/SKILL.md:152-158` | `data/analytics_data_<YYYYMMDD>.json` / `data/benchmark_<YYYYMMDD>.json` etc. | データソースの参照ガイド | **正当**（仕様書） |
| A3-13 | `.claude/skills/analytics-report/SKILL.md:109` | `reports/{channel_slug}_analytics_YYYYMMDD.html` | HTML レポート保存先 | `channel_slug` は `config/channel/meta.json::channel.short` 由来と明記 → 外出し不要。**正当** |
| A3-14 | `.claude/skills/streaming/references/swap_video.sh:20` | `infra/terraform/streaming` | Terraform モジュールパス | CLI 引数で上書き可能。**正当** |
| A3-15 | `.claude/skills/lyria/SKILL.md:169,210` | `02-Individual-music/{NN}_{name}.wav` / `worktree_sync.sh` パス | コレクション内ファイル命名規約 | CollectionPaths 想定。**正当** |
| A3-16 | `.claude/skills/comments-reply/SKILL.md:24,64` | `config/channel/comments.json` / `comment_reply_history.json` | 設定・履歴ファイル | `config/channel/comments.json` 自体は `examples/channel_config.example/comments.json` と一致。**正当** |
| A3-17 | `.claude/skills/discover-competitors/SKILL.md:101,105-106` | `auth/token.json` / `research/lo-fi-discovery.{md,csv}` | OAuth トークン / 出力先 | **正当** |
| A3-18 | `.claude/skills/channel-setup/references/claude-md-template.md:101` | `collections/planning/` → `collections/live/` 自動移動 | CLAUDE.md テンプレ内の説明 | **正当** |
| A3-19 | `.claude/skills/video-analyze/SKILL.md:49,87` | `data/video_analysis/<slug>/<video_id>.json` / `reports/video_analysis/<slug>.md` | CLI 出力先 | CLI 内定義。**正当** |
| A3-20 | `.claude/skills/benchmark/SKILL.md:51-52` | `data/benchmark_YYYYMMDD.json` / `docs/benchmarks/*.md` | データ出力先 | CLI 内定義。**正当** |
| A3-21 | `.claude/skills/collection-ideate/SKILL.md:153,172-174,320,323,327` | `collections/planning/_plan-previews/<dir>/` | プレビュー画像保存先 | プレビュー保管場所の慣習。**正当**（`_` プレフィックスは設計意図） |
| A3-22 | `.claude/skills/wf-next/SKILL.md:50` | `git rev-parse --git-common-dir` で worktree 検知 | worktree 検出ロジック | **正当**（git 標準） |

**結論**: A-3 系は **ほぼ全件正当**（コレクション構造の慣習・コード内定数・ガイド文書）。**A3-6 + A3-7** のみ「Python 化された helper（`CollectionPaths.glob_planning()` / `.glob_live()`）への集約」が将来の保守性向上に効く（**P2**）。

---

## 5. A-4 — 既存 config キーと重複して直書きしている箇所

`examples/channel_config.example/*.json` のキーと突き合わせ、SKILL.md / references 側で「config に既にある or 置けるはずの値」を**ハードコード or 個数指定** している箇所を列挙。

| # | file:line | 直書き内容 | 対応する config キー | 対応案 |
|---|---|---|---|---|
| A4-1 | `.claude/skills/channel-setup/references/config-generation-rules.md:25-28` | 「`tags.base` は **10 個程度**」「`tags.themes` は **6-10 テーマ** 各 **3 語程度**」 | `examples/channel_config.example/content.json::tags.base / tags.themes`（個数は config に保持されない） | **要確認**: 個数を `content.json::tags.min_count` (現在 30) と整合させるべきか不明。examples 側に `min_count: 30` があるが SKILL.md は別の数字。**ドキュメント整合のため `content.json::tags.{base_count_target,themes_count_target}` 追加を提案** |
| A4-2 | `.claude/skills/channel-setup/references/config-generation-rules.md:36-37` | 「`perfect_for` は **4 項目**」「`hashtags` は **5 個** 程度」 | `content.json::descriptions.perfect_for[]` / `descriptions.hashtags[]`（個数は config に保持されない） | 数値は **ガイドライン** であり強制値ではない。**正当**だが、video-description/SKILL.md:89 の「ハッシュタグ 13個（base + theme固有）」と数字がブレている → ガイド統一が必要（**P2**） |
| A4-3 | `.claude/skills/video-description/SKILL.md:89,107` | 「ハッシュタグ **13個**（base + theme固有）」「ハッシュタグ 13個（base + theme）」 | `content.json::descriptions.hashtags`（既存値 3 個） | A4-2 の 5 個 vs 13 個矛盾。`config/channel/content.json` 側で base+theme の合計目標値を持つキー（`hashtags_total_target` 等）を **要確認** |
| A4-4 | `.claude/skills/channel-setup/references/config-template/youtube.json:3` | `"category_id": "10"` | `examples/channel_config.example/youtube.json::youtube.category_id` | テンプレート初期値として **正当**。ただし `channel-setup/references/upload-settings-template.json:3` / `schedule-template.json:11` で **二重定義**（同じ `"10"` が 3 ファイル）→ Single Source 違反。**P2** |
| A4-5 | `.claude/skills/channel-setup/references/config-template/youtube.json:4` / `upload-settings-template.json:4` / `schedule-template.json` (privacy 関連) | `"privacy_status": "public"` / `"private"` で揺れあり | `youtube.json::youtube.privacy_status` | `upload-settings-template.json:4` は `"public"`、`schedule-template.json:9` は `"private"`。**運用上の意図不明・矛盾の可能性**（要確認）。Single Source 候補は `examples/channel_config.example/youtube.json` |
| A4-6 | `.claude/skills/channel-setup/references/upload-settings-template.json:22-23` | `min_video_duration: 30 / max_video_duration: 7200` | `audio.json::audio.target_duration_{min,max}`（分単位、現在 60/75） | スケール違い（秒 vs 分）と用途違い（upload validator vs target）あり。**重複していないが概念は近い** → `audio.json` に統合 or 別 namespace の明示が必要（**P2**） |
| A4-7 | `.claude/skills/channel-setup/references/schedule-template.json:12-13,28-29` | `max_retries: 3 / retry_delay_seconds: 300 / delay_between_uploads: 5 / uploads_per_batch: 5 / upload_quota_per_day: 6 / concurrent_uploads: 1` | 既存 config 外（schedule_config.json は examples に含まれていない） | テンプレ自体が **未整備の config 設計**。`config/channel/upload.json` 等を別途定義する余地（**P3**、要確認） |
| A4-8 | `.claude/skills/channel-setup/references/upload-settings-template.json:9-14` | `thumbnail_search_patterns: ["main.png","*main*.png","thumbnail.png","*thumb*.png"]` | `examples/channel_config.example` には存在しない | **新規キー**として `youtube.json` か新 `upload.json` に追加候補（**P3**） |
| A4-9 | `.claude/skills/channel-setup/references/schedule-template.json:5` | `"timezone": "Asia/Tokyo"` | 既存 config 外 | チャンネルごとに差し替え可能性。**P3** |
| A4-10 | `.claude/skills/video-upload/SKILL.md:113` / `metadata-audit/SKILL.md:36,45` / `postmortem/SKILL.md:45` | 「YouTube タイトル長制限 **100文字**」「タイムスタンプ数 **< 3 もしくは > 12**」「video_id **11 文字**」 | YouTube API 仕様。`config/channel/*.json` に置く性質ではない | **正当**（プラットフォーム制約） |
| A4-11 | `.claude/skills/video-description/SKILL.md:66` | 「テーマが辞書にない場合は `config/channel/content.json` の `descriptions.perfect_for`（デフォルト）を使用」 | 既に `content.json::descriptions.perfect_for` を参照 | **正当**（既存 config キーへの参照）。逆引きで `descriptions.perfect_for` 直書きが SKILL.md 内に他にないか追加確認したが**重複なし** |
| A4-12 | `.claude/skills/channel-setup/references/claude-md-template.md:13` | `config/channel/{meta,content,youtube,analytics,playlists,workflow,audio}.json` を列挙（7 ファイル） | `examples/channel_config.example/*.json` は **8 ファイル**（comments.json を含む） | テンプレが古い可能性。**comments.json が抜けている**（**P2**、文書更新で対応） |
| A4-13 | `.claude/skills/channel-new/SKILL.md:100` | 「`config/channel/{meta,content,youtube,analytics,playlists,workflow,audio}.json` 計 **7 ファイル**」 | 同上 — comments.json が抜けている | A4-12 と同じ（**P2**） |
| A4-14 | `.claude/skills/lyria/SKILL.md:60,85` / `lyria/config.default.yaml:17` / `loop-video/SKILL.md:107,116` 等 | モデル名 | A-2 と重複 | A-2 参照 |
| A4-15 | `.claude/skills/channel-setup/references/localizations-template.json:5-12` | `ja.title_template` / `en.title_template` の `{style} {theme} ... [{duration_display}]` | `examples/channel_config.example/content.json::title.template` | テンプレ重複（ja は別文言、en は同一）。`content.json::title.template` を localization の base に再利用すべき（**P2**、要確認） |
| A4-16 | `.claude/skills/playlist/SKILL.md:67` | `"all"` プレイリストは末尾追加 / それ以外は先頭追加 | `playlists.json` には `auto_add_activities` / `auto_add_themes` キーがあるが `auto_add` の挙動定義は SKILL.md 内のみ | playlist.json スキーマに `insertion_order: "head"\|"tail"` を追加するとロジックが config 駆動になる（**P3**） |

**結論**: A-4 系の主要対応候補は **A4-2/A4-3（ハッシュタグ個数のドキュメント整合）**、**A4-4（`category_id="10"` の 3 ファイル重複）**、**A4-12/A4-13（comments.json が config ファイル一覧から漏れている）**、**A4-15（localizations title_template と content.json::title.template の重複）**。

---

## 6. A-5 — 生 `json.load` / `yaml.safe_load` で channel config を読んでいる references スクリプト

| # | file:line | コード | 判定 |
|---|---|---|---|
| A5-1 | `.claude/skills/channel-setup/references/verification.md:9-15` | `import json, glob; for p in sorted(glob.glob('config/channel/*.json')): json.load(open(p)); print(f'OK: {p}')` | **false positive**: JSON 構文検証用途であり、設定値の消費ではない。`load_config()` で同じことをすると逆に失敗時の行特定が困難になる → **正当** |

**結論**: `.claude/skills/**` 配下では **生 load による config 消費はゼロ**。`load_config()` / `load_skill_config()` 経路が完全に統一されている（healthy state）。

参考: `Grep "load_config|load_skill_config"` で確認された使用件数 = **34 件**（35 skill 中 24 skill が `load_config()` 前提を SKILL.md 冒頭に明記）。残り 11 skill（masterup / live-clean / videoup / comments-reply / playlist / discover-competitors / channel-import / channel-research / channel-setup / channel-direction / channel-new / thumbnail-compare / viewer-voice / streaming / metadata-audit）は config 不要 or オフライン操作中心。

---

## 7. 主要な発見のサマリー（top 5 影響度）

| 順位 | 検出 | 影響度 | 推奨アクション |
|---|---|---|---|
| **1** | A4-2/A4-3 — `descriptions.perfect_for` 個数（4）と `hashtags` 個数（5 vs 13）がドキュメント間で矛盾 | **高**（誤実装の温床） | `channel-setup/references/config-generation-rules.md` と `video-description/SKILL.md` でガイドラインを統一。`content.json` に `descriptions.perfect_for_target_count` 等の Single Source キーを置く |
| **2** | A1-1/A1-2 — 「30 分」鮮度しきい値が analytics-collect / analytics-analyze で完全に直書き重複 | **中**（運用変更時に 2 箇所同時修正必要） | `config/skills/analytics.yaml::freshness_minutes` または `config/channel/analytics.json::cache.freshness_minutes` に統合 |
| **3** | A1-9/A1-11 — postmortem の CTR 判定閾値（0.5/0.7/0.9/±10%）が SKILL.md 内に固定 | **中**（チャンネルごとに調整したい運用シーンが想定される） | `config/skills/postmortem.yaml::thresholds` を新設 |
| **4** | A4-12/A4-13 — `comments.json` が「config/channel/*.json 計 7 ファイル」から漏れている | **中**（新規チャンネルで comments-reply skill を使う際に config が欠落する） | `channel-setup/references/claude-md-template.md:13` / `channel-new/SKILL.md:100` の列挙を 8 ファイルに更新 |
| **5** | A4-4 / A4-5 — `category_id="10"` / `privacy_status` が 3 テンプレファイルに重複（しかも privacy で値が揺れている） | **中**（設計上の Single Source 違反） | `channel-setup/references/config-template/youtube.json` を Single Source とし、`upload-settings-template.json` / `schedule-template.json` から削除 or 参照記述に置換 |

**追加で目立つもの（P2）**:
- A2-8: masterup SKILL.md 本文の Suno CDN URL 4 箇所を skill-config 値の引用に統一
- A2-10: streaming の 1Password ボルトパス（`op://Personal/...`）を `config/skills/streaming.yaml` に外出し
- A3-6/A3-7: `collections/planning/` / `collections/live/` の Python 化されたヘルパー集約

---

## 8. カバレッジ

### 走査した skill 一覧（35 件、全件）

```
alignment-check / analytics-analyze / analytics-collect / analytics-report /
audience-persona / benchmark / channel-direction / channel-import / channel-new /
channel-research / channel-setup / channel-status / collection-ideate / comments-reply /
discover-competitors / live-clean / loop-video / lyria / masterup / metadata-audit /
playlist / postmortem / streaming / suno / thumbnail / thumbnail-compare /
video-analyze / video-description / video-upload / videoup / viewer-voice /
viewing-scene / wf-new / wf-next / wf-status
```

### 走査ファイル種別

- `SKILL.md` × 35
- `config.default.yaml` × 9（benchmark / collection-ideate / loop-video / lyria / masterup / suno / thumbnail / video-analyze / video-description）
- `references/**/*.{md,sh,py,json,yaml,tf}` × 37
- 合計: **81 ファイル**

### Grep パターン一覧（実行済み）

| パターン | 用途 |
|---|---|
| `\b(max\|min\|timeout\|retry\|limit\|threshold)[_-]?\w*\s*[:=]\s*\d+` | A-1 数値検出 |
| `\b(max\|min\|timeout\|retry\|limit\|threshold\|count\|delay\|interval\|days\|hours\|seconds\|sec\|ms\|page_size\|batch)\b\s*[:=]\s*\d+` | A-1 拡張 |
| `\b\d+\s*(秒\|分\|時間\|日\|days\|hours\|minutes\|seconds\|hr\|min)\b` | A-1 自然言語の数値 |
| `\b(gemini\|gpt\|lyria\|veo\|claude\|suno\|grok\|sonnet\|opus\|haiku)[-_.][\w.-]+` | A-2 モデル名 |
| `https?://[^\s\)\]]+` | A-2 URL |
| `collections/(live\|planning\|deprecated)/` | A-3 パス |
| `config/channel/` | A-3 / A-4 突合 |
| `10-assets\|20-documentation\|01-master\|02-Individual-music\|11-design` | A-3 コレクション構造 |
| `json\.load\|yaml\.safe_load\|yaml\.load` | A-5 |
| `load_config\|load_skill_config` | A-5 反転確認 |
| `\b\d+\s*文字\|\b\d+(\.\d+)?\s*MB\b\|tag.*count\|hashtag.*count` | A-1/A-4 補完 |
| `\bauth/\|\bbranding/\|\bdocs/channel/\|\bdocs/benchmarks/...` | A-3 補完 |

### 比較対象（A-4 一次情報）

`examples/channel_config.example/` 配下 8 ファイル全件を Read で熟読:
- `meta.json`（19 行）
- `content.json`（43 行）
- `youtube.json`（13 行）
- `analytics.json`（11 行）
- `audio.json`（7 行）
- `playlists.json`（6 行）
- `workflow.json`（2 行、空）
- `comments.json`（37 行）

---

## 9. 注意点・リスク（誤検出・偽陽性の可能性）

| # | 内容 |
|---|---|
| R-1 | **A-3 のパス直書き判定はやや厳しめ**: 「bash スクリプト内のファイル名」「ガイド文書内の説明的パス」は本来正当だが、機械的に拾うとノイズ化する。今回は §4 で「正当」マークで明示的に切り分けた |
| R-2 | **A-1 の閾値「正当 vs 外出し」の境界が主観的**: streaming の `RuntimeMaxSec=11h` は Terraform 側の Single Source、Lyria 184 秒は API 物理制約 → どちらも config 化する意味は薄い。判定は §2 のコメント欄に都度記載 |
| R-3 | **A-4 の「ドキュメント記述 vs ハードコード」の区別**: video-description SKILL.md の「ハッシュタグ 13個」は **ガイドライン** でありコード制約ではない可能性がある。実装側 (`metadata_generator.py`) の挙動を確認していないため **要確認** マークで報告 |
| R-4 | **CLI 既定値の引用は「重複」と数えない方針**: discover-competitors SKILL.md の「`--min-subscribers 10000`」等は CLI 側 Single Source の引用なので A-1 から除外 |
| R-5 | **`channel-setup/references/config-template/*.json` は意図的な雛形**: ここに値があるのは Single Source（テンプレ）として正当。`upload-settings-template.json` / `schedule-template.json` との重複 (A4-4/A4-5) のみ問題 |
| R-6 | **A-2 のモデル名は将来更新が頻発**: skill-config 化済みでも SKILL.md 本文に書かれたモデル名（例: `gemini-3.1-flash-image-preview`）は default 値変更時に同期が必要。今回は「skill-config が存在すれば OK」と判定したが、長期的には SKILL.md 本文の「{model}」プレースホルダ化が望ましい |

---

## 10. 調査できなかった項目とその理由

| 項目 | 理由 |
|---|---|
| **`config/channel/comments.json` の現実装による参照状況** | examples 配下のサンプルは確認したが、実 CLI (`yt-comments-reply`) のソース読み込みは Part A 対象外（依頼スコープ: `.claude/skills/**`）。**A-5 の反転確認は SKILL.md レベルのみ** |
| **`channel-setup/references/schedule-template.json` の歴史的経緯** | `examples/channel_config.example/` に対応する `schedule.json` が無く、テンプレートだけが存在する状態。「廃止予定」「未使用」の可能性を git log では追わず（保守的に「要確認」と報告） |
| **A4-3 のハッシュタグ 13 個ロジックの実装根拠** | `metadata_generator.py` を読まずに SKILL.md 記述のみで判定（時間制約）。テキストでは「base + theme固有」とあるため計算式は推定可能だが、ガイドラインなのか強制値なのかは要確認 |
| **streaming の Terraform 内ハードコード** | `infra/terraform/streaming/` 配下は依頼スコープ `.claude/skills/**` 外。`streaming/SKILL.md` で参照されている `RuntimeMaxSec=11h` 等は terraform 側にあるため未走査 |
| **既存 skill-config 9 件の中身が `config/channel/*.json` の同名キーと意図せず競合していないか** | `audio.target_duration_min` は `audio.json` と `lyria/config.default.yaml::duration_padding_min` で意味が分離されておりセーフだが、他組合せは網羅未確認（80% 基準で見送り） |

---

## 11. 推奨/結論（外出し優先度 P1/P2/P3 振り分け）

### P1（必須対応・効果大）

| ID | 内容 | 対応工数 |
|---|---|---|
| **P1-a** | **ハッシュタグ個数の Single Source 化** — `config-generation-rules.md`（5 個）と `video-description/SKILL.md`（13 個）のガイドラインを整合。`content.json::descriptions.hashtags_target_count` or `hashtags_base + hashtags_per_theme` の 2 値を追加 | 小 |
| **P1-b** | **comments.json を config ファイル一覧に追加** — `channel-setup/references/claude-md-template.md:13` / `channel-new/SKILL.md:100` を 7 → 8 ファイルへ更新 | 極小 |
| **P1-c** | **`category_id="10"` の Single Source 化** — `channel-setup/references/{config-template/youtube.json, upload-settings-template.json, schedule-template.json}` のうち config-template/youtube.json のみを Single Source として残し、他から削除（または「youtube.json を参照」コメント化）| 小 |
| **P1-d** | **`privacy_status` の矛盾解消** — `upload-settings-template.json:4` `"public"` と `schedule-template.json:9` `"private"` の食い違い。意図を確認し統一 | 小 |

### P2（重要・効果中）

| ID | 内容 |
|---|---|
| **P2-a** | analytics-collect / analytics-analyze の **30 分鮮度** を `config/skills/analytics.yaml` に集約 |
| **P2-b** | postmortem の **CTR 判定閾値**（0.5/0.7/0.9/±10%）を `config/skills/postmortem.yaml::thresholds` に集約 |
| **P2-c** | streaming の **notify timeout**（5 秒 / 10 秒）と **1Password ボルトパス**を `config/skills/streaming.yaml` に外出し |
| **P2-d** | masterup SKILL.md 本文の Suno CDN URL 4 箇所を skill-config 値の引用に統一（実コードが skill-config を読んでいるなら SKILL.md の文字列は「`{cdn_url_template}` 参照」表現に変更） |
| **P2-e** | `collections/{planning,live}/` の Python helper（`CollectionPaths.glob_planning()` / `.glob_live()`）導入と 14 SKILL.md からの参照置換 |
| **P2-f** | `localizations-template.json::*.title_template` と `content.json::title.template` の整合化（localizations は ja のみ独自パターン、en は重複） |
| **P2-g** | videoup の **ffmpeg 解像度・ビットレート・CRF** を `config/skills/videoup.yaml` に新設 |

### P3（あれば良い・効果小）

| ID | 内容 |
|---|---|
| **P3-a** | analytics-report HTML の KPI カード枚数（4）/ max-width（1200px） を skill-config 化 |
| **P3-b** | playlist の `"all"` プレイリスト挿入順（head/tail）を `playlists.json` スキーマに追加 |
| **P3-c** | `schedule-template.json` の存在意義の整理（examples 側に対応キーが無いため、`config/channel/upload.json` 新設 or テンプレ削除を検討） |
| **P3-d** | `upload-settings-template.json::thumbnail_search_patterns` を `config/channel/youtube.json` に統合 |
| **P3-e** | A-2 系の「SKILL.md 本文に書かれたモデル名」を将来的に skill-config 値の `{{model}}` プレースホルダで埋め込む形式に統一（テンプレ更新時の同期コスト削減） |

---

## 12. 補足: A-3 で見送りとした「ほぼ全件正当」の根拠

`collection_paths.CollectionPaths` クラス（`src/youtube_automation/utils/collection_paths.py`）が **既に標準コレクションディレクトリ構造を一次情報として持つ**ため、SKILL.md 内の「`01-master/master.mp3`」「`10-assets/main.png`」「`20-documentation/descriptions.md`」等の直書きは **`CollectionPaths` 仕様の文書化**として正当と判定した。

ただし **A3-6 + A3-7（`collections/planning/` / `collections/live/` の Glob 14 箇所）** は Python 化された helper にまとめると将来のリネーム耐性が上がるため **P2** として残した（コレクションのトップレベルディレクトリ名そのものを変える事案は稀だが、`_plan-previews/` の追加など下位構造変更は実例あり）。
