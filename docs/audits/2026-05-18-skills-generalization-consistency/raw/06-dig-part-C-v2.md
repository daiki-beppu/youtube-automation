# Data Consistency Audit — `.claude/skills/**/SKILL.md`

担当: dig.dig-part-c（観点 2.1〜2.4 = C-1 〜 C-4）
対象: `/Users/mba/02-yt/takt-worktrees/20260518T0804-353-issue-353-chore-skills-sukiru/.claude/skills/**/SKILL.md` 全 35 件
読み取り日: 2026-05-18

---

## 1. 概要 — 検出件数サマリ

| 観点 | 内容 | 検出件数 | 優先度 |
|---|---|---|---|
| **C-1** | description ↔ 実装乖離 | **3 件**（major 1・minor 2） | P1 |
| **C-2** | バトン双方向整合 — 不整合ペア | **片方向参照のみのペア 14 組**（意図あり 10・要修正 4） | P1 |
| **C-3** | deprecated `short` / `community` 参照（workflow.json 由来） | **0 件**（混同候補 13 件 → 全て無関係と判定） | P1 |
| **C-4** | description 形式の揺れ | スタイル分類 5 + 開始句完全統一（35/35）+ 長さ約 4× の差 | P2 |

最大の発見:

- **`/video-analyze` SKILL.md の「呼び出し側スキル」セクションが /lyria・/channel-direction で「使われている」と書いているが、両 SKILL.md には対応する処理が無い**（C-1 #1）。  
- **`/lyria` の出力 (`01-master/master.wav`) と `/masterup` の出力 (`01-master/master.mp3`) が `/videoup`/`generate_videos.sh` の検出パターン (`master-mix.{wav,…}` + `*-Master.mp3` フォールバック) のいずれにもマッチしない**ため、`/wf-next` を経由しない素直なバトン（lyria → videoup, masterup → videoup）はドキュメント通りには動かない可能性（C-1 #2 / C-2 補足）。
- description は全 35 件が `Use when …` で揃っていて開始句は完全統一だが、末尾の指示語（「必ず使用すること」/「使用すること」/「〜と書かれた cross-ref note」など）が **5 系統**に揺れている（C-4）。

---

## 2. C-1 — description ↔ 実装乖離

評価軸: SKILL.md の description（YAML frontmatter）が宣言した機能・責任範囲と、本文・スクリプト実装の整合。

| # | skill | description 抜粋 | 実装の該当 / 不在 | 乖離の種類 |
|---|---|---|---|---|
| C-1.1 | **`/video-analyze`** ↔ **`/lyria`** / **`/channel-direction`** | `/video-analyze` Overview 末尾: 「`/benchmark`・`/analytics-analyze`・`/alignment-check`・`/thumbnail-compare`・`/viewer-voice` の精度を底上げする」+ 本文「呼び出し側スキル」: `/channel-direction` Step 1 と Step 2 議論ポイント 6・Step 3 決定事項「BGM 構造方針」で `bgm_arc` 平均を使う／`/lyria` Step 2「ベンチマーク BGM 構造の参照」で `composition.json` のフェーズ境界の初期値として活用する | `/channel-direction` Step 1 は `docs/channel-research.md` のみを読み込み `bgm_arc` 言及なし。Step 2 議論ポイント 6 は「差別化ポイント」、Step 3 決定事項テーブルに「BGM 構造方針」行なし。`/lyria` 全文に `bgm_arc` / `composition.json` / `phase.at_min` の記述ゼロ（grep 確認済み） | **矛盾／過剰記述** — `/video-analyze` 側が他スキルの仕様を一方的に宣言しているが、相手 SKILL.md にその実装が無い |
| C-1.2 | **`/video-upload`** | description: 「Complete Collection のアップロードと live 移行を実行」 | 本文 Channel Adaptation セクションは `collection` 型 + `single_release` 型（JP+EN 同日 2 本アップ、`yt-upload-auto` 使用）を扱う。description は `single_release` を全く触れていない | **過少記述（minor）** — description が `collection` 型のみ前提に読める。`single_release` チャンネルが description で自スキル発火を期待しにくい |
| C-1.3 | **`/analytics-report`** | description: 「Analytics分析レポートの表示・閲覧が必要なとき」「既存レポートの参照・比較が必要な場面で必ず使用すること」 | 本文 Quick Reference は `latest` / `list` / `html` の 3 モード。`html` は「データ集約 + Chart.js ビジュアルレポート生成」で**新規生成**の責務がある（line 44-110） | **過少記述（minor）** — description は「表示・閲覧」しか書いていないが、`html` モードは「全 analytics スナップショット + benchmark を集約して HTML を新規生成」する。トリガーワードに「ビジュアル」「ダッシュボード」「HTML レポート生成」が無い |

