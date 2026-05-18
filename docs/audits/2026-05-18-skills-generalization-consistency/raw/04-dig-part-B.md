# dig-part-b — 重複スクリプト & skill-config 外出し余地

実行日: 2026-05-18
担当: B-1（重複スクリプト）/ B-2（root scripts/ vs skill references/ 二重管理）/ B-3（skill-config 余地）/ B-4（命名揺れ）
対象: `.claude/skills/**` 配下 35 スキル + ルート `scripts/` ディレクトリ

---

## 1. 概要

- **重複クラスタ**: 強重複（hash 完全一致 / 機能完全重複）= 2 件、弱重複（共通スニペット）= 4 件
- **二重管理（B-2）**: ルート `scripts/gcp-bootstrap.sh` / `scripts/gcp-terraform-apply.sh` は `.claude/skills/channel-setup/references/` の **完全コピー**（MD5 一致）。CLAUDE.md「単一 skill からしか呼ばれないものを `scripts/` に残すと、skill の自己完結性が崩れて配布時に取り残される」原則に明確に違反
- **config 外出し候補（B-3）**: 35 スキル中 9 スキルが `config.default.yaml` を既に持つ。残り 26 スキルから **15 件以上の外出し候補** を抽出（5 件以上要求に対して達成）
- **命名揺れ（B-4）**: `references/` 内のファイル命名は概ね一貫しているが、`*-rules.md` / `*-guide.md` / `*-examples.md` / `*-templates.md` の 4 系統で目的別の使い分けが曖昧な箇所が散見される。完全に "同名同責務" の揺れは検出されず（後述）

---

## 2. B-1 重複スクリプト

### クラスタ 1（P1・**強重複**）: GCP bootstrap / terraform-apply のルート ↔ skill 二重配置

| ファイル | 行数 | MD5 |
|---|---|---|
| `scripts/gcp-bootstrap.sh` | 252 | `e421b5dbf74d3a6b2b1d67faa1d1606a` |
| `.claude/skills/channel-setup/references/gcp-bootstrap.sh` | 252 | `e421b5dbf74d3a6b2b1d67faa1d1606a` |
| `scripts/gcp-terraform-apply.sh` | 109 | `358b6bc04f9fd0fa914641e01745a244` |
| `.claude/skills/channel-setup/references/gcp-terraform-apply.sh` | 109 | `358b6bc04f9fd0fa914641e01745a244` |

**重複箇所**: 全行が bit 単位で同一（4 ファイル × 2 ペア）。

**重複根拠**: `.claude/skills/channel-setup/references/gcp-bootstrap.md` の Usage 例にも `scripts/gcp-bootstrap.sh` を案内する記述（line 19）と `SKILL_REF="$(git rev-parse --show-toplevel)/.claude/skills/channel-setup/references"` を案内する記述（line 29）が併記されており、**「どっちを叩くべきか」が文書内で分裂している**。CLAUDE.md は明示的に「skill 固有のスクリプトは `.claude/skills/<skill>/references/` に配置」「ルート `scripts/` には複数の文脈から共有される共通スクリプトのみ」と規定するため、ルート側が削除対象。

**共通化案**: ルート `scripts/gcp-bootstrap.sh` / `scripts/gcp-terraform-apply.sh` を **削除**。`gcp-bootstrap.md` 内 Usage 例は `.claude/skills/channel-setup/references/gcp-bootstrap.sh` へのパスに統一する（`yt-skills sync` で各チャンネル repo に配布される唯一のパス）。

**推奨配置先**: `.claude/skills/channel-setup/references/`（既存）。ルートからは撤去。

---

### クラスタ 2（P2・**弱重複**）: bash 色付きログヘルパー（`log/ok/warn/error`）

| ファイル | 該当行 |
|---|---|
| `.claude/skills/channel-setup/references/gcp-bootstrap.sh` | 54-57（log/ok/warn/error 各 1 行）+ 98, 211（dry-run 紫） |
| `.claude/skills/channel-setup/references/gcp-terraform-apply.sh` | 19-21（log/ok/error） |
| `.claude/skills/streaming/references/swap_video.sh` | 24-26（log/ok/error） |

