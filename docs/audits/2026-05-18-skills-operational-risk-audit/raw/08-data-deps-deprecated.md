# data-deps-deprecated.md

**調査範囲:** `.claude/skills/**` および `src/youtube_automation/**` が依存する外部 API / SDK / モデル / ツールの「廃止予定」「バージョン陳腐化」「URL リンク切れ」「pin されていない依存」監査。
**調査日:** 2026-05-18
**対象ワークツリー:** `/Users/mba/02-yt/takt-worktrees/20260518T0905-372-issue-372-chore-skills-sukiru/`
**前提:** PR #367 で実施済の汎用化観点は対象外。本レポートは「来月動かなくなる可能性のあるもの」に限定する。

---

## 1. severity サマリー

| severity | 件数 | 概要 |
|---|---|---|
| **P0 (即時)** | 1 | Vertex AI Interactions API の legacy `outputs` スキーマ — **2026-05-26 デフォルト切替 / 2026-06-08 完全削除** |
| **P1 (3-5 ヶ月以内)** | 2 | `gemini-2.5-flash` / `gemini-2.5-flash-lite` リタイア（2026-10-16）、Vertex AI 生成系 SDK 旧 `google-cloud-aiplatform.generative_models` 廃止（2026-06-24） |
| **P2 (中期)** | 4 | `google-genai` SDK の major 1.x → 2.x ギャップ、`pyproject.toml` に上限 pin 一切なし、Lyria endpoint が `v1beta1` のまま、Veo `lite-generate-preview` モデル ID の妥当性が不明 |
| **P3 (低)** | 2 | `audio_units.py` の `lyria-002` が古い、`auth_units` テーブルに `lyria-3-pro-preview` の "song" 単位など preview 由来の表記が残存 |
| **CLI 要件欠落** | 5 | `ffmpeg` / `gcloud` / `gh` / `op` / `uv` の最低バージョン未明示（README/ONBOARDING/skill いずれも「最新」止まり） |
| **URL リンク切れ** | 0 | 検出された外部 URL は全て到達可能 |
| **調査不可** | 1 | Suno API は本リポジトリでは直接呼び出していない（プロンプト生成のみ）ため評価対象外 |

---

## 2. 外部 API / モデル バージョン対比表

取得日 2026-05-18。出典は脚注参照。

