# 観点 5: 依存・廃止 API・互換性 — 監査データ（再実行版）

調査日: 2026-05-18
担当: dig.part-c-deps-retry
対象リビジョン: HEAD（worktree `20260518T0905-372-issue-372-chore-skills-sukiru`）
前提: 前回試行 `dig.part-c-deps-deprecation` は `[ERROR] Claude CLI execution aborted` で中断。本レポートはその再実行であり、既出 3 本（`data-dependencies.md` / `data-external-api-deprecation.md` / `data-backward-compat-shims.md`）の検出結果を一本化したうえで、観点 5.5（skill 内 deprecated 記述）/ 5.6（外部 CLI ツール依存）/ 5.7（wheel drift）の独立検証分を補強している。

PR #367 で扱った観点 1（汎用化・設定切り出し）/ 観点 2（整合性）の既出指摘は再検出していない（参照箇所は注記のみ）。

---

## サマリー（severity 別）

| severity | 件数 | 内訳（1 行要約） |
|---|---|---|
| **P0** | 0 | （即時 prod 停止級の検出なし） |
| **P1** | 7 | Gemini 2.5 系 2 モデルが 2026-10-16 shutdown 予告 / `google-genai` メジャー遅延 / 全依存に version 上限なし / `google-auth-httplib2` deprecated / Suno 非公式依存 deprecation メモなし / skill バージョン追跡なし（`yt-skills sync --force` 不徹底で乖離） / `veo_generator` が ffmpeg 不在チェックなし |
| **P2** | 11 | Lyria 3 が `v1beta1` 直叩き / Veo lite が preview / `japanize-matplotlib` 4 年超停滞 / `Workflow` dataclass 空 dead shim / `uv.lock` 下流非伝播 / CLAUDE.md L.38 が実態と矛盾 / skill 配布の `--force` 運用未明示 / skill 12 件で `## 前提` 欠落 / `veo_generator.strip_audio`/`trim_tail` の ffmpeg 直叩きフォールバックなし / `_disabled` フラグの仕様が lyria 以外で文書化されず / OAuth scope の skill 側記述欠落 |
| **P3** | 5 | `requires-python>=3.11` 過剰制約の可能性 / dead extras `veo = []` / v1→v2 config 移行 CLI が v5.5.0 でも残存 / `lyria-002` が `audio_units._AUDIO_UNIT_BY_MODEL` に残置 / CLAUDE.md L.140 「旧 `get_channel_status` は廃止」の文言は配布 template 側 |

凡例: P0=即時障害、P1=数か月以内に対応必須、P2=リファクタ候補、P3=記述整備レベル。

---

## 観点 5.1: 廃止予定 API バージョン参照

### 5.1.1 Vertex AI Gemini モデル

| モデル / バージョン | 使用箇所 | 公式ステータス（2026-05-18） | shutdown |
|---|---|---|---|
| `gemini-2.5-flash` | `.claude/skills/video-analyze/config.default.yaml:7`, `.claude/skills/benchmark/config.default.yaml:23`, `src/youtube_automation/scripts/benchmark_collector.py:523` | **deprecated**（後継 `gemini-3-flash-preview`） | **2026-10-16 earliest（≒ 5 か月後）** |
| `gemini-2.5-flash-lite` | `src/youtube_automation/scripts/populate_scene_phrases.py:33`（`DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"`） | **deprecated**（後継 `gemini-3.1-flash-lite`） | **2026-10-16 earliest** |
| `gemini-3.1-flash-image-preview` | `src/youtube_automation/utils/image_provider/config.py:27`（`_DEFAULT_GEMINI_MODEL`）, `.claude/skills/thumbnail/config.default.yaml:18`, `.claude/skills/collection-ideate/SKILL.md:139` | preview / GA 移行情報未公開 | 未告知（preview 継続中） |

出典: `https://ai.google.dev/gemini-api/docs/deprecations`（2026-05-18 確認、既出レポート `data-external-api-deprecation.md:28-31` で取得済み）。

→ **P1**: 5 か月以内に `benchmark` / `video-analyze` / `wf-new`（`yt-populate-scene-phrases` 経由）の 3 スキル / CLI が後継モデルへ追従しないと sunset 当日にエラー化。skill 側の config.default.yaml も同時更新必要。

### 5.1.2 Vertex AI Veo モデル

| モデル | 使用箇所 | ステータス | 備考 |
|---|---|---|---|
| `veo-3.1-fast-generate-001` | `src/youtube_automation/utils/veo_generator.py:15`（`DEFAULT_MODEL`）, `.claude/skills/loop-video/config.default.yaml:8`, `.claude/skills/loop-video/SKILL.md:107,116` | **GA**（2025-11-17 promoted） | 現役 |
| `veo-3.1-generate-001` | `.claude/skills/loop-video/SKILL.md:116`（選択肢） | **GA** | 現役 |
| `veo-3.1-lite-generate-preview` | `.claude/skills/loop-video/SKILL.md:86,116`, `.claude/skills/loop-video/config.default.yaml:7` のコメント | **preview**（2026-04-02 導入） | **P2**: preview のまま運用すると静かに sunset される余地。SKILL.md に「preview のため将来変更あり」のメモなし |

出典: `https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes`（既出 `data-external-api-deprecation.md:33-35`）。

### 5.1.3 Vertex AI Lyria 3 モデル + endpoint

| モデル | 使用箇所 | ステータス |
|---|---|---|
| `lyria-3-pro-preview` | `src/youtube_automation/utils/audio_units.py:14`, `.claude/skills/lyria/config.default.yaml:17`, `.claude/skills/lyria/SKILL.md:60,85,94` | **preview**（GA 未告知） |
| `lyria-3-clip-preview` | `src/youtube_automation/utils/audio_units.py:15`, `.claude/skills/lyria/SKILL.md:85` | **preview** |
| `lyria-002` | `src/youtube_automation/utils/audio_units.py:16`（unit マッピングのみ、生成箇所なし） | レガシー / dead reference → **P3**（撤去候補） |

