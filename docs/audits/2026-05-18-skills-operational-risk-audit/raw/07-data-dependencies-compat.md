# Part C: 依存・廃止 API・互換性レポート

**調査日**: 2026-05-18
**担当**: `dig.part-c-dependencies-compat`
**対象リビジョン**: HEAD (`20260518T0905-372-issue-372-chore-skills-sukiru`)
**スコープ**: 計画 `plan.1.20260518T090751Z.md` の **Part C** (観点 5: 廃止 API・SDK・依存 / 観点 6: 外部サービス単一障害点)
**非スコープ**: 失敗時挙動 / コスト制御 (Part A) / シークレット (Part B) — 既存レポート参照

> 注: order.md の章番号体系では本 Part が扱うのは「観点 6: 依存 / 環境前提 / 廃止リスク」+ それを掘り下げた「外部サービス単一障害点」観点。本プロンプト内呼称「観点 5 + 観点 6」は plan.1 内部の番号付け（Part C 観点 5 = deps、観点 6 = SPOF）に合わせている。

---

## 1. severity 別サマリー

| severity | 件数 | 概要 |
|---|---|---|
| **P0** | 1 | Vertex AI Lyria 3 `interactions` API レスポンススキーマが **2026-05-26 にデフォルト切替 / 2026-06-08 に legacy 完全削除**。`lyria_client.py:149` は legacy `outputs` を直接読み込み済、無音失敗で `None` を返して停止 |
| **P1** | 4 | (a) `gemini-2.5-flash` / `gemini-2.5-flash-lite` shutdown 2026-10-16 (4 use site), (b) `google-genai` 1.69 vs 2.4 major gap + 上限 pin なし → CI 再ビルドで突然 2.x が降ってくる, (c) `google-auth-httplib2` upstream で deprecated 表明, (d) skill バージョン追跡なし — `yt-skills sync --force` 明示が前提 |
| **P2** | 6 | Lyria 3 endpoint `v1beta1` 直叩き、Veo 3.1 Lite ID の表記揺れ、`dead extras` (`veo = []`)、`japanize-matplotlib` 4 年超停滞、空 `Workflow` dataclass、CLAUDE.md L38 と L100 の矛盾 |
| **P3** | 3 | `audio_units.py` の `lyria-002` 残置、v1→v2 config 移行 CLI 撤去判断、`requires-python = ">=3.11"` 過剰制約疑い |
| **CLI 要件欠落** | 5 | `ffmpeg` / `gcloud` / `gh` / `op` / `uv` の **最低バージョン**未明示。`ONBOARDING.md:31-39` 全項目「最新」のみ |
| **障害時ガイダンス欠落** | 27/35 skill | SKILL.md に「API 障害時 / rate limit 時 / 未認証時 / CLI 不在時」のいずれも記述なし |
| **調査不可** | 3 | Suno UI 仕様変更スケジュール、Lyria 3 GA 時期、`veo-3.1-lite-generate-preview` の公式 publisher model ID |

主要 finding 上位 3 件:
1. **[P0]** `src/youtube_automation/utils/lyria_client.py:149` legacy schema 依存 — 2026-05-26 にサイレント失敗
2. **[P1]** `pyproject.toml:13-28` 全 16 依存が上限なし — `uv lock --upgrade` で破壊的更新を引き込む余地
3. **[P1]** 35 skill 中 27 件で外部サービス障害時ガイダンスゼロ — 沈黙停止運用

---

## 2. 観点 5-1: モデル名 / API バージョン hard-coding 監査

### 2.1 使用モデル一覧

| モデル ID | 使用箇所 (`file:line`) | deprecation 状況 | severity | 出典 |
|---|---|---|---|---|
| `gemini-2.5-flash` | `.claude/skills/benchmark/config.default.yaml:23`, `.claude/skills/video-analyze/config.default.yaml:7`, `.claude/skills/wf-new/references/scene_phrases.md:26`, `src/youtube_automation/scripts/benchmark_collector.py:523` | **deprecated**、shutdown **2026-10-16** | **P1** | [^gemini-dep] |
| `gemini-2.5-flash-lite` | `src/youtube_automation/scripts/populate_scene_phrases.py:33` (`DEFAULT_GEMINI_MODEL`) | **deprecated**、shutdown **2026-10-16** | **P1** | [^gemini-dep] |
| `gemini-3.1-flash-image-preview` | `src/youtube_automation/utils/image_provider/config.py:27`, `.claude/skills/thumbnail/config.default.yaml:18`, `.claude/skills/collection-ideate/SKILL.md:139` | preview（shutdown 未告知） | P2 | [^gemini-dep] |
| `veo-3.1-fast-generate-001` | `src/youtube_automation/utils/veo_generator.py:15`, `src/youtube_automation/scripts/generate_loop_video.py:85`, `.claude/skills/loop-video/config.default.yaml:8`, `.claude/skills/loop-video/SKILL.md:107,116` | **GA** (2025-11-17) | OK | [^vertex-rn] |
| `veo-3.1-generate-001` | `.claude/skills/loop-video/SKILL.md:116`, `src/youtube_automation/scripts/generate_loop_video.py:86` | **GA** | OK | [^vertex-rn] |
| `veo-3.1-lite-generate-preview` | `.claude/skills/loop-video/config.default.yaml:7`, `.claude/skills/loop-video/SKILL.md:116`, `src/youtube_automation/scripts/generate_loop_video.py:75,86` | **preview**（公式 publisher model ID として明示確認できず、表記揺れ疑い） | P2 (要検証) | [^veo-lite] |
| `lyria-3-pro-preview` | `.claude/skills/lyria/config.default.yaml:17`, `.claude/skills/lyria/SKILL.md:60,85,94`, `src/youtube_automation/utils/audio_units.py:14` | **preview**（GA 未告知） | P2 | [^lyria-docs] |
| `lyria-3-clip-preview` | `.claude/skills/lyria/SKILL.md:85`, `src/youtube_automation/utils/audio_units.py:15` | **preview** | P2 | [^lyria-docs] |
| `lyria-002` | `src/youtube_automation/utils/audio_units.py:16` (cost_tracker 単価マッピングのみ、選択肢に出てこない) | レガシー Lyria 2 (実利用なし) | P3 | — |
| `gpt-image-2` | `src/youtube_automation/utils/image_provider/config.py:150`, `.claude/skills/thumbnail/config.default.yaml:89` | **GA** (2026-04-21) | OK | [^openai-models] |
| `dall-e-*` / `gpt-image-1` / `imagen-*` | コードベースに参照 **0 件** (grep で確認) | — (削除済 dall-e は不使用) | OK | — |
| `claude-*` / Anthropic SDK | コードベースに参照 **0 件** | — (本リポジトリは Anthropic SDK を直接叩かない) | OK | — |