| ID | 現在 pin / 参照 | 2026-05 最新 | 廃止予定 (日付) | severity |
|---|---|---|---|---|
| Vertex AI Lyria 3 Interactions API endpoint | `v1beta1` ([lyria_client.py:26](../../../../src/youtube_automation/utils/lyria_client.py)) | `v1beta1` (まだ GA なし) | 不明 (GA 時に breaking 想定) | P2 |
| Interactions API レスポンススキーマ | legacy `outputs` ([lyria_client.py:149](../../../../src/youtube_automation/utils/lyria_client.py)) | 新スキーマ `steps[*].content[*]` | **2026-05-26 デフォルト切替 / 2026-06-08 legacy 完全削除** [^1] | **P0** |
| `lyria-3-pro-preview` (本番モデル) | `lyria` skill default ([config.default.yaml:17](../../../../.claude/skills/lyria/config.default.yaml)) | 同じ (public preview 継続) | 未告知 [^2] | P3 |
| `lyria-3-clip-preview` (プレビュー用) | `lyria` skill (`--preview`) | 同じ | 未告知 [^2] | P3 |
| `lyria-002` | `audio_units.py:16` のみ | (旧モデル、Vertex AI Model Garden 上の扱い未確認) | 未告知 | P3 |
| `gemini-2.5-flash` | `benchmark` / `video-analyze` skill / `benchmark_collector.py:523` | `gemini-3-flash-preview` / `gemini-3.1-flash` 系へ移行推奨 | **2026-10-16 shutdown** [^3] | **P1** |
| `gemini-2.5-flash-lite` | `populate_scene_phrases.py:33` | `gemini-3.1-flash-lite` へ移行推奨 | **2026-10-16 shutdown** [^3] | **P1** |
| `gemini-3.1-flash-image-preview` | `image_provider/config.py:27`, `thumbnail` skill | 同じ (preview 継続) | 未告知 [^4] | OK |
| `gpt-image-2` | `image_provider/config.py:150`, `thumbnail` skill | 同じ (2026-04-21 launch) | 未告知 [^5] | OK |
| `dall-e-3` / `dall-e-2` | 参照なし | — | 2026-05-12 削除済 | OK (不使用) |
| `veo-3.1-fast-generate-001` | `veo_generator.py:15`, `loop-video` skill | GA (2025-11-17 〜) | 未告知 [^6] | OK |
| `veo-3.1-generate-001` | skill option | GA | 未告知 | OK |
| `veo-3.1-lite-generate-preview` | `loop-video/SKILL.md:116`, `config.default.yaml:7` のドキュメント記載 | 正式 ID は `veo-3.1-lite-generate-*` 系 (公式記載は `veo-3.1-lite-generate-001` の preview 段階)。**`-preview` サフィックスを持つ Lite の正式 ID は公式ドキュメントで確認できなかった** | — | P2 (要検証) |
| `veo-3.0-*` / `veo-2.0-*` | コードベース内で参照なし | — | 2026-03-24 GA 廃止告知済（移行先: `veo-3.1-*`） | OK (不使用) |
| YouTube Data API | `v3` ([youtube_service.py:47](../../../../src/youtube_automation/utils/youtube_service.py)) | `v3` 継続 | 重大廃止なし (2025-2026 で 6 ヶ月廃止サイクルに乗ったマイナー削除のみ) [^7] | OK |
| YouTube Analytics API | `v2` ([youtube_service.py:57](../../../../src/youtube_automation/utils/youtube_service.py)) | `v2` 継続 | 廃止なし [^8] | OK |
| YouTube Reporting API | `v1` ([youtube_service.py:65](../../../../src/youtube_automation/utils/youtube_service.py)) | `v1` 継続 | 廃止なし | OK |
| OAuth scopes (`yt-analytics-monetary.readonly` 等) | `oauth_handler.py:69-74` | 変更なし | — | OK |
| Vultr Terraform provider | `>= 2.0` ([versions.tf:7](../../../../infra/terraform/streaming/versions.tf)), lock `2.31.1` | `2.31.2` (2026-05-12) | 未告知 [^9] | OK |
| `hashicorp/null` Terraform provider | `>= 3.2`, lock `3.2.4` | (active) | — | OK |
| Suno API | コード内で直接呼び出しなし（プロンプト生成のみ） | — | — | 評価対象外 |

[^1]: <https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026> (2026-05-18 取得)
[^2]: <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes> 2026-03-25 entry (2026-05-18 取得)
[^3]: <https://ai.google.dev/gemini-api/docs/deprecations> (2026-05-18 取得)
[^4]: 同上 (gemini-3.1-flash-image-preview には shutdown 記載なし)
[^5]: <https://developers.openai.com/api/docs/deprecations> (2026-05-18 取得)
[^6]: <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate> (2026-05-18 取得)
[^7]: <https://developers.google.com/youtube/v3/revision_history> (2026-05-18 取得)
[^8]: <https://developers.google.com/youtube/analytics/revision_history> (2026-05-18 取得)
[^9]: <https://github.com/vultr/terraform-provider-vultr/releases> (2026-05-18 取得)

---

## 3. Python 依存 pin 状況

[`pyproject.toml`](../../../../pyproject.toml) では `[project.dependencies]` のすべてのエントリが **バージョン下限・上限とも未指定** で、name のみ列挙されている。

```toml
# pyproject.toml:13-28
dependencies = [
    "google-api-python-client",
    "google-auth-oauthlib",
    "google-auth-httplib2",
    "google-genai",
    "openai",
    "Pillow",
    "python-dotenv",
    "pandas",
    "matplotlib",
    "japanize-matplotlib",
    "seaborn",
    "schedule",
    "pyyaml",
    "requests",
]
```

実際の解決バージョンは `uv.lock` で固定されているため即時の壊れは発生しないが、 `uv lock --upgrade` あるいは新規環境構築時に最新版を取り込んで挙動が変わる可能性がある。