endpoint:

- `src/youtube_automation/utils/lyria_client.py:7,26`: `https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/global/interactions`
  - `v1beta1` を直叩き。docstring (`lyria_client.py:1-9`) に「google-genai SDK 1.71.0 時点で `interactions` 未対応のため `requests` で直接叩く」と理由明記
  - **P2**: Lyria 3 GA 化 / SDK 対応のいずれかが起きた瞬間に自前 `requests` 実装は破棄すべき。SKILL.md / 実装側に「いつ撤去するか」のトリガー記載なし

### 5.1.4 YouTube Data / Analytics / Reporting

| service / version | 箇所 | 廃止リスク |
|---|---|---|
| `youtube / v3` | `src/youtube_automation/utils/youtube_service.py:49`, `src/youtube_automation/auth/oauth_handler.py:239`, `src/youtube_automation/scripts/fetch_stream_key.py:114` | 公式 deprecation アナウンスなし。`commentThreads.markAsSpam` / `guideCategories` 等の廃止予告 endpoint 使用は 0 件確認 |
| `youtubeAnalytics / v2` | `src/youtube_automation/utils/youtube_service.py:57` | 廃止懸念なし |
| `youtubereporting / v1` | `src/youtube_automation/utils/youtube_service.py:65` | 廃止懸念なし |

主要 endpoint 30 件超を grep 確認し、廃止予告中の endpoint 使用は 0 件（出典: `data-external-api-deprecation.md:72-88`）。

### 5.1.5 OpenAI 画像 API

| モデル | 箇所 | ステータス |
|---|---|---|
| `gpt-image-2` | `src/youtube_automation/utils/image_provider/config.py:150`, `.claude/skills/thumbnail/config.default.yaml:89` | **GA**（2026-04-21）、現役 |
| `dall-e-2` / `dall-e-3` | コード内 0 件確認（grep） | API 削除済み（2026-05-12）だが影響なし |

`utils/cost_tracker.py` の `PRICING` テーブルは `gpt-image-2` / `gpt-image-1.5` / `gpt-image-1-mini` の 3 モデルを CHANGELOG (行 40-44) で追加済み。

### 5.1.6 Suno（非公式 / UI スクレイピング）

- `.claude/skills/masterup/SKILL.md:84,89`: `https://cdn1.suno.ai/{song_id}.mp3` を直接 `curl` でダウンロード
- `.claude/skills/masterup/SKILL.md:72-79` Step 2: WebFetch で `https://suno.com/playlist/xxx` HTML スクレイピング
- **公式 API なし**、CDN 永続性も不明（`SKILL.md:92` に注意書きあり）
- SKILL.md / 実装側に「いつ壊れる可能性があるか」のメモは **無し**

→ **P1**: 復旧手段ゼロのリスク。Suno UI 仕様変更や CDN 廃止が起きた瞬間に `/suno` `/masterup` チェーンが破綻する。代替プランを明文化していない。

### 5.1.7 Vultr API

- `infra/terraform/streaming/versions.tf:5-8`: `vultr/vultr` provider `>= 2.0`
- `src/youtube_automation/utils/streaming/vultr_bandwidth.py` で `/v2/instances/{id}/bandwidth` を直接呼び出し（`utils/streaming/vultr_bandwidth.py:1` の docstring）
- Vultr API v2 は現役、deprecation 告知は調査範囲では見つからず → 健全

---

## 観点 5.2: ライブラリ version pin / 最低バージョン要件

### 5.2.1 `[project.dependencies]`（出典: `pyproject.toml:13-28`）

全 14 依存に **`==` / `>=` / `~=` / `<` のいずれの制約も付与されていない**。

| パッケージ | uv.lock 解決 | PyPI latest (2026-05-18) | 遅延 | コメント |
|---|---|---|---|---|
| `google-api-python-client` | 2.193.0 | 2.196.0 | パッチ 3 | 健全 |
| `google-auth-oauthlib` | 1.3.0 | 1.4.0 | マイナー 1 | 健全 |
| `google-auth-httplib2` | 0.3.0 | 0.4.0（**deprecated 表明**） | パッチ | **P1**（5.4 で詳述） |
| `google-genai` | 1.69.0 | **2.4.0** | **メジャー 1** | **P1**: SDK 2.x で type 経路変更の可能性。直 import 箇所 6 件（`utils/genai_client.py:23`, `utils/veo_generator.py:36`, `utils/image_provider/gemini.py:36`, `utils/video_analyzer.py:27`, `scripts/video_analyze.py:29`, `scripts/benchmark_collector.py:538`） |
| `openai` | 2.33.0 | 2.37.0 | パッチ 4 | 健全 |
| `Pillow` | 12.1.1 | 12.2.0 | パッチ 1 | 健全 |
| `python-dotenv` | 1.2.2 | 1.2.2 | 同等 | 健全 |
| `pandas` | 3.0.1 | 3.0.3 | パッチ 2 | コードは 3.x 追従済み。下流環境次第で爆発 |
| `matplotlib` | 3.10.8 | 3.10.9 | パッチ 1 | 健全 |
| `japanize-matplotlib` | 1.1.3 | 1.1.3（2020-10-21、4 年超停滞） | 同等 | **P2**（5.5 で詳述） |
| `seaborn` | 0.13.2 | 0.13.2 | 同等 | 現役 |
| `schedule` | 1.2.2 | 1.2.2 | 同等 | 現役 |
| `pyyaml` | 6.0.3 | 6.0.3 | 同等 | 健全 |
| `requests` | 2.33.0 | 2.34.2 | パッチ 1 | 健全 |

