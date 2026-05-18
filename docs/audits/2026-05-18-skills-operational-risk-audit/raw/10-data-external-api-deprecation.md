# C-2: 外部 API の廃止 / バージョン追従 — 監査データ

調査日: 2026-05-18
担当: dig.part-c-deps-deprecation
対象リビジョン: HEAD

---

## 6.6 Vertex AI API バージョン（Lyria / Veo / Gemini）

### 6.6.1 使用モデル一覧と endpoint

| モデル / バージョン | 使用箇所 | 公式ステータス（2026-05-18 時点） | shutdown 予定 |
|---|---|---|---|
| `gemini-2.5-flash` | `.claude/skills/video-analyze/config.default.yaml:7`, `.claude/skills/benchmark/config.default.yaml:23`, `src/youtube_automation/scripts/benchmark_collector.py:523` | **deprecated**（後継 `gemini-3-flash-preview`） | **2026-10-16 earliest** |
| `gemini-2.5-flash-lite` | `src/youtube_automation/scripts/populate_scene_phrases.py:33`（`DEFAULT_GEMINI_MODEL`） | **deprecated**（後継 `gemini-3.1-flash-lite`） | **2026-10-16 earliest** |
| `gemini-3.1-flash-image-preview` | `src/youtube_automation/utils/image_provider/config.py:27`, `.claude/skills/thumbnail/config.default.yaml:18`, `.claude/skills/collection-ideate/SKILL.md:139` | preview / GA 移行情報未公開 | 未告知（preview 継続中） |
| `veo-3.1-fast-generate-001` | `src/youtube_automation/utils/veo_generator.py:15`, `.claude/skills/loop-video/config.default.yaml:8`, `.claude/skills/loop-video/SKILL.md:107,116` | **GA**（2025-11-17 promoted） | 未告知 |
| `veo-3.1-generate-001` | `.claude/skills/loop-video/SKILL.md:116`（選択肢として記載） | **GA**（2025-11-17） | 未告知 |
| `veo-3.1-lite-generate-preview` | `.claude/skills/loop-video/SKILL.md:86,116`, `.claude/skills/loop-video/config.default.yaml:7` | **preview**（2026-04-02 導入） | 未告知 |
| `lyria-3-pro-preview` | `src/youtube_automation/utils/audio_units.py:14`, `.claude/skills/lyria/config.default.yaml:17`, `.claude/skills/lyria/SKILL.md:60,85,94` | **preview** | 未告知 |
| `lyria-3-clip-preview` | `src/youtube_automation/utils/audio_units.py:15`, `.claude/skills/lyria/SKILL.md:85` | **preview** | 未告知 |
| `lyria-002` | `src/youtube_automation/utils/audio_units.py:16`（cost_tracker 単価マッピングのみ） | レガシー（Lyria 2） | 未告知 |
| `gpt-image-2` | `src/youtube_automation/utils/image_provider/config.py:150`, `.claude/skills/thumbnail/config.default.yaml:89` | **GA**（2026-04-21 リリース） | 未告知 |

### 6.6.2 出典・取得日

- Gemini deprecation table: `https://ai.google.dev/gemini-api/docs/deprecations`（2026-05-18 取得）
  - 「gemini-2.5-flash Release: June 17, 2025, Shutdown: October 16, 2026, Replacement: gemini-3-flash-preview」
  - 「gemini-2.5-flash-lite Release: July 22, 2025, Shutdown: October 16, 2026, Replacement: gemini-3.1-flash-lite」
  - 「gemini-3.1-flash-image-preview Release: February 26, 2026, Shutdown: No shutdown date announced」
- Veo GA / preview ステータス: `https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes`（2026-05-18 取得）
  - 「veo-3.1-generate-001 / veo-3.1-fast-generate-001 promoted to GA on 2025-11-17」
  - 「veo-3.1-generate-preview / veo-3.1-fast-generate-preview migration deadline: 2026-04-02」
  - 「veo-3.1-lite-generate-preview introduced 2026-04-02」
- Lyria 3 ステータス: `https://docs.cloud.google.com/vertex-ai/generative-ai/docs/music/generate-music`（2026-05-18 取得）
  - 「Lyria 3 is in preview, not GA. Available model IDs: lyria-3-clip-preview, lyria-3-pro-preview」
- OpenAI gpt-image-2: WebSearch + `https://developers.openai.com/api/docs/models/gpt-image-2`（2026-05-18 取得）
  - 「gpt-image-2 officially launched 2026-04-21」
  - 「dall-e-2 / dall-e-3 deprecated and removed from API on 2026-05-12」

### 6.6.3 endpoint 設計

`src/youtube_automation/utils/lyria_client.py:26`:

```python
_ENDPOINT = "https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/global/interactions"
```

→ **`v1beta1` を直接叩いている**（`google-genai` SDK 1.71.0 時点で `interactions` 未対応のため `requests` で直叩き、と docstring 明記）。`v1beta1` は Google Cloud 慣例で GA 移行時に endpoint が `v1` に変わる可能性が高い。Lyria 3 が GA 化されたとき、もしくは新 SDK が `interactions` をサポートしたタイミングで自前 `requests` 実装は破棄すべき。

Vertex AI region: `genai_client.py:27` で `_DEFAULT_LOCATION = "us-central1"`。`lyria_client.py:26` は `locations/global` を hardcode（Lyria 3 は global のみのため）。`auth/SETUP.md:11-13` に「`gemini-3.1-flash-image-preview` などの画像系: `global` のみ／`veo-3.1-fast-generate-001` などの Veo 系: `us-central1` など region 指定」と注意書きあり。

---

## 6.7 YouTube Data API v3

### 6.7.1 ServiceRegistry の API バージョン指定

出典: `src/youtube_automation/utils/youtube_service.py:49,57,65`

```python
build("youtube", "v3", credentials=...)
build("youtubeAnalytics", "v2", credentials=credentials)
build("youtubereporting", "v1", credentials=credentials)
```

`src/youtube_automation/auth/oauth_handler.py:239`, `src/youtube_automation/scripts/fetch_stream_key.py:114` でも `youtube/v3` を直接 build。

### 6.7.2 廃止予告 API endpoint の使用有無

主要 endpoint 使用箇所（grep ベース）:

| endpoint | 使用箇所 | 廃止リスク |
|---|---|---|
| `videos().insert` | `src/youtube_automation/utils/upload_core.py:74` | 中核機能、廃止懸念なし |
| `videos().list` | `src/youtube_automation/utils/streaming_archive.py:60`, `bulk_update_descriptions_from_md.py:102`, `metadata_audit.py:138`, `competitor_discovery.py:134`, `comments/replier.py:134` | 廃止懸念なし |
| `videos().update` | `src/youtube_automation/scripts/bulk_update_descriptions_from_md.py:153` | 廃止懸念なし |
| `playlists().insert` | `src/youtube_automation/scripts/playlist_manager.py:60` | 廃止懸念なし |
| `playlistItems().insert/list/delete` | `playlist_manager.py:91,209,367,385`, `playlist_status.py:38`, `competitor_discovery.py:118`, `comments/replier.py:52`, `video_listing.py:49` | 廃止懸念なし |
| `commentThreads().list` | `src/youtube_automation/utils/comments/fetcher.py:59`, `scripts/fetch_benchmark_comments.py:50` | 廃止懸念なし |
| `comments().insert` | `src/youtube_automation/utils/comments/replier.py:214` | 廃止懸念なし |
| `search().list` | `src/youtube_automation/utils/streaming/archive_counter.py:64`, `agents/collection_uploader.py:150` | 高 quota cost（100 units）注意 |
| `channels().list` | `src/youtube_automation/auth/oauth_handler.py:255` | 廃止懸念なし |

**`commentThreads.markAsSpam` / `commentThreads.setModerationStatus` / `guideCategories` 等の廃止予告 endpoint の使用は 0 件確認**（grep）。

YouTube Data API v3 自体は 2026-05-18 時点で deprecation アナウンスなし（公開検索結果）。Reporting API v1 と Analytics API v2 も同様。

---

## 6.8 OpenAI API

### 6.8.1 使用モデル

`src/youtube_automation/utils/image_provider/config.py:150`:

```python
return OpenAIConfig(
    model=d.get("model", "gpt-image-2"),
    ...
)
```

`.claude/skills/thumbnail/config.default.yaml:89`:

```yaml
model: gpt-image-2
```

### 6.8.2 deprecation schedule との突合せ

- `dall-e-2` / `dall-e-3`: **2026-05-12 にすでに API から削除済み**（OpenAI Deprecations 2026 通知）
  - codebase 内で `dall-e` 文字列の使用箇所: 0 件確認（grep）→ **影響なし**
- `gpt-image-1`: 現役（gpt-image-2 の旧世代だが deprecation なし）
- `gpt-image-1.5`: 現役（2025-12 リリース）
- `gpt-image-2`: **2026-04-21 GA**、現役

→ codebase は最新世代を使用しており健全。

`utils/cost_tracker.py` の `PRICING` テーブルは `gpt-image-2` / `gpt-image-1.5` / `gpt-image-1-mini` の 3 モデルを CHANGELOG（行 40-44）で追加済み。

### 6.8.3 OpenAI Python SDK の互換性