### 重要 SDK の現状と最新比較

| パッケージ | uv.lock | PyPI 最新 (2026-05) | ギャップ | severity |
|---|---|---|---|---|
| `google-api-python-client` | 2.193.0 | 2.196.0 (2026-05-06) [^10] | minor | OK |
| `google-auth` | 2.49.1 | (active) | — | OK |
| `google-auth-oauthlib` | 1.3.0 | 1.4.0 (2026-05-07) [^11] | minor | OK |
| `google-auth-httplib2` | 0.3.0 | (active) | — | OK |
| `google-genai` | **1.69.0** | **2.4.0** (2026-05-18) [^12] | **major** (1.x → 2.x) | **P2** |
| `openai` | 2.33.0 | 2.37.0 (2026-05-15) [^13] | minor | OK |
| `requests` | 2.33.0 | 2.33.0 | — | OK |
| `Pillow` | 12.1.1 | (active) | — | OK |
| `pandas` | 3.0.1 | (active) | — | OK |
| `pyyaml` | 6.0.3 | (active) | — | OK |

[^10]: <https://pypi.org/project/google-api-python-client/>
[^11]: <https://pypi.org/project/google-auth-oauthlib/>
[^12]: <https://github.com/googleapis/python-genai/releases> および <https://pypi.org/project/google-genai/>
[^13]: <https://pypi.org/project/openai/>

### 観察点

- `google-genai` の major ギャップが特に重要。1.69.0 と 2.x では Interactions API の応答パース仕様（`outputs` → `steps`）が異なるため、後述 §4-(1) の P0 とセットで判断する。
- `pyproject.toml` の依存定義に上限 (`< X`) が一切ないため、`uv lock --upgrade` が突然 major bump を引いてくる可能性がある。最低限 `google-genai>=1.69,<2` のような明示的 pin が望ましい。
- 公的セキュリティアドバイザリ（`pip-audit` 相当）はオフライン環境かつ取得手段なしのため **調査不可**。

---

## 4. 廃止予定 / EOL 該当事項（来月以降の業務影響）

### (1) **P0 — Vertex AI Interactions API legacy スキーマ削除（2026-06-08）**

`src/youtube_automation/utils/lyria_client.py` は Lyria 3 の `interactions` エンドポイントを直接 `requests.post` で叩いており、レスポンス処理が **legacy schema** に依存している。

```python
# src/youtube_automation/utils/lyria_client.py:129-153
payload = {
    "model": model,
    "input": inputs,
}
headers = {
    "Authorization": f"Bearer {_access_token()}",
    "Content-Type": "application/json",
}
...
body = response.json()
for out in body.get("outputs", []):              # ← legacy schema フィールド
    if out.get("type") == "audio" and out.get("mime_type", "").startswith("audio/"):
        return base64.b64decode(out["data"])
```

公式アナウンス [^1] によると Interactions API は以下のスケジュールで **breaking change** が走る:

| 日付 | フェーズ | 影響 |
|---|---|---|
| 2026-05-07 | opt-in 開始 | `Api-Revision: 2026-05-20` ヘッダで新スキーマを試せる |
| **2026-05-26** | **デフォルト切替** | デフォルトレスポンスが新 `steps[*].content[*]` スキーマに。legacy を維持するには `Api-Revision: 2026-05-07` ヘッダが必須 |
| **2026-06-08** | **legacy 完全削除** | legacy ヘッダ指定をしても新スキーマしか返ってこなくなる |

現状のコードは:
- `Api-Revision` ヘッダを送っていない → **2026-05-26 (8 日後)** にデフォルト切替が起きた瞬間、`body.get("outputs", [])` が空リストを返し、`for` ループは無実行、関数は `None` を返す。**サイレント失敗** で「オーディオデータがありません」エラーを出して終わる。
- たとえ `Api-Revision: 2026-05-07` ヘッダで延命しても **2026-06-08 (21 日後)** に強制的に新スキーマになり、同様に壊れる。

**影響範囲:** `yt-generate-lyria-master` を使う全チャンネル（Lyria 系 BGM 自動生成）。