→ **P1（全体）**: `pyproject.toml` の依存に上限指定が無いため、下流チャンネル側で `uv add git+...` した際に **同日に release された破壊的アップデートが当たる**。`uv.lock` をリポに commit していても、下流の `uv.lock` には伝播しない（5.7.4 参照）。

### 5.2.2 `[project.optional-dependencies]`（出典: `pyproject.toml:33-35`）

```toml
dev = ["pytest", "ruff"]
veo = []  # google-genai, Pillow moved to main dependencies
```

`veo = []` は空の extras。`pip install 'youtube-channels-automation[veo]'` を打っても何もインストールされない **dead extras**（→ **P3**）。

### 5.2.3 hard pin（`==`）の有無

`==` による hard pin は 0 件。security update を取れない過剰 pin は無い（健全方向）。ただし 5.2.1 の上限不在とトレードオフ。

### 5.2.4 推奨される上限制約候補

- `google-genai`: メジャー乖離（1.69 → 2.4）。SDK 2.x で `types.GenerateVideosConfig` / `types.Image.from_file` の path 変更可能性あり。当面 `google-genai>=1.60,<2` を推奨
- `pandas`: コードは 3.x 解決済みだが、下流で 2.x ↔ 3.x が混在すると `DataFrame.append` 等で破綻するため `pandas>=3,<4` 推奨
- `Pillow`: メジャーリリース直前なら `<13` を切る

---

## 観点 5.3: Python バージョン制約

### 5.3.1 宣言の整合性

3 箇所で 3.11 一致:

- `pyproject.toml:9`: `requires-python = ">=3.11"`
- `pyproject.toml:107`: `[tool.ruff] target-version = "py311"`
- `.python-version:1`: `3.11`
- `uv.lock:3`: `requires-python = ">=3.11"`

→ 整合性 OK。

### 5.3.2 実 syntax との突合せ（過剰制約の可能性）

- `from __future__ import annotations` 使用ファイル: 88 件（前回計測、`data-dependencies.md:135`）— 3.10 互換性を残す形
- `match` / `case` (3.10+): 0 件
- `typing.Self` / `typing.override` (3.11+ / 3.12+): 0 件
- 旧式 `Dict` / `List` / `Optional` from `typing`: 残存（`src/youtube_automation/agents/youtube_auto_uploader.py:20` 等）

→ **P3**: 実 syntax は 3.10 互換レベル。`requires-python = ">=3.11"` は過剰制約の可能性。ただし transitive 依存（`pandas` 3.x が py3.10 を切っている可能性）の確認なしに緩めるのは危険なので、現状維持が妥当。

---

## 観点 5.4: 後方互換 shim ドリフト

### 5.4.1 CLAUDE.md の宣言 vs 実態

`CLAUDE.md:38` (project instructions):

> - `utils/`, `agents/`, `auth/`, `scripts/` — submodule 利用者向け **後方互換 shim**（新規開発は `src/youtube_automation/` 側で行う）

実態（`ls -la /` で確認、`data-backward-compat-shims.md:18-24` で再現済み）:

| ディレクトリ | 存在 | 中身 | 性質 |
|---|---|---|---|
| `utils/` | **不在** | — | CLAUDE.md L.38 の記述が obsolete |
| `agents/` | **不在** | — | 同上 |
| `auth/` | 存在 | `SETUP.md`, `client_secrets_template.json` の 2 ファイルのみ | shim ではなく template + ドキュメント |
| `scripts/` | 存在 | `gcp-bootstrap.sh`, `gcp-terraform-apply.sh` の 2 シェル | Python shim ではなく共通シェル |

`CLAUDE.md:100`（同一ファイル）には:

> - ルート直下の `scripts/` にはシェルスクリプト（`.sh`）のみ配置。Python shim は廃止済み

→ **CLAUDE.md 内部で矛盾**。L.38 が古い記述、L.100 が現状を反映。Python shim として残っているのは **0 個**。

→ **P2（docs）**: CLAUDE.md L.38 を「`auth/`（template 配布用） / `scripts/`（共通 .sh 配布用）」に書き換え、`utils/` / `agents/` への言及を削除すべき。

### 5.4.2 `google-auth-httplib2` の deprecated 表明

PyPI `google-auth-httplib2 0.4.0` (2026-05-07 リリース) ページ:

> "this library is no longer maintained. For any new usages please see provided transport layers by google-auth library."

直 import 0 件確認（`grep "google_auth_httplib2" src/` で空）。`googleapiclient.discovery.build` の内部依存。

→ **P1**: 即時撤去不可だが新規 import 禁止 + Google 公式の移行ガイド追跡が必要。CHANGELOG / docs 側に「googleapiclient 依存のため当面残置」のメモを追加すべき。

### 5.4.3 v1→v2 設定移行 CLI の残存

- `pyproject.toml:48`: v1→v2 config 移行 CLI の entry point
- `src/youtube_automation/utils/config/loader.py:100-106`: 旧 `channel_config.json` は ConfigError で fail-fast
- 現在のバージョン: v5.5.0（`pyproject.toml:7`、3 メジャーバージョン経過）

→ **P3**: 移行未完了の下流の存在は外部観測不可。loader が hard fail するので「移行せずに使う」運用は実質不可能。撤去判断は CHANGELOG / 配布実績の追跡が前提。

### 5.4.4 `Workflow` dataclass の dead shim

- `src/youtube_automation/utils/config/workflow.py:8-15`: 空の dataclass（フィールド 0 個）
- `src/youtube_automation/utils/config/loader.py:266-271`: `_build_workflow` は無条件で空 `Workflow()` を返す（downstream の `workflow.json` 内の `workflow` / `post_upload` / `short` / `community` キーは無視）
- `CHANGELOG.md:500`: 「`config/channel/workflow.json` の `post_upload` / `short` / `community` キーは削除しなくても loader は素通しする」と明示

