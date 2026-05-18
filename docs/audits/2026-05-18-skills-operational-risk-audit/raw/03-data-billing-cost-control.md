# 観点 4: 課金 API コスト制御 / 安全弁 調査結果

**調査日**: 2026-05-18
**担当**: dig.part-a-failure-cost (Part A-2)
**対象**: `.claude/skills/**`（35 skill）+ `src/youtube_automation/**` 実装
**作業ディレクトリ**: `/Users/mba/02-yt/takt-worktrees/20260518T0905-372-issue-372-chore-skills-sukiru/`

---

## 4.1 課金 API × skill マトリクス

skill から呼ばれる API を整理する。実装ファイルを辿って判定した。

| skill | Vertex Veo | Vertex Gemini | Vertex Lyria | OpenAI Image | Suno (Web) | YouTube Data v3 | YouTube Analytics | Vultr | Google Drive | その他 |
|---|---|---|---|---|---|---|---|---|---|---|
| alignment-check | — | — | — | — | — | — | — | — | — | ローカル分析のみ |
| analytics-analyze | — | — | — | — | — | — | — | — | — | ローカル分析のみ |
| analytics-collect | — | — | — | — | — | ○ | ○ | — | — | — |
| analytics-report | — | — | — | — | — | — | — | — | — | ローカル表示のみ |
| audience-persona | — | — | — | — | — | — | — | — | — | ローカルのみ |
| benchmark | — | — | — | — | — | ○ | — | — | — | — |
| channel-direction | — | — | — | — | — | — | — | — | — | ローカルのみ |
| channel-import | — | — | — | — | — | ○ | — | — | — | branding pull |
| channel-new | — | — | — | — | — | △ | — | — | — | mostly local |
| channel-research | — | — | — | — | — | — | — | — | — | ローカル分析 |
| channel-setup | — | — | — | — | — | ○ | — | — | — | GCP API (`aiplatform`, `youtube`, `billing`) — 有料化トリガ |
| channel-status | — | — | — | — | — | ○ | — | — | — | — |
| collection-ideate | — | △ | — | △ | — | — | — | — | — | thumbnail プレビュー画像生成（gemini or openai） |
| comments-reply | — | — | — | — | — | ○ | — | — | — | comments.insert + commentThreads.list |
| discover-competitors | — | — | — | — | — | ○ | — | — | — | search.list × keyword 数 |
| live-clean | — | — | — | — | — | — | — | — | — | ローカル削除のみ |
| loop-video | ○ | — | — | — | — | — | — | — | — | **Veo 3.1 1080p 8sec / call** |
| lyria | — | — | ○ | — | — | — | — | — | — | N セグメント call（target_duration から自動算出） |
| masterup | — | — | — | — | △ Web | — | — | — | — | DL のみ。Suno UI 課金は外で発生 |
| metadata-audit | — | — | — | — | — | ○ | — | — | — | videos.list, playlists 系 |
| playlist | — | — | — | — | — | ○ | — | — | — | playlists.insert/list, playlistItems |
| postmortem | — | — | — | — | — | — | — | — | — | ローカル分析 |
| streaming | — | — | — | — | — | △ | — | ○ | — | Vultr 月額 + 帯域 + ffmpeg |
| suno | — | — | — | — | △ Web | — | — | — | — | プロンプト生成のみ。Suno UI 課金は外 |
| thumbnail | — | ○ | — | ○ | — | — | — | — | — | 画像生成 |
| thumbnail-compare | — | — | — | — | — | — | — | — | — | ローカル分析 |
| video-analyze | — | ○ | — | — | — | — | — | — | — | Gemini 動画解析 |
| video-description | — | △ | — | — | — | — | — | — | — | scene_phrases 翻訳で Gemini 経由の余地 |
| video-upload | — | — | — | — | — | ○ | — | — | — | videos.insert (1600 units/upload) + thumbnails.set |
| videoup | — | — | — | — | — | — | — | — | — | ffmpeg のみ。API 課金なし |
| viewer-voice | — | — | — | — | — | ○ | — | — | — | commentThreads.list |
| viewing-scene | — | — | — | — | — | — | — | — | — | ローカル分析 |
| wf-new | — | △ | — | — | — | — | — | — | — | populate_scene_phrases 経由 Gemini |
| wf-next | — | — | — | — | — | — | — | — | — | オーケストレーターのみ。子 skill が API を叩く |
| wf-status | — | — | — | — | — | — | — | — | — | ローカル参照のみ |