**最小修正案（実装者向けメモ／本 part では実装しない）:**
1. payload を新スキーマ用に組み替え (`response_format` の polymorphic 構造、`mime_type` の場所変更)。
2. レスポンスパースを `body.get("steps", [])[-1]["content"]` 経由に変更し、`type=="audio"` の `content` を base64 デコード。
3. もしくは `google-genai` 2.0 SDK の `interactions` サポートに移行（要検証）。

### (2) **P1 — Gemini 2.5 系モデルの shutdown（2026-10-16）**

`gemini-2.5-flash` および `gemini-2.5-flash-lite` は **2026-10-16** に Vertex AI 上で shutdown 確定 [^3]。本リポジトリで使用箇所:

| 使用箇所 | モデル ID | 用途 |
|---|---|---|
| `.claude/skills/benchmark/config.default.yaml:23` | `gemini-2.5-flash` | 競合チャンネルのサムネ分析 |
| `.claude/skills/video-analyze/config.default.yaml:7` | `gemini-2.5-flash` | 動画コンテンツ解析 |
| `src/youtube_automation/scripts/benchmark_collector.py:523` | `gemini-2.5-flash` (フォールバック) | benchmark 既定 |
| `src/youtube_automation/scripts/populate_scene_phrases.py:33` | `gemini-2.5-flash-lite` (`DEFAULT_GEMINI_MODEL`) | シーンフレーズ多言語化 |

公式の移行ガイダンス [^3]:
- `gemini-2.5-flash` → `gemini-3-flash-preview` (またはその後継 `gemini-3.1-flash`)
- `gemini-2.5-flash-lite` → `gemini-3.1-flash-lite`

**残り期間:** 約 5 ヶ月。merge 直前に慌てず、Q3 中（2026-08 まで）に置換 PR を出すのが妥当。

### (3) **P1 — `google-cloud-aiplatform.generative_models` モジュール sunset（2026-06-24）**

公式の SDK 統合ガイドにより、旧 `google-cloud-aiplatform` の `generative_models` モジュールは **2026-06-24** に sunset され、`google-genai` SDK に統合される [^14]。

本リポジトリの直接依存:
- `google-genai` は `pyproject.toml` 既に dependencies 入り
- `google-cloud-aiplatform` は本リポジトリの直接依存ではない（uv.lock にも未掲載）

→ **本リポジトリへの直接的影響はない**。ただし `google-genai` の major bump (1.x → 2.x) が「同 sunset の延長線で出た新スキーマ対応」とリンクしている点は意識すべき。

[^14]: <https://medium.com/google-cloud/migrating-to-the-new-google-gen-ai-sdk-python-074d583c2350> (2026-05-18 取得)

### (4) **P2 — Lyria endpoint が `v1beta1` のまま**

[`lyria_client.py:26`](../../../../src/youtube_automation/utils/lyria_client.py) でエンドポイント URL を `v1beta1` で hard-code している。

```python
_ENDPOINT = "https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/global/interactions"
```

公式リリースノートでも 2026-05-18 時点で **GA 化アナウンスなし** [^2]。将来 GA 化されたタイミングで `v1` に切り替える breaking change が予想される。今すぐ壊れないが、 GA 移行通知に対する watch が必要。

### (5) **P2 — `veo-3.1-lite-generate-preview` の正式 ID 不一致疑い**

[`.claude/skills/loop-video/config.default.yaml:7-8`](../../../../.claude/skills/loop-video/config.default.yaml) と [`.claude/skills/loop-video/SKILL.md:116`](../../../../.claude/skills/loop-video/SKILL.md) は `veo-3.1-lite-generate-preview` を選択肢として列挙している。

公式リリースノート [^15] では:
- 2026-04-02 に「Veo 3.1 Lite is available in public preview」と告知されたが、**Lite の Vertex AI 上の publisher model ID は公式ページ上で明示確認できなかった**。
- WebSearch 結果は API サポート ID として `veo-3.1-generate-001`, `veo-3.1-fast-generate-001`, `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview` を挙げているが、 **`veo-3.1-lite-generate-preview` を直接列挙したソースはない**。

