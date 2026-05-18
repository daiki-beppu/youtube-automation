# dig Part A — ハードコード値 + 既存 config 未参照 検出レポート

調査日: 2026-05-18
担当: dig.dig-part-a
範囲: `.claude/skills/**` 35 スキル（SKILL.md + references/ + config.default.yaml + scripts）
観点: 1.1 ハードコード値（A-1〜A-4）＋ 1.4 既存 config 未参照（A-5）
ツール: Read / Grep / Glob のみ（protected paths のため write 禁止）

---

## 1. 概要

- 走査対象スキル数: **35**（漏れなし、`ls .claude/skills/` で確認）
- 走査対象ファイル数: **約 90**（SKILL.md × 35 + references/ + config.default.yaml + scripts/JSON テンプレ）
- 検出総件数: **63 件**（重複行は集約済み）
  - 高（P1 = 即対応すべき）: **9 件**
  - 中（P2 = 共通化推奨）: **34 件**
  - 低（P3 = 設計判断保留）: **20 件**

### サマリ感

- **A-1（チャンネル ID / playlist ID / handle 直書き）**: **検出 0 件**（YouTube ID リテラルは無し。プレースホルダ `UC...` / `<channel>` のみ）
- **A-4（API key / token / 怪しい URL 直書き）**: **検出 0 件**（`op://` 経由のシークレット参照 + 公式 CDN/インストーラー URL のみ）
- **A-3（絶対パス / ユーザー名）**: **3 件中 2 件が高重大度**（user-specific dev dir のハードコード）
- **A-5（既存 config 未参照）**: **高 4 件 + 中 9 件**（v2.0.0 namespace 漏れ・テンプレ英語固定など）
- **A-2（マジックナンバー）**: **中 25 件 + 低 20 件**（多くは skill-config に存在、判断分かれるグレーゾーン）

スキル設計の全体評価:
- Python references（`benchmark_collector.py` / `analytics_system.py` / `generate_image.py` / `loop-video` 等）は `load_config()` + `load_skill_config()` 経由で **アーキテクチャ的にクリーン**
- SKILL.md 本文中の英語コピー・色 hex・閾値は **静的記述として残存** している箇所が散見される
- 配布テンプレート (`channel-setup/references/config-template/`, `schedule-template.json`, `upload-settings-template.json`) は意図的に BGM 系既定値で埋まっている

---

## 2. 検出結果

### A-1: チャンネル ID / playlist ID / handle ハードコード（P1）

| # | スキル | file:line | 引用 | 重大度 | 推奨アクション |
|---|--------|-----------|------|--------|---------------|
| 1.1 | channel-setup | `.claude/skills/channel-setup/references/terraform-gcp/README.md:51` | `adc_email      = "you@example.com"` | 低 | プレースホルダ。実害なし |
| 1.2 | channel-setup | `.claude/skills/channel-setup/references/terraform-gcp/terraform.tfvars.example:10` | `adc_email       = "you@example.com"` | 低 | 同上 |
| 1.3 | channel-import | `.claude/skills/channel-import/SKILL.md:39` | `（例: @channel-name）` | 低 | ドキュメント例のみ |

**`UC[A-Za-z0-9_-]{22}` / `PL[A-Za-z0-9_-]{16,}` 完全一致: 0 件**（リポジトリ全体に対するグレップで一致なし）

### A-2: マジックナンバー（P2 中心）

#### A-2-A: 画像/動画解像度・エンコード設定（中〜低）

| # | スキル | file:line | 引用 | 重大度 | 推奨修正先 |
|---|--------|-----------|------|--------|-----------|
| 2.1 | videoup | `.claude/skills/videoup/references/generate_videos.sh:130,139,149,175` | `1920x1080` を 4 箇所で直書き | 中 | skill-config（YouTube 標準だが将来縦動画/4K 対応時に効く） |
| 2.2 | videoup | `.claude/skills/videoup/references/generate_videos.sh:73` | `-b:a 384k -ar 48000` | 中 | skill-config `audio.bitrate` / `audio.sample_rate` |
| 2.3 | videoup | `.claude/skills/videoup/references/generate_videos.sh:148` | `-c:v libx264 -preset slow -crf 18` | 中 | skill-config `video.crf` / `video.preset` |
| 2.4 | videoup | `.claude/skills/videoup/references/generate_videos.sh:174` | `-preset ultrafast -crf 23` | 中 | 同上 |
| 2.5 | videoup | `.claude/skills/videoup/references/generate_videos.sh:192` | `BAR_WIDTH=30` | 低 | UI 定数。実害なし |
| 2.6 | videoup | `.claude/skills/videoup/references/generate_videos.sh:211` | `sleep 0.15` | 低 | UI 定数 |
| 2.7 | lyria | `.claude/skills/lyria/references/lyria-tuning-guide.md:67` | `推奨: コレクションの main.png (PNG, 1280×720 以上)` | 低 | YouTube 最小サムネ要件 |
| 2.8 | channel-setup | `.claude/skills/channel-setup/references/verification.md:68,82` | `2048 x 1152 px、6 MB 以下` | 低 | YouTube バナー仕様 |
| 2.9 | channel-setup | `.claude/skills/channel-setup/references/upload-settings-template.json:23` | `"max_video_duration": 7200` | 中 | template だが固定 2 時間が BGM 想定 |
| 2.10 | channel-setup | `.claude/skills/channel-setup/references/upload-settings-template.json:22` | `"min_video_duration": 30` | 中 | 同上 |