**重複箇所**: `printf '\033[0;36m[<tag>]\033[0m %s\n' "$*"` 形式の ANSI 色付きログ関数定義が 3 ファイルで完全に同一構造（タグ文字列のみ違う）。

**共通化案**: 規模が小さく（3 ファイル × 4 行）、各スクリプトが独立配置・独立配布される性質上、**現状維持を推奨**。共通化（`lib/log.sh` 等）はかえって配布時の `source` パス解決を増やし、`yt-skills sync` の単純さを壊す。**B-1 として「重複ではあるが共通化非推奨」**として明示する。

**推奨配置先**: 各スクリプト内に inline 維持。ただし規約として SKILL.md / contributing 文書に「shell スクリプト追加時は `log/ok/error` の 3 helper を inline で定義する」というスタイルガイドを追記する余地はある。

---

### クラスタ 3（P3・**弱重複**）: usage helper（`sed -n 'A,Bp' "$0" | sed 's/^# \{0,1\}//'`）

| ファイル | 該当行 |
|---|---|
| `.claude/skills/channel-setup/references/gcp-bootstrap.sh` | 60 |
| `.claude/skills/channel-setup/references/gcp-terraform-apply.sh` | 23 |
| `.claude/skills/streaming/references/swap_video.sh` | 28 |

**重複箇所**: ヘッダコメントから usage を切り出す idiom が 3 ファイルで完全に同一。

**共通化案**: クラスタ 2 と同じ理由で **現状維持**。inline で十分。

---

### クラスタ 4（P3・**部分重複**）: ffmpeg 起動コマンド（`videoup` vs `streaming`）

| ファイル | 用途 |
|---|---|
| `.claude/skills/videoup/references/generate_videos.sh` | 静止画 or loop.mp4 + master 音声 → MP4 |
| `.claude/skills/streaming/references/run-ffmpeg.sh` | 24/7 live stream（VPS 上で systemd 経由） |

**重複箇所**: どちらも `ffmpeg -stream_loop -1 -i <video> ...` を共有するが、**用途・実行コンテキストが完全に異なる**（前者は macOS でローカル動画生成、後者は Vultr VPS 上で `exec` 経由 RTMP push）。コード片の見た目は似るがロジックは独立。

**共通化案**: **非推奨**。ローカル動画生成 vs ライブ配信は責務が異なり、共通化するとコードの可読性が落ちる。B-1 候補としては「重複ではない」と明示。

---

### クラスタ 5（P3・**運用重複**）: `set -euo pipefail` 開始定型

| ファイル数 | 6 ファイル全てで開頭 `set -euo pipefail` |
|---|---|
| 該当 | `gcp-bootstrap.sh` / `gcp-terraform-apply.sh` / `swap_video.sh` / `healthcheck.sh` / `notify.sh` / `worktree_sync.sh` |

**重複箇所**: bash strict mode 宣言の 1 行。

**共通化案**: **不要**。bash の言語要素で共通化対象にすべきものではない。スタイル規約として把握しておく。

---

## 3. B-2 二重管理（ルート `scripts/` ↔ skill `references/`）

### 対応関係マッピング

| ルート `scripts/` | 対応する `.claude/skills/<skill>/references/` | hash 一致 | CLAUDE.md 規約上の判定 |
|---|---|---|---|
| `gcp-bootstrap.sh` | `channel-setup/references/gcp-bootstrap.sh` | ✅ 完全一致 | **ルート側を削除**（単一 skill のみが参照） |
| `gcp-terraform-apply.sh` | `channel-setup/references/gcp-terraform-apply.sh` | ✅ 完全一致 | **ルート側を削除**（単一 skill のみが参照） |

### 二重管理の根拠

- `channel-setup/references/gcp-bootstrap.md`（line 19）で `scripts/gcp-bootstrap.sh` の Usage 案内
- 同 md ファイルの後方（line 29）で `SKILL_REF=...` 経由の skill 内パス案内
- CLAUDE.md 規約: **「単一 skill からしか呼ばれないものを `scripts/` に残すと、skill の自己完結性が崩れて配布時に取り残される」**
- これらは `channel-setup` skill 専用であり、他 skill からは一切参照されていない（grep で確認: `gcp-bootstrap.sh` を直接呼ぶ参照は `channel-setup/references/gcp-bootstrap.md` のみ）