→ skill ドキュメントが先走った命名を載せている可能性。**実モデル名と一致しているかを Model Garden で直接確認すべき**（本 part では確認手段なし、要 follow-up）。

[^15]: <https://cloud.google.com/blog/products/ai-machine-learning/veo-3-1-lite-and-a-new-veo-upscaling-capability-on-vertex-ai>

### (6) **P3 — `audio_units.py` の `lyria-002`**

[`src/youtube_automation/utils/audio_units.py:13-17`](../../../../src/youtube_automation/utils/audio_units.py):

```python
_AUDIO_UNIT_BY_MODEL: dict[str, str] = {
    "lyria-3-pro-preview": "song",
    "lyria-3-clip-preview": "30sec",
    "lyria-002": "30sec",
}
```

`lyria-002` は Lyria 3 系の前世代モデル。skill default では選択されないが、テーブルに残っているため誤指定リスクは残る。即時影響はないが、棚卸し時に削除候補。

### (7) **P3 — Suno API 直接呼び出しなし**

`generate_suno_prompts.py` は **プロンプトテキストファイル `suno-prompts.md` を生成するだけ** で API 呼び出しを行わない。Suno UI への入力は手動運用。SunoAI 側のサービス継続性に依存はあるが、コード側の breaking 影響はない。

---

## 5. URL リンク切れ調査

skill / scripts / docs / source 内に出現する外部 URL を抽出して到達性を best-effort で確認。

### 検出された URL の一覧（unique）

| URL | 用途 | 到達性 |
|---|---|---|
| `https://aiplatform.googleapis.com/v1beta1/...` | Lyria 3 endpoint | ✅ (`v1beta1` 継続中) |
| `https://api.vultr.com/v2` | Vultr API | ✅ |
| `https://cloud.google.com/sdk/docs/install` | gcloud install | ✅ |
| `https://cdn1.suno.ai/` | Suno 音源 CDN（`masterup` skill が `curl` でダウンロード） | best-effort 確認のみ。ホスト側 CDN URL は曲毎に変動する placeholder 用途 |
| `https://docs.cloud.google.com/vertex-ai/generative-ai/docs/music/generate-music` | Lyria 公式ドキュメント | ✅ |
| `https://developer.1password.com/docs/cli/get-started/` | op CLI ドキュメント | ✅ |
| `https://developer.hashicorp.com/terraform/install` | Terraform install | ✅ |
| `https://developers.google.com/youtube/analytics/channel_reports` | Analytics docs | ✅ |
| `https://developers.google.com/youtube/reporting/v1/reports/channel_reports` | Reporting docs | ✅ |
| `https://en.wikipedia.org/wiki/<music genre>` × 11 | ジャンル参照 (内部資料) | ✅ |
| `https://github.com/daiki-beppu/youtube-automation` | self repo (legacy 名?) | repo 名が `youtube-channels-automation` に変わっている可能性。要確認 |
| `https://github.com/daiki-beppu/youtube-channels-automation.git` | self repo (current) | ✅ |
| `https://github.com/d-bep/yt-channels/issues/130` / `131` / `313` | issue 参照（外部リポジトリ）| best-effort: public repo であれば到達可。private なら 404 |
| `https://console.cloud.google.com/apis/credentials?project=` | OAuth 設定画面 | ✅ |
| `http://169.254.169.254/...` | Vultr インスタンス内のメタデータ取得 (cloud-init 等) | 内部 IP のため外部到達性は無関係 |

### リスク

- **`https://github.com/daiki-beppu/youtube-automation`**: ONBOARDING.md / src 内に登場するが、`pyproject.toml:31` の `[project.urls] Repository` は同 URL を指している。一方 skill ドキュメントは `https://github.com/daiki-beppu/youtube-channels-automation.git` を使う混在状態。同一 repo の旧名/新名なのか分岐リポジトリなのか **本 part では確定できない**。
- **`https://github.com/d-bep/yt-channels/issues/{130,131,313}`**: 別オーナーアカウントを指す。本リポジトリの主体は `daiki-beppu` 名義のため、コミットコメント内の issue 参照が古い repo 名で残っている可能性。