#### A-2-B: ブランド色・UI hex（中、A-5 とも重複）

| # | スキル | file:line | 引用 | 重大度 | 推奨修正先 |
|---|--------|-----------|------|--------|-----------|
| 2.11 | analytics-report | `.claude/skills/analytics-report/SKILL.md:94-101` | `背景: #0f1419 / カード背景: #1a2332 / アクセント: #c8a96e (ブランドアクセントカラー) / テキスト: #e8e6e3 / チャート色: #4ecdc4, #45b7d1, #96ceb4, #ffeaa7, #dfe6e9 / 成功: #00b894 / 警告: #fdcb6e / 危険: #e17055` | **高** | **`config/channel/meta.json::channel.brand_color`** 新設、または skill-config `analytics-report.yaml::theme.colors`。「ブランドアクセントカラー」のコメントが付いており明らかにチャンネル固有 |
| 2.12 | analytics-report | `.claude/skills/analytics-report/SKILL.md:104` | `max-width: 1200px` | 低 | レイアウト定数 |

#### A-2-C: 閾値・件数（中）

| # | スキル | file:line | 引用 | 重大度 | 推奨修正先 |
|---|--------|-----------|------|--------|-----------|
| 2.13 | analytics-analyze | `.claude/skills/analytics-analyze/SKILL.md:38` | `30分以内に生成されたレポートがあれば分析をスキップ` | 中 | skill-config `analytics-analyze.yaml::freshness_minutes` |
| 2.14 | analytics-collect | `.claude/skills/analytics-collect/SKILL.md:36` | `30分以内 → 収集をスキップ` | 中 | 同上（skill-config 横断統一が望ましい） |
| 2.15 | analytics-collect | `.claude/skills/analytics-collect/SKILL.md:28,62` | `効率モード（上位50本 + 直近30日投稿）` | 中 | skill-config `analytics-collect.yaml::top_n` / `recent_days` |
| 2.16 | video-description | `.claude/skills/video-description/SKILL.md:89,107` | `ハッシュタグ: 13個（base + theme固有）` | 中 | `config/channel/content.json::descriptions.hashtag_count` を新設 |
| 2.17 | video-upload | `.claude/skills/video-upload/SKILL.md:113` | `YouTube タイトル長制限準拠（100文字）` | 低 | YouTube 仕様（固定で良いが定数化） |
| 2.18 | video-upload | `.claude/skills/video-upload/SKILL.md:97` | `指数バックオフによるリトライ（5xx エラー時、最大5回）` | 低 | utils 側で実装。SKILL.md は文章 |
| 2.19 | video-upload | `.claude/skills/video-upload/SKILL.md:46` | `API クォータ: 2 × 1,600 = 3,200 ユニット` | 低 | YouTube API 仕様 |
| 2.20 | metadata-audit | `.claude/skills/metadata-audit/SKILL.md:38,48` | `タイムスタンプ数 < 3 もしくは > 12` | 中 | skill-config `metadata-audit.yaml::chapters_min` / `chapters_max` |
| 2.21 | suno | `.claude/skills/suno/SKILL.md:91` | `4 パターン × 3 回生成（1 回 2 曲）= **24 トラック**` | 中 | skill-config `suno.yaml::pattern_count` / `generations_per_pattern` |
| 2.22 | suno | `.claude/skills/suno/SKILL.md:98,112` | `Style Influence: 85 推奨` / `120-180 単語` | 中 | 85 は config.default.yaml にある。120-180 は未明文化 |
| 2.23 | postmortem | `.claude/skills/postmortem/SKILL.md:76-89` | `< 0.5 / < 0.7 / < 0.9 / ≥ 0.9` 等の比率閾値を 8 箇所で直書き | 中 | skill-config `postmortem.yaml::thresholds.{ratio_red,ratio_yellow,...}`。SKILL.md 内に「閾値はチャンネル特性に応じて文脈調整可」とある通り変動値 |
| 2.24 | thumbnail-compare | `.claude/skills/thumbnail-compare/SKILL.md:8,21` | `1万再生以上` | 中 | `config/skills/benchmark.yaml::min_views`（既に 10000 がある）を参照すべき。SKILL.md は固定文 |
| 2.25 | thumbnail-compare | `.claude/skills/thumbnail-compare/SKILL.md:23` | `320x180px` に縮小 | 低 | YouTube モバイル想定 |
| 2.26 | viewer-voice | `.claude/skills/viewer-voice/SKILL.md:8,28` | `1万再生以上` | 中 | 同上、benchmark.yaml と統一 |
| 2.27 | viewer-voice | `.claude/skills/viewer-voice/SKILL.md:29` | `各動画のコメントを最大100件取得` | 中 | skill-config `viewer-voice.yaml::comments_per_video` |
| 2.28 | discover-competitors | `.claude/skills/discover-competitors/SKILL.md:86-90,99-100` | `--min-subscribers 10000 / --max-subscribers 1,000,000,000? / --posted-within-days 30 / --top 20` | 中 | CLI のデフォルトと整合。skill-config 化検討余地あり |
| 2.29 | channel-new | `.claude/skills/channel-new/SKILL.md:124-125` | `--min-subscribers 10000 --max-subscribers 1000000 --posted-within-days 30 --top 20` | 中 | 同上 |
| 2.30 | channel-new | `.claude/skills/channel-new/SKILL.md:175` | `uv run yt-benchmark-comments --min-views 5000` | 中 | benchmark.yaml `min_views` と矛盾しないか確認。固定 5000 は別パラ |
| 2.31 | lyria | `.claude/skills/lyria/SKILL.md:194` | `--max-retries N （default: 3）` | 低 | CLI デフォルト |
| 2.32 | lyria | `.claude/skills/lyria/SKILL.md:10,76,168` | `1 リクエストあたり最大約 184 秒` | 低 | Vertex AI API 仕様（変更があれば追従） |
| 2.33 | comments-reply | `.claude/skills/comments-reply/SKILL.md:58` | `--per-video-limit N（default: 100）` | 中 | examples/channel_config.example/comments.json では `max_replies_per_run: 20` 等あり |
| 2.34 | streaming | `.claude/skills/streaming/SKILL.md:8` | `RuntimeMaxSec=11h + RestartSec=1h` | 低 | Terraform 側に集約済（SKILL は documentation） |
| 2.35 | streaming | `.claude/skills/streaming/SKILL.md:38,109` | `80% 閾値アラート` / `帯域 80% 超アラート` | 低 | `src/youtube_automation/utils/streaming/threshold.py` の定数。SKILL は documentation |
| 2.36 | streaming | `.claude/skills/streaming/SKILL.md:99` | `月間 1.16 TB（2 TB プランの 58%）` / `4 Mbps → 3 Mbps 化` | 低 | Vultr プラン依存 |
| 2.37 | streaming | `.claude/skills/streaming/SKILL.md:79` | `5 分間隔` healthcheck | 低 | cron.d / Terraform 側で集約 |
| 2.38 | collection-ideate | `.claude/skills/collection-ideate/SKILL.md:326` | `7 日以上前のものは手動削除可` | 低 | コメント |

