# workflow チートシート

`/wf-auto` `/wf-new` `/wf-next` `/wf-status` `/collection-ideate` と `workflow-state.json` の使い分けを 1 枚で。**迷ったらまずこのファイル**。

> Skill 全体のカタログは [`docs/features.md`](features.md) を参照。

## いまどの skill を呼ぶ？（判定フロー）

```
ユーザーの問い                       → 呼ぶ skill
────────────────────────────────────────────────
「次なに作る？」「テーマ候補が欲しい」  → /collection-ideate   （企画候補を提案する）
「企画から公開後処理まで全部進めて」      → /wf-auto             （新規開始または未完了地点から完走）
「新しいコレクション始めたい」          → /wf-new              （企画選択 → ディレクトリ作成 → 素材準備）
「制作中のやつ、次のステップやって」    → /wf-next             （phase に応じて次工程を 1 段実行）
「どこまで進んだ？読むだけ」           → /wf-status           （実行はしない・読み取り表示のみ）
```

別の言い方をすると：

| ユーザーの状況 | 使う skill |
|---|---|
| collection の有無を問わず **企画から公開後処理まで進めたい** | `/wf-auto`（正規入口） |
| 制作中コレクションが **無い** + 企画候補も **無い** | `/collection-ideate` → 候補が決まったら `/wf-new` |
| 制作中コレクションが **無い** + 企画候補は **頭にある** | `/wf-new`（その中で `/collection-ideate` が走る） |
| 制作中コレクションが **ある** + 進める意思がある | `/wf-next` |
| 制作中コレクションの **現在地だけ知りたい** | `/wf-status` |

## 5 つの skill の責務早見表

| Skill | 何をする | 何をしない | 一時停止する場面 |
|---|---|---|---|
| `/wf-auto` | collection 不在なら `/wf-new` から開始し、存在すれば未完了地点から制作・公開・post-publish まで状態駆動で再評価する | 子 skill の実装を複製しない | 認証、CAPTCHA、承認待ち、公開未許可など人間の介入が必要な場面 |
| `/collection-ideate` | analytics mode / benchmark fallback mode、または `ttp_mode: false` の minimal mode の入力でペルソナ別 3 企画候補を生成 | コレクションディレクトリは作らない | 提案表示のみ（選択は `/wf-new` 側で）。`ttp_mode: true` の minimal mode は `/benchmark` を案内して停止 |
| `/wf-new` | 企画選択 → `yt-init-collection` でディレクトリ + `workflow-state.json` 作成 → サムネ・音楽素材生成 | 楽曲の最終マスタリングや動画化はしない | 通常は (1) 企画選択 (2) サムネ承認。`ttp_mode: false` の minimal mode は企画候補生成前にテーマ / ジャンル / 雰囲気の直接入力確認を追加し、`true` は `/benchmark` の案内で停止 |
| `/wf-next` | `workflow-state.json::phase` に応じて次工程を 1 段実行（Suno DL / Lyria 生成 / 動画化 / アップロード） | 新規コレクションは作らない | マスター音源が無い phase = "prepared" 状態（ユーザーがミキシング+マスタリングを行う） |
| `/wf-status` | `collections/planning/*/workflow-state.json` の現在地を一覧・詳細表示 | **実行系は一切呼ばない** | なし |

## 制作の 3 フェーズと skill の流れ

`/wf-new` と `/wf-next` はオーケストレーターとして動作する。各 phase の生成・変換処理は Agent ツールで一作業ずつ subagent へ委譲し、メインエージェントは `workflow-state.json` の管理、AskUserQuestion / config 駆動の承認ゲート、成果物の存在・phase 整合検証を担当する。subagent は state を書き込まず、承認を取得しない。

subagent が失敗した、期待成果物が無い、または現在の phase と整合しない場合、メインは state を更新しない。次の `/wf-new` / `/wf-next` は同じ未完了ステップから再開する。`approval_gates.audio` / `approval_gates.upload`、`skip_manual_mastering`、thumbnail 承認、playlist 初期化承認は従来どおりメインが config と実ファイルを確認して処理する。

```
Phase 1 ─ 企画 + 素材準備           /wf-new
   ├─ /collection-ideate            (analytics mode / benchmark fallback mode、または ttp_mode=false の minimal mode で 3 候補生成)
   ├─ yt-init-collection             (ディレクトリ + workflow-state.json 作成)
   ├─ /thumbnail   または main.png    (サムネ確定)
   ├─ /suno もしくは /lyria          (音楽プロンプト or 設計)
   └─ /loop-video                    (背景ループ動画)
                          ↓ phase: "prepared"
Phase 2 ─ 制作                      /wf-next
   ├─ Suno パス: /masterup           (Suno UI で人手生成 → DL + クロスフェード)
   └─ Lyria パス: /lyria             (Lyria 3 API でセグメント生成)
                          ↓ raw_master 配置 → ユーザーが mixing+mastering
                          ↓ 最終マスターを 01-master/ に配置
                          ↓ phase: "mastered"
Phase 3 ─ 公開（全自動）             /wf-next
   ├─ /videoup           (動画生成)
   ├─ /video-description (概要欄)
   └─ /video-upload      (YouTube アップロード + planning/ → live/ 移行)
                          ↓ phase: "complete"
振り返り（T+7 日後推奨）             /analytics-analyze
```

## `workflow-state.json` の扱い

### 配置と役割

- **配置**: `collections/planning/<YYYYMMDD-short-theme>-collection/workflow-state.json`
- **役割**: コレクションの phase / assets / upload 状態を持つ単一の真実源（single source of truth）
- **更新主体**: **`/wf-new` `/wf-next` を実行するメインエージェントだけが更新する**（`updated_at` / `phase` / `assets` / `upload`）。実作業を担う subagent は読み取りが必要な場合を除き state に触れず、書き込まない