### 2.2 API バージョン / endpoint の hard-coding

| 種別 | 箇所 | バージョン | リスク |
|---|---|---|---|
| YouTube Data API | `src/youtube_automation/utils/youtube_service.py:49` (`build("youtube", "v3", ...)`) | `v3` | 廃止予告なし [^yt-rev] |
| YouTube Analytics API | `src/youtube_automation/utils/youtube_service.py:57` | `v2` | 廃止予告なし [^yt-analytics] |
| YouTube Reporting API | `src/youtube_automation/utils/youtube_service.py:65` | `v1` | 廃止予告なし |
| Vertex AI Lyria 3 Interactions | `src/youtube_automation/utils/lyria_client.py:26` (`v1beta1` 直叩き) | `v1beta1` | **P2: GA 化時に endpoint 変更**。実装は `requests` で URL を組み立てている (`lyria_client.py:124`) ため SDK の更新を待たずに直接修正が必要 |
| Vertex AI google-genai client | `src/youtube_automation/utils/genai_client.py:23-44` | google-genai SDK 経由 (バージョン自動解決) | google-genai 2.x へ移行時に SDK API 互換性確認要 |
| Lyria 3 response schema | `src/youtube_automation/utils/lyria_client.py:149` (legacy `outputs` フィールド読み取り) | **2026-05-26 デフォルト切替で破壊** | **P0** [^lyria-bcm] |

### 2.3 skill 側 prompt にモデル名が埋まっているか

- `.claude/skills/lyria/SKILL.md:60,85,94`、`.claude/skills/loop-video/SKILL.md:107,116`、`.claude/skills/thumbnail/SKILL.md:41`、`.claude/skills/video-analyze/SKILL.md:58`、`.claude/skills/benchmark/SKILL.md:98`、`.claude/skills/collection-ideate/SKILL.md:139` がモデル ID を直接記述。skill 同梱版は wheel に固定されるため、deprecated モデル更新時は **skill 配布側 + 下流の `yt-skills sync --force` が必須**。バージョン bump の責任所在を明文化していない（後段 §5 参照）。

### 2.4 廃止予定モデル：影響範囲とタイムライン

| 日付 | 事象 | 影響経路 |
|---|---|---|
| **2026-05-26** | Lyria 3 Interactions API デフォルトスキーマ切替 | `yt-generate-lyria-master` / `/lyria` 全チャンネル |
| **2026-06-08** | Lyria 3 legacy schema 完全削除 | 同上、`Api-Revision: 2026-05-07` ヘッダ延命策も失効 |
| **2026-10-16** | `gemini-2.5-flash*` shutdown | `/benchmark`, `/video-analyze`, `yt-populate-scene-phrases`, `benchmark_collector` 全チャンネル |

[^gemini-dep]: <https://ai.google.dev/gemini-api/docs/deprecations> (2026-05-18 取得)
[^vertex-rn]: <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes> (2026-05-18 取得)
[^veo-lite]: <https://cloud.google.com/blog/products/ai-machine-learning/veo-3-1-lite-and-a-new-veo-upscaling-capability-on-vertex-ai> (2026-05-18 取得)
[^lyria-docs]: <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/music/generate-music> (2026-05-18 取得)
[^lyria-bcm]: <https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026> (2026-05-18 取得)
[^openai-models]: <https://developers.openai.com/api/docs/models/gpt-image-2> + `https://developers.openai.com/api/docs/deprecations` (2026-05-18 取得)
[^yt-rev]: <https://developers.google.com/youtube/v3/revision_history>
[^yt-analytics]: <https://developers.google.com/youtube/analytics/revision_history>