C-1 で**特に問題ない**例（参考、35 件中の代表）: `/streaming`（description に並べた 12 個のキーワードが全て §1-5 にカバーされる）、`/postmortem`（description 末尾の「`/thumbnail-compare` `/alignment-check` `/viewer-voice` `/video-analyze` 等の既存スキルへバトンする」が Phase 4 表に厳密に対応）、`/masterup`（前工程 / 次工程の明示がそのまま Overview に展開）。

---

## 3. C-2 — バトンの双方向整合性

抽出方針: SKILL.md 本文の **「前工程」「次工程」「前フェーズ」「次フェーズ」「Next Step → /X」「Cross References」**、および description 内の「/X の後」「/X の前」を手掛かりに 1 次バトンペアを抽出。`→` 記号での `/X` 参照も対象。

### 3.1 対照表（A → B 参照と B → A 参照）

| # | A | B | A → B 参照根拠 | B → A 参照根拠 | 整合 |
|---|---|---|---|---|---|
| 1 | `/channel-new` | `/channel-research` | Step 7 「次は /channel-research」+ Cross Refs | Cross Refs「/channel-new → 前フェーズ」+ Overview | ✓ 双方向 |
| 2 | `/channel-research` | `/channel-direction` | Step 7 + Cross Refs | description「/channel-research の分析結果をもとに」+ Cross Refs + Step 1 が `docs/channel-research.md` を読む | ✓ 双方向 |
| 3 | `/channel-direction` | `/channel-setup` | Step 5「次は /channel-setup」+ Cross Refs | description「/channel-direction で方向性が確定し」+ Step 1 が `channel-direction.md` を読む + Cross Refs「/channel-direction → 前フェーズ」 | ✓ 双方向 |
| 4 | `/channel-setup` | `/wf-new` | Step 8.5「初回コレクション制作: /wf-new」+ Cross Refs | 前提「config/channel/ が存在すること」止まり（/channel-setup 名指しなし） | △ 片方向（意図あり: /wf-new は複数経路エントリ） |
| 5 | `/channel-import` | `/wf-new` | Step 8.5「コレクション制作: /wf-new」+ Cross Refs | 同上（/channel-import 名指しなし） | △ 片方向（同上） |
| 6 | `/wf-new` | `/wf-next` | Cross Refs「後続ステップ管理: /wf-next」+ 完了案内 | Cross Refs「新規開始: /wf-new」 | ✓ 双方向 |
| 7 | `/wf-new` | `/collection-ideate` | Phase 1 で Skill ツールで実行 + Cross Refs「企画生成: /collection-ideate」 | description / 本文に /wf-new 言及なし（Next Step は /thumbnail と /suno を直接案内） | △ 片方向（意図あり: /collection-ideate は単独でも使う） |
| 8 | `/collection-ideate` | `/thumbnail` | Next Step「→ /thumbnail <theme>」 | When to Use と Quick Reference に /collection-ideate 直前提なし。`/wf-new` 経由でのみ間接連携 | △ 片方向 |
| 9 | `/thumbnail` | `/suno` | Next Step「→ /suno <theme>」 | description「Lyria チャンネルでは /lyria を使う」+ いつ使うか節 `/channel-direction → /channel-setup` のみ。`/thumbnail` 名指しなし | △ 片方向（**Lyria 経路で欠落**: `/thumbnail` Next Step は `/suno` 一本で `/lyria` を案内しない） |
| 10 | `/suno` | `/masterup` | Next Step「→ /masterup <playlist-url>」 | description「前工程: /suno」+ Overview「前工程: /suno」 | ✓ 双方向（最も明示的） |
| 11 | `/lyria` | `/videoup` | Next Step「→ /videoup」 | When to Use・Step 2 で `/masterup` を案内、`/lyria` の言及なし。さらに `/videoup`/`generate_videos.sh` の master 検出は `master-mix.*` + `*-Master.mp3` で **`/lyria` の `01-master/master.wav` は拾えない** | × 片方向 + 命名不整合（要修正） |
| 12 | `/masterup` | `/videoup` | Next Step「→ /videoup」 | Step 2「なければ /masterup でのマスター音源生成を案内」（前向き案内のみ）。さらに `/videoup` の検出パターンは `master-mix.*` で **/masterup の `master.mp3` も拾えない** | △ 片方向 + 命名不整合（要修正） |
| 13 | `/videoup` | `/video-description` | Next Step「→ /video-description <collection-path>」 | When to Use「コレクションの動画が完成し」のみ、`/videoup` 名指しなし | △ 片方向（許容範囲） |
| 14 | `/video-description` | `/video-upload` | Next Step「→ /video-upload <collection-path>」 | Cross References「/video-description — アップロード前に descriptions.md を生成」+ 本文 Step 3 で /video-description を自動実行 | ✓ 双方向 |
| 15 | `/video-upload` | `/metadata-audit` | Cross References「/metadata-audit — アップロード後の整合性監査」 | Overview「アップロード後に YouTube 側にメタデータが正しく反映されたか確認したいとき」（/video-upload 名指しなし、機能で示唆） | △ 片方向（許容範囲） |
| 16 | `/video-upload` | `/playlist` | Cross References「/playlist — プレイリスト状態確認」 | Cross References「/video-upload — アップロード時に内部で `assign_video()` が呼ばれる」 | ✓ 双方向 |
| 17 | `/wf-next` | `/analytics-analyze` | complete phase「→ /analytics-analyze で初週パフォーマンス」 | description「/analytics-collect でデータ収集後に実行」のみ、`/wf-next` 名指しなし | △ 片方向（意図あり: postmortem 経路） |
| 18 | `/analytics-collect` | `/analytics-analyze` | Next Step「→ /analytics-analyze」 | description / When to Use とも /analytics-collect を前提と明示 | ✓ 双方向 |
| 19 | `/analytics-analyze` | `/collection-ideate` | Next Step「→ /collection-ideate」 | 前提スキル状態確認 + Phase 1-2 が `reports/analysis_*.md` を読み込む | ✓ 双方向 |
| 20 | `/analytics-report` | `/analytics-analyze` | Next Step「→ /analytics-analyze で詳細な戦略分析」 | description / 本文に /analytics-report 言及なし | △ 片方向（許容範囲: /analytics-report は読み取り側ツール） |
| 21 | `/viewer-voice` | `/audience-persona` | description「/audience-persona や /viewing-scene の前提データ」 | 前提「`docs/plans/viewer-voice-analysis.md` が存在すること。未実施の場合は先に /viewer-voice」 | ✓ 双方向 |
| 22 | `/audience-persona` | `/viewing-scene` | description「/viewing-scene の入力になる」 | 前提「`persona-definition.md` が存在すること（未実施なら /audience-persona）」 | ✓ 双方向 |
| 23 | `/channel-new` | `/discover-competitors` | Step 5 が MANDATORY で `yt-discover-competitors` を呼ぶ + 「詳細は /discover-competitors skill 参照」 | Cross References「/channel-new Step 5: 新チャンネル開設フロー内での前段呼び出し」 | ✓ 双方向 |
| 24 | `/channel-new` | `/benchmark` | Step 6「ベンチマークデータは /benchmark スキルに委譲」 | Overview「/collection-ideate の Phase 1-2 から自動呼び出しされる」（/channel-new 名指しなし） | △ 片方向（要追記検討） |
| 25 | `/collection-ideate` | `/benchmark` | Phase 1-3「Skill ツールで /benchmark を実行」 | Overview「/collection-ideate の Phase 1-2 から自動呼び出しされる」 | ✓ 双方向 |
| 26 | `/postmortem` | `/thumbnail-compare` ほか 6 | Phase 4 検証ステップ表に `/thumbnail-compare` `/alignment-check` `/viewer-voice` `/audience-persona` `/discover-competitors` `/video-analyze` `/channel-direction` `/comments-reply` を列挙 | いずれも /postmortem 言及なし | △ 片方向（意図あり: fan-out 案内、許容範囲） |
| 27 | `/lyria` | `/suno` | description「Suno で人手生成するチャンネルでは /suno を使う」+ `_disabled: true` 時の案内 | description「Lyria チャンネルでは /lyria を使う」 | ✓ 双方向（排他的選択を相互明示） |
| 28 | `/masterup` | `/lyria` | description「Lyria チャンネルでは /lyria が自動で音源を出力するため本スキルは不要」 | description「/masterup 不要」 | ✓ 双方向 |
| 29 | `/wf-status` | `/wf-next` | Cross Refs | Cross Refs | ✓ 双方向 |
| 30 | `/wf-status` | `/channel-status` | description「チャンネル登録者数など YouTube 側の統計は /channel-status」 | description「ローカルのコレクション制作進捗は /wf-status」 | ✓ 双方向（理想的な相互排他案内） |
| 31 | `/channel-new` | `/channel-import` | （言及なし） | description「新規チャンネル開設は /channel-new を使うこと」 | △ 片方向（/channel-new 側にも代替案内があると親切） |
| 32 | `/loop-video` | `/videoup` | Next Step「→ /videoup <collection-path>」 | Step 2「`10-assets/loop.mp4` が既にあればスキップ。なければ /loop-video でのループ動画生成を案内」 | ✓ 双方向 |
| 33 | `/video-analyze` | `/suno` | 呼び出し側スキル「/suno — Instructions 冒頭で `bgm_arc` 平均を読み込み…」 | Instructions 中盤に「ベンチマーク BGM 構造の参照」セクションがあり `data/video_analysis/<slug>/*.json` を実際に読み込む | ✓ 双方向（**整合する例**） |
| 34 | `/video-analyze` | `/lyria` | 呼び出し側スキル「/lyria — Step 2…composition.json のフェーズ境界…」 | grep ヒットなし（`bgm_arc` / `composition.json` / `video-analyze` いずれも /lyria SKILL.md 内に存在しない） | × **不整合**（C-1 #1 重複） |
| 35 | `/video-analyze` | `/channel-direction` | 呼び出し側スキル「/channel-direction — Step 1 の分析サマリーで…BGM 構造方針の根拠データとして使う」 | grep ヒットなし | × **不整合**（C-1 #1 重複） |
| 36 | `/video-analyze` | `/benchmark` / `/analytics-analyze` / `/alignment-check` / `/thumbnail-compare` / `/viewer-voice` | Overview「これら 5 つの精度を底上げする」 | 5 件すべて 関連ファイルに `data/video_analysis/<slug>/<video_id>.json — /video-analyze の …出力` を明記 | ✓ 双方向（**模範的**） |
| 37 | `/alignment-check` | `/suno` / `/lyria` | Next Step 不整合カテゴリ表「音楽ミスマッチ → /suno または /lyria」 | `/suno` Step 3 と `/lyria` Step 5「`/alignment-check` がコレクション横断で音楽 mood × サムネ × タイトルの整合を機械的に判定できるよう、`planning.music` を populate」 | ✓ 双方向（**模範的**） |