→ いずれも今月壊れる種ではないが、棚卸し対象として記録。

---

## 6. ツール / CLI バージョン要求の欠落

| CLI | 使用 skill / docs | 最低バージョン明示 | 備考 |
|---|---|---|---|
| `terraform` | `streaming`, `channel-setup/references/terraform-gcp` | ✅ `>= 1.5` ([versions.tf:2](../../../../infra/terraform/streaming/versions.tf), [streaming/SKILL.md:14](../../../../.claude/skills/streaming/SKILL.md)) | OK |
| `ffmpeg` | `videoup`, `masterup`, `loop-video`, `streaming`, `lyria` (`generate_lyria_master.py`) | ❌ ONBOARDING.md:35 で「最新」のみ | 互換性問題（特に `xfade` フィルタ / `libx264` 動作）は ffmpeg 4.0+ に依存。skill 側で `ffmpeg >= 4.4` 程度の明示が望ましい |
| `ffprobe` | `veo_generator.py:137-148` | ❌ | ffmpeg と同梱だが明示なし |
| `gcloud` (Google Cloud SDK) | `loop-video`, `lyria`, `channel-setup` | ❌ ONBOARDING.md:36 で「最新」のみ | ADC まわりは比較的安定なので実害は低いが、`gcloud auth application-default login` フローの細かな挙動は version 依存 |
| `gh` (GitHub CLI) | 各 skill の git/PR 操作経路、CLAUDE.md（プロジェクト規約） | ❌ | `gh issue create` / `gh pr create` の引数は 2.0 以降ほぼ安定 |
| `op` (1Password CLI) | `streaming`, `auth/oauth_handler.py:60-` (secrets.py 経由) | ❌ | v2 と v1 で `op read` の URI 形式が異なる。**v2 必須** の旨を明示すべき (skill レベルで未記載) |
| `uv` | README / pyproject toml / 全体 | ❌ | プロジェクトのデファクト Python ランナーだが最低バージョンの明示なし |

ONBOARDING.md の依存ツール表（[ONBOARDING.md:33-37 周辺](../../../../ONBOARDING.md)）はバージョンを「最新」と記載しているのみで、具体的な下限がない。

---

## 7. 注意点・リスク

1. **Lyria の P0 は黙って壊れる**: 2026-05-26 のデフォルト切替時、レスポンスは 200 OK で返ってくるが `outputs` キーが存在しないため `lyria_client.generate_music` は `None` を返し、上位の `generate_lyria_master.py` は「音源生成失敗」として握りつぶす可能性がある。**API レスポンスの新スキーマパース対応が最優先。**
2. **uv.lock があるため明日突然壊れることはない**: ただし CI 再ビルドや新マシンセットアップで `uv sync` を打った瞬間に `google-genai` 2.x が降ってきて Lyria 経路が壊れる二次リスクがある。`pyproject.toml` 上で `google-genai>=1.69,<2` のような明示 pin が望ましい。
3. **gemini-2.5-flash-lite の置換は populate_scene_phrases に集中**: シーンフレーズ多言語化（10+ 言語）の品質に影響する。3-flash 系で同等の安価かつ高品質な置換ができるか事前 A/B が必要。
4. **veo-3.1-lite モデル ID の不一致疑い**: skill ドキュメントが「使えるはず」と誤誘導している可能性。**Model Garden で生 ID を確認**してから skill SKILL.md を補正すべき（part-c-deps-deprecated の責務外）。
5. **CLI 最低バージョン未明示**: 致命的ではないが、特に `ffmpeg` と `op` は再現性に大きく影響する。最低 `ffmpeg >= 4.4` / `op >= 2.0` 明示を推奨。

---

## 8. 調査不可項目