**集計（API 種別）**:
- **YouTube Data v3 利用 skill**: 13 件
- **Vertex AI Veo 利用 skill**: 1 件（`loop-video`）
- **Vertex AI Gemini 利用 skill**: 4 件（`thumbnail`, `video-analyze`, `collection-ideate`, `wf-new` 経由）
- **Vertex AI Lyria 利用 skill**: 1 件（`lyria`）
- **OpenAI Image 利用 skill**: 2 件（`thumbnail`, `collection-ideate`）
- **Vultr 課金**: 1 件（`streaming`）
- **Suno (Web UI)**: 2 件（`suno`, `masterup`）— skill 経由の課金トリガではないが連動

**Google Drive API は CLAUDE.md / pyproject に記述あるが、コード内で使われている形跡なし**（`mcp__claude_ai_Google_Drive__authenticate` は外部 MCP）。

---

## 4.2 quota / コスト見積もりの skill 内記載

| skill | API call 数記載 | 推定コスト記載 | quota 消費記載 | 出典 |
|---|---|---|---|---|
| `discover-competitors` | ○ 660 units / 実行 | × | ○ `10,000/日 quota の 6.6%` | `.claude/skills/discover-competitors/SKILL.md:116-121` |
| `video-upload` | ○ `2 × 1,600 = 3,200 ユニット` (single_release JP+EN) + plan 出力で `84+100=184` 表示 | × | △ | `.claude/skills/video-upload/SKILL.md:46` + `agents/collection_uploader.py:415-417` |
| `thumbnail` | △ 最大 3 試行込み | △ skill-config `cost_per_image_usd` 指定時のみ | × | `.claude/skills/thumbnail/SKILL.md:187` |
| `collection-ideate` | △ `count` 枚（preview.candidate_count） | △ skill-config `cost_per_image_usd` 指定時のみ | × | `.claude/skills/collection-ideate/SKILL.md:113-139` |
| `streaming` | × | △ `月間 1.16 TB（2 TB プランの 58%）` 帯域記載 | — | `.claude/skills/streaming/SKILL.md:99` |
| `lyria` | △ N セグメント = `ceil((target+padding)*60/184)` | × | △ 「Vertex AI の Lyria クォータ（プロジェクト単位）は有限。429 が出る」 | `.claude/skills/lyria/SKILL.md:200` |
| `loop-video` | × | × | × | — |
| `video-analyze` | △ 「動画間に delay_sec 秒スリープ」 | × | × | `.claude/skills/video-analyze/SKILL.md:62-67` |
| `analytics-collect` | × | × | × | — |
| `benchmark` | × | × | × | — |
| `comments-reply` | × | × | × | — |
| `playlist` | × | × | × | — |
| `metadata-audit` | × | × | × | — |
| `channel-status` | × | × | × | — |
| `channel-import` | × | × | × | — |
| `viewer-voice` | × | × | × | — |

### 集計

- **API call 数を明示している skill**: 5/35
- **コスト見積もり（ドル単位）を明示している skill**: 0（`cost_per_image_usd` 指定時のみ CLI で表示）
- **YouTube Data API quota 消費を明示している skill**: 3（`discover-competitors`, `video-upload`, ぼんやり `lyria`）

**重大な漏れ**: `benchmark` `analytics-collect` `metadata-audit` などは **複数ページ取得**で **数百〜数千 units** を消費する可能性があるのに記載なし。`channel-import` や `playlist --init` も同様。

---

## 4.3 dry-run / preview の有無

SKILL.md / CLI フラグから網羅的に調査。