### 3.2 「片方向参照のみ」ペア一覧（要修正候補）

整合性が**意図的でなく** description / 本文の改善余地がある片方向参照ペアは次の **4 組**:

| # | 不整合ペア | 推奨修正方針 |
|---|---|---|
| A | **`/video-analyze` ↔ `/lyria`**（#34） | `/video-analyze` 側の「呼び出し側スキル」セクションから `/lyria` 項を削除する、もしくは `/lyria` 本文に `bgm_arc` 利用ステップを追加する。現状の `/lyria` は単一プロンプト + セグメント数自動算出のみで「フェーズ境界」概念が無い |
| B | **`/video-analyze` ↔ `/channel-direction`**（#35） | 同上。`/channel-direction` Step 2 議論ポイント / Step 3 決定事項テーブルに「競合の BGM 構造」「BGM 構造方針」を追加するか、`/video-analyze` 側から該当記述を削除 |
| C | **`/thumbnail` Next Step が `/suno` 単独**（#9） | `/thumbnail` Next Step に「Lyria チャンネルでは `/lyria <theme>`」分岐を追加。現状の `/wf-new` Phase 2c には分岐があるが、`/thumbnail` を**単独で**走らせるユーザーが `/lyria` への接続を見落とす |
| D | **`/lyria` / `/masterup` → `/videoup` の master ファイル命名**（#11, #12） | `/videoup`/`generate_videos.sh` が探すパターンは `master-mix.{wav,m4a,aac,mp3,flac}` + `*-Master.mp3` フォールバック。`/lyria` (`master.wav`) と `/masterup` (`master.mp3`) 双方の出力名がマッチしないため、(a) generate_videos.sh の検出パターン拡張、(b) 各スキルの出力名統一、(c) 各 SKILL.md の Next Step に「最終マスターは `01-master/master-mix.{ext}` にリネームしてから /videoup」と明示、のいずれかで揃える |