### 解決推奨アクション

1. `scripts/gcp-bootstrap.sh` を削除
2. `scripts/gcp-terraform-apply.sh` を削除
3. `channel-setup/references/gcp-bootstrap.md` の Usage 例から `scripts/gcp-bootstrap.sh` 直書きを削除し、`SKILL_REF` 経由のパスのみに統一
4. ルート `scripts/` ディレクトリは **CLAUDE.md 規約通り「複数 skill 共有スクリプトのみ」** を残す（現状この条件を満たすファイルは 0 件になる → ディレクトリを空にするか、`README.md` で「共通化されたスクリプトのみ置く」ポリシーを明文化）

---

## 4. B-3 skill-config 外出し余地（最低 10 件要求 → 15 件抽出）

### 既存 `config.default.yaml` 保有スキル（参考、対象外）

`benchmark` / `collection-ideate` / `loop-video` / `lyria` / `masterup` / `suno` / `thumbnail` / `video-analyze` / `video-description` （計 9 スキル）

### 外出し候補（26 スキル中 15 件抽出）

| # | skill | 抽出した定数 / 外出し対象 | 想定 YAML キー | 移行コスト |
|---|---|---|---|---|
| 1 | `analytics-collect` | 鮮度判定しきい値「30 分以内ならスキップ」（SKILL.md line 38） | `freshness_minutes: 30` | 小 |
| 2 | `analytics-analyze` | 鮮度判定しきい値「30 分以内に生成されたレポートがあれば分析をスキップ」（SKILL.md line 38） | `freshness_minutes: 30` | 小 |
| 3 | `analytics-report` | HTML レポートのカラーパレット（#0f1419 / #1a2332 / #c8a96e 等、SKILL.md line 92-100 で 8 色固定） / Chart.js 色定義 / fontsize 系 | `html_report.colors.{bg,card,accent,...}` | 中（HTML テンプレ全体の整理を伴う） |
| 4 | `audience-persona` | WebSearch クエリテンプレ（`{genre.primary} music listener demographics` 等の 3 テンプレ、SKILL.md line 38-39） / 関連コミュニティリスト（Reddit, Discord） | `search_queries: [...]` / `community_hints: [...]` | 小 |
| 5 | `channel-direction` | 議論ポイント 7 項目の固定リスト（TTP 対象選定 / ジャンル & スタイル / ターゲット / コンテンツ戦略 / ビジュアルアイデンティティ / 差別化 / チャンネル名）と各項目の説明 | `discussion_points: [...]` | 中（フロー記述の構造化が必要） |
| 6 | `channel-new` | 競合発掘の固定パラメータ「3-5 個（多くて 8 個まで）」「`--min-subscribers 10000 --max-subscribers 1000000`」「`--posted-within-days 30`」「`--top 20`」（SKILL.md line 124-128） | `discovery.{keyword_count_range, default_min_subs, default_max_subs, posted_within_days, top}` | 小 |
| 7 | `discover-competitors` | 上記 channel-new と完全に共通する API パラメータの既定値表（SKILL.md line 87-91） | 同上（共有 config 候補） | 小 |
| 8 | `live-clean` | 削除対象ファイルパターン（`master.mp3` / `master-mix.wav` / `*-Master.mp4` / `02-Individual-music/*.mp3` / `loop_normalized.mp4`）（SKILL.md line 47-51） + 保護対象ファイルパターン | `cleanup.{delete_patterns, protect_patterns}` | 小 |
| 9 | `postmortem` | 症状判定の四分位閾値（0.5 / 0.7 / 0.9）（SKILL.md line 72-78） + 仮説マッピング表の閾値（0.7 倍 / 0.9 倍 / 0.5 倍）（line 86-89） | `thresholds.{red, yellow, light_yellow, healthy}` + `hypothesis_thresholds` | 中（判定ロジックが SKILL.md 内に散在） |
| 10 | `streaming` | systemd ヘルスチェック分類ルール（`ok` / `idle` / `manual` / `anomaly` の 4 値定義）と通知ポリシー（SKILL.md line 82-90 + `healthcheck.sh` の `classify_status()` 関数） | `healthcheck.{state_table, notify_on}` | 大（shell スクリプト側の参照経路も書き換え必要） |
| 11 | `streaming` | cron 例の固定タイミング（毎月 1 日 0:00 / 毎日 6:00、SKILL.md line 94-96） | `cron.{report_schedule, threshold_check_schedule}` | 小 |
| 12 | `streaming` | 帯域目安「1.16 TB / 2 TB プランの 58%」「11h+1h 断続」「4 Mbps → 3 Mbps」（SKILL.md line 98 + 110） | `bandwidth.{monthly_estimate_tb, plan_quota_tb, runtime_max_hours, restart_sec_hours, bitrate_options}` | 中（README との整合性確保が必要） |
| 13 | `thumbnail-compare` | 評価項目 8 軸の固定リスト（アートスタイル / キャラサイズ / 顔の見え方 / 活動の具体性 / 楽器の有無 / テキスト構成 / 明るさ / 再生数相関）（SKILL.md line 32-40） + サムネサイズ「320x180px」（line 22） | `evaluation_axes: [...]` + `small_thumbnail_size: {w, h}` | 小 |
| 14 | `video-upload` | API ステータス固定設定 `selfDeclaredMadeForKids: false` / `containsSyntheticMedia: true`（SKILL.md line 107-109） / YouTube タイトル長制限「100文字」 / NG ワード列挙（Epic, Ultimate） | `upload.api_status.{...}` + `metadata.{max_title_length, forbidden_words}` | 小 |
| 15 | `video-description` | 必須要素のハッシュタグ数「13個」（SKILL.md line 89, 107） / 最小チャプター数「3」（line 59, 90） / Cards の固定タイミング `12:00` は既に config 化済みだが、これらの追加値は未 config 化 | 既存 `config.default.yaml` に追記: `tags.hashtag_total: 13` + `timestamps.min_chapters: 3` | 小 |