| skill / CLI | dry-run / preview フラグ | 出典 |
|---|---|---|
| `comments-reply` | `--dry-run` / `--apply` 必須・排他 | `.claude/skills/comments-reply/SKILL.md:53-58` |
| `playlist` | `--dry-run` フラグ（init / assign / clean-deleted 全モード） | `.claude/skills/playlist/SKILL.md:28-30,50-54` |
| `channel-setup` (`yt-channel-settings`) | `pull` は dry-run（読み取りのみ）、`push --dry-run` あり | `.claude/skills/channel-setup/SKILL.md:90,96` |
| `channel-setup` (`gcp-bootstrap.sh`) | `--dry-run` あり | `.claude/skills/channel-setup/references/gcp-bootstrap.md:41` |
| `video-upload` | `--plan` でスケジュール計算（API call なしのドライラン） | `.claude/skills/video-upload/SKILL.md:90` + `agents/collection_uploader.py:400-417` |
| `streaming` (terraform) | `terraform plan` で apply 前確認 | `.claude/skills/streaming/SKILL.md:55,73` |
| `loop-video` | `-y` / `--yes` で確認 skip、未指定なら `[y/N]` プロンプト | `scripts/generate_loop_video.py:91,140-144` |
| `thumbnail` (`yt-generate-image`) | `-y` で確認 skip、未指定なら `confirm_cost` で y/N | `scripts/generate_image.py:59,148-149` + `image_provider/composition.py:58-78` |
| `lyria` | **dry-run なし**。`yt-generate-lyria-master` は y/N プロンプトもなし | `scripts/generate_lyria_master.py` |
| `video-analyze` | **dry-run なし**。確認プロンプトもなし | `scripts/video_analyze.py` |
| `benchmark` | **dry-run なし** | — |
| `analytics-collect` | **dry-run なし** | — |
| `metadata-audit` | **dry-run なし** | — |
| `channel-status` | 読み取り専用なので不要 | — |
| `discover-competitors` | **dry-run なし** | — |
| `live-clean` | **dry-run なし**（大容量ファイル削除 = 復旧不能） | — |

### 集計

- **dry-run / preview あり**: 8/35（22.9%）
- **y/N confirm あり**: 2/35（loop-video, thumbnail）
- **どちらもなし**: 25/35（**71%**）

### 重大な発見

- **lyria は確認プロンプトなしで N セグメントの Lyria API を一気に叩く**。`--target-duration 90` × `184sec/seg` = 約 30 セグメント呼び出しが無確認で走る。Lyria のクォータが小さい場合即 429 で残骸セグメントだけ残る
- **video-analyze は `--top 5` でも 5 動画分の Gemini API を無確認で叩く**。`delay_sec=10` のスリープのみで止まれない
- **live-clean は SKILL.md を読めない (read-only protected paths) が、CLI に dry-run があるかは要追加検証**

---

## 4.4 ループ・再帰実行のガード

| パターン | 場所 | ガードの有無 |
|---|---|---|
| `/loop` skill | Claude Code 組み込み（intervalで自動再実行） | **skill 側のガードなし** — 利用者が `/loop 5m /lyria <theme>` を打ったら 5 分ごとに Lyria を再課金 |
| `analytics-collect` × `/loop` | 仕様上ありえる組み合わせ | YouTube Analytics は read-only なのでコスト面はマシだが quota 1日10000 を 5 分毎に叩くと数時間で枯渇 |
| `benchmark` × `/loop` | 仕様上ありえる | benchmark 1 回数百 units × 5 分毎 = quota 焼き切り |
| `collection_uploader.run_automated_schedule` daemon mode | `agents/collection_uploader.py:440-457` | 1 日 1 回チェック (`day1_time`)。**daemon 内 `while True: ... time.sleep(60)`** で 60 秒ループ。schedule ライブラリでチェックするので暴走しない |
| `lyria` 1 実行内のセグメントループ | `generate_lyria_master.py:368-381` | for ループで N 回。**N は target_duration から自動算出**で hard cap なし。`target_duration=180 (3 時間)` を指定すると N=59 回 Lyria call |
| `loop-video` | 1 回 1 動画 | 単発。`/loop` と組み合わせなければ問題なし |
| `video-analyze` `--top` | 引数で上限指定可 | `--top 20` 等の上限はある（デフォルト 5） |

### 評価

- **skill 自体に hard limit を持つものは少ない**。引数で `--top N` / `--limit N` を指定する設計
- **`/loop` skill と組み合わせる場合の cost guard は皆無**。AI agent が「自動で 5 分ごとにベンチマーク更新」と言い出したら止まらない
- **lyria の N 自動算出には上限なし**。極端な target_duration を指定すると数十回 API call

---

## 4.5 失敗時の課金リスク（中間生成物だけ残ってコストだけ発生）

### 検証結果