**意図的に片方向**と判断したペア（10 組）: #4, #5, #7, #8, #13, #15, #17, #20, #24, #26, #31 — オーケストレータからの fan-out 案内（/wf-new / /postmortem / /channel-new 等）と「読み取り側ツール」（/wf-status / /analytics-report 等）の組合せ。SKILL.md の双方を膨らませる効用が小さい。

---

## 4. C-3 — deprecated `short` / `community` 参照

仮定: CLAUDE.md の `workflow.json (v4.0.0 で short / community 撤去、後方互換で素通し)` 注記。`short` / `community` を workflow.json の旧 channel-type / content-type フィールドとして想定し、参照残骸を検索。

`Grep` 実行結果（`(short|community)` / case-insensitive / 35 SKILL.md 全件）:

| file:line | 該当文字列 | 種別 | workflow.json 由来か |
|---|---|---|---|
| `audience-persona/SKILL.md:39` | `background music community` | プロンプト用テキスト | × （Reddit 等のオンラインコミュニティを指す） |
| `channel-import/SKILL.md:21` | `gh repo create <short>` | `<short>` プレースホルダ（channel.short の意） | × （meta.json の `channel.short` 由来） |
| `channel-import/SKILL.md:22` | `cd <short>` | 同上 | × |
| `channel-new/SKILL.md:47` | `gh repo create <short>` | 同上 | × |
| `channel-new/SKILL.md:48` | `cd <short>` | 同上 | × |
| `channel-new/SKILL.md:94` | `--short "<仮 SHORT>"` | `yt-channel-init` の `--short` 引数 | × |
| `channel-direction/SKILL.md:106` | `短縮名: {short}` | テンプレ内変数 | × |
| `wf-new/SKILL.md:59` | `YYYYMMDD-<short>-<theme>-collection/` | ディレクトリ命名 | × |
| `wf-new/SKILL.md:73` | 同上 | 同上 | × |
| `wf-new/SKILL.md:139` | 同上 | 同上 | × |
| `analytics-report/SKILL.md:73` | `Complete Collection のみ表示（Shorts を除外）` | YouTube Shorts 動画フォーマット | × |
| `analytics-report/SKILL.md:109` | `channel.short` を小文字化 | meta.json の channel.short | × |
| `analytics-report/SKILL.md:123` | `Shorts は…除外（タイトルに #Shorts を含む）` | YouTube Shorts | × |
| `suno/SKILL.md:122` | `(short instrumental cue, optional 1-2 line spoken intro)` | 歌詞テンプレ内テキスト | × |
| `video-analyze/SKILL.md:66` | `Shorts は Gemini の 1fps サンプリング制約により精度が落ちるため非推奨` | YouTube Shorts | × |