### 追加で抽出した候補（参考、低優先度）

| # | skill | 抽出した定数 | 想定 YAML キー | 移行コスト |
|---|---|---|---|---|
| 16 | `wf-new` | track count デフォルト「12」（SKILL.md line 50） | `default_track_count: 12` | 小 |
| 17 | `metadata-audit` | タイムスタンプ数判定の上下限「< 3」「> 12」（SKILL.md line 37, 47） | `validation.{min_chapters, max_chapters}` | 小 |
| 18 | `playlist` | 自動 assign の表示順ルール（`"all"` は末尾追加、それ以外は先頭追加）（SKILL.md line 66-67） | `assignment.{all_position, default_position}` | 小 |
| 19 | `viewing-scene` | WebSearch キーワードテンプレ（`{genre.primary} music for study` / `{genre.style} music for work` / `作業用BGM {genre.primary}`、SKILL.md line 47） | `search_queries: [...]` | 小 |

### B-3 まとめ

- **即効性が高い候補**（移行コスト「小」+ 単一値外出し）: #1, #2, #6, #7, #8, #11, #13, #15, #16, #17, #18 → 11 件
- **構造変更が必要な候補**（移行コスト「中〜大」）: #3, #5, #9, #10, #12 → 5 件
- **共通化候補**: #6 と #7 は完全に同じ API パラメータデフォルトを別々に持つため、`config.default.yaml` を共有または `channel-new` から `discover-competitors` を参照するパターンに統一すべき

---

## 5. B-4 命名揺れ（`references/` 内ファイル名）

### 走査結果

`.claude/skills/**/references/` 配下の全ファイル（25 ファイル）を走査した結果、以下のパターンが検出された:

| パターン | 該当ファイル | 命名一貫性 |
|---|---|---|
| `*-template*.md` | `channel-setup/references/claude-md-template.md`, `channel-setup/references/config-template/*.json`, `video-description/references/description-templates.md` | 単数 vs 複数（`template.md` vs `templates.md`）の揺れあり |
| `*-rules.md` | `collection-ideate/references/freshness-rules.md`, `channel-setup/references/config-generation-rules.md` | 一貫（`<対象>-rules.md`） |
| `*-examples.md` | `collection-ideate/references/object-design-examples.md`, `suno/references/lyrics-examples.md`, `suno/references/suno-examples.md` | 一貫（`<対象>-examples.md`） |
| `*-guide.md` | `lyria/references/lyria-tuning-guide.md` | 1 件のみ（揺れなし） |
| `*-checklist.md` / `*-structure.md` / `verification.md` 等 | 各 1 件 | 揺れなし |