---

## 3. 観点 5-2: Python 依存 version pin 監査

### 3.1 `pyproject.toml` 依存表（取得日 2026-05-18）

出典: `pyproject.toml:13-28` + uv.lock + PyPI

| パッケージ | 現在 pin (`pyproject.toml`) | uv.lock 解決 | PyPI 最新 | risk | 推奨 |
|---|---|---|---|---|---|
| `google-api-python-client` | （無制約） | 2.193.0 | 2.196.0 | minor 遅延 | `>=2.193,<3` |
| `google-auth-oauthlib` | （無制約） | 1.3.0 | 1.4.0 | minor 遅延 | `>=1.3,<2` |
| `google-auth-httplib2` | （無制約） | 0.3.0 | 0.4.0 (deprecated 表明) | **P1** | `>=0.3,<1` で当面延命 + 撤去計画 |
| `google-genai` | （無制約） | **1.69.0** | **2.4.0** | **P1** (major gap) | `>=1.69,<2`（Lyria 新スキーマ対応後に解放） |
| `openai` | （無制約） | 2.33.0 | 2.37.0 | minor 遅延 | `>=2.33,<3` |
| `Pillow` | （無制約） | 12.1.1 | 12.2.0 | パッチ遅延 | `>=12,<13` |
| `pandas` | （無制約） | 3.0.1 | 3.0.3 | パッチ遅延 | `>=3,<4` |
| `matplotlib` | （無制約） | 3.10.8 | 3.10.9 | パッチ遅延 | `>=3.10,<4` |
| `japanize-matplotlib` | （無制約） | 1.1.3 | 1.1.3 (2020-10-21 stop) | **P2** メンテ停滞 | 置換検討 (`matplotlib.font_manager`) |
| `seaborn` | （無制約） | 0.13.2 | 0.13.2 (2024-01-25) | 軽度停滞 | `>=0.13,<1` |
| `schedule` | （無制約） | 1.2.2 | 1.2.2 (2024-06-18) | 軽度停滞 | `>=1.2,<2` |
| `pyyaml` | （無制約） | 6.0.3 | 6.0.3 | OK | `>=6,<7` |
| `requests` | （無制約） | 2.33.0 | 2.34.2 | パッチ遅延 | `>=2.33,<3` |
| `python-dotenv` | （無制約） | 1.2.2 | 1.2.2 | OK | `>=1.2,<2` |
| `pytest` (dev) | （無制約） | 9.0.2 | 9.0.3 | OK | `>=9,<10` |
| `ruff` (dev) | （無制約） | 0.15.8 | 0.15.13 | OK | `>=0.15` |

### 3.2 全依存上限不在の影響

- `[project.dependencies]` 14 件 + `[project.optional-dependencies] dev` 2 件 = **計 16 件すべて name のみ**で `<X` 上限を持たない（`pyproject.toml:13-28, 33-34`）
- 下流チャンネルが `uv add git+https://...youtube-channels-automation` した時点で **その日の PyPI 最新を引き込む**（`uv.lock` は本リポジトリ側にしか効かず、下流リポジトリの `uv.lock` は独立）
- **特にクリティカル**: `google-genai` 1.x → 2.x の major bump は Vertex AI クライアント API が再設計されている。`src/youtube_automation/utils/genai_client.py:23`, `veo_generator.py:36`, `image_provider/gemini.py`, `scripts/video_analyze.py:29` 等が全停止しうる

### 3.3 dead extras

`pyproject.toml:35`:

```toml
veo = []  # google-genai, Pillow moved to main dependencies
```

→ `pip install 'youtube-channels-automation[veo]'` で何も入らない placeholder。撤去対象（P2）。

[^pypi-genai]: <https://pypi.org/project/google-genai/>
[^pypi-httplib2]: <https://pypi.org/project/google-auth-httplib2/>

---

## 4. 観点 5-3: 外部 CLI 依存マトリクス

### 4.1 skill × CLI

`grep -rnE 'command -v|shutil\.which|gh\b|terraform\b|ffmpeg\b|gcloud\b|op\b|yt-dlp|uv\b|rsync' .claude/skills` を集約。