→ **P2**: 動作影響なし。`Workflow` フィールド自体を `ChannelConfig` から落とすにはメジャーバージョン更新が必要。

### 5.4.5 `lyria-002` の dead reference

- `src/youtube_automation/utils/audio_units.py:16`: `"lyria-002": "30sec"` を unit マップに残置
- `tests/test_generate_music_unit_resolver.py:9,25`: テスト側でも検証中
- ただし**生成側で `lyria-002` を呼ぶ箇所は 0 件**（grep 確認）— 古い cost_tracker ログを読むための互換マッピングのみ

→ **P3**: 完全 dead でなく旧ログ読み出し互換目的。コメントで意図を残せばよい。

---

## 観点 5.5: skill 内 deprecated 記述・撤廃済み機能の残存参照

### 5.5.1 撤廃済み機能への明示的言及（健全側）

- `.claude/skills/collection-ideate/SKILL.md:114`: 「Issue #132 以降、ハードコード単価表は撤廃済み」と明示。コード側 (`src/youtube_automation/utils/cost_tracker.py:9,22,104`) と整合
- `.claude/skills/channel-setup/references/claude-md-template.md:140`: 「旧 `get_channel_status` は廃止」と明示。`pyproject.toml:45` で `yt-channel-status = "youtube_automation.scripts.get_channel_status:main"` として entry point 化済み（モジュール path として `get_channel_status` は残るが CLI 呼び出しは `yt-channel-status` に統一）→ template の文言は健全

### 5.5.2 整合性のずれが残る記述

- `.claude/skills/wf-new/references/schema.md:124-128`「旧スキーマ互換」: `workflow-state.json` の `steps` キーが存在する場合の旧/新スキーマ判別ロジック。`/wf-status` 側に依存している記述だが、`/wf-status/SKILL.md` 内に対応するロジック説明が無い（旧スキーマの「読み取り専用扱い」運用がどこに実装されているか不明）→ **P2**: docs ↔ 実装の trace が切れている

### 5.5.3 「廃止予定」「TODO: remove」「将来削除」検索結果

`grep -rnE "廃止|deprecated|TODO:\s*remove|将来削除|撤廃|撤去|obsolete|sunset|EOL"` の skill 配下ヒット 4 件:

| file:line | 内容 | 判定 |
|---|---|---|
| `.claude/skills/collection-ideate/SKILL.md:114` | 「Issue #132 以降、ハードコード単価表は撤廃済み」 | 健全（コード反映済み） |
| `.claude/skills/channel-setup/references/claude-md-template.md:140` | 「旧 `get_channel_status` は廃止」 | 健全（template 注釈） |
| `.claude/skills/wf-new/references/schema.md:124` | 「旧スキーマ互換」 | **P2**（trace 切れ） |
| `.claude/skills/streaming/references/notify.sh:34` | 「Issue #166 / #174」（SSRF 防御の参照） | 健全（実装側 `utils/notification.py:1,9` と整合） |

### 5.5.4 preview 状態の API モデルに対する将来リスクメモ

| skill | preview モデルへの言及 | 「いつ壊れる可能性があるか」のメモ |
|---|---|---|
| `.claude/skills/lyria/SKILL.md:85` | `lyria-3-pro-preview` / `lyria-3-clip-preview` | **メモなし**（GA 移行時の endpoint 変更注意なし） |
| `.claude/skills/loop-video/SKILL.md:86,116` | `veo-3.1-lite-generate-preview` | **メモなし**（preview のまま運用するリスク注意なし） |
| `.claude/skills/thumbnail/config.default.yaml:18` | `gemini-3.1-flash-image-preview` | **メモなし** |
| `.claude/skills/masterup/SKILL.md:84,92` | Suno CDN 直叩き | 「CDN URL は public だが永続性は不明」のみ。仕様変更時の代替プランなし |

→ **P2**: 4 skill に「preview / 非公式依存 → 将来 breaking change の可能性」のメモを 1-2 行入れるべき。

### 5.5.5 `_disabled` フラグの仕様文書化

- `.claude/skills/lyria/config.default.yaml:11-12`: `_disabled: false` を default 値で配布
- `.claude/skills/lyria/SKILL.md:17,59,101-102`: `_disabled: true` の場合 `/suno` を案内して終了する仕様を明示

しかし他の skill の `config.default.yaml` 9 件（benchmark / collection-ideate / loop-video / masterup / suno / thumbnail / video-analyze / video-description）に `_disabled:` は記載なし。**lyria だけが特殊扱い**だが、その由来（なぜ lyria だけ on/off 切替が必要か）が docs に書かれていない。

→ **P2**: `_disabled` パターンが lyria 専用の慣習か / 他 skill にも展開予定かを SKILL.md か共通 references に明文化すべき。

### 5.5.6 撤廃済み機能の `_skills/` への巻き戻り

CHANGELOG（v4.0.0）で `wf-next/references/community_draft.py` / `post_upload_actions.py`（symlink）/ `wf-new/references/schema.md` の `community` フィールド定義などが撤去済みとされる（`data-backward-compat-shims.md:163-166`）。

現在の `.claude/skills/wf-new/references/schema.md` を確認（5.5.2 で抜粋）したところ「community」「post_upload」「short」関連の記述は **見つからず**、撤去は完了。skill 同梱物としては clean。

---

## 観点 5.6: 外部 CLI ツール依存

### 5.6.1 各 skill が前提とする外部バイナリ