### 手で触っていい？ ダメ？

| 操作 | OK / NG | 理由 |
|---|---|---|
| `/wf-status` で **眺める** | ✅ OK | 読み取りなので副作用ゼロ |
| `phase` を手で書き換える | ❌ NG | skill 側が更新するので競合する。「中断して別 phase からやり直したい」なら `/wf-next` を呼ぶ |
| `assets.*` フラグを手で書き換える | ⚠️ NG（原則） | 冪等性の前提が崩れ、未完了ステップ判定が壊れる。誤って `true` にすると skill が当該ステップをスキップする |
| `planning.music.*`（mood / tempo / instruments 等）を手で編集 | ⚠️ 限定 OK | `/suno` や `/lyria` 実行**前**に微調整するのは可。実行**後**に書き換えると音源との整合が崩れる |
| `title_template_check.allow_volume_patterns: true` を追加 | ⚠️ 限定 OK | `Vol.` / `Part` / `#N` / ローマ数字による意図的なシリーズ名を公開タイトルに使うコレクションだけに記録する。未設定は既定どおり検出し、他のタイトル鋳型チェックは緩和しない |
| `upload.video_id` を手で書き換える | ❌ NG | YouTube 側との整合が崩れる |
| ファイル全体を **削除** する | ⚠️ 慎重に | コレクションをやり直すなら可。ただしディレクトリも一緒に消した方が安全 |

> **基本方針**: `workflow-state.json` は **AI が管理するもの** と見なし、ユーザーは `/wf-status` で読むだけにする。手で編集したくなったら、まず「同じ結果を skill 経由で達成できないか」を考える。

### スキーマ全体

フィールド定義（`stage` / `phase` / `assets.*` / `upload.*` / `planning.music.*`）は `.claude/skills/wf-new/references/schema.md` を参照。

## よくある質問

**Q. `/wf-new` で企画選択した後、別の企画にしたい**
A. `collections/planning/<dir>/` ごと削除して `/wf-new` をやり直す（`workflow-state.json` だけ書き換えても 10-assets/ の素材と整合しない）。

**Q. `/wf-next` を呼んだら何も起きない**
A. `phase: "prepared"` で `raw_master` 配置済み + `master_audio` 未配置の場合、**ユーザーが mixing+mastering を完了して `01-master/` に最終マスターを置く** ことが次の前提。`/wf-status` で詳細を見ると「ミキシング+マスタリング待ち」と表示される。raw master をそのまま公開する運用なら次項の `skip_manual_mastering` を参照。

**Q. raw master をそのまま最終マスターとして使いたい（外部 DAW でのマスタリング不要）**
A. `config/channel/workflow.json` に `workflow.wf_next.skip_manual_mastering: true` を設定する。`/wf-next` のマスター音源検出（2-B）で `01-master/` に別ファイルが見つからなくても、`assets.raw_master` をそのまま `assets.master_audio` として採用し `phase: "mastered"` へ自動で進む（毎回 `workflow-state.json` を手で編集する必要はない）。`approval_gates.audio` は「採用前に確認プロンプトを出すか」だけを制御する別設定で、こちらを `true` にしても raw=final の自動採用は有効にならない。

```json
{
  "workflow": {
    "wf_next": {
      "skip_manual_mastering": true
    }
  }
}
```

**Q. `/wf-next` がエラーで止まった**
A. `phase: "publishing"` で停止していれば、`assets` フラグの状態から未完了ステップを特定し、`/wf-next` をもう一度呼ぶと未完了ステップから再開する（冪等性あり）。

**Q. analytics やベンチマークが無いと `/collection-ideate` は止まる？**
A. `reports/analysis_*.md` が無い場合、`data/benchmark_*.json` があれば benchmark fallback mode で続行する。どちらも無ければ minimal mode として `ttp_mode` を確認する。minimal mode では企画候補生成前にテーマ / ジャンル / 雰囲気を直接確認する既存挙動は `ttp_mode: false` の場合だけ適用し、`true` は転写元が無いため `/benchmark` を案内して停止し、`data/benchmark_*.json` 生成後に再実行する。analytics mode へ進めるのは、ファイル名日付が最新の Markdown と同日付 JSON が揃い、analysis JSON validator が成功し、ペアが stale でない場合だけ。Markdown があるのに同日付 JSON がない、または validator が失敗する場合は fallback せず停止する。stale の判定と更新手順は `.claude/skills/collection-ideate/references/freshness-rules.md::stale report の自動更新` を正とし、`/wf-new` は独自に再定義しない。相対 stale は `/analytics-analyze`、絶対 stale は `/analytics-collect` → `/analytics-analyze` を追加確認なしで同じ subagent 作業内に自動実行する。全呼び出し後に Markdown / JSON 同日付ペア、validator、相対・絶対鮮度、入力モードを先頭から再検証し、成功時は中断せず企画フローを続ける。skill 呼び出しまたは再検証に失敗した場合は、失敗した skill / 検証項目、理由、`/wf-new` の再開条件を表示し、古い report を採用せず停止する。fresh / benchmark fallback mode / minimal mode では stale 更新用の Analytics skill を追加で呼ばない。`yt-doctor` の入力モード表示は Markdown と stale の予備確認であり、JSON/validator の最終 Hard Gate には使わない。`freshness_days` は `.claude/skills/collection-ideate/config.default.yaml` の既定 7 日を使い、`config/skills/collection-ideate.yaml` で上書きできる。

**Q. 「planning/」と「live/」って何**
A. 制作中は `collections/planning/<dir>/`、`/video-upload` で公開完了すると `collections/live/<dir>/` に移動する（`/wf-next` の Phase 3 最後）。