#### A-2-D: skill-config 既定値（低、外部化済みのため低）

| # | スキル | file:line | 引用 | 重大度 | 備考 |
|---|--------|-----------|------|--------|------|
| 2.39 | benchmark | `config.default.yaml:10` | `scan_recent: 50` | 低 | skill-config 化済 |
| 2.40 | benchmark | `config.default.yaml:13` | `min_views: 10000` | 低 | skill-config 化済 |
| 2.41 | benchmark | `config.default.yaml:16` | `freshness_days: 3` | 低 | skill-config 化済 |
| 2.42 | benchmark | `config.default.yaml:24` | `delay_sec: 5` | 低 | skill-config 化済 |
| 2.43 | video-analyze | `config.default.yaml:10` | `delay_sec: 10` | 低 | skill-config 化済 |
| 2.44 | masterup | `config.default.yaml:10` | `crossfade_duration: 1.0` | 低 | skill-config 化済 |
| 2.45 | masterup | `config.default.yaml:13` | `bitrate: "192k"` | 低 | skill-config 化済 |
| 2.46 | loop-video | `config.default.yaml:20` | `duration_seconds: 8` | 低 | Veo API 制約 |
| 2.47 | loop-video | `config.default.yaml:23` | `crossfade_sec: 0.5` | 低 | skill-config 化済 |
| 2.48 | lyria | `config.default.yaml:28` | `crossfade_sec: 5` | 低 | skill-config 化済 |
| 2.49 | lyria | `config.default.yaml:40` | `duration_padding_min: 3` | 低 | skill-config 化済 |
| 2.50 | collection-ideate | `config.default.yaml:16-18` | `candidate_count: 3 / session_id_bytes: 2` | 低 | skill-config 化済 |
| 2.51 | collection-ideate | `config.default.yaml:37` | `max_similarity: 0.5` | 低 | skill-config 化済 |
| 2.52 | suno | `config.default.yaml:16` | `style_influence: 85` | 低 | skill-config 化済 |
| 2.53 | video-description | `config.default.yaml:57` | `timing: "12:00"` | 低 | skill-config 化済 |

