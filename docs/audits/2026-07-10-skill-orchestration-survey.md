# スキルオーケストレーション調査レポート (2026-07)

Issue: [#1810 [skills] 全スキル横断オーケストレーション化の調査 — 連鎖棚卸しと組み替え推奨案](https://github.com/daiki-beppu/youtube-automation/issues/1810)

## 1. イントロ

同梱スキルには前工程・後工程の連鎖（制作系・analytics 系・リサーチ系など）が複数存在するが、オーケストレーターとして設計されているのは制作チェーンの `/wf-next` のみ。本レポートは以下を調査し、組み替え推奨案をまとめる。

- 全スキルの連鎖関係の棚卸し（§2）
- 連鎖グループの同定とオーケストレーター化の評価（§3）
- 既存オーケストレーター `/wf-next` の設計分析（§4）
- Claude Code / Codex の skill 実行仕様上の制約（§5）
- 宣言的な自動連鎖 API の設計案比較（§6）
- 組み替え推奨案と後続 issue 分割案（§7）

**対象スキル数について**: issue 本文は「44 スキル」としているが、調査時点（2026-07-10、main = cd81f5b9）の `.claude/skills/` 配下の実数は **45 スキル**である。本レポートは実数 45 を対象とする。

調査方法: 全 45 SKILL.md の description / 本文の前後工程記述・`/skill` 相互参照を読み取り、`docs/workflow-cheatsheet.md`・`docs/takt-operations.md`・`docs/skill-design/skill-authoring-guidelines.md`・`.claude/settings.json`（hooks）・`.takt/workflows/lite.yaml` と突き合わせた。

## 2. 全スキル依存関係一覧（45 スキル）

凡例: 「前工程」= そのスキルの入力を作るスキル、「後工程」= そのスキルの出力を消費するスキル。`channel-new`（config 生成）と `setup`（ツール・OAuth）はほぼ全スキルの共通前提のため、各行では固有の依存のみ記載する。

| # | skill | グループ | 前工程 | 後工程 |
|---|-------|---------|--------|--------|
| 1 | wf-new | 制作オーケストレーター | channel-new, setup, collection-ideate（内部呼出） | wf-next, suno-helper |
| 2 | wf-next | 制作オーケストレーター | wf-new | analytics-analyze（T+7 案内）, postmortem |
| 3 | wf-status | 制作オーケストレーター（read-only） | wf-new | wf-next |
| 4 | collection-ideate | 制作チェーン入口 | analytics-analyze / benchmark（fallback）/ audience-persona-design | wf-new, community-draft |
| 5 | thumbnail | 制作チェーン | collection-ideate, wf-new | loop-video, thumbnail-compare, alignment-check |
| 6 | loop-video | 制作チェーン | thumbnail（main.png） | videoup |
| 7 | suno-lyric | 制作チェーン（Suno パス先頭） | — | suno |
| 8 | suno | 制作チェーン（Suno パス） | suno-lyric | suno-helper, masterup |
| 9 | suno-helper | 制作チェーン（Suno パス） | suno, wf-new（server 起動） | masterup |
| 10 | masterup | 制作チェーン（Suno パス） | suno, suno-helper | videoup |
| 11 | lyria | 制作チェーン（Lyria パス。Suno と排他） | wf-next（API 呼出） | videoup |
| 12 | videoup | 制作チェーン | masterup / lyria, loop-video | video-upload, video-description |
| 13 | video-description | 制作チェーン | videoup（wf-next から並列起動） | video-upload, metadata-audit |
| 14 | playlist | 制作チェーン / 配信 | wf-next（初期化ゲート） | video-upload |
| 15 | video-upload | 制作チェーン / 配信 | videoup, video-description, playlist, thumbnail | community-post（自動呼出）, metadata-audit, pinned-comment |
| 16 | community-post | リリース後 | video-upload（最終ステップから呼出） | — |
| 17 | community-draft | リリース後 | collection-ideate（企画文脈） | community-post 相当の投稿 |
| 18 | pinned-comment | リリース後 | video-upload | — |
| 19 | comments-reply | リリース後 | （公開動画。明示的スキル依存なし） | — |
| 20 | metadata-audit | リリース後 / 監査 | video-upload | video-description（修正委譲） |
| 21 | benchmark | リサーチ・戦略（収集起点） | — | channel-research, viewer-voice, collection-ideate（fallback 入力） |
| 22 | channel-research | リサーチ・戦略 | benchmark, viewer-voice | collection-ideate, wf-new |
| 23 | discover-competitors | リサーチ・戦略 | benchmark, channel-research | viewer-voice, benchmark（対象追加） |
| 24 | viewer-voice | リサーチ・戦略 | benchmark, discover-competitors | audience-persona-design（viewer-voice-analysis.md を供給） |
| 25 | audience-persona-design | リサーチ・戦略 | viewer-voice（viewer-voice-analysis.md 必須） | viewing-scene, collection-ideate |
| 26 | viewing-scene | リサーチ・戦略 | audience-persona-design | collection-ideate |
| 27 | analytics-collect | analytics（収集） | setup（OAuth） | analytics-analyze |
| 28 | analytics-analyze | analytics（分析） | analytics-collect | collection-ideate, analytics-report, postmortem |
| 29 | analytics-report | analytics（表示、read-only） | analytics-analyze | — |
| 30 | video-analyze | analytics / リサーチ横断 | 公開動画・競合動画（benchmark 等） | collection-ideate, suno（genre_line 供給）, alignment-check |
| 31 | alignment-check | 監査 | thumbnail, suno / lyria | postmortem（事前監査） |
| 32 | thumbnail-compare | 監査 | thumbnail, benchmark | （方向性見直しループ） |
| 33 | postmortem | analytics（事後分析ハブ） | analytics-analyze, alignment-check | collection-ideate（次企画改善） |
| 34 | short | ショート（collection 型。short-release と排他） | setup, 完成コレクション | short-thumbnail, video-upload |
| 35 | short-release | ショート（release 型。short と排他） | 完成リリース楽曲 | short-thumbnail |
| 36 | short-thumbnail | ショート | short / short-release | — |
| 37 | distrokid-helper | 音楽配信 | masterup / lyria, thumbnail, ext-install | （DistroKid Web 操作は Chrome 拡張の責務） |
| 38 | ext-install | 単発ユーティリティ（配信ツール準備） | — | suno-helper, distrokid-helper |
| 39 | automation-release | システムリリース | —（`[Unreleased]` 蓄積が前提） | automation-update（下流追従） |
| 40 | automation-update | システムリリース（下流側） | automation-release | — |
| 41 | setup | 基盤 | — | ほぼ全チェーンの前提 |
| 42 | channel-new | 基盤 / ハブ | — | ほぼ全スキルの config 前提を作る |
| 43 | channel-status | 単発ユーティリティ | channel-new | — |
| 44 | streaming | 単発ユーティリティ（独立） | — | — |
| 45 | live-clean | 単発ユーティリティ（メンテ） | video-upload（live 移行後）, videoup（tmp 残骸） | — |

横断ノードの補足:

- `benchmark` はリサーチ収集の起点で、制作（collection-ideate fallback）・監査（thumbnail-compare / alignment-check）・analytics（analytics-analyze の比較材料）すべてが参照する。
- Suno パス（suno-lyric → suno → suno-helper → masterup）と Lyria パス（lyria）は音楽エンジンで排他、`videoup` 以降で合流する。`short` / `short-release` も同様にチャンネル型で排他。この 2 組の排他はスキル authoring ガイドライン①（発動キーワード相互排他）で担保されている。

## 3. 連鎖グループの同定とオーケストレーター化評価

| グループ | 構成スキル | 評価 | 理由 |
|---------|-----------|------|------|
| 制作チェーン | wf-new / wf-next / wf-status + 4〜15 | **済（先行事例）** | `/wf-next` が workflow-state.json 駆動で既にオーケストレーション済み。組み替え不要、他グループへの展開元パターン |
| analytics チェーン | analytics-collect → analytics-analyze → analytics-report | **可** | 3 段の線形チェーンで人の判断分岐がなく、各段の成果物（生データ → レポート）がファイルとして残るため状態判定を機械化できる。外部反映がなく承認ゲート不要で、最も低リスクにオーケストレーター化できる |
| リリース後チェーン | video-upload 後続の community-post / pinned-comment / metadata-audit（+ comments-reply） | **条件付き可** | `/video-upload` → `/community-post` の自動呼出という散文連鎖が既にあり、後続 3 スキルを 1 つの「公開後処理」として束ねる余地がある。ただし全て外部反映（YouTube への書き込み）のため、config 駆動承認ゲート（wf-next の approval_gates パターン）が必須条件。comments-reply は動画公開に非同期（任意時点で実行）なのでチェーンに含めない |
| リサーチ・戦略チェーン | benchmark → (discover-competitors) → viewer-voice → audience-persona-design → viewing-scene → collection-ideate, channel-research | **条件付き（前提ガードのみ強化、自動連鎖は不可）** | 各段の出力（persona-definition.md 等）はユーザーの戦略判断を経て確定するもので、自動で次段に進めるとチャンネルの方向性が無審査で決まってしまう。実行頻度も低く（方向性見直し時のみ）、自動化の便益が薄い。成果物ファイルの存在ガード（ガイドライン③）を統一する改善に留めるのが妥当 |
| ショート系 | short / short-release → short-thumbnail | **不可** | 実質 2 段のチェーンで、オーケストレーター（state ファイル + 制御スキル）の導入コストが連鎖の複雑さを上回る。現行の散文委譲（description の前後工程明記）で十分 |
| 音楽配信 | ext-install → distrokid-helper | **不可** | 本質が Chrome 拡張を使った operator 手順（人がブラウザを操作する）で、スキル側は準備（server 起動・metadata 生成）まで。自動連鎖の対象になる後半が agent の制御外にある |
| システムリリース | automation-release → automation-update | **不可** | 上流（本リポジトリ）と下流（チャンネルリポジトリ）で実行環境・実行者が分かれ、間に PR マージ・リリース公開という人のイベントを挟む。単一セッションのオーケストレーションが成立しない |
| 基盤・単発 | setup / channel-new / channel-status / streaming / live-clean / ext-install / comments-reply / community-draft | **不可（対象外）** | 連鎖の起点・前提または独立ユーティリティであり、順序制御の対象になる連鎖を持たない |

## 4. 既存オーケストレーター /wf-next の設計分析

`/wf-next` の設計は 4 つの要素に分解でき、他チェーンへ移植する際は要素ごとに採否を判断できる。

| 要素 | 内容 | 移植性 |
|------|------|--------|
| ① 状態駆動 | コレクションごとの `workflow-state.json` を単一の真実源とし、`phase` を読んで対応する次工程を **1 段だけ**実行し state を更新する | 「進行中の案件」が複数並走し得るチェーン（制作）に必須。analytics のように「最新データがあるか」だけ判れば良いチェーンでは、専用 state ファイルより成果物のタイムスタンプ判定で足りる |
| ② 冪等性 | 途中エラーで停止しても再実行で未完了ステップから再開（`assets` フラグで判定）。手編集は禁止 | 全チェーンに移植価値あり。冪等判定を SKILL.md の散文でなく reference script（例: `wf-next/references/master_audio_transition.py`）に code 化する点が決定性の要 |
| ③ config 駆動承認ゲート | `config/channel/workflow.json::workflow.wf_next.approval_gates` で宣言し、SKILL.md 本体を書き換えない（`yt-skills sync` の配布衝突を回避）。既定 false = 全自動で後方互換 | 外部反映を含むチェーン（リリース後チェーン）に必須。sync 配布と両立する唯一の下流カスタマイズ手段でもある |
| ④ 薄い委譲層 | 子スキル（/masterup, /videoup, /video-upload…）の内部ロジックを再実装せず、順序制御と state 更新だけを担う | 全チェーンに移植価値あり。委譲は散文（agent が子 SKILL.md を読んで実行）である点が §5 の制約に直結する |

## 5. 制約 — Claude Code / Codex の skill 実行仕様

調査の結果、**skill から別 skill をプログラム的に発動する宣言的 API は存在せず、現行の連鎖はすべて SKILL.md 本文の自然言語（散文）委譲である**。以下が確認された制約。

1. **skill→skill の呼び出し手段**: リポジトリ全体で `SlashCommand` tool / `Skill` tool の使用実績は 0 件（rg で確認）。`/wf-next` の「子スキルへ委譲」も、agent が子スキルの SKILL.md を読んで手順を実行する散文オーケストレーションであり、呼び出しの成否・完了を機械的に検知する仕組みはない。
2. **hooks は skill を発動できない**: `.claude/settings.json` の hooks は PreToolUse（機密ファイル編集ブロック）・PostToolUse（ruff 整形、CHANGELOG 追記 NOTE）・UserPromptSubmit(main branch 警告)の 3 種のみで、全て通知・ブロックゲート用途。hooks から skill を起動する機構は Claude Code に存在せず、できるのは additionalContext / stderr で「次に /xxx を実行せよ」という指示文を注入することまで（従うかは LLM 依存）。さらに hooks は Claude Code 対話セッション専用で、Codex CLI・takt（Agent SDK 経由）では発火しない。
3. **yt-skills sync 配布制約**: `.claude/skills/` は wheel に force-include され下流チャンネルリポジトリへ sync 展開されるため、**SKILL.md はチャンネル間で共通**。チャンネルごとの連鎖挙動の差異（ゲート有無・パス選択）は SKILL.md でなく `config/channel/*.json` に置く必要がある（wf-next の approval_gates が先行例）。連鎖定義をマニフェスト化する場合も同じ制約に従う（同梱デフォルト + config 上書き）。
4. **Codex 共用制約**: スキルは `.agents/skills` symlink 経由で Codex CLI からも読まれる共用資産。`AskUserQuestion` → 通常のユーザー確認、`Bash run_in_background` → 非同期 session + poll などの読み替え規約（`docs/takt-operations.md`）があり、連鎖機構も「Claude Code 専用ツールに依存しない、テキスト指示 + スクリプト」で構成しないと Codex 側で動かない。hooks 方式がこの制約に抵触する（前項）。
5. **ヘッドレス実行の制約（takt 型の評価材料）**: takt は Agent SDK を `settingSources:['project']` + `acceptEdits` で呼ぶ非対話ランナーで、prompt に答える人間がいないため**対話型の承認ゲート（AskUserQuestion）が成立しない**。また `.claude/skills/**` は protected paths のため Claude provider からの編集は deny される（codex provider でのみ回避可）。skill の description は全 step・全 phase で毎回注入されるため、スキル数・description 肥大はヘッドレス実行コストに直結する。
6. **決定性の現在地**: 決定的に動くのは reference script（`uv run` / `python` 実行）と takt の `structured_output` + `when:` 式分岐のみ。SKILL.md の散文手順は LLM の解釈を経るため、順序保証・完了検知は本質的に確率的。wf-next が状態判定を script に切り出しているのは、この制約への既存の回答である。

## 6. 宣言的な自動連鎖 API の設計案比較

§5 の制約を踏まえ、4 案を比較する（案 D は比較基準としての現状維持強化）。

| 観点 | 案 A: チェーン定義マニフェスト + 汎用インタープリタ skill | 案 B: hooks による決定的連鎖注入 | 案 C: ヘッドレスランナー（takt 型 workflow） | 案 D: 現状維持 + 規約強化 |
|------|------|------|------|------|
| 方式概要 | チェーン（step 列・前提成果物・ゲート）を JSON マニフェストで宣言し、wf-next を汎化した単一のインタープリタ skill が「state 判定 script + 子スキル散文委譲」で 1 段ずつ進める | PostToolUse / Stop hooks が成果物の出現を検知し、次スキルの発動指示を additionalContext で注入する | チェーンを workflow YAML（takt の lite.yaml 相当）で定義し、ヘッドレスランナーが step ごとに agent セッションを起動、`structured_output` + `when:` 式で分岐する | SKILL.md description の前後工程表記を機械可読な統一書式にし、前提ガード（ガイドライン③）を全スキルに徹底する |
| 決定性 | 中〜高（step 順序・前提判定はマニフェスト + script で決定的。子スキル実行自体は散文委譲のまま） | 低〜中（発火は決定的だが、注入指示に LLM が従う保証がなく、実行強制もできない） | 高（step 遷移・分岐が runner の code で完結） | 低（発動順序は完全にユーザー / LLM 依存のまま） |
| Codex 共用 | **可**（テキスト + script 構成。既存の読み替え規約で吸収可能） | **不可**（hooks は Claude Code 専用。Codex / takt 経由で発火しない） | 可（takt は codex provider 運用実績あり） | 可 |
| 承認ゲート対応 | **可**（wf-next の config 駆動 approval_gates パターンをマニフェスト属性としてそのまま採用） | 弱（exit 2 ブロックと指示注入のみで、2 択の対話ゲートを表現できない） | **弱**（非対話のため対話ゲート不成立。ゲート位置でチェーンを分割し人が再起動する運用で代替） | 可（各スキル個別のゲートのまま） |
| 実装コスト | 中（wf-next の状態判定 script とゲート機構の汎化 + マニフェスト schema 設計。前例があるため設計リスクは低い） | 中〜高（hook script 群の新規開発 + settings.json の配布・維持。効果が不確実なわりに高コスト） | 高（takt は本リポジトリの開発 issue 用で、下流チャンネルリポジトリには未導入。運用チェーン用 runner の新規配布・保守が必要） | 低 |
| yt-skills sync 配布適合 | 高（マニフェスト同梱デフォルト + `config/channel/` 上書きで既存パターンに乗る） | 低（settings.json hooks は sync の配布対象外で、下流への展開手段がない） | 低（runner バイナリ / 設定の配布が sync の枠外） | 高 |
| リポジトリ内の前例 | wf-next + workflow-state.json + references script 共有（collection-ideate → thumbnail/references の委譲呼出） | なし（hooks は通知・ブロック専用の実績のみ） | .takt/workflows/lite.yaml（structured_output + when 分岐の宣言的 DSL） | 発動キーワード相互排他などガイドライン 7 ルール |

**評価結論**:

- **案 A を主軸に採用する**。決定性・Codex 共用・承認ゲート・配布適合の 4 観点すべてで実用水準を満たす唯一の案であり、wf-next という動作実績のあるパターンの汎化なので設計リスクが最小。
- **案 B は不採用**。Codex 共用不可・配布不可の 2 点が致命的で、決定性の利得も「注入した指示に従うか」が LLM 依存な時点で見かけほど高くない。
- **案 C は不採用（将来オプションとして保留）**。決定性は最も高いが、承認ゲートが本質的に成立しないため外部反映チェーンに使えず、下流配布コストも高い。「AFK で analytics チェーンを丸ごと回したい」等の非対話・非外部反映ユースケースが顕在化した時点で、案 A のマニフェストを runner から解釈する拡張として再検討するのが妥当（マニフェストを共有すれば二重定義にならない）。
- **案 D は案 A の前段として部分採用**。前後工程表記の統一と前提ガード徹底は、案 A のマニフェスト化の下ごしらえ（依存関係の機械抽出）としてそのまま活きる。

## 7. 組み替え推奨案

### 7.1 グループ別の推奨

| グループ | 推奨 | wf-next パターン踏襲 | 理由 |
|---------|------|---------------------|------|
| analytics チェーン | 案 A でオーケストレーター skill 化（`/analytics-run` 仮称: collect → analyze → report を 1 コマンドで） | **条件付き踏襲** — ②冪等性・④薄い委譲層は踏襲。①はコレクション単位 state ファイルでなく成果物タイムスタンプ（データ鮮度）判定に軽量化。③承認ゲートは外部反映がないため省略（既定で全自動） | 線形・無分岐・read 系のため、state 管理の複雑さが不要。「データ更新してから分析」という 2 段の手動発動を 1 段に畳める即効性がある |
| リリース後チェーン | 案 A で `/video-upload` 後続（community-post → pinned-comment → metadata-audit）を post-publish チェーン化 | **踏襲** — ①②④に加え、③config 駆動承認ゲートを必須採用（外部反映のため）。upload 済み動画 ID 単位の実行履歴で冪等性を担保 | 現状 `/video-upload` → `/community-post` だけが散文自動呼出で、pinned-comment / metadata-audit は手動発動が漏れやすい。ゲート付き連鎖で「公開後のやり忘れ」を機械的に防げる |
| リサーチ・戦略チェーン | オーケストレーター化しない。前提ガード（ガイドライン③）の統一強化のみ | **踏襲しない** — 自動で次段に進める設計自体が不適（各段の確定はユーザーの戦略判断） | 成果物ファイル（viewer-voice-analysis.md, persona-definition.md）の存在ガードは既に一部スキルにあるため、書式と失敗時案内（前工程スキルへの誘導）を統一するだけで連鎖の迷子は解消する |
| ショート系・音楽配信・システムリリース・基盤 | 現状維持（案 D の表記統一のみ適用） | **踏襲しない** | §3 のとおり、チェーンが短すぎる / 人・外部システムのイベントを挟む / 連鎖がない |

### 7.2 移行手順

1. **表記統一（案 D 部分）**: 全 45 スキルの description・本文の前後工程表記を統一書式に揃え、依存関係を機械抽出できる状態にする（本レポート §2 の表が初版データになる）。
2. **マニフェスト schema 設計（案 A 基盤)**: チェーン定義（step 列・前提成果物パス・ゲート宣言・冪等判定 script 参照）の JSON schema を設計し、`config/channel/workflow.json` の `workflow.wf_next` を同 schema の一インスタンスとして位置づける（wf-next は書き換えず整合のみ確認）。
3. **analytics チェーンで先行実装**: リスク最小（read 系・ゲート不要）の `/analytics-run` をインタープリタ skill の初号として実装し、マニフェスト + 状態判定 script のパターンを確立する。
4. **リリース後チェーンへ展開**: 確立したパターンに③承認ゲートを加えて post-publish チェーンを実装する。既存の `/video-upload` → `/community-post` 散文呼出は新チェーンへ委譲するよう書き換える。
5. **リサーチ系の前提ガード統一**: オーケストレーター化はせず、ガイドライン③準拠の存在ガードと前工程誘導を各スキルに揃える。
6. 各段で `yt-skills sync` の配布確認（下流 config 未設定時に後方互換で全自動 / 既定動作が変わらないこと）をテストで担保する。