| skill | 必要バイナリ | SKILL.md / references の宣言 | `command -v` チェック | フォールバック |
|---|---|---|---|---|
| `streaming` | `terraform >= 1.5`, `op`, `ssh-keygen`, `ssh-add`, `realpath`, `curl`, `ffmpeg`（VPS 側） | `SKILL.md:14` で `terraform`/`uv`/`op` 明示。**`ssh-keygen` / `ssh-add` は SKILL.md 文面に無く `swap_video.sh` のみ** | `references/swap_video.sh:61,65,69,73` で 4 件チェック | エラー文言で `brew install coreutils` / `openssh-client 導入` 明記。**P0 級ガードあり** |
| `channel-setup` | `gcloud`, `terraform`, `jq` | `references/gcp-bootstrap.md` / `gcp-bootstrap.sh` で gcloud 明示 | `references/gcp-bootstrap.sh:107` で gcloud / `gcp-terraform-apply.sh:37,41` で terraform/jq | 公式インストール URL 明記。**良好** |
| `videoup` | `ffmpeg`, `ffprobe`, `afinfo`（macOS、optional） | **SKILL.md に `## 前提` セクションなし**（SKILL.md:1-65 全文確認） | `references/generate_videos.sh:79,95` で ffmpeg / afinfo | ffmpeg なし時は `ERROR: ffmpeg not found` で exit 1 |
| `masterup` | `curl`, `rsync`, `ffmpeg`（CLI 経由） | `SKILL.md:63-64` の「前提条件」は WebFetch のみ。**ffmpeg / rsync の宣言なし** | なし（CLI 側 `src/youtube_automation/scripts/generate_master.py:174` で `shutil.which("ffmpeg")` チェック） | CLI 側はあり、shell ステップ側はなし |
| `lyria` | `gcloud`（ADC）, `ffmpeg`（`generate_lyria_master.py:94` で subprocess 直叩き） | `SKILL.md:18` で `gcloud auth application-default login` 明示。**ffmpeg の宣言なし** | なし（直接 `subprocess.run(["ffmpeg", ...])`） | ffmpeg 不在時は `FileNotFoundError` で opaque 失敗 |
| `loop-video` | `gcloud`（ADC）, `ffmpeg`（`--smooth` 時） | `SKILL.md:49` で gcloud 明示。`SKILL.md:32` で「FFmpeg クロスフェード補正」言及 | なし（`utils/veo_generator.py:122,161,241` で `subprocess.run(["ffmpeg", ...])` 直叩き、shutil.which 検査なし） | **P1**: ffmpeg 不在時に opaque `FileNotFoundError`。ガード追加すべき |
| `video-analyze` | `gcloud`（ADC） | `SKILL.md:21` で明示 | なし | 健全 |
| `suno` | （Suno UI 操作、ローカルバイナリなし） | SKILL.md に `## 前提` なし | — | — |
| `channel-new` | `gh`, `uv` | `SKILL.md:47-51` でコマンド使用。**`gh` の宣言は無し** | なし | `gh` 不在時 `command not found` で fail |
| `channel-import` | `gh`, `uv` | `SKILL.md:21` でコマンド使用 | なし | 同上 |
| その他 24 skill | `uv`（暗黙必須）以外なし | — | — | — |

### 5.6.2 個別検出 P1 級

- **`src/youtube_automation/utils/veo_generator.py:122,161,241`**: `ffmpeg` を `subprocess.run(check=True)` で直叩きしているが、`shutil.which("ffmpeg")` 検査なし。`generate_master.py:174` / `finalize_master.py:230` は適切に検査しているのに、Veo 系だけ抜け。`loop-video` skill 経由で発覚する。→ **P1**（修正は別タスク）

### 5.6.3 SKILL.md `## 前提` セクション欠落 12 件

`grep -L '^前提\|^## 前提\|^### 前提' .claude/skills/*/SKILL.md` の結果:

```
channel-direction, channel-import, channel-new, channel-research, channel-setup,
discover-competitors, live-clean, metadata-audit, suno, thumbnail-compare,
videoup, viewer-voice
```

うち以下は **実際に外部依存があるのに `## 前提` が無い**:

| skill | 不在の理由（推測） | 必要な記述 |
|---|---|---|
| `channel-new` | フロー説明に組み込まれている | `gh`, `uv` |
| `channel-import` | 同上 | `gh`, `uv` |
| `channel-setup` | references 側で記述 | `gcloud`, `terraform`, `jq` |
| `videoup` | references 側で記述 | `ffmpeg`, `ffprobe` |
| `suno` | ローカルバイナリなしのため不要 | （該当なし） |
| `metadata-audit` | `uv` のみ | （該当なし） |

→ **P2**: 4 skill（`channel-new` / `channel-import` / `channel-setup` / `videoup`）は SKILL.md トップに `## 前提` を追加すべき。

### 5.6.4 「このツールが誰の責任で入るか」の記述

- `.claude/skills/streaming/references/swap_video.sh:66`: `realpath` 不在時 "macOS なら brew install coreutils" を明示 → 良好
- `.claude/skills/channel-setup/references/gcp-bootstrap.sh:108`: gcloud 不在時 `https://cloud.google.com/sdk/docs/install` を明示 → 良好
- 他の skill には dotfiles / nix / brew / uv / pip いずれの責任で入るかの記述なし

→ **P2**: SKILL.md 内に「環境前提（macOS dotfiles / 各 OS パッケージ）」セクションを共通で持つことを検討。

---

## 観点 5.7: wheel 配布アセット drift

### 5.7.1 `[tool.hatch.build.targets.wheel.force-include]` の整合

出典: `pyproject.toml:82-88`

```toml
[tool.hatch.build.targets.wheel.force-include]
".claude/skills" = "youtube_automation/_skills"
".claude/CLAUDE.template.md" = "youtube_automation/_claude_md/CLAUDE.template.md"
```

実体確認:

- `.claude/skills/`: 存在、35 サブディレクトリ（`find -maxdepth 1 -type d` で 36、parent 除外）
- `.claude/CLAUDE.template.md`: 存在、12,119 bytes（`ls -la` 確認）

→ force-include の指定先と実体ファイルは整合。

### 5.7.2 `[tool.hatch.build.targets.sdist] include`（出典: `pyproject.toml:92-104`）