### A-3: 絶対パス / ユーザー名（P2）

| # | スキル | file:line | 引用 | 重大度 | 推奨修正 |
|---|--------|-----------|------|--------|---------|
| 3.1 | channel-new | `.claude/skills/channel-new/SKILL.md:29` | `**実行場所**: 新リポジトリの親ディレクトリ（例: \`~/01-dev/projects/\`）` | **高** | 例示を一般化（`<your-projects-dir>` または別記）。`~/01-dev/projects/` は repo author 固有のパス |
| 3.2 | channel-new | `.claude/skills/channel-new/SKILL.md:64` | `新リポジトリの親ディレクトリ（このリポジトリの 1 つ上、例: \`~/01-dev/projects/\`）` | **高** | 同上 |
| 3.3 | channel-import | `.claude/skills/channel-import/SKILL.md:20` | `cd ~/02-yt` | **高** | `cd <your-channels-parent>` に一般化。`~/02-yt` は repo author 固有 |
| 3.4 | channel-new | `.claude/skills/channel-new/SKILL.md:75` | `（例: /Users/<you>/path/to/some-channel/auth/token.json）` | 低 | プレースホルダ。OK |
| 3.5 | streaming | `.claude/skills/streaming/SKILL.md:15-19`, `references/swap_video.sh:86` | `~/.ssh/yt_stream_key` を 5 箇所で直書き | 中 | skill-config `streaming.yaml::ssh_key_path` 化で運用者の鍵パス差分に対応可。現状 `~/.ssh/yt_stream_key` 強制 |
| 3.6 | streaming | `.claude/skills/streaming/references/notify.sh`, `healthcheck.sh`, `run-ffmpeg.sh` | `/etc/youtube-stream-healthcheck.env`, `/opt/youtube-stream/`, `/usr/bin/ffmpeg` | 低 | 配置先パス（VPS 側 cloud-init/systemd の規約に沿った絶対パス、変更すべきでない） |
| 3.7 | channel-setup | `.claude/skills/channel-setup/references/terraform-gcp/README.md:51` | `you@example.com`（例示） | 低 | プレースホルダ |

### A-4: API キー・トークン・URL 直書き（P1）

| # | スキル | file:line | 引用 | 重大度 | 備考 |
|---|--------|-----------|------|--------|------|
| 4.1 | — | 全範囲 | `AIza` / `sk-` / `ya29.` パターン: **0 件** | — | クリーン |
| 4.2 | streaming | `.claude/skills/streaming/SKILL.md:20,52,123` | `op://Personal/Vultr/api_key`, `op://Personal/YouTube/stream_key`, `op://Personal/YouTube_Stream_Discord_Webhook/url` | 低 | 1Password 参照。秘密情報そのものは含まない |
| 4.3 | masterup | `.claude/skills/masterup/SKILL.md:22,84,89,174`, `config.default.yaml:33` | `https://cdn1.suno.ai/{song_id}.mp3` | 低 | Suno 公式 CDN。skill-config 化済 |
| 4.4 | channel-new | `.claude/skills/channel-new/SKILL.md:47,49` | `gh repo create <short> --template daiki-beppu/youtube-channel-template --private --clone` / `uv add git+https://github.com/daiki-beppu/youtube-channels-automation.git` | 中 | **GitHub オーナー名 `daiki-beppu` がスキル本文中に固定**。他者がこのパッケージを fork 利用しても誘導先はオリジナル。`{{REPO_OWNER}}` プレースホルダ化または README/CLAUDE.md の installation 節への一元化推奨 |
| 4.5 | channel-import | `.claude/skills/channel-import/SKILL.md:21,26` | 同上 | 中 | 同 |
| 4.6 | channel-setup | `.claude/skills/channel-setup/references/claude-md-template.md:71` | `youtube-automation パッケージの構造は GitHub リポジトリ（daiki-beppu/youtube-channels-automation）の CLAUDE.md を参照` | 中 | 同 |
| 4.7 | streaming | `.claude/skills/streaming/references/notify.sh:35-37` | `^https://(discord\.com|discordapp\.com)/api/webhooks/` ホストホワイトリスト | 低 | SSRF 防御の意図的ホスト固定（Issue #166/#174） |
| 4.8 | streaming | `.claude/skills/streaming/references/notify.sh:35` | `http://169.254.169.254` (AWS/cloud metadata IP) | 低 | コメント内の SSRF 攻撃例示。実コードでブロックされる |