`openai==2.33.0` （uv.lock）→ PyPI 2.37.0 が最新。`from openai import OpenAI` (`src/youtube_automation/utils/image_provider/openai.py:16`) で利用しているのみ。SDK 1.x → 2.x の breaking change（client インスタンス化方式変更）には対応済み（2.x で書かれている）。

---

## 6.9 Suno API

### 6.9.1 契約形態

Suno **公式 API は無し**。下記のような非公式 / UI スクレイピング経由でアクセスしている。

### 6.9.2 CDN URL 経由ダウンロード

`.claude/skills/masterup/SKILL.md:84-89`:

```bash
curl -L -o "02-Individual-music/{filename}.mp3" "https://cdn1.suno.ai/{song_id}.mp3"
```

`.claude/skills/masterup/SKILL.md:22`:

```yaml
suno_download.cdn_url_template: "https://cdn1.suno.ai/{song_id}.mp3"
```

SKILL.md:92 に「CDN URL は public だが永続性は不明。生成後なるべく早めにダウンロードすること」と注意書きあり。

### 6.9.3 WebFetch でプレイリスト HTML スクレイピング

`.claude/skills/masterup/SKILL.md:72-79` Step 2:

> WebFetch ツールを使ってプレイリスト URL (例: `https://suno.com/playlist/xxx`) を取得し、prompt で全曲の情報を抽出するよう指示

→ **Suno UI の HTML 構造に依存**。Suno が SPA 化したり HTML 構造を変えた瞬間に壊れる。

### 6.9.4 「いつ壊れる可能性があるか」のメモ

`/suno` `/masterup` の SKILL.md / 実装側に Suno 仕様変更に関する deprecation メモ・モニタリングは **無し**。

→ 公開情報なし（Suno 側に SLA / 廃止スケジュールの公開なし）。**未検証 / 公開情報なし** として report.

---

## 6.10 Google API 全般 — `googleapiclient.discovery.build` 棚卸し

| service / version | 箇所 | 用途 |
|---|---|---|
| `youtube` / `v3` | `src/youtube_automation/utils/youtube_service.py:49`（YouTubeOAuthHandler 経由）, `auth/oauth_handler.py:239`, `scripts/fetch_stream_key.py:114` | YouTube Data API |
| `youtubeAnalytics` / `v2` | `src/youtube_automation/utils/youtube_service.py:57` | Analytics |
| `youtubereporting` / `v1` | `src/youtube_automation/utils/youtube_service.py:65` | Reporting |

→ 3 サービス × 各 1 バージョン。すべて現役。

`fetch_stream_key.py:114` で `oauth_handler` を経由せず直接 `build` している点はリファクタリング余地ありだが API バージョン的には問題なし。

---

## まとめ（外部 API 廃止リスク severity）

| ID | 内容 | severity | shutdown 予定 |
|---|---|---|---|
| 6.6.1 | `gemini-2.5-flash` が deprecated、shutdown 2026-10-16（earliest） | **P1** | 5 ヶ月後 |
| 6.6.1 | `gemini-2.5-flash-lite` が deprecated、shutdown 2026-10-16 | **P1** | 5 ヶ月後 |
| 6.6.1 | `lyria-3-pro-preview` / `lyria-3-clip-preview` が preview 状態（GA への移行未告知） | P2 | 未告知 |
| 6.6.1 | `veo-3.1-lite-generate-preview` が preview（`loop-video` の選択肢） | P2 | 未告知 |
| 6.6.3 | Lyria 3 `interactions` は `v1beta1` を直叩き（公式 SDK 未対応のため `requests`） | P2 | 未告知 |
| 6.7 | YouTube Data API v3 関連で廃止予告 endpoint 使用は **無し** | — | — |
| 6.8 | `dall-e-*` deprecation の影響 **無し**（コード非使用） | — | — |
| 6.9 | Suno は非公式 CDN URL + UI HTML スクレイピング依存、deprecation メモ無し | **P1** | 未公開 |

### 主要発見

1. **Gemini 2.5 系（2 モデル）は 2026-10-16 に shutdown 予告済み**。`benchmark`, `video-analyze`, `populate_scene_phrases` の 3 スキル/CLI が直接ヒット。事実上 5 ヶ月の猶予
2. **Lyria 3 が preview のまま**。`/lyria` スキルは preview 状態の `v1beta1` `interactions` REST を直叩き。GA 移行時に endpoint URL が変わる可能性あり
3. **Suno 連携は非公式**。永続性なし、復旧手段ゼロのリスクが顕在化していない

調査不可項目:
- Suno UI / CDN の正確な廃止スケジュール: 公開情報なし
- Vertex AI Lyria 3 GA 化時期: 公開情報なし