**結論: workflow.json の deprecated 由来の `short` / `community` 参照は 0 件**。

ヒットした 15 件はすべて、(a) `meta.json::channel.short`（チャンネル短縮名スラグ）の正規参照、(b) YouTube Shorts 動画フォーマット、(c) プロンプト/歌詞内の英単語 "short" の散文、のいずれかで、workflow.json の旧フィールドとは無関係。

---

## 5. C-4 — description 形式の揺れ

### 5.1 開始句

| 開始句パターン | 件数 |
|---|---|
| `Use when <Japanese clause>` | **35 / 35（100%）** |

`Use when …` の英語＋日本語ハイブリッド開始は **完全統一**。

### 5.2 末尾の指示語（行動指示）— スタイル分類ヒストグラム

| スタイル | 件数 | 該当 skill |
|---|---|---|
| (A) 「〜場面で必ず使用すること」 | **14** | analytics-analyze / analytics-collect / analytics-report / alignment-check / audience-persona / collection-ideate / live-clean / loop-video / thumbnail / thumbnail-compare / video-description / videoup / viewer-voice / viewing-scene |
| (B) 「〜場面で使用すること」「使用すること」 | **5** | benchmark / comments-reply / playlist / streaming / video-analyze |
| (C) cross-ref note で締める（`/X を使う` / `/X が責務` / `/X` 等の参照で終わる） | **9** | channel-status / channel-import / lyria / masterup / metadata-audit / suno / wf-new / wf-next / wf-status |
| (D) 「〜前に実行する」「〜後に実行する」（ワークフロー序列） | **3** | channel-direction / channel-research / channel-setup |
| (E) アクション動詞で締める（バトンする / エントリポイント / 本スキルは不要 / 実行 / 並行検証ツールとしても使える） | **4** | channel-new / discover-competitors / postmortem / video-upload |