### 具体的な命名揺れ（plan.md の例: `prompt.md` vs `prompts.md`, `template.md` vs `templates/`）

- **`template.md` vs `templates.md` の揺れ**:
  - `channel-setup/references/claude-md-template.md`（単数）
  - `video-description/references/description-templates.md`（複数）
  - **どちらも 1 ファイルだが、後者は「複数テンプレを束ねる」意図のため複数形を採用**したものと推測される。差異が意図的か否かを判定するには中身比較が必要（後述）

- **`prompt.md` vs `prompts.md` の揺れ**:
  - **検出なし**。`.claude/skills/**/references/` 内に `prompt.md` / `prompts.md` という名前のファイルは存在しない

- **`template.md` vs `templates/` の揺れ**:
  - `channel-setup/references/config-template/`（ディレクトリ、JSON 4 ファイル収容）
  - `channel-setup/references/claude-md-template.md`（単一 md）
  - `video-description/references/description-templates.md`（単一 md だが内部にテンプレ多数）
  - **揺れあり**: 「単一テンプレを md 1 つで持つ」「複数テンプレをディレクトリで持つ」「複数テンプレを 1 つの md にまとめる」の 3 様式が共存

### 命名揺れの統一案

| 用途 | 推奨命名 | 補足 |
|---|---|---|
| 単一テンプレ md | `<対象>-template.md`（単数） | 例: `claude-md-template.md` ✅ |
| 複数テンプレを 1 md に束ねる | `<対象>-templates.md`（複数） | 例: `description-templates.md` ✅ |
| 複数テンプレを別 file で並べる | `<対象>-templates/` ディレクトリ | 例: `config-template/` → `config-templates/` に rename することで複数形 + ディレクトリ化が一致 |
| ルール | `<対象>-rules.md` | 一貫済み |
| 例示 | `<対象>-examples.md` | 一貫済み |
| ガイド | `<対象>-guide.md` | 一貫済み |

→ **唯一の改善対象**: `channel-setup/references/config-template/`（4 JSON 収容）を `config-templates/` にリネーム。これで「ディレクトリ = 複数形」のルールが揃う。**ただし `yt-skills sync` 配布パスへの影響と `channel-setup/SKILL.md` 本文の書き換えコストが発生するため、優先度は P3**。

---

## 6. 主要な発見のサマリー（影響度の高い 3〜5 件）

### S-1（影響度: 高、優先度: P1）
`scripts/gcp-bootstrap.sh` および `scripts/gcp-terraform-apply.sh` が `.claude/skills/channel-setup/references/` と **MD5 単位で完全重複**。CLAUDE.md 規約に明確に違反しており、配布時に取り残されたコピーをユーザーが叩く事故の温床。**削除アクション 1 つで解消可能**で工数が極小。

### S-2（影響度: 中、優先度: P2）
26 スキル中 **15 件以上で skill-config 化候補がある**。特に `analytics-collect` / `analytics-analyze` の鮮度しきい値「30 分」、`postmortem` の四分位閾値、`live-clean` のファイルパターン、`channel-new` / `discover-competitors` の API パラメータデフォルトはチャンネル単位で運用が変わる典型的な可変設定であり、外出ししないとチャンネル固有チューニングのたびに SKILL.md を直接書き換える状況になる。

### S-3（影響度: 中、優先度: P2）
`channel-new` と `discover-competitors` で **完全に同一の API パラメータデフォルト**（min_subscribers, max_subscribers, posted_within_days, top, per_keyword）が別々の SKILL.md 内に記述されている。`discover-competitors` 側に `config.default.yaml` を作って `channel-new` がそれを参照する形に整理すべき。

