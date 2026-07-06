# workflow チートシート

`/wf-new` `/wf-next` `/wf-status` `/collection-ideate` と `workflow-state.json` の使い分けを 1 枚で。**迷ったらまずこのファイル**。

> Skill 全体のカタログは [`docs/features.md`](features.md) を参照。

## いまどの skill を呼ぶ？（判定フロー）

```
ユーザーの問い                       → 呼ぶ skill
────────────────────────────────────────────────
「次なに作る？」「テーマ候補が欲しい」  → /collection-ideate   （企画候補を提案する）
「新しいコレクション始めたい」          → /wf-new              （企画選択 → ディレクトリ作成 → 素材準備）
「制作中のやつ、次のステップやって」    → /wf-next             （phase に応じて次工程を 1 段実行）
「どこまで進んだ？読むだけ」           → /wf-status           （実行はしない・読み取り表示のみ）
```

別の言い方をすると：

| ユーザーの状況 | 使う skill |
|---|---|
| 制作中コレクションが **無い** + 企画候補も **無い** | `/collection-ideate` → 候補が決まったら `/wf-new` |
| 制作中コレクションが **無い** + 企画候補は **頭にある** | `/wf-new`（その中で `/collection-ideate` が走る） |
| 制作中コレクションが **ある** + 進める意思がある | `/wf-next` |
| 制作中コレクションの **現在地だけ知りたい** | `/wf-status` |

## 4 つの skill の責務早見表

| Skill | 何をする | 何をしない | 一時停止する場面 |
|---|---|---|---|
| `/collection-ideate` | analytics mode / benchmark fallback mode / minimal mode の入力でペルソナ別 3 企画候補を生成 | コレクションディレクトリは作らない | 提案表示のみ（選択は `/wf-new` 側で） |
| `/wf-new` | 企画選択 → `yt-init-collection` でディレクトリ + `workflow-state.json` 作成 → サムネ・音楽素材生成 | 楽曲の最終マスタリングや動画化はしない | 通常は (1) 企画選択 (2) サムネ承認。minimal mode は企画候補生成前にテーマ / ジャンル / 雰囲気の直接入力確認を追加 |
| `/wf-next` | `workflow-state.json::phase` に応じて次工程を 1 段実行（Suno DL / Lyria 生成 / 動画化 / アップロード） | 新規コレクションは作らない | マスター音源が無い phase = "prepared" 状態（ユーザーがミキシング+マスタリングを行う） |
| `/wf-status` | `collections/planning/*/workflow-state.json` の現在地を一覧・詳細表示 | **実行系は一切呼ばない** | なし |

## 制作の 3 フェーズと skill の流れ

```
Phase 1 ─ 企画 + 素材準備           /wf-new
   ├─ /collection-ideate            (analytics mode / benchmark fallback mode / minimal mode で 3 候補生成)
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
- **更新主体**: 原則として **`/wf-new` `/wf-next` の skill が自動更新する**（`updated_at` / `phase` / `assets` / `upload`）

### 手で触っていい？ ダメ？

| 操作 | OK / NG | 理由 |
|---|---|---|
| `/wf-status` で **眺める** | ✅ OK | 読み取りなので副作用ゼロ |
| `phase` を手で書き換える | ❌ NG | skill 側が更新するので競合する。「中断して別 phase からやり直したい」なら `/wf-next` を呼ぶ |
| `assets.*` フラグを手で書き換える | ⚠️ NG（原則） | 冪等性の前提が崩れ、未完了ステップ判定が壊れる。誤って `true` にすると skill が当該ステップをスキップする |
| `planning.music.*`（mood / tempo / instruments 等）を手で編集 | ⚠️ 限定 OK | `/suno` や `/lyria` 実行**前**に微調整するのは可。実行**後**に書き換えると音源との整合が崩れる |
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
A. `reports/analysis_*.md` が無い場合は止まらず、`data/benchmark_*.json` があれば benchmark fallback mode、どちらも無ければ minimal mode で進む。minimal mode では企画候補生成前にテーマ / ジャンル / 雰囲気を直接確認する。`reports/analysis_*.md` が stale（最新 `data/analytics_data_*.json` より古い、または収集データ自体が実行日から解決済み `freshness_days` を超えて経過）の場合だけ fallback せず、`/analytics-analyze` 再実行（絶対鮮度 stale では `/analytics-collect` を先行）を案内して止まる。`freshness_days` は `.claude/skills/collection-ideate/config.default.yaml` の既定 7 日を使い、`config/skills/collection-ideate.yaml` で上書きできる。

**Q. 「planning/」と「live/」って何**
A. 制作中は `collections/planning/<dir>/`、`/video-upload` で公開完了すると `collections/live/<dir>/` に移動する（`/wf-next` の Phase 3 最後）。