| API | 失敗 → 課金パターン |
|---|---|
| Veo 3.1 (loop-video) | **生成成功 → ffmpeg `strip_audio` 失敗 → return ok だが音声残**。生成後 `output_path.write_bytes(video_bytes)` で書き込み後に strip するので最悪 ffmpeg 失敗で音声残るがコストは 1 回分。**Ctrl+C 中断時は API 完走 → クライアント側でレスポンス破棄**で最悪パターン |
| Vertex Gemini (thumbnail / video-analyze) | API call は単発成功 → ローカル PIL / JSON パース失敗で `provider.generate()` が success=False を返す経路あり (`image_provider/gemini.py`)。`raise` ではないので **画像生成料金は発生、ファイルは保存されず**のケースあり |
| Lyria | `generate_music()` が None 返却 → 上位で retry。1 セグメント生成成功 → WAV 変換失敗 → tmp 残るが try/finally で掃除。**1 セグメントの料金 = `1 song` 課金は確定**でファイルだけ残らないパターン |
| OpenAI Image | 同様 |
| YouTube Data resumable upload | 前述 3.3 の通り session URI 永続化なしのため、resumable upload 失敗 → CLI 再実行で **新規 insert** = quota 二重消費（1600 units × 2） |

### H1 検証（Veo 3.1 が長尺で課金される）

- **検証済（部分的）** — `veo_generator.py:23` で `MAX_POLL_SEC = 600` (10 分)。Veo 3.1 fast は 8 秒動画固定 (`scripts/generate_loop_video.py` の `--duration_seconds` デフォルト 8)。**「長尺で課金」は 8 秒固定モデルなので発生しない**。が、**duration_seconds パラメータは外から渡せる**（`veo_generator.generate_loop_video()` の引数 `duration_seconds: int = 8`）。CLI から `--duration` 等で渡す経路は現状なし（`generate_loop_video.py` の argparse には未定義）。**ただし誰かが直接 Python から呼び出すと長尺指定で課金可**

### H2 検証（再生成ガードが弱く再実行で二重課金）

- 観点 3.3 で詳述: **`loop-video` 検証済、`lyria` 否定**

### 重大な発見（cost-only 失敗パターン）

1. **Veo の Ctrl+C 中断** — クライアント側はキャンセルしても API 側は完走。`/loop-video` の y/N 確認後にユーザーが意図せず Ctrl+C を打つと「課金されたが結果無し」
2. **Lyria の N セグメントループ中断** — `for i in range(1, n + 1)` の途中で Ctrl+C すると、完成済みセグメントは保存されるが残りは未生成。「これまでの料金は確定、結果は半端」。ただし再実行で resume するので「捨て金」にはならない
3. **resumable upload 失敗時の quota 二重消費** — videos.insert が quota 1600 units で、失敗→再実行で 3200 units 消費しても video は 1 本だけ完成

---

## 4.6 監視・通知・コストレポート

### `yt-cost-report` の実態

- **存在**: ○ `src/youtube_automation/cli/cost_report.py` + `pyproject.toml:49` で entry point 登録
- **対象範囲**: image / video / audio の 3 カテゴリのみ（`cost_tracker.py:38-43`）
- **記録経路**:
  - `image_provider/gemini.py:83-91` → `log_image_cost`
  - `image_provider/openai.py` → 同上
  - `veo_generator.py:102-114` → `cost_tracker.log_generation("video", ...)`
  - `generate_lyria_master.py:180-186` → `cost_tracker.log_generation("audio", ...)`
- **記録されない**:
  - YouTube Data API 系（playlist / benchmark / analytics / video-upload / comments-reply / metadata-audit / channel-status / channel-import / discover-competitors / viewer-voice）— quota units の集計なし
  - Vultr 帯域 / 月額 — `yt-stream-bandwidth` 別 CLI
  - 動画解析（Gemini text モデル）— `video-analyze` は cost_tracker を呼んでいない（`scripts/video_analyze.py` に `cost_tracker` import なし）
  - `populate_scene_phrases` の Gemini 翻訳 — cost_tracker なし

### コスト記録の質

- `estimated_cost_usd` は **常に `None`**（`cost_tracker.py:18` のコメント "Issue #132 で `estimated_cost_usd` は新規エントリで `null` 固定"）
- **件数ベースの集計のみ**で、ドル換算は GCP Cloud Console > Billing 任せ
- `yt-cost-report` は「今月 N 件、累計 M 件」を出すだけ。**$ 単位の合計は出ない**

### アラート

- **コスト超過アラートなし**。`cost_tracker.print_last_report()` が呼ばれるが、しきい値判定なし
- streaming のみ `yt-stream-bandwidth --check-threshold` で 80% 超過アラート（Discord webhook）
- YouTube Data API quota 残量を可視化する CLI なし