```toml
include = [
    "src/",
    "tests/",
    ".claude/skills/",
    ".claude/CLAUDE.template.md",
    "scripts/",
    "auth/SETUP.md",
    "auth/client_secrets_template.json",
    "README.md",
    "LICENSE",
    "pyproject.toml",
]
```

sdist には `auth/SETUP.md` / `auth/client_secrets_template.json` も含まれるが、**wheel の `force-include` には auth/ 配布の指定がない**。

| パス | sdist | wheel | 用途 |
|---|---|---|---|
| `.claude/skills/` | ✓ | ✓（`_skills/` として） | yt-skills sync で配布 |
| `.claude/CLAUDE.template.md` | ✓ | ✓（`_claude_md/` として） | yt-skills sync --asset claude-md |
| `auth/SETUP.md` | ✓ | ✗ | 下流は手動参照前提か |
| `auth/client_secrets_template.json` | ✓ | ✗ | 同上 |
| `scripts/` | ✓ | ✗ | 共通 .sh は wheel 同梱外 |

→ **P2**: `auth/` ディレクトリの取扱いが sdist / wheel で非対称。`yt-skills sync --asset auth-template` のような専用 asset entry を追加するか、現状の運用（下流が template を git submodule 等で参照）を SKILL.md に明文化するか整理が必要。なお `src/youtube_automation/auth/oauth_handler.py:99-102` は **下流側** の `<channel_dir>/auth/` / `<channel_dir>/automation/auth/` を検索しており、wheel 内の auth は前提にしていない（互換性問題ではない）。

### 5.7.3 `_skills/` / `_claude_md/` の参照ロジック

出典: `src/youtube_automation/cli/skills_sync.py:27,40,47,71-89`

```python
from importlib.resources import as_file, files
...
resource = files("youtube_automation").joinpath(spec["resource_name"])
with as_file(resource) as p:
    path = Path(p)
    if path.exists():
        return path
```

`_ASSET_SPECS` (`skills_sync.py:37-53`) で `_skills` / `_claude_md` の 2 entry が登録され、未登録 asset には KeyError を返す。実装は健全。

開発時 fallback (`skills_sync.py:82`) で repo root 直下の `<source_subdir>` を見るため、ローカルテストでも動作する設計。

### 5.7.4 下流アップデート時の drift

- `yt-skills sync` のデフォルトは `force=False`（`skills_sync.py:114-115` 相当、`--force` を明示しないと skipped）
- `skills_sync.py:194,228` に「(skipped を上書きするには --force を指定してください)」メッセージを表示
- ただし `README.md` / `ONBOARDING.md` / 各 SKILL.md に「upgrade 時に `yt-skills sync --force` を実行」と明示する記述は **見つからず**

→ **P1**: skill ファイルだけ古いまま、ランタイム（`google-genai` 等の依存）は最新を引く乖離リスク。`pyproject.toml` の依存にも上限なし（5.2 参照）のため、両側で予期しない breaking 当たりが発生しうる。下流アップデート手順を `README.md` 等に明示すべき。

### 5.7.5 skill 単独バージョンの不在

各 skill ディレクトリには独立した version 表記が**無い**:

- `grep "^version:" .claude/skills/**/SKILL.md` で 0 件（既出 `data-backward-compat-shims.md:218`）
- skill 単体のバージョンは `pyproject.toml::version` のみがソース

→ **P1**: skill renaming（`analyze` → `analytics-analyze` 等、`CHANGELOG.md:154` 既出）のような破壊的変更があったとき、下流が古い skill ファイルを保持しているか検出する手段がない。

### 5.7.6 `_disabled` flag を持つ config と yt-skills sync の挙動

`.claude/skills/lyria/config.default.yaml:12` の `_disabled: false` が初期値として配布される。下流が `config/skills/lyria.yaml` で deep-merge 上書きする運用 (`SKILL.md:20`)。

→ `yt-skills sync` でファイル名は配布されるが、下流の上書き内容は触らない。健全だが、`_disabled` が他 skill にも展開された場合の挙動仕様が未文書化（5.5.5 と重複）。

---

## 35 skill × 外部 API / バイナリ依存マトリクス

凡例: ✓=直接依存 / ○=`uv run yt-*` 経由 / ▲=Optional / —=無し