**主な揺れポイント**:

- 「必ず使用すること」を付ける skill と付けない skill が混在。必須 / 任意のニュアンスを意図的に書き分けているかが不明瞭。
- 末尾に**他 skill への参照**を入れる流派（C）が 9 件あるが、`/wf-new` `/wf-next` のようなオーケストレーション系と `/lyria` `/suno` のような排他的選択は意図が異なる。
- ワークフロー序列を末尾に書く流派（D）は新チャンネル開設の 3 つの skill だけ。production pipeline 側（/wf-new → /wf-next 等）には序列が書かれていない。

### 5.3 長さ分布

| 文字数レンジ | 件数 | 代表例 |
|---|---|---|
| 〜100 | 1 | `video-upload`（約 75 文字） |
| 100-150 | 4 | `channel-status` / `masterup` / `wf-status` / `lyria`（実測は約 140-180） |
| 150-200 | 16 | 大多数 |
| 200-250 | 11 | `channel-new` / `postmortem` / `audience-persona` ほか |
| 250+ | 3 | `channel-setup`（約 280 — dual mode 説明） / `streaming` / `postmortem` |

`video-upload` の description が**極端に短く**（C-1.2 で指摘した `single_release` 漏れと相関）、`channel-setup` の description が**極端に長い**（dual mode を強引に詰め込み）。3.7× の幅。

### 5.4 トリガーワードの粒度

| 流派 | 例 | 件数（概算） |
|---|---|---|
| 「」付き日本語ワード列挙 | alignment-check「整合性チェック」「一致してるか確認」… | 24 |
| 鉤括弧なし日本語＋英語混在 | postmortem「why flopped」「postmortem」「振り返り」 | 5 |
| 鉤括弧なし、機能説明のみ | video-upload / channel-direction | 6 |

### 5.5 代表例 5 件（スタイル差を最も顕著に示す）

1. **(A) 典型形 — `loop-video`**:  
   `Use when コレクションのサムネイル画像からループ動画背景を生成したいとき。Veo 3.1 API で main.png/jpg を元に微細アニメーション付きの 8秒シームレスループ動画を生成。ループ動画、背景動画、loop.mp4、アニメーション背景、動画背景など、静止画を動画化する場面で必ず使用すること`

2. **(C) cross-ref で締める — `channel-status`**:  
   `Use when チャンネル全体の YouTube 統計（登録者数・総再生回数・動画別パフォーマンス）を取得したいとき。…YouTube API から数字を取得するときに使用する。ローカルのコレクション制作進捗は /wf-status`

3. **(E) 極端に短い — `video-upload`**:  
   `Use when コレクションの動画が完成し、YouTubeへのアップロード自動化が必要なとき。Complete Collection のアップロードと live 移行を実行`