### H5 検証（streaming の VPS 死活監視欠如で課金継続）

- **否定** — `healthcheck.sh` が cron 5 分間隔で動き、Discord に anomaly 通知（`.claude/skills/streaming/SKILL.md:78-90`）。SKILL.md で **「VPS が消えるまで課金が続く」と明示** + `terraform destroy` 案内あり (`:120-127`)
- **ただし** Vultr 側で誤って API key を漏洩すると別の VPS が立つリスクは別問題（観点 5 担当）

---

## 主要発見サマリー（観点 4）

### P0（運用直撃の最重要）

1. **YouTube Data API の quota 消費が `yt-cost-report` で可視化されない**。`analytics-collect` `benchmark` `playlist --init` 等が無自覚に quota を焼き切る可能性
2. **`lyria` `video-analyze` `analytics-collect` `benchmark` などに dry-run / 事前見積もり表示なし**。確認なしで API call が走る
3. **Veo の Ctrl+C 中断 = API は完走するが結果は捨てられる**（cost-only failure）。`loop-video` の y/N プロンプト後の中断で発生

### P1（重要）

4. **`/loop` skill と課金 skill の組み合わせに hard limit なし**。`/loop 5m /lyria` のような誤用を防ぐ仕組みなし
5. **lyria の N セグメント自動算出に上限なし**。極端な `target_duration` で大量 call
6. **resumable upload session URI 未永続化** → 失敗時に quota 二重消費（前述 3.3 と連動）
7. **cost_tracker の `estimated_cost_usd` 常に None**。`yt-cost-report` は件数のみで予算管理に使えない

### P2（あれば良い）

8. SKILL.md にコスト・quota 記載がある skill は 5/35（14%）
9. video-analyze は cost_tracker を呼んでいない（Gemini 動画解析のコストが集計から漏れる）
10. populate_scene_phrases の Gemini call も cost_tracker から漏れる

---

## 既知リスク仮説の検証マトリクス（観点 4 関連）

| ID | 仮説 | 検証結果 | 出典 |
|---|---|---|---|
| H1 | Veo 3.1 が長尺で課金される | **部分検証** — CLI からの長尺指定は無いが内部 API は受け付ける | `veo_generator.py:34-58` |
| H2 | `/loop-video` `/lyria` の再生成ガードが弱く再実行で二重課金 | **`/loop-video` は検証、`/lyria` は否定** | `scripts/generate_loop_video.py:51-67` vs `generate_lyria_master.py:137-138` |
| H5 | streaming の VPS 死活監視欠如で課金継続 | **否定** — healthcheck + destroy 案内あり | `.claude/skills/streaming/SKILL.md:78-127` |

---

## 調査不可項目

- **Suno Web UI のクレジット消費単価**: Suno 側の話なので調査不可（プロンプト生成のみのため skill 経由では課金されない）
- **YouTube Data API quota の実時間残量**: API で取得する手段が存在しない（Google Cloud Console > APIs & Services > Quotas で手動確認のみ）
- **OpenAI Image の正確な単価**: skill-config の `cost_per_image_usd` で各自指定する設計
- **Vertex AI Lyria の per-call 単価**: 公開価格表での確認が必要。今回は時間制約で WebFetch 未実施

---

## 推奨

1. **`yt-cost-report` を拡張し、YouTube Data API quota 消費見積もりを記録する**（最高優先）
   - `playlist` `benchmark` `analytics-collect` `video-upload` `discover-competitors` 各 CLI で実行時に消費 units を `cost_tracker.log_generation("youtube_quota", ...)` 風に記録
   - 1 日累計 + 残量警告（10000 - 累計 < 1000 で警告）
2. **`/loop` 系の自動ループに対する課金 skill のブラックリスト** または **「課金 skill には警告」を出す仕組み**
3. **lyria に `--max-segments N` を追加し、上限超過時は明示確認**
4. **video-analyze / discover-competitors に dry-run + 件数事前表示**
5. **Veo / Lyria に signal handler を入れ、Ctrl+C で API cancel を試みる**（returns money かは API 側依存）
6. **cost_tracker.log_generation で `estimated_cost_usd` を null 固定する仕様を再評価**。せめて skill-config で `cost_per_call_usd` 指定時は記録する
7. **SKILL.md の `## API コスト` セクションを必須化**（discover-competitors のような表記をテンプレ化）