| skill | 必須 CLI | 存在チェック | 不在時メッセージ |
|---|---|---|---|
| `streaming` | `terraform`, `op`, `ssh-keygen`, `ssh-add`, `realpath` | ✅ `swap_video.sh:61,65,69,73` で `command -v` チェックあり | ✅ shell スクリプトはエラー終了 + 案内メッセージ。SKILL.md:14 で要件記載 |
| `channel-setup` (gcp-bootstrap) | `gcloud`, `jq`, `terraform` | ✅ `gcp-bootstrap.sh:107`, `gcp-terraform-apply.sh:37,41` | ✅ メッセージあり |
| `videoup` | `ffmpeg`, `afinfo` (macOS のみ) | ✅ `generate_videos.sh:79,95` | ✅ `ffmpeg` がないと exit 1。`afinfo` は optional fallback |
| `masterup` | `yt-dlp`, `ffmpeg`, `curl` | ❌ SKILL.md は外部 CLI 呼び出しの存在チェックなし | ❌ コマンドが PATH に無い場合は `command not found` で停止。SKILL.md にも導入手順記載なし |
| `loop-video` | `ffmpeg`, `ffprobe`, `gcloud` (ADC) | ✅ `src/youtube_automation/utils/veo_generator.py:122,140` で subprocess 呼び出し（`ffmpeg` 不在は subprocess エラー） | ❌ subprocess CalledProcessError で raw stderr が漏れる |
| `lyria` | `gcloud` (ADC), `ffmpeg` (worktree_sync.sh は `set -e` のみ) | ❌ Python 側 `lyria_client.py` は ADC 未取得時 `ConfigError` で friendly メッセージあり (`lyria_client.py:118-122`)。`ffmpeg` 不在チェックは `generate_lyria_master.py` 経路では未確認 | △ ADC 系は OK、`ffmpeg` 系は曖昧 |
| `video-upload` / `comments-reply` / `playlist` / `analytics-collect` / `benchmark` / `discover-competitors` / `metadata-audit` / `channel-status` | `gcloud` (ADC), 内部 Python のみ | — | OAuth 未認証時は `auth/oauth_handler.py:138-` で `FileNotFoundError` 親切メッセージ |
| `pr` / `issue` / `release` (built-in `gh` 依存) | `gh` | ❌ skill 側に `gh` 不在チェックなし。skill 本文も「`gh` がインストールされている前提」 | ❌ 未認証 (`gh auth status` 失敗) 時はそのまま `gh` のエラーが出る |
| `parallel` / `cmux` 系 | `cmux` | ❌ skill 側で `command -v` チェックなし | ❌ |
| `nix` 系 | `nix`, `darwin-rebuild` | ❌ | ❌ |

### 4.2 SKILL.md `Prerequisites` セクションの有無

- 明示的に「事前に必要なツール」セクションがあるのは `streaming/SKILL.md:14` のみ（`terraform >= 1.5 / uv / op` を列挙）
- 他 34 skill は前提 CLI の宣言なし。`ONBOARDING.md:31-39` の prerequisites 表に集約（**最低バージョン未明示**）

### 4.3 ONBOARDING.md 「最低バージョン未明示」一覧（`ONBOARDING.md:31-39`）

| CLI | 記載バージョン | 推奨記載 |
|---|---|---|
| `uv` | 最新 | `>= 0.4` 程度を明示推奨 |
| `ffmpeg` | 最新 | `>= 4.4`（`xfade` フィルタ + `libx264` の安定動作下限） |
| `gcloud` | 最新 | `>= 480`（ADC 関連の挙動安定） |
| `op` | 最新 | **`>= 2.0` 必須**（v1 は `op read` URI 形式違い） |
| `gh` | （記載なし） | `>= 2.0` |

---

## 5. 観点 5-4: 後方互換 shim 生存確認

### 5.1 ルート直下 shim の実態

CLAUDE.md（プロジェクト固有）L38:

> `utils/`, `agents/`, `auth/`, `scripts/` — submodule 利用者向け **後方互換 shim**

CLAUDE.md L100:

> ルート `scripts/` にはシェルスクリプト（`.sh`）のみ配置。Python shim は廃止済み

→ **同一ファイル内で矛盾**。実態は:

| ディレクトリ | 存在 | 中身 | 性質 | 削除候補 |
|---|---|---|---|---|
| `utils/` | **不在** | — | CLAUDE.md L38 が古い記述 | — (既に削除済) |
| `agents/` | **不在** | — | 同上 | — |
| `auth/` | 存在 | `SETUP.md`, `client_secrets_template.json` | shim ではなく **template + ドキュメント** | 保持（用途は別） |
| `scripts/` | 存在 | `gcp-bootstrap.sh`, `gcp-terraform-apply.sh` | shim ではなく **共通シェル** | 保持 |

→ ルート直下に「Python shim として残っているもの」は **0 件**。CLAUDE.md L38 の修正が必要（P2: docs）。

### 5.2 dead backward-compat shim（コード上）

| ID | 箇所 | 内容 | 状態 |
|---|---|---|---|
| `Workflow` dataclass | `src/youtube_automation/utils/config/workflow.py:8-15` | フィールド 0 個の空 dataclass。v4.0.0 で `short` / `community` を撤去 | **dead shim**（P2: メジャー bump 時に整理候補） |
| `_build_workflow` | `src/youtube_automation/utils/config/loader.py:266-271` | 常に空 `Workflow()` を返す placeholder | 上と同根 |
| `workflow.json` 内 `short` / `community` キー | `CHANGELOG.md:500` で「素通し」運用宣言 | downstream の `workflow.json` 内の旧キーは無視される | 仕様的に確定済み |
| v1→v2 config 移行 CLI | 当時 `pyproject.toml:48` に登録 | **現在 v5.5.0**、3 メジャー超経過 | P3: 撤去判断要（loader 側は `loader.py:100-106` で legacy 形式を hard fail するため、コマンド自体は実質要らない可能性） |
| `gemini_image:` namespace 旧 schema | `src/youtube_automation/utils/image_provider/config.py:102-107` で `DeprecationWarning` 発行中 | 旧 namespace から新 `image_generation:` への移行ガード | `.claude/skills/**/config.default.yaml` には `gemini_image:` の利用箇所 **0 件**（grep 確認済み）→ 既に下流配布版で使われていない疑い |
| `OpenAIConfig.thinking` | `src/youtube_automation/utils/image_provider/openai.py:53` で `warnings.warn` | openai-python SDK が `thinking` kwarg を受け取らないため警告のみ | SDK 側が対応するまで保持 |