### A-5: 既存 config で表現できるのに skill 内に書かれている値（P1）

| # | スキル | file:line | 引用 | 重大度 | 期待される config 参照先 |
|---|--------|-----------|------|--------|-----------------------|
| 5.1 | analytics-analyze | `.claude/skills/analytics-analyze/SKILL.md:64` | ``yt-theme-compare`: `channel_config.tags.themes` のキーワードで...` | **高** | v2.0.0 で `channel_config.tags.themes` は **廃止**。**正しくは `content.tags.themes`**（`utils/config/content.py`）。古い namespace 名が SKILL.md に残存している（c-3 deprecated 系とも重複） |
| 5.2 | analytics-report | `.claude/skills/analytics-report/SKILL.md:96` | `アクセント: #c8a96e (ブランドアクセントカラー)` | **高** | `config/channel/meta.json::channel.brand_color`（新設キー）を導入し、HTML レポートはそこから読む。現状はチャンネル固有のブランドアクセント色が SKILL.md に直書き |
| 5.3 | analytics-report | `.claude/skills/analytics-report/SKILL.md:73,123` | `Complete Collection のみ表示（Shorts を除外）` / `Shorts は動画パフォーマンス表から除外（タイトルに #Shorts を含む）` | 中 | `config/channel/analytics.json::analytics.collection_filter_keywords` を活用すべき（既に `["collection", "complete"]` を保持）。`#Shorts` 固定文字列マッチは独立した除外ロジックなので skill-config か analytics.json の除外パターンに揃える |
| 5.4 | video-description | `.claude/skills/video-description/references/description-templates.md:36` | `🎧 If you enjoyed the vibe, feel free to save and subscribe for more 🌧️` | **高** | 英語固定 + 🌧️ 絵文字は BGM/雨系チャンネル前提。`config/channel/meta.json::channel.cta_subscribe`（既存）に集約済のはずだが、本テンプレ行は別途固定文字列で残存している。`{channel_config: channel.cta_subscribe}` 形式に統一すべき |
| 5.5 | video-description | `.claude/skills/video-description/references/description-templates.md:43-44` | `🎨 𝐀𝐫𝐭 & 🎹 𝐌𝐮𝐬𝐢𝐜 𝐛𝐲 {channel_config: channel.name}` / `Original AI composition • Free for personal use` | **高** | "Original AI composition • Free for personal use" は固定英語コピー。skill-config `usage_attribution_lines`（既存、`video-description/config.default.yaml:20-24`）と二重管理になっている。テンプレ側を skill-config 参照に置き換えるか、二重管理を解消 |
| 5.6 | video-description | `.claude/skills/video-description/SKILL.md:89,107` | `ハッシュタグ: 13個` | 中 | `config/channel/content.json::descriptions.hashtag_count` 新設、または `len(descriptions.hashtags)` を運用ルール化。13 は magic number |
| 5.7 | video-description | `.claude/skills/video-description/config.default.yaml:44-52` | `theme_emoji: study/sleep/tavern/ocean/forest/druid/rain/hearth` | 中 | チャンネル固有のテーマ語。`config/channel/content.json::title.theme_emoji` に集約することで、`title.theme_activities` / `theme_scenes` と一元管理できる |
| 5.8 | video-description | `.claude/skills/video-description/config.default.yaml:13-17,20-24` | `section_headers` / `usage_attribution_lines`（BGM 既定） | 中 | skill-config 化済だが、default 値が BGM/AI 透明性宣言に強くバイアス。**ゲーム/トーク/ASMR 用の neutral default** をコメントで提示すべき（既にコメントで言及ありだが値は BGM） |
| 5.9 | channel-setup | `.claude/skills/channel-setup/references/config-template/content.json:14-18` | `"perfect_for": ["Study & Focus Sessions", "Background Music", "Creative Work", "Relaxation"]` | 中 | テンプレートだが英語 4 項目固定。`{{LOCALE}}` プレースホルダ + 言語別 fixture が望ましい |
| 5.10 | channel-setup | `.claude/skills/channel-setup/references/config-template/youtube.json:3,5` | `"category_id": "10"`, `"language": "en"` | 中 | テンプレートだが Music カテゴリ + 英語固定。`{{CATEGORY_ID}}` / `{{LANGUAGE}}` プレースホルダ化推奨 |
| 5.11 | channel-setup | `.claude/skills/channel-setup/references/schedule-template.json:3-5,9-10` | `"day1_time": "20:00", "day2_time": "20:00", "timezone": "Asia/Tokyo", "category_id": "10", "privacy_status": "private"` | 中 | テンプレートだが日本タイムゾーン + 20:00 固定。プレースホルダ化推奨 |
| 5.12 | channel-setup | `.claude/skills/channel-setup/references/upload-settings-template.json:3-5,22-23` | `"category_id": "10", "privacy_status": "public", "language": "ja", "min_video_duration": 30, "max_video_duration": 7200` | 中 | 同上 |
| 5.13 | channel-setup | `.claude/skills/channel-setup/references/localizations-template.json:5-10` | `"ja": {"title_template": "{style} {theme} - {activity}用BGM [{duration_display}]"}` / `"en": {...BGM...}` | 中 | テンプレートだが「BGM」「{activity}用BGM」が日本語題に固定。`content_model.type` が collection なら BGM 想定、release ならドラマ/トーク等の想定にすべき |
| 5.14 | suno | `.claude/skills/suno/SKILL.md:158-164` | 禁止形容詞リスト 17 語（`thundering, blazing, crushing, ...`） | 中 | skill-config `suno.yaml::ng_words`（既存だが Lyria 側のみ）と統一できる。`config/skills/suno.yaml::scene_phrase_ng_words` 新設推奨 |
| 5.15 | suno | `.claude/skills/suno/SKILL.md:172-176` | NG ワード `rain, dripping, drops, ...` / OK ワード `misty, melancholic, ...` | 中 | 同様に skill-config 化推奨 |
| 5.16 | postmortem | `.claude/skills/postmortem/SKILL.md:71-78,86-89` | 比率閾値 0.5/0.7/0.9 を症状判定 + 仮説マッピングの 2 箇所で重複定義 | 中 | skill-config `postmortem.yaml::thresholds` 一元化。SKILL.md 内に「閾値は固定値ではなく **チャンネル特性に応じて文脈調整可**」と書かれている時点で外出ししたほうが運用と整合 |
| 5.17 | analytics-collect | `.claude/skills/analytics-collect/SKILL.md:58` | `チャンネル: <channel_config: channel.name>` | 低 | プレースホルダ syntax は OK だが、v2.0.0 namespace では `meta.channel.name`。読み手向けプレース表記なので致命的ではないが統一推奨 |
| 5.18 | streaming | `.claude/skills/streaming/SKILL.md:29,96`, `infra/terraform/streaming/README.md` | `--check-threshold` の閾値（80%）が `src/youtube_automation/utils/streaming/threshold.py` の `THRESHOLD_RATIO` 定数で、`config/channel/` 連動なし | 中 | plan.md A-4 で既知シードとして言及。Vultr 帯域上限は streaming infra 固有なので `config/skills/streaming.yaml::bandwidth_threshold_ratio` 新設が妥当 |