| # | skill | Gemini | Veo | Lyria | OpenAI | YouTube API | Vultr | Suno | ffmpeg | gcloud | terraform | gh | op | rsync | 課金 API |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | alignment-check | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 2 | analytics-analyze | — | — | — | — | ○ | — | — | — | — | — | — | — | — | — |
| 3 | analytics-collect | — | — | — | — | ○ | — | — | — | — | — | — | — | — | YouTube Data quota |
| 4 | analytics-report | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 5 | audience-persona | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 6 | benchmark | ✓ `gemini-2.5-flash` | — | — | — | ○ | — | — | — | ✓ ADC | — | — | — | — | **Gemini + YouTube quota** |
| 7 | channel-direction | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 8 | channel-import | — | — | — | — | ○ | — | — | — | — | — | ✓ | — | — | — |
| 9 | channel-new | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — |
| 10 | channel-research | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 11 | channel-setup | — | — | — | — | — | — | — | — | ✓ | ✓ | — | — | — | — |
| 12 | channel-status | — | — | — | — | ○ | — | — | — | — | — | — | — | — | YouTube quota |
| 13 | collection-ideate | ▲（image preview） | — | — | ▲（image preview） | ○ | — | — | — | ▲ ADC | — | — | — | — | **画像 ×3 / preview** |
| 14 | comments-reply | — | — | — | — | ○ | — | — | — | — | — | — | — | — | YouTube quota |
| 15 | discover-competitors | — | — | — | — | ○ | — | — | — | — | — | — | — | — | YouTube `search.list` 100 unit |
| 16 | live-clean | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 17 | loop-video | — | ✓ `veo-3.1-fast-generate-001` | — | — | — | — | — | ✓ (`--smooth`) | ✓ ADC | — | — | — | — | **Veo per-second** |
| 18 | lyria | — | — | ✓ `lyria-3-pro-preview` | — | — | — | — | ✓ (CLI 経由) | ✓ ADC | — | — | — | — | **Lyria per-song** |
| 19 | masterup | — | — | — | — | — | — | ✓ CDN | ✓ (CLI 経由) | — | — | — | — | ✓ | （Suno UI は別課金） |
| 20 | metadata-audit | — | — | — | — | ○ | — | — | — | — | — | — | — | — | — |
| 21 | playlist | — | — | — | — | ○ | — | — | — | — | — | — | — | — | YouTube quota |
| 22 | postmortem | — | — | — | — | ○ | — | — | — | — | — | — | — | — | — |
| 23 | streaming | — | — | — | — | ○（archive） | ✓ | — | （VPS 側） | — | ✓ | — | ✓ | — | **Vultr 時間課金** |
| 24 | suno | — | — | — | — | — | — | （UI 操作のみ） | — | — | — | — | — | — | — |
| 25 | thumbnail | ✓ `gemini-3.1-flash-image-preview` | — | — | ✓ `gpt-image-2` | — | — | — | — | ▲ ADC | — | — | — | — | **画像 per-image** |
| 26 | thumbnail-compare | — | — | — | — | — | — | — | ✓ (`scripts/compare_thumbnails.py:73`) | — | — | — | — | — | — |
| 27 | video-analyze | ✓ `gemini-2.5-flash` | — | — | — | — | — | — | — | ✓ ADC | — | — | — | — | **Gemini per-token** |
| 28 | video-description | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 29 | video-upload | — | — | — | — | ○ | — | — | — | — | — | — | — | — | YouTube quota |
| 30 | videoup | — | — | — | — | — | — | — | ✓ | — | — | — | — | — | — |
| 31 | viewer-voice | — | — | — | — | ○ | — | — | — | — | — | — | — | — | YouTube quota |
| 32 | viewing-scene | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 33 | wf-new | ▲ `gemini-2.5-flash`（scene_phrases） | — | — | — | — | — | — | — | ▲ ADC | — | — | — | — | Gemini per-token |
| 34 | wf-next | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 35 | wf-status | — | — | — | — | — | — | — | — | — | — | — | — | — | — |

合計依存件数:

- **Gemini 依存**: 5 skill（benchmark, collection-ideate, thumbnail, video-analyze, wf-new）→ うち 3 件（benchmark / video-analyze / wf-new）が `gemini-2.5-flash[-lite]` を使用 → **2026-10-16 shutdown 直撃**
- **Veo 依存**: 1 skill（loop-video）
- **Lyria 依存**: 1 skill（lyria）
- **OpenAI 依存**: 2 skill（collection-ideate, thumbnail）
- **YouTube Data quota 重課金**: discover-competitors（`search.list` 100 unit/呼び出し）
- **VPS 課金（Vultr）**: streaming のみ
- **Suno（非公式）**: 2 skill（masterup, suno）

---

## 注意点 / リスク

1. **2026-10-16 の Gemini 2.5 shutdown**は 5 か月の猶予しかない。`benchmark` / `video-analyze` / `wf-new` の config.default.yaml 3 ファイル + 実装 1 か所（`scripts/populate_scene_phrases.py:33`）を後継モデルに置き換える必要あり
2. **`google-genai` のメジャー乖離（1.69 → 2.4）** は SDK 2.x の breaking change 影響範囲が未調査。本リポジトリは 6 ファイルで直 import している（5.2.1 表で列挙）
3. **依存に version 上限なし + 下流 lock 非伝播** の組み合わせは「下流が `uv add` した日次のタイミング次第で動作が変わる」状態。CI 上の re-lock が無い限り、本リポジトリで test が green でも下流環境で破綻しうる
4. **Suno 非公式依存** は復旧手段ゼロ。`/suno` `/masterup` チェーンは Suno UI / CDN 仕様変更で即停止する。代替プラン（Lyria への切り替えガイド等）の事前準備が必要
5. **wheel 配布の `force=False` デフォルト** で「skill ファイルだけ古い」乖離が下流で発生しうる。skill 内に「依存パッケージ X.Y.Z 以上を想定」のような contract が無い

---

## 調査できなかった項目

| 項目 | 理由 |
|---|---|
| 下流チャンネルでの実利用バージョン | 外部リポジトリ閲覧不可（git remote 接続なし） |
| Vertex AI Lyria 3 の GA 化時期 | 公開情報なし。`https://docs.cloud.google.com/vertex-ai/generative-ai/docs/music/generate-music` に明示なし |
| Suno UI / CDN の廃止スケジュール | Suno 側に SLA / 公開廃止スケジュールなし |
| `google-genai` 1.69 → 2.x の breaking change 一覧 | リリースノート全件追跡は本タスクスコープ外。SDK 直 import 6 ファイルの動作影響は別途検証必要 |
| `pandas` 3.x が py3.10 / 3.11 のサポート範囲 | uv.lock の transitive 解決が py3.11 で安定している事実のみ確認。下限緩和検証は別タスク |

---

## 推奨アクション