### 5.3 deprecated 警告経路

`grep -rnE 'warnings\.warn|DeprecationWarning' src/` 結果（テスト除く）:

| 箇所 | 内容 |
|---|---|
| `src/youtube_automation/utils/image_provider/openai.py:53` | `OpenAIConfig.thinking` 渡されたが SDK 側で無視される警告 |
| `src/youtube_automation/utils/image_provider/config.py:102-107` | 旧 `gemini_image:` namespace 利用警告 |

→ deprecated 経路を skill から呼んでいる箇所は無し（`gemini_image:` namespace は .claude/skills/ 配下に存在しない）。

---

## 6. 観点 6-1: 外部サービス単一障害点マップ

### 6.1 サービス × skill 依存マトリクス

| 外部サービス | 依存 skill | 失敗時 fallback | 障害復旧手段 |
|---|---|---|---|
| **Vertex AI (Gemini)** | `benchmark`, `video-analyze`, `wf-new` (scene_phrases), `collection-ideate` | ❌ なし | Google ステータスページ確認 → 手動再実行 |
| **Vertex AI (Veo)** | `loop-video` | ❌ なし。`utils/veo_generator.py:60-62, 70-72, 81-83, 91-93` で `except Exception` で `return False` | コスト発生済み（操作中断のみ） |
| **Vertex AI (Lyria 3)** | `lyria`, `masterup` (経路: マスター結合のみ、生成は Lyria) | ❌ なし。`lyria_client.py:140-146` で `print` + `return None` | リトライは `generate_lyria_master.py` 側で `--max-retries`（既定 3）。429 は SKILL.md:200 で「クォータ管理は本スキルの責務外」と宣言 |
| **OpenAI Images API** | `thumbnail` (provider: openai) | ✅ `gemini`/`openai` の **provider 切替可** (`image_provider/config.py:120-`) — config だけで切替成立 | provider を gemini にスイッチ |
| **Suno (UI + CDN)** | `suno`, `masterup` | ❌ 完全ロックイン。`/suno` はプロンプト生成のみで API 呼ばないが、`/masterup` の `curl https://cdn1.suno.ai/{id}.mp3` + WebFetch HTML スクレイピング | 公式 SLA / 廃止スケジュール **未公開** |
| **Vultr API + VPS** | `streaming` | ❌ 単一プロバイダ依存 | `terraform destroy` で停止、別プロバイダで `infra/terraform/streaming/` 再構築は要書き換え（vultr provider hardcode `versions.tf:5-8`） |
| **YouTube Data API v3** | `video-upload`, `comments-reply`, `playlist`, `analytics-collect`, `benchmark`, `metadata-audit`, `channel-status`, `discover-competitors`, `videoup` (upload 経路) | ❌ なし。quota exceeded は googleapiclient HttpError → `YouTubeAPIError.from_http_error` 変換 (`utils/exceptions.py`) | 日次 quota 10,000 units リセット待ち |
| **YouTube Analytics API v2** | `analytics-analyze`, `analytics-collect`, `analytics-report` | ❌ なし | 同上 |
| **YouTube Reporting API v1** | analytics 系（CTR） | ❌ | 同上 |
| **1Password CLI (`op`)** | `secrets.py` 経由で全 secret 取得 | ✅ `.env` `os.environ` フォールバックあり (`utils/secrets.py:55-58`)、`op` 不在時は `shutil.which("op")` 経由で silent skip (`secrets.py:60`) | `.env` 経路で代替可 |
| **GitHub CLI (`gh`)** | `pr`, `issue`, `release`, `branch-clean`, takt 経由全体 | ❌ なし、PATH 依存 | `gh auth login` 手動 |
| **Terraform** | `streaming`, `channel-setup` (terraform-gcp) | ❌ なし | brew install 等 |
| **ffmpeg / ffprobe** | `loop-video`, `masterup`, `videoup`, `streaming`, `lyria` (master 結合) | ❌ なし | brew install |
| **yt-dlp** | `masterup` | ❌ なし | brew install / pip install |
| **GCP ADC (`gcloud auth application-default login`)** | Vertex AI 系全部 (`lyria`, `loop-video`, `thumbnail` (gemini)) | ❌ なし。`lyria_client.py:117-122` / `genai_client.py:38-42` で `GOOGLE_CLOUD_PROJECT` 未設定エラーは出すが、ADC 無効時の挙動は SDK 任せ | 手動 `gcloud auth application-default login` |

### 6.2 fallback あり vs なし のサマリー