4. **(D) ワークフロー序列付き — `channel-research`**:  
   `Use when /channel-new で収集したベンチマークデータを徹底分析したいとき。…/channel-new の後、/channel-direction の前に実行する`

5. **(B) dual mode 詰め込み — `channel-setup`**:  
   `Use when /channel-direction で方向性が確定し、チャンネルのテクニカルセットアップを行いたいとき、または運用中チャンネルの YouTube 側設定（branding / status / localizations）をローカル config と同期したいとき。「セットアップ」… および「設定反映」「チャンネル設定更新」「branding push」… など既存チャンネルの設定 push に関わる場面で使用すること。新規セットアップは /channel-direction の後に実行する`

---

## 6. 主要な発見のサマリー（上位 5 件）

1. **`/video-analyze` SKILL.md の「呼び出し側スキル」セクションが /lyria・/channel-direction について事実誤認を含む**（C-1.1 / C-2 #34, #35）。/suno と /video-analyze 間は実装と整合している（line 45）のと対照的に、/lyria と /channel-direction には対応コードが無い。Owner が `/video-analyze` 側か下流 2 スキル側のどちらに合わせるかを決める必要あり。

2. **`/lyria` (`master.wav`) と `/masterup` (`master.mp3`) の出力ファイル名が `/videoup`/`generate_videos.sh` の検出パターン (`master-mix.*` + `*-Master.mp3`) のいずれにもマッチしない**（C-2 #11, #12）。`/wf-next` 経由なら `01-master/` を再走査する 2-B 検出ロジック（line 51 の `.m4a/.wav/.flac/.aac/.mp3` 拡張子マッチ）が救うが、`/lyria` / `/masterup` の Next Step「→ /videoup」を素直に従うと素材が見つからない。実害有り。

3. **`/thumbnail` の Next Step が `/suno` 単独で `/lyria` を案内しない**（C-2 #9）。`/wf-new` Phase 2c には music_engine 分岐があるが、ユーザーが `/thumbnail` を単独実行した場合に `/lyria` ルートが見えない。Lyria 利用チャンネルでの導線断絶。

4. **description のスタイル揺れは大きく分けて 5 系統**（C-4）。開始句は完璧に揃っているのに、末尾の指示語が「必ず使用すること（14）」「使用すること（5）」「cross-ref（9）」「序列（3）」「アクション動詞（4）」と分散。読み手が「必ず」の有無に意味を求める可能性があるため、ガイドラインで統一すべきか「あえて使い分け」と明文化すべきか判断が必要。

5. **`/video-upload` description は `collection` 型しか触れていないが、実装は `single_release` 型（JP+EN 同日 2 本アップ）にも対応している**（C-1.2）。`single_release` チャンネル運営者が description で skill 発火を期待しにくい。

---

## 7. カバレッジ

走査した SKILL.md 全 35 件（`Glob` で完全一覧化、`Bash ls | wc -l` で総数 35 を確認）:

```
alignment-check         analytics-analyze       analytics-collect
analytics-report        audience-persona        benchmark
channel-direction       channel-import          channel-new
channel-research        channel-setup           channel-status
collection-ideate       comments-reply          discover-competitors
live-clean              loop-video              lyria
masterup                metadata-audit          playlist
postmortem              streaming               suno
thumbnail               thumbnail-compare       video-analyze
video-description       video-upload            videoup
viewer-voice            viewing-scene           wf-new
wf-next                 wf-status
```

C-1: 全 35 件の description ↔ 本文を読み比較 / C-2: `→` `前工程` `次工程` `前フェーズ` `次フェーズ` `Cross References` を grep し 37 のバトンペアを抽出 / C-3: `(short|community)` で大文字小文字無視 grep（15 ヒットを 1 件ずつ判定）/ C-4: 35 件の description を分類。

---

## 8. 注意点・リスク

- **意図的な非対称バトン**: オーケストレータ（/wf-new / /wf-next / /channel-new / /channel-import / /postmortem）は本質的に「呼び出す側」で、呼ばれる skill 側に「私は /wf-new から呼ばれます」と書くと冗長になる。本レポートは 10 ペアを「意図あり」と判定したが、最終レポートで「**意図的非対称**」と「**修正すべき非対称**」の閾値を明示しないと、機械的に「全 14 ペアを修正」と読まれる恐れがある。