| # | 観点 | severity | アクション | 想定工数 |
|---|---|---|---|---|
| R-01 | 5.1 | **P1** | `gemini-2.5-flash[-lite]` を後継モデル（`gemini-3-flash-preview` / `gemini-3.1-flash-lite`）に差し替え。`.claude/skills/{benchmark,video-analyze}/config.default.yaml` 2 件 + `src/youtube_automation/scripts/{benchmark_collector.py:523,populate_scene_phrases.py:33}` 2 件 + `scene_phrases.md:26,41` の docs を一斉更新 | 0.5d |
| R-02 | 5.2 | **P1** | `pyproject.toml` の dependencies に上限制約を追加。最低限 `google-genai>=1.60,<2`, `pandas>=3,<4`, `Pillow>=12,<13` の 3 件 | 0.25d |
| R-03 | 5.4 | **P1** | `CLAUDE.md:38` の「`utils/`, `agents/`, `auth/`, `scripts/` — submodule 利用者向け 後方互換 shim」を実態（`auth/` template、`scripts/` 共通 .sh）に合わせて書き換え。L.100 と矛盾解消 | 0.1d |
| R-04 | 5.4 | **P1** | `google-auth-httplib2` の deprecated 表明を CHANGELOG / docs に追記し、新規 import 禁止ルールを CLAUDE.md に明示 | 0.1d |
| R-05 | 5.6 | **P1** | `src/youtube_automation/utils/veo_generator.py:122,161,241` の ffmpeg 直叩きに `shutil.which("ffmpeg")` ガードを追加（`generate_master.py:174` と同パターン） | 0.25d |
| R-06 | 5.7 | **P1** | `README.md` / `ONBOARDING.md` に「upgrade 時は `uv run yt-skills sync --force` を実行」を明記。下流ドリフト防止 | 0.1d |
| R-07 | 5.7 | **P1** | skill にバージョン追跡を導入（SKILL.md frontmatter に `version:` を追加 or `_skills/VERSION` を同梱）。下流が古い skill を保持しているか検出可能にする | 0.5d |
| R-08 | 5.1 | **P1** | `.claude/skills/masterup/SKILL.md` / `.claude/skills/suno/SKILL.md` に「Suno UI 仕様変更時の代替プラン」セクションを追加（Lyria への切替手順 / fallback 提示） | 0.25d |
| R-09 | 5.1 | P2 | `.claude/skills/lyria/SKILL.md` に「`v1beta1` 直叩きは Lyria 3 GA 化 + google-genai SDK 対応で撤去予定」のメモを追加 | 0.1d |
| R-10 | 5.1 | P2 | `.claude/skills/{loop-video,thumbnail}/config.default.yaml` の preview モデル指定に「preview のため将来変更あり」のコメントを追加 | 0.1d |
| R-11 | 5.4 | P2 | `Workflow` dataclass / `_build_workflow` を次期メジャーバージョンで完全撤去。`ChannelConfig.workflow` フィールドを削除し、空 dataclass の依存を断つ | 0.5d |
| R-12 | 5.5 | P2 | `.claude/skills/wf-new/references/schema.md:124-128`「旧スキーマ互換」の実装側 trace を `/wf-status/SKILL.md` に追記（どこに旧スキーマ判別ロジックがあるか明示） | 0.1d |
| R-13 | 5.6 | P2 | `.claude/skills/{channel-new,channel-import,channel-setup,videoup}/SKILL.md` に `## 前提` セクションを追加（`gh`, `gcloud`, `terraform`, `jq`, `ffmpeg` 等の必要バイナリ宣言） | 0.5d |
| R-14 | 5.5 | P2 | `_disabled` フラグの仕様（lyria 専用慣習 / 共通展開の有無）を `.claude/skills/lyria/SKILL.md` または共通 reference に明文化 | 0.1d |
| R-15 | 5.7 | P2 | `auth/SETUP.md` / `auth/client_secrets_template.json` の wheel 配布方針を整理（sdist のみ / `yt-skills sync --asset auth-template` 専用 entry 追加のいずれか） | 0.25d |
| R-16 | 5.2 | P2 | `japanize-matplotlib` を `matplotlib.font_manager` 直接登録に置き換え、停滞ライブラリ依存を断つ | 1.0d |
| R-17 | 5.2 | P2 | `uv.lock` を下流に伝播させる手段（git submodule with lockfile / `pip install --constraint`）を `README.md` で案内 | 0.25d |
| R-18 | 5.4 | P3 | `pyproject.toml:35` の `veo = []` dead extras を削除（または何かに使う） | 0.05d |
| R-19 | 5.3 | P3 | `requires-python` 緩和を検討する場合は transitive 解決を py3.10 でも試す。緩和不要なら現状維持 | 0.25d |
| R-20 | 5.4 | P3 | v1→v2 config 移行 CLI の撤去判断。次期メジャー（v6）で削除候補とし CHANGELOG にアナウンスを 1 リリース前に出す | 0.1d |
| R-21 | 5.4 | P3 | `src/youtube_automation/utils/audio_units.py:16` の `"lyria-002": "30sec"` は「旧ログ読み出し互換のため残置」のコメントを追加 | 0.05d |
| R-22 | 5.1 | P3 | `lyria-3-pro-preview` を `_AUDIO_UNIT_BY_MODEL` のキーとして固定しているのは preview 表記ごと変わるリスクあり。GA 化後に名称変更が来た場合のための fallback ロジック追加検討 | 0.25d |

合計想定工数（P1 のみ）: **2.05 日**

---

## PR #367 既出指摘との重複回避メモ

PR #367 (`docs/audits/2026-05-18-skills-generalization-consistency.md`) は観点 1（汎用化・設定切り出し）/ 観点 2（整合性）を扱った。本レポートでは以下の境界を維持:

- **ハードコード値の汎用化**（観点 1.1〜1.4）: 再検出しない。本レポートで挙げた `gemini-2.5-flash` 等のモデル ID 直書きは「廃止予定 API への参照」観点 5.1 として扱い、汎用化観点としては触れない
- **description ↔ 実装の乖離**（観点 2.1〜2.4）: 再検出しない。観点 5.5.2 の「旧スキーマ互換 trace 切れ」は「撤廃済み機能の残存参照」観点 5.5 として扱い、整合性監査ではなく依存・廃止リスク観点で記述