| 種別 | サービス | 切替方法 |
|---|---|---|
| **fallback あり** | OpenAI ↔ Gemini (画像生成) | skill config (`image_generation.provider: gemini` / `openai`) |
| **fallback あり** | 1Password (`op`) ↔ `.env` (環境変数) | プロセス起動時の `os.environ` 自動探索 |
| **fallback なし** (= ロックイン) | Vertex AI Lyria 3 / Veo 3.1 / Gemini text / YouTube Data API / Vultr / Suno / `gh` / `terraform` / `ffmpeg` / `yt-dlp` | — |

`/lyria` ↔ `/suno` は **音楽生成プロバイダ** として概念上は代替関係だが、生成プロセスが skill 自体まで完全に異なる（Lyria は自動、Suno は UI 手動）ためコード的な fallback は実装不可。

### 6.3 circuit breaker / quota guard

- **コード側**: なし（`generate_lyria_master.py` の `--max-retries` 既定 3 のみ）
- **skill 側**: `discover-competitors/SKILL.md:14,116-121` のみ quota 消費見積もりを記述（660 units / 実行）
- **`benchmark/SKILL.md:99,106`**: `thumbnail_analysis.delay_sec=5` で間隔調整
- **`video-analyze/SKILL.md:67`**: `delay_sec` でレート制限回避
- **`lyria/SKILL.md:200`**: 「クォータ管理・並列実行制御は本スキルの責務外」と明示 → 集中実行時の 429 リスクが顕在

---

## 7. 観点 6-2: SKILL.md 内の障害時ガイダンス記載監査

### 7.1 35 skill × 障害時記述マトリクス

検索キーワード: `rate limit|レート制限|429|503|quota|fallback|障害|止まったとき|エラーの場合|失敗時|落ちている|落ちた|API.*(エラー|失敗)|タイムアウト|timeout|サービス停止|認証.*失敗|認証エラー|未認証|未インストール|command not found|require[ds]?`

`grep -ciE` ヒット件数 (`/SKILL.md` のみ対象):

| skill | hits | コメント |
|---|---|---|
| `lyria` | **3** | rate limit (`SKILL.md:200`), `--max-retries` (`170,194`) |
| `discover-competitors` | **3** | quota 消費見積もり (`14,116-121`) |
| `benchmark` | 2 | delay_sec / rate limit対策 (`99,106`) |
| `channel-setup` | 2 | YouTube API 400 エラー回避 (`104`) |
| `collection-ideate` | 2 | 順次実行で rate limit 回避 (`168`) |
| `comments-reply` | 1 | OAuth 403 時の token.json 削除手順 (`66`) |
| `masterup` | 1 | `master.tmp.mp3` の atomic rename (`130`)（失敗時保護） |
| `video-analyze` | 1 | API レート制限 delay (`67`) |
| **alignment-check** | 0 | ❌ |
| **analytics-analyze** | 0 | ❌ |
| **analytics-collect** | 0 | ❌ |
| **analytics-report** | 0 | ❌ |
| **audience-persona** | 0 | ❌ |
| **channel-direction** | 0 | ❌ |
| **channel-import** | 0 | ❌ |
| **channel-new** | 0 | ❌ |
| **channel-research** | 0 | ❌ |
| **channel-status** | 0 | ❌ |
| **live-clean** | 0 | ❌ |
| **loop-video** | 0 | ❌（Veo 課金経路、最重要なのに） |
| **metadata-audit** | 0 | ❌ |
| **playlist** | 0 | ❌ |
| **postmortem** | 0 | ❌ |
| **streaming** | 0 | ❌（Vultr API 障害時の経路なし） |
| **suno** | 0 | ❌ |
| **thumbnail** | 0 | ❌（OpenAI / Gemini 両方使う） |
| **thumbnail-compare** | 0 | ❌ |
| **video-description** | 0 | ❌ |
| **video-upload** | 0 | ❌（YouTube quota exceeded 経路なし） |
| **videoup** | 0 | ❌ |
| **viewer-voice** | 0 | ❌ |
| **viewing-scene** | 0 | ❌ |
| **wf-new** | 0 | ❌ |
| **wf-next** | 0 | ❌ |
| **wf-status** | 0 | ❌ |

→ **27/35 skill (77%)** で「外部サービス障害時にどうするか」「未認証時の対応」「rate limit 時の挙動」のいずれも SKILL.md に記述なし。**沈黙して止まる運用**になる。

### 7.2 重要 skill の不足箇所

- **`/loop-video`**: Veo 3.1 課金。`utils/veo_generator.py:60-62, 70-72, 81-83, 91-93` で `return False` する 4 経路あるが SKILL.md にはエラー類型と対処手順なし
- **`/video-upload`**: `utils/upload_core.py` 経由。YouTube quota exceeded 時の挙動が SKILL.md に未記載（Part A の `data-failure-recovery.md` 参照）
- **`/streaming`**: SKILL.md:14 で必須 CLI を列挙するが、`terraform plan` 失敗時 / Vultr API 障害時の手順なし
- **`/thumbnail`**: `gemini` ↔ `openai` の provider 切替は実装上可能なのに SKILL.md:41 に「provider が落ちた時の切替手順」記述なし
- **`/comments-reply`**: 唯一 OAuth 403 時の `auth/token.json` 削除手順を記載（良い例）

### 7.3 `op read` / `gh` / `terraform` 不在時の挙動