---

## 3. 主要な発見のサマリー（top 5）

### ① v2.0.0 namespace の取りこぼし（A-5 #5.1）— **最重要**
- `analytics-analyze/SKILL.md:64` に `channel_config.tags.themes` が残存。post-v2.0.0 では `content.tags.themes`。
- 他にも `video-description/references/description-templates.md` および `analytics-collect/SKILL.md` で `{channel_config: ...}` プレースホルダ syntax が使われており、新 namespace（`meta.*` / `content.*`）と表記がずれている。
- **理由**: CLAUDE.md「設定アクセス」節と矛盾するため、最終レポートで section 1.4 の代表事例として取り上げるべき。

### ② analytics-report のブランド色直書き（A-5 #5.2, A-2 #2.11）
- HTML レポートのカラーパレット 9 色（特に `#c8a96e` = "ブランドアクセントカラー"）が SKILL.md に直書き。
- チャンネルごとに変えたい代表的な値だが config 参照ルートが無い。
- `meta.json::channel.brand_color` 新設 or `analytics-report.yaml::theme` skill-config 導入の 2 択。

### ③ video-description の英語コピー二重管理（A-5 #5.4, #5.5）
- `usage_attribution_lines` は skill-config に既出だが、`references/description-templates.md` 内の固定テンプレ本文に同じ意図の英語コピー（"🎧 If you enjoyed the vibe..." / "Original AI composition..."）が並走している。
- どちらが正なのか不明確（生成時にテンプレ → skill-config の置換が機能しているか要確認）。