### S-4（影響度: 中、優先度: P2）
`streaming` skill の `healthcheck.sh` 内に 4 状態分類（ok / idle / manual / anomaly）と通知ポリシーが **shell 関数 + state file 経路で固定実装**されている。チャンネル/オペレーター単位で「manual を anomaly 扱いにしたい」「特定状態だけ通知 OFF にしたい」などのカスタムを入れるには現状 shell を直接編集する必要があり、skill-config 化の恩恵が大きい。ただし shell スクリプト経由参照のため移行コストは大。

### S-5（影響度: 低、優先度: P3）
shell スクリプト 3 ファイル（gcp-bootstrap.sh / gcp-terraform-apply.sh / swap_video.sh）で `log/ok/error` の ANSI 色付き helper と `sed -n ... usage()` idiom が重複しているが、共通化はかえって配布の単純さを壊すため **共通化非推奨**。スタイル規約として明文化する程度に留める。

---

## 7. カバレッジ

### 走査済み（全 35 スキル）

```
alignment-check / analytics-analyze / analytics-collect / analytics-report / audience-persona /
benchmark / channel-direction / channel-import / channel-new / channel-research /
channel-setup / channel-status / collection-ideate / comments-reply / discover-competitors /
live-clean / loop-video / lyria / masterup / metadata-audit /
playlist / postmortem / streaming / suno / thumbnail /
thumbnail-compare / video-analyze / video-description / video-upload / videoup /
viewer-voice / viewing-scene / wf-new / wf-next / wf-status
```

### 走査ファイル種別

- SKILL.md: 35 ファイル（全件）
- `references/*.sh`: 8 ファイル（全件）
- `references/*.py`: 0 ファイル（存在せず → B-1 で `.py` レベルの skill 内重複は検出 0 件）
- `references/*.md`: 16 ファイル（全件）
- `references/*.json`: 7 ファイル（全件）
- `references/*.yaml` / `config.default.yaml`: 9 ファイル（全件、B-3 既存 config 確認のため）
- ルート `scripts/`: 2 ファイル（全件、B-2 二重管理確認のため）

### 走査しなかった範囲（意図的除外）

- `src/youtube_automation/` 配下の Python 実装本体（タスク対象は skill 内のみ）
- `infra/terraform/streaming/` の Terraform モジュール（B-1 範囲外）
- `examples/` / `tests/`（タスク対象外）

---

## 8. 注意点・リスク

### 過剰な共通化リスク

- **shell helper 共通化**（クラスタ 2/3）: `lib/log.sh` 化すると `yt-skills sync` の配布経路と `source` パス解決が複雑化する。`channel-setup/references/gcp-bootstrap.sh` 等は単独で完結する必要があり、共通化非推奨。
- **B-3 で抽出した候補の中には「意図的に SKILL.md 内に書いている」値**が含まれる可能性がある。例えば `audience-persona` の WebSearch クエリテンプレは「AI に対する指示文」の一部であり、外出しすると AI が読まなくなるリスクがある。skill-config 化する際は「AI が読む文章 vs 機械的パラメータ」を切り分ける必要がある。
- **`postmortem` の閾値外出し**（候補 #9）は移行コスト「中」だが、SKILL.md 本文中に「閾値は固定値ではなく文脈調整可」と明記されている部分があるため、外出し後も SKILL.md 内に「閾値は config 上書き可能だがチャンネル特性で動的調整可」と明記する必要がある。

### 現状で意図的に分けている可能性

- `channel-setup/references/config-template/` がディレクトリ形式（複数 JSON）になっているのは、チャンネルセットアップで 4 種の責務別 config を同時生成するため。**意図的なディレクトリ化**であり、命名揺れ B-4 の優先度を下げる根拠になる。
- ルート `scripts/gcp-bootstrap.sh` が残っている理由は **既存ドキュメントの URL 互換性**かもしれない（git 履歴を見ていないため確証なし）。削除する際は CLAUDE.md / README.md / 外部 issue/PR からの参照リンクを破壊しないか確認が必要。

### 移行時の互換性懸念

- ルート `scripts/gcp-bootstrap.sh` 削除は、**チャンネル repo 側の運用ドキュメント**（各チャンネル repo の README 等）が `scripts/gcp-bootstrap.sh` を直書き参照している場合に破壊的変更となる。削除前に下流チャンネル repo を grep するべき（ただし下流 repo は本タスクの調査対象外）。