- **description の文体差は意図的か揺れか**: 「必ず使用すること」の付与は「ユーザーが言及せずとも積極的に発動して欲しい skill（example: alignment-check）」と「ユーザー指示のみで動く skill（example: video-upload）」の区別の意図かもしれない。本レポートは「揺れ」と分類したが、実は意図的な可能性も残る — issue 化の前に owner ヒアリングを推奨。

- **`/video-analyze` の事実誤認は新規追加された機能予告である可能性**: 「呼び出し側スキル」セクションは `/lyria` / `/channel-direction` を「将来こう使う予定」として書いている可能性がある（実装はまだ）。git 履歴を確認していないため、もしそうなら C-1.1 は「未実装の予告」として別カテゴリで扱うべき。

- **`/videoup` の master 命名不整合は実害判定が要再現**: `/wf-next` の 2-B 検出ロジックが救うことが多い実運用なら、SKILL.md のドキュメント表記だけ揃えれば十分。常時 `/wf-next` 経由を前提にできるなら `/lyria` / `/masterup` の Next Step を「→ /wf-next」に書き換えるだけで解決。

---

## 9. 調査不可項目とその理由

- **CLAUDE.md の `workflow.json (v4.0.0 で short / community 撤去)` 注記以外に deprecated 化されたフィールドがあるかは未確認**。本タスクは workflow.json の `short` / `community` のみを対象としたが、他にも音楽エンジン関連や旧スキーマ（v1 workflow-state.json など）で deprecated 化された参照が残っている可能性は否定できない。これは別途観点が必要。

- **`/video-analyze` の「呼び出し側スキル」記述が「過去に存在した実装が削除された残骸」か「将来予定の予告」かは git 履歴 / issue tracker を見ないと断定できない**。本レポートは「現状の SKILL.md 同士の整合性」のみを評価。

- **description のスタイル揺れが意図的か無計画かは owner 確認が必要**（前述）。本レポートは表面的な分類のみ。

- **本タスクでは references/ 配下のサブドキュメントは原則読まない**（plan.md より）。`references/scene_phrases.md`、`references/lyria-tuning-guide.md`、`references/object-design-examples.md` などにバトンや実装詳細が書かれている可能性があるが、本タスク範囲外。

---

## 10. 推奨 / 結論

最終レポート（`docs/audits/skills-audit-2026-05-18.md`）で取り上げる優先度付け:

| 優先度 | 対応事項 | 根拠観点 | 推奨アクション |
|---|---|---|---|
| **P1-高** | `/video-analyze` の「呼び出し側スキル」記述（/lyria / /channel-direction 行）を実装と整合させる | C-1.1 / C-2 #34, #35 | git log 確認の上、削除 or 下流実装追加 |
| **P1-高** | `/lyria` `/masterup` の出力名と `/videoup`/`generate_videos.sh` の検出パターンを整合させる | C-2 #11, #12 | 実装側の検出パターン拡張 or SKILL.md 上「→ /wf-next」経路への書き換え |
| **P1-中** | `/thumbnail` Next Step に `/lyria` 分岐を追加 | C-2 #9 | description は変えず Next Step に分岐追加 |
| **P1-中** | `/video-upload` description に `single_release` 型を追記 | C-1.2 | description 末尾に「single_release 型（JP+EN 同日アップロード）にも対応」追記 |
| **P2-低** | `/analytics-report` description にトリガーワード「ビジュアル」「HTML レポート生成」を追記 | C-1.3 | description のトリガーキーワード列を拡充 |
| **P2-低** | description 末尾指示語のガイドライン化（A〜E 5 系統の使い分け基準）| C-4 | meta-doc `.claude/skills/CONTRIBUTING.md`（仮）で明文化 |
| **P3-参考** | `/channel-new` description に「既存チャンネルなら /channel-import」相互案内を追加 | C-2 #31 | 1 文追加で /wf-status ↔ /channel-status と同じ模範形に |

C-3 は **対応不要**（0 件）。