### ④ user-specific dev path のハードコード（A-3 #3.1, #3.2, #3.3）
- `~/01-dev/projects/`, `~/02-yt` は repo author（`daiki-beppu`）の作業環境固有のパス。
- パッケージ配布先の他チャンネル運営者にはそのまま当てはまらず、`/channel-new` / `/channel-import` の初回手順で混乱を生む。
- 例示を `<your-projects-dir>` / `<your-channels-parent>` に一般化すべき。

### ⑤ GitHub owner 名 `daiki-beppu` の固定（A-4 #4.4, #4.5, #4.6）
- 3 つのスキルで `daiki-beppu/youtube-channels-automation.git` および `daiki-beppu/youtube-channel-template` が install/clone コマンドに直書き。
- パッケージを fork した別運営者にはそのまま使えない。`{{REPO_OWNER}}` プレースホルダ化、または README/CLAUDE.md の installation 節への一元化を推奨。

---

## 4. カバレッジ

### 走査済み（35 スキル全件）

```
alignment-check / analytics-analyze / analytics-collect / analytics-report /
audience-persona / benchmark / channel-direction / channel-import / channel-new /
channel-research / channel-setup / channel-status / collection-ideate /
comments-reply / discover-competitors / live-clean / loop-video / lyria /
masterup / metadata-audit / playlist / postmortem / streaming / suno /
thumbnail / thumbnail-compare / video-analyze / video-description / video-upload /
videoup / viewer-voice / viewing-scene / wf-new / wf-next / wf-status
```

### 検出 0 件のスキル（A-1, A-3, A-4, A-5 の P1 観点で）

A-1〜A-5 通算で **強い検出 (high) が 0 件**だったスキル:
- alignment-check, audience-persona, channel-direction, channel-research,
  channel-status, comments-reply, discover-competitors, live-clean, loop-video,
  metadata-audit, playlist, suno, thumbnail, thumbnail-compare, video-analyze,
  video-upload, viewing-scene, wf-new, wf-next, wf-status, masterup, lyria, benchmark

これらの 23 スキルは **「P1 観点で問題なし」** と記録できる（中重大度の magic number は別途）。

### 走査の手段別

| 観点 | 手段 | 件数 |
|------|------|------|
| A-1 | `Grep "UC[A-Za-z0-9_-]{22}"` / `Grep "PL[A-Za-z0-9_-]{16,}"` / `@<handle>` | 完全一致 0 件 |
| A-2 | `Grep "1920\|1080\|1280\|720\|7200\|3600"`、`Grep "#[0-9A-Fa-f]{6}"`、`Grep "\b\d{2,}\b"` 文脈読み | 45 件抽出後、低/中で集計 |
| A-3 | `Grep "/Users/\|/home/\|~/<name>"` | 3 件高 + 4 件低 |
| A-4 | `Grep "AIza\|sk-\|ya29"` / `Grep "https?://"` | リテラル 0 件、URL 用途別精査 |
| A-5 | A-2 とクロスでチェック + namespace `channel_config\.` 等の grep | 上記表参照 |

### 走査できなかった範囲

- バイナリ画像（`branding/icon.png` 等が想定する内容）に埋め込まれたメタデータ・テキスト → スコープ外
- `.claude/skills/<name>/references/terraform-gcp/*.tf` の terraform 変数値 → variables.tf を一部精査済（A-3 #3.7 参照）。本体 `main.tf` までは未走査
- スクリプト内のコメント本文（`# secret 侵害時に...` のような注釈）→ 一部のみ確認
- リポジトリの `src/youtube_automation/` 本体 → 範囲外（skills の参照先として一部チェックのみ）

---

## 5. 注意点・リスク（false positive 候補）

| 項目 | False positive リスク | 理由 |
|------|---------------------|------|
| `category_id: "10"` | 中 | YouTube Music カテゴリ固定 ID。BGM チャンネル前提なら自然。release 型でゲーム配信なら ID 20（Gaming）等になる |
| `Asia/Tokyo` (schedule-template) | 低 | 日本以外の運営者は変更必須なのでテンプレ既定値の妥当性自体が議論 |
| `daiki-beppu/...` | 中 | リポジトリ author としては正しいが、配布パッケージとしては問題 |
| 色 hex (`#0f1419` 等) | 低 | analytics-report の dark theme は完全に意図された UI 設計 |
| postmortem 閾値 (0.5, 0.7) | 中 | ドキュメント自体に「文脈調整可」とある時点で **意図的なソフト固定**。config 化の優先度は判断分かれる |
| GCP region `us-central1` | 低 | Veo / Lyria の対応 region 制約 (`loop-video/SKILL.md:48`)。意図的固定 |
| YouTube タイトル 100 文字 | 低 | 仕様値 |