### 7.3 後続 issue 分割案（/to-issues に渡せる粒度）

| # | 想定 issue タイトル | スコープ | 依存 |
|---|--------------------|---------|------|
| F1 | [skills] 前後工程表記の統一書式化 — 全 45 スキルの description / 本文の連鎖表記を機械可読に揃える | 全 SKILL.md の表記のみ（ロジック変更なし）。書式は skill-authoring-guidelines に追記 | なし |
| F2 | [skills] チェーン定義マニフェストの schema 設計 — step / 前提成果物 / ゲート / 冪等判定の宣言形式 | schema 文書 + examples。wf-next の workflow.json 設定を同 schema で説明できることを検証 | F1 |
| F3 | [skills] /analytics-run オーケストレーター新設 — collect → analyze → report のマニフェスト駆動連鎖 | 新規 skill + 状態判定 reference script + テスト。承認ゲートなし | F2 |
| F4 | [skills] post-publish チェーン化 — video-upload 後続（community-post / pinned-comment / metadata-audit）の config 駆動ゲート付き連鎖 | 新規 or video-upload 拡張 + `config/channel/` へのゲート宣言追加（既定 false で後方互換） | F2, F3 |
| F5 | [skills] リサーチ系 6 スキルの前提ガード統一 — 成果物存在チェックと前工程誘導をガイドライン③準拠に | benchmark / discover-competitors / viewer-voice / audience-persona-design / viewing-scene / channel-research の本文修正のみ | F1 |

## 8. 検証

| issue 要件 | 対応セクション |
|-----------|---------------|
| 1. 全スキルが 1 行以上現れる依存関係一覧表 | §2（45 行） |
| 2. 連鎖グループ同定と評価（可 / 不可 / 条件付き + 理由） | §3 |
| 3. wf-next 既存設計との比較・各推奨案の踏襲判断 | §4, §7.1 |
| 4. skill 実行仕様上の制約セクション | §5 |
| 5. 3 パターン以上の設計案比較表（決定性・Codex 共用・承認ゲート・実装コスト） | §6（4 案） |
| 6. 組み替え推奨案（対象・方式・移行手順・後続 issue 分割） | §7 |