| 経路 | 不在時の挙動 |
|---|---|
| `op` 不在 (`utils/secrets.py:60`) | `shutil.which("op")` が `None` → 警告なく `os.environ` のみで解決 → 取れなければ `ConfigError` で 「`.env` または 1Password 設定」を案内 (`secrets.py:75-79`) ✅ 良 |
| `op` あり、`op read` 失敗 (`secrets.py:72-73`) | 例外を握りつぶしてフォールスルー → 上と同じ `ConfigError` ✅ 良 |
| `gh auth status` 未認証 | skill 側のチェックなし → `gh issue create` / `gh pr create` の raw stderr が直接表示（takt 経路では deny される可能性） ❌ |
| `terraform` 未インストール | `swap_video.sh:61` で `command -v` チェックあり → 親切メッセージ ✅ / その他経路（`streaming/SKILL.md:54` の手動 `terraform init`）は手動実行で `command not found` |
| `ffmpeg` 未インストール | `videoup/references/generate_videos.sh:79` `command -v` あり ✅、`utils/veo_generator.py:122-128`（subprocess）は CalledProcessError で raw stderr |
| `yt-dlp` 未インストール（`masterup`） | チェックなし、`command not found` で落ちる ❌ |

---

## 8. 仮説検証結果（H9〜H12）

| ID | 仮説 | 結果 | 根拠 |
|---|---|---|---|
| **H9** | `gemini-2.0-flash-exp` 等 `-exp` サフィックス付きモデルが production 経路で使われている | **否定** | `grep -rnE '-exp\b' src/ .claude/skills/` で 0 件。実利用は `gemini-2.5-flash` / `gemini-2.5-flash-lite` / `gemini-3.1-flash-image-preview` のみ |
| **H10** | `veo-2.0-generate-001` の retire 後に動かなくなる skill が複数ある | **否定** | `grep -rnE 'veo-2\.0\|veo-3\.0' src/ .claude/skills/` で 0 件。実利用は `veo-3.1-fast-generate-001` / `veo-3.1-generate-001` / `veo-3.1-lite-generate-preview`。**ただし** Veo 系では `gemini-2.5-flash*` の方が 2026-10-16 リスクとして上位 |
| **H11** | ルート直下 shim の中に「もはや誰も import していない死んだ shim」がある | **△ 部分検証 — ルート shim は実在しない、コード内 shim は実在** | `utils/` / `agents/` ルート直下に shim ファイル無し（既に削除済）。一方で `Workflow` dataclass (`src/youtube_automation/utils/config/workflow.py:8-15`) が空、`_build_workflow` (`loader.py:266-271`) が無条件 placeholder で **dead shim**。v1→v2 config 移行 CLI も v5.5.0 で 3 メジャー超経過しており撤去候補 |
| **H12** | `pyproject.toml` の依存にメジャーバージョン pin が無く、google-cloud-aiplatform の breaking change で全停止する余地がある | **検証（pin 不在を確認、ただし google-cloud-aiplatform は直接依存していない）** | 直接依存は 16 件全て上限なし (`pyproject.toml:13-28`)。`google-cloud-aiplatform` は直接依存ではない（uv.lock にも未掲載）が、代わりに **`google-genai`** が 1.69 → 2.4 メジャー差で同等のリスク。実質的に H12 は `google-genai` で実現する |

---

## 9. 調査不可項目とその理由

| # | 項目 | 理由 |
|---|---|---|
| 1 | Suno UI / CDN の正確な廃止スケジュール | 公開情報なし（Suno は SLA / 廃止予告ポリシーを公表していない）。「未検証 / 公開情報なし」 |
| 2 | Vertex AI Lyria 3 GA 化時期 | 公式 release-notes 上 2026-05-18 時点で GA アナウンスなし。`v1beta1` のままがいつまで継続するか不明 |
| 3 | `veo-3.1-lite-generate-preview` の正式 publisher model ID | Vertex AI Model Garden に直接アクセスできず、複数 web ソースで表記揺れ。確定不可 |
| 4 | `daiki-beppu/youtube-automation` vs `youtube-channels-automation` のリポジトリ名混在 | GitHub 上で実体を確認する権限が `gh` 経由ではこの worktree から実行不可。`pyproject.toml:31` の URL と `ONBOARDING.md:48-51` の URL を比較した範囲では同一所有者下に並存している可能性あり |
| 5 | 下流チャンネルでの実利用バージョン | git remote 接続不可、ローカル `.takt/runs/` には下流の情報なし |
| 6 | `pip-audit` 相当の CVE スキャン | 1 件ずつ精査する手段が限られ、本 Part の責務外 |

---

## 10. 推奨アクション（severity 付き、別 issue 化想定）

### 10.1 即時対応（P0 — 2026-05-25 までに）

| # | アクション | 対象 | コミット先 |
|---|---|---|---|
| 1 | Lyria 3 Interactions API 新スキーマ対応（`steps[*].content[*]` 読み取り） | `src/youtube_automation/utils/lyria_client.py:148-154` | 別 issue。応急処置として `Api-Revision: 2026-05-07` ヘッダ追加（`lyria_client.py:133-136`）で 2026-06-08 までは延命可能だが、本対応が必須 |

### 10.2 短期（P1 — Q3 2026 中）