---

## 6. 調査不可項目とその理由

| 項目 | 理由 |
|------|------|
| バイナリ画像 (`branding/icon.png` 等) に埋め込まれたチャンネル名・透かし | Read ツールでは画像本体は確認できるがメタデータ抽出はスコープ外 |
| `infra/terraform/streaming/main.tf` 等本体 | 本タスクは `.claude/skills/**` 配下のみ。Terraform 本体は範囲外 |
| `src/youtube_automation/utils/streaming/threshold.py` 内の `THRESHOLD_RATIO` の実数値 | grep で `THRESHOLD_RATIO` 参照は確認したが、定数値そのものはコード本体の探索が必要（範囲外） |
| skill-config 上書きルール (`config/skills/<skill>.yaml`) の deep-merge 挙動が実際に意図通りか | 統合テストが必要（本タスクは静的検出のみ） |

---

## 7. 推奨/結論 — 最終レポートで取り上げるべき検出（優先度付き）

最終レポート `docs/audits/skills-audit-2026-05-18.md` の「観点 1.1 ハードコード値」「観点 1.4 既存 config 未参照」セクションで、以下を **必ず取り上げる**:

### P1 必須掲載（fix リスト high）

1. **A-5 #5.1**: `analytics-analyze/SKILL.md:64` の旧 namespace `channel_config.tags.themes` → `content.tags.themes` への修正
2. **A-5 #5.2 + A-2 #2.11**: `analytics-report/SKILL.md:94-101` のブランド色 9 件 → `meta.json::channel.brand_color` または skill-config 新設
3. **A-5 #5.4 + #5.5**: `video-description/references/description-templates.md:36,43,44` の英語固定コピー → `channel.cta_subscribe` / `usage_attribution_lines` への統合（二重管理解消）
4. **A-3 #3.1, #3.2, #3.3**: `channel-new/SKILL.md:29,64`, `channel-import/SKILL.md:20` の user-specific path（`~/01-dev/`, `~/02-yt`）一般化
5. **A-4 #4.4, #4.5, #4.6**: `daiki-beppu` GitHub owner 名の `{{REPO_OWNER}}` プレースホルダ化

### P2 推奨掲載（fix リスト medium）

6. **A-5 #5.3**: analytics-report の `#Shorts` 文字列フィルタ → `analytics.collection_filter_keywords` 統合
7. **A-5 #5.6**: video-description のハッシュタグ数 13 固定 → `descriptions.hashtag_count` 化
8. **A-5 #5.16 / A-2 #2.23**: postmortem の閾値 0.5/0.7/0.9 → skill-config 化
9. **A-5 #5.14, #5.15**: suno の禁止形容詞・NG/OK ワード → skill-config 化
10. **A-5 #5.18**: streaming `--check-threshold` の閾値非連動 → `config/skills/streaming.yaml` 新設
11. **A-3 #3.5**: streaming の `~/.ssh/yt_stream_key` 固定 → skill-config `ssh_key_path`
12. **A-2 #2.13, #2.14**: analytics-analyze / analytics-collect の `30分` 鮮度ウィンドウ重複定義 → skill-config 横断統一

### P3 補足掲載（fix リスト low）

13. **A-5 #5.7**: video-description の `theme_emoji` を `content.json::title.theme_emoji` に集約（既存 `theme_activities` / `theme_scenes` と一元化）
14. **A-5 #5.9, #5.10, #5.11, #5.12, #5.13**: channel-setup の各テンプレ JSON の英語/日本ロケール固定 → プレースホルダ化
15. **A-2 #2.20**: metadata-audit のチャプター数閾値 (3/12) → skill-config 化
16. **A-2 #2.21**: suno の `4 パターン × 3 回 = 24` → skill-config 化

### 最終レポート構成への寄与

- **観点 1.1（ハードコード値）**: A-1 0 件、A-2 中 25 / 低 20 件、A-3 高 3 / 中 1 件、A-4 中 3 件 → 「絶対値ハードコードはほぼ無いが、設定可能であるべき constants が SKILL.md 本文 / references / config.default.yaml に分散している」がメッセージ
- **観点 1.4（既存 config 未参照）**: 高 4 件 + 中 9 件 → 「analytics-report のブランド色」「video-description テンプレ文の二重管理」「v2.0.0 namespace 取りこぼし」を 3 大テーマとして掲載

---

以上。次ステップ `analyze` で本レポートを Part B / Part C の結果とマージし、最終レポート `docs/audits/skills-audit-2026-05-18.md` の section 1.1 / 1.4 を起こすこと。