---

## 9. 調査不可項目とその理由

| 項目 | 理由 |
|---|---|
| **B-1 内、ハッシュ完全一致以外の機能重複**（例: SKILL.md 本文の表現重複） | grep ベースで「機能的に同じことをやっている記述」を抽出するには意味論的解析が必要。本タスクは「行数 + 主要 token の一致」レベル指定のため、`description:` 冒頭文や Phase 構造の重複は意図的にスコープ外（→ Part C で扱う領域） |
| **B-3 のチャンネル運用実態に基づく優先度**（実際にチャンネル単位でカスタムしたい頻度） | 利用ログや git 履歴を見ていないため「過去 1 年で何回上書きされたか」のデータがない。優先度は SKILL.md 内記述の「カスタム推奨」記述の有無で代替判定した |
| **`utils/config/loader.py::load_skill_config()` を実際に呼んでいる skill の網羅リスト**（plan.md B-4 相当） | 本タスクは観点 1.2 + 1.3 を担当する dig-part-b の範囲指定であり、`src/youtube_automation/` 配下のコード走査は範囲外。`config.default.yaml` ファイルの有無から間接判定した |

---

## 10. 推奨／結論（優先度付き）

### P1（最終レポートに必ず含めるべき提案）

- **R-1**: `scripts/gcp-bootstrap.sh` および `scripts/gcp-terraform-apply.sh` を **削除**。`channel-setup/references/gcp-bootstrap.md` 内の Usage 例を `SKILL_REF` 経由のパスに統一する。CLAUDE.md 規約と一致させ、配布時に取り残されるリスクを排除。**工数極小、効果高**。

### P2（強く推奨）

- **R-2**: `analytics-collect` / `analytics-analyze` に `config.default.yaml` を追加し、鮮度判定しきい値「30 分」を外出し。両 skill で同一の値を使っているため、できれば 1 つの共有 config（`analytics-common.yaml` 等）に集約する案も検討。
- **R-3**: `discover-competitors` に `config.default.yaml` を追加し、API パラメータデフォルト（min_subs / max_subs / posted_within_days / top / per_keyword）を外出し。`channel-new` Step 5 もこの config を参照する形に統一。
- **R-4**: `live-clean` に `config.default.yaml` を追加し、削除対象パターン / 保護対象パターンを外出し。チャンネルごとに「個別トラックは残したい」「マスタービデオは残したい」などの運用差を吸収。
- **R-5**: `video-upload` に `config.default.yaml` を追加し、`selfDeclaredMadeForKids` / `containsSyntheticMedia` / NG ワードリストを外出し。AI 申告ポリシーは将来的に YouTube 側仕様変更が予想されるため、config 化しておくと変更時の追従が楽。

### P3（あれば良い）

- **R-6**: `postmortem` の四分位閾値（0.5 / 0.7 / 0.9）を `config.default.yaml` に外出し。ただし「文脈調整可」記述を残す。
- **R-7**: `streaming` の cron 例タイミング・帯域目安値を `config.default.yaml` に外出し。`healthcheck.sh` の状態分類ルールは移行コストが大きいため、まずは「分類ルールの 4 値と通知 ON/OFF 表のみ」を config 化する段階的アプローチを推奨。
- **R-8**: `channel-setup/references/config-template/` を `config-templates/` にリネーム（命名揺れ統一）。`SKILL.md` 本文と `yt-skills sync` 配布経路の同時更新が必要。
- **R-9**: `audience-persona` / `viewing-scene` の WebSearch クエリテンプレを `config.default.yaml` に外出し。ただし「AI が読む文章」要素を切り分けて、AI 指示文は SKILL.md に残し、テンプレ文字列のみ config 側に移す。

### 非推奨（明示）

- **R-X (non-recommend)**: shell helper（`log/ok/error` / `usage()` idiom）の共通化は **行わない**。配布の単純さを優先し、各 shell スクリプト内 inline 維持。
- **R-Y (non-recommend)**: `videoup/generate_videos.sh` と `streaming/run-ffmpeg.sh` の ffmpeg 経路統合は **行わない**。用途・実行環境が完全に異なるため。