| # | アクション | 対象 |
|---|---|---|
| 2 | `gemini-2.5-flash` → `gemini-3-flash-preview` 系へ移行 | `.claude/skills/{benchmark,video-analyze}/config.default.yaml`, `benchmark_collector.py:523` |
| 3 | `gemini-2.5-flash-lite` → `gemini-3.1-flash-lite` へ移行 | `populate_scene_phrases.py:33` |
| 4 | `pyproject.toml` に少なくとも `google-genai>=1.69,<2`, `google-auth-httplib2<1`, その他全 main 依存に `<X+1` 上限を追加 | `pyproject.toml:13-28` |
| 5 | `yt-skills sync --force` 必須運用を README / ONBOARDING.md に明示 | `ONBOARDING.md`, `README.md` |
| 6 | `google-auth-httplib2` の `transport` 移行計画を立てる（upstream deprecated 表明への追従） | discovery 用に検証 |

### 10.3 中期（P2）

| # | アクション | 対象 |
|---|---|---|
| 7 | SKILL.md に「外部サービス障害時の対応」セクションを 27 件の skill に追加 | 観点 6-2 表に列挙した 27 skill |
| 8 | `Workflow` dataclass + `_build_workflow` を撤去（メジャー bump 時） | `src/youtube_automation/utils/config/workflow.py`, `loader.py:266-271` |
| 9 | `[project.optional-dependencies] veo = []` を撤去 | `pyproject.toml:35` |
| 10 | `japanize-matplotlib` 撤去 / `matplotlib.font_manager` 経由の日本語フォント登録に置換 | `launch_curve_plotter.py`, `channel_trend.py`, `theme_performance.py` |
| 11 | `veo-3.1-lite-generate-preview` の公式 publisher model ID を Vertex AI Model Garden で確認、不一致なら skill 補正 | `.claude/skills/loop-video/config.default.yaml`, `SKILL.md` |
| 12 | CLAUDE.md L38 を「`utils/`, `agents/` shim は撤去済」に修正 | `CLAUDE.md` |

### 10.4 低（P3）

| # | アクション | 対象 |
|---|---|---|
| 13 | `audio_units.py` から `lyria-002` を削除 | `src/youtube_automation/utils/audio_units.py:16` |
| 14 | v1→v2 config 移行 CLI 撤去判断（migration 完了とみなす） | `pyproject.toml:48`, `loader.py:100-106` |
| 15 | ONBOARDING.md に各 CLI の最低バージョンを明示（`ffmpeg >= 4.4`, `op >= 2.0`, `gh >= 2.0`, `gcloud >= 480`） | `ONBOARDING.md:31-39` |
| 16 | `gemini_image:` namespace deprecation warning を撤去（実利用 0 件確認済） | `utils/image_provider/config.py:100-107` |
| 17 | `masterup`, `videoup` に `yt-dlp` / `ffmpeg` の `command -v` チェックを追加（または skill 側で前提宣言） | 各 skill / references shell |

---

## 11. Part A / Part B との非重複確認

本 Part が **触れていない** Part A/B の範囲:

| カテゴリ | 本 Part スコープ外 | 担当レポート |
|---|---|---|
| 失敗時リトライ / 部分生成物掃除 / `trap` / `set -e` | 蝶々で扱わない | `data-failure-recovery.md` (Part A) |
| 課金単価 / `cost_tracker` / dry-run / confirm prompt | 触れない | `data-billing-cost.md`, `data-billing-cost-control.md` (Part A) |
| シークレット直書き / `op://` 検出 / token scope grep | 触れない | `data-security-secrets.md` (Part B) |
| `StrictHostKeyChecking` / Terraform SSH host_key | 触れない（terraform に `host_key` 設定不在のみ言及）| `data-security-secrets.md` (Part B) |
| shell injection / `eval`, `subprocess shell=True` | 触れない | `data-security-secrets.md` (Part B) |

本 Part が **重複している** 箇所と説明:

| 項目 | 重複先 | 説明 |
|---|---|---|
| モデル名 deprecation 表 | `data-external-api-deprecation.md`, `data-deps-deprecated.md` | 既存 Part C 試行で重複生成された 2 ファイルと内容が重なる。本レポートは **計画指定の最終出力** として一本化、章番号体系を統一 |
| Python 依存 pin 表 | `data-dependencies.md` | 同上、本レポートに集約 |
| 後方互換 shim | `data-backward-compat-shims.md` | 同上、本レポートに集約 |

→ 既存 4 partial ファイル (`data-deps-deprecated.md` / `data-backward-compat-shims.md` / `data-external-api-deprecation.md` / `data-dependencies.md`) は本レポートの **詳細補足** として残存させる。analyze step では本 `data-dependencies-compat.md` を一次入力とし、必要時に partial ファイルへ参照を貼ること。

---

## 12. 未調査 skill リスト（カバレッジ確認）

35 skill のうち、SKILL.md 障害時ガイダンス監査は **全件カバー済み**（§7.1 表）。
外部 CLI 依存マトリクスは **主要 9 skill 群 + その他 26 件 = 全 35 件カバー済み**（§4.1 表）。
未調査 skill: **0 件**。