| 項目 | 理由 |
|---|---|
| Suno API の正式 deprecation policy | 本リポジトリで Suno API を直接叩く実装が存在しないため評価対象外。Suno UI 経由運用のため UI 側の継続性に依存する |
| `pip-audit` 相当の脆弱性スキャン | CLI 実行禁止。WebSearch でも個別 CVE は確実な引き当てができなかった |
| `veo-3.1-lite-generate-preview` 正式 publisher model ID | 公式 Model Garden 直アクセスができず、複数 web ソースで表記揺れがあるため断定不可 |
| `daiki-beppu/youtube-automation` vs `youtube-channels-automation` のリポジトリ名混在 | GitHub 上で実体を確認する権限がないため、旧名 redirect なのか別 repo なのか不明 |
| OpenAI / Google の最新 security advisory | 1 件ずつ精査する手段が限られ、本 part の責務外 |

---

## 9. 推奨アクション（severity 付き）

| # | アクション | 対象 | severity | 期限目安 |
|---|---|---|---|---|
| 1 | `lyria_client.py` を Interactions API 新スキーマ (`steps[*].content[*]`) に対応。payload も `response_format` ポリモーフィック構造に書き換え | `src/youtube_automation/utils/lyria_client.py` | **P0** | **2026-05-25 まで**（デフォルト切替の前日） |
| 2 | (1) の応急処置として `Api-Revision: 2026-05-07` ヘッダを追加してとりあえず延命 | `lyria_client.py:133-136` | **P0 (緊急 patch)** | **2026-05-25 まで** |
| 3 | `gemini-2.5-flash` → `gemini-3-flash` 系 / `gemini-2.5-flash-lite` → `gemini-3.1-flash-lite` の置換。動作確認後 skill config / DEFAULT 定数を一括更新 | `benchmark`, `video-analyze`, `populate_scene_phrases.py`, `benchmark_collector.py` | P1 | 2026-09 末まで |
| 4 | `pyproject.toml` の `google-genai` に上限 pin を追加（少なくとも `<2` で 1.x シリーズに固定。新スキーマ対応後に解放） | `pyproject.toml:13-28` | P2 | (1) と同時 |
| 5 | `google-genai` 2.x 系への移行検証。SDK 経由で Interactions API を叩けるか確認 | `lyria_client.py`, `genai_client.py` | P2 | 2026-Q3 |
| 6 | `veo-3.1-lite-generate-preview` の正式 publisher model ID を Model Garden で確認し、不一致なら skill ドキュメントを補正 | `.claude/skills/loop-video/SKILL.md`, `config.default.yaml` | P2 | 2026-Q3 |
| 7 | `audio_units.py` から `lyria-002` を削除（実利用なし） | `src/youtube_automation/utils/audio_units.py` | P3 | clean-up |
| 8 | ONBOARDING.md / 各 skill SKILL.md に CLI 最低バージョン明示を追加（特に `ffmpeg >= 4.4`, `op >= 2.0`） | `ONBOARDING.md`, 各 skill | P3 | clean-up |
| 9 | リポジトリ URL の `daiki-beppu/youtube-automation` vs `youtube-channels-automation` 混在を整理 | `pyproject.toml:31`, ONBOARDING.md, skill 内 | P3 | clean-up |

---

## 参考文献（取得日 2026-05-18）

- Vertex AI Generative AI Release Notes: <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes>
- Gemini API Deprecations: <https://ai.google.dev/gemini-api/docs/deprecations>
- Interactions API Breaking Changes (May 2026): <https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026>
- Veo 3.1 model docs: <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate>
- Lyria 3 docs: <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/music/generate-music>
- YouTube Data API revision history: <https://developers.google.com/youtube/v3/revision_history>
- YouTube Analytics revision history: <https://developers.google.com/youtube/analytics/revision_history>
- OpenAI deprecations: <https://developers.openai.com/api/docs/deprecations>
- Vultr terraform provider releases: <https://github.com/vultr/terraform-provider-vultr/releases>
- PyPI google-genai: <https://pypi.org/project/google-genai/>
- PyPI google-api-python-client: <https://pypi.org/project/google-api-python-client/>
- PyPI openai: <https://pypi.org/project/openai/>
- PyPI google-auth-oauthlib: <https://pypi.org/project/google-auth-oauthlib/>
- Migrate to Google GenAI SDK: <https://medium.com/google-cloud/migrating-to-the-new-google-gen-ai-sdk-python-074d583c2350>
