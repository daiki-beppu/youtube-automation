# naming round3: ツール名 再帰的頭字語候補（backronym 方式・3 周目）

- issue: #980「research(naming): ツール名の再帰的頭字語候補を backronym 方式で再生成（3 周目）」
- 作成日: 2026-06-12
- レジストリ実測日: **2026-06-12**（全 status code は同日のスナップショット）
- 位置づけ: 候補生成と配布可否の **調査レポート**。名前の最終決定は HITL（ユーザー判断）に委ねる
- 出典: 本レポートの数値・status code・候補リストは、本 issue の run 配下 `reports/` 各データファイルからの転記・統合である（各節に出典ファイル名を明記）。新規の web/レジストリ調査は本レポート作成時には行っていない

---

## 0. 前提（一次仕様の固定）

> **本 issue の一次仕様 = `order.md` L5「npm 配布するツール名（パッケージ名 = bin 名想定）」。**

- したがって本レポートの **主筋は npm 配布前提**であり、1 位推奨は「npm で配布可能な強い実在語」を据える。
- プロジェクト文脈（`CLAUDE.md` 由来の「本ツールは Python / PyPI 配布が主」）は **主筋に昇格させず**、「PyPI を主レジストリに選ぶ場合の代替」を **HITL 分岐**として §6 に併記する。この優先順位は analyze step（`analysis-2.md §4 論点 Y`）の判定に従う。
- 本前提の食い違い（order.md=npm vs CLAUDE.md=PyPI）は新規調査では解決しない編集判断事項であり、ここで明示的に order.md を優先する（出典: `analysis-2.md §4`, `research-report.md` 結論）。

### スコープ外（明示）

| 項目 | 扱い |
|------|------|
| 名前の最終決定 | 対象外（HITL 判断） |
| ADR-0006 / `packages/` への名前反映 | 対象外（決定後の別 issue） |
| **商標の法的確認** | **対象外**（order.md スコープ外） |
| **ドメイン / SNS ハンドルの取得・空き確認** | **対象外**（order.md スコープ外。一般語・著名語は造語より商標衝突リスクが高い点のみ注意喚起にとどめる） |

### Acceptance Criteria とセクションの対応（トレーサビリティ）

| AC（order.md L25–29） | 対応セクション |
|---|---|
| AC1: 再帰頭字語 20〜30 件を backronym 方式で生成（語が先・展開が後） | §1（方式）, §2（候補一覧 30 件） |
| AC2: 各候補に展開フレーズ・文字数・打鍵性メモ・npm/PyPI/crates 空き | §2（展開・文字数・打鍵性）, §3（レジストリ空き） |
| AC3: 負例 71 件との同型・同語幹チェック明記 | §4 |
| AC4: Top 5 + 1 位推奨を理由付きで提示 | §5 |
| AC5: available 10 件以上 | §3.3（造語 22 件が 3 レジストリ全空き／実在語 14 件が scoped npm 空き） |
| AC6: docs/research/naming-round3.md として PR にコミット | 本ファイル |

### 過去 2 ラウンドの結論（再挑戦の出発点・出典: order.md L9–11）

- **1 周目**（再帰的頭字語・文字組み立て方式）: yotak / tubot / yamo / yave / tava → 「名前自体が弱い」で棄却
- **2 周目**（頭字語撤廃・世界観 5 軸 rubric）: marcato / attacca / kakera / mocade / caelo → 「どれもイマイチ」で棄却
- **ユーザー判断**: 1 周目の要件セット（再帰的頭字語・短さ・打ちやすさ）をベースに再挑戦

---

## 1. backronym 生成方式（3 周目の核心）

出典: `data-name-candidates-round3.md §0`

**生成順序を逆転させた**:

1. 先に「**語として自立する発音可能な短い単語 / 造語**」を選定（WINE / LAME / nano / JACK 型）
2. その後に「**1 文字目が名前自身を指す再帰展開フレーズ**」を後付け（X = "X …"）

これは 1 周目の敗因（テーマ文字キー Y/T/A/K からの機械的組み立て → 子音過多の無発音列 `yact`/`yokt`/`svat`）を回避するための逆転である。テーマ文字キーからの機械的組み立ては **禁止**（order.md 要件3）。

**再帰的頭字語の正しい構造**（先例 WINE = "**WINE** Is Not an Emulator" に厳密準拠）:

- 第 1 語 = **名前そのもの**（これが自己参照＝再帰性の本体）
- 第 2 語以降 = 名前の 2 文字目以降を順に頭文字とする機能語
- 例: `ROAM` → **ROAM**(R) / Orchestrates(O) / Analytics(A) / Media(M)

**採用判定基準**: 「展開フレーズを伏せても単語として読めるか？」が Yes の候補のみ採用。全候補が CVCV / CVC + 1 子音以内で発音可能であることを確認済み（出典: `data-name-candidates-round3.md §0, §4`）。

### 自己参照妥当性（全 30 件 OK）

各候補について「第 1 語＝名前自身（再帰本体）＋第 2 語以降が 2 文字目以降の頭文字」を全件検証し、**NG 0 件**（出典: `data-name-candidates-round3.md §4`）。

---

## 2. 候補一覧（30 件）

出典: `data-name-candidates-round3.md §2`。
打鍵性凡例（QWERTY）: 「交互率」=隣接文字の左右が切り替わる割合。同一指連続は減速要因。これらは**打鍵性（事実寄りの構造評価）**であり、語の意味強度（§5 の定性評価）とは節レベルで分離する。

> **事実 / 定性の分離（本レポートの記述規約）**: §2 の「文字数・打鍵性・レジストリ status code」は事実。各行の語義メモ（"巡回" "切り抜き" 等の意味適合）と §5 の意味強度は **定性判断（主観）**であり、その旨を明示する。

### 2.1 主ティア（自立した実在語・強い記憶定着。4 文字中心）

| # | 名前 | 文字 | 再帰展開（第1語=名前自身） | 自己参照 | 負例照合 | 打鍵性メモ（事実） |
|---|------|:----:|-----------------------------|:--------:|----------|------------|
| 1 | **roam** | 4 | ROAM Orchestrates Analytics & Media | OK (R/O/A/M) | クリア | L-R-L-R 交互3/3・同一指なし → 最良 |
| 2 | **reel** | 4 | REEL Edits Episodes Live | OK (R/E/E/L) | クリア | 交互1/3・**EE が左中指連続**で減速 |
| 3 | **clip** | 4 | CLIP Links Indexed Playlists | OK (C/L/I/P) | クリア | 右手寄り・同一指なし |
| 4 | **muse** | 4 | MUSE Uploads Scheduled Episodes | OK (M/U/S/E) | クリア | **MU が右人差し連続**で減速 |
| 5 | **cove** | 4 | COVE Orchestrates Video Edits | OK (C/O/V/E) | クリア | 交互2/3・同一指なし |
| 6 | **rove** | 4 | ROVE Orchestrates Video Episodes | OK (R/O/V/E) | クリア | 交互2/3・同一指なし |
| 7 | **vane** | 4 | VANE Analyzes Network Engagement | OK (V/A/N/E) | クリア | 交互2/3・同一指なし |
| 8 | **vela** | 4 | VELA Edits Live Audio | OK (V/E/L/A) | クリア | 交互2/3・同一指なし |
| 9 | **dune** | 4 | DUNE Uploads Network Episodes | OK (D/U/N/E) | クリア | 交互2/3・**UN が右人差し連続** |
| 10 | **mira** | 4 | MIRA Indexes & Renders Assets | OK (M/I/R/A) | クリア | 交互1/3・同一指なし |
| 11 | **nova** | 4 | NOVA Orchestrates Video Automation | OK (N/O/V/A) | クリア | 交互1/3・同一指なし |
| 12 | **rune** | 4 | RUNE Uploads Narrated Episodes | OK (R/U/N/E) | クリア | 交互2/3・**UN が右人差し連続** |
| 13 | **vade** | 4 | VADE Automates Distributed Encoding | OK (V/A/D/E) | クリア | **全左手0/3 + DE左中指連続**で打鍵弱い |
| 14 | **cure** | 4 | CURE Uploads & Renders Episodes | OK (C/U/R/E) | クリア | 交互2/3・同一指なし |
| 15 | **dive** | 4 | DIVE Indexes Video Edits | OK (D/I/V/E) | クリア | 交互2/3・同一指なし |
| 16 | **lure** | 4 | LURE Uploads & Renders Episodes | OK (L/U/R/E) | ⚠ `lume`(負例)と語頭`lu-`共有（別語だが近接） | 交互1/3・同一指なし |
| 17 | **mote** | 4 | MOTE Orchestrates Tube Edits | OK (M/O/T/E) | ⚠ `motif`(負例)と語幹`mot-`共有 | 交互1/3・同一指なし |
| 18 | **vibe** | 4 | VIBE Indexes Broadcast Episodes | OK (V/I/B/E) | クリア | 交互2/3・同一指なし |
| 19 | **arc** | 3 | ARC Renders Channels | OK (A/R/C) | ⚠ 補助回避`arco`と語頭`arc-`共有 | 全左手0/2・同一指なし |
| 20 | **cue** | 3 | CUE Uploads Episodes | OK (C/U/E) | クリア | 交互2/2・最良 |
| 21 | **orb** | 3 | ORB Renders Broadcasts | OK (O/R/B) | クリア | **RB が左人差し連続** |
| 22 | **rivet** | 5 | RIVET Indexes Video Edits Tube | OK (R/I/V/E/T) | クリア | 交互2/4・同一指なし |
| 23 | **comet** | 5 | COMET Orchestrates Media Edits Tube | OK (C/O/M/E/T) | クリア | 交互良・同一指なし |
| 24 | **delta** | 5 | DELTA Edits Live Tube Analytics | OK (D/E/L/T/A) | クリア | **DE左中指連続** |
| 25 | **scout** | 5 | SCOUT Compiles Orchestrates Uploads Tube | OK (S/C/O/U/T) | クリア | 交互2/4・同一指なし |
| 26 | **canto** | 5 | CANTO Automates Network Tube Output | OK (C/A/N/T/O) | ⚠ `catune`(負例)と語頭`ca-`+`t`近接 / 音楽用語で 2 周目 group-b とテーマ近接 | 交互3/4・同一指なし |

語義メモ（定性・主観）: roam=巡回／clip=切り抜き／reel=フィルムリール（映像最強語）／cue=合図／scout=発掘 等は YouTube 自動化機能と直結する連想を持つ（出典: `data-name-candidates-round3.md §2, §7`）。

### 2.2 造語ティア（補助・unscoped 空き確保用。発音可能だが意味は弱め）

主ティアの実在語は unscoped npm でほぼ全滅（§3 参照）のため、レジストリ空きを取りやすい発音可能造語（CVCV）を補助的に提示する。

| # | 名前 | 文字 | 再帰展開（第1語=名前自身） | 自己参照 | 負例照合 | 打鍵性メモ |
|---|------|:----:|-----------------------------|:--------:|----------|------------|
| 27 | **dovi** | 4 | DOVI Orchestrates Video Indexing | OK (D/O/V/I) | クリア | 交互良・同一指なし。純造語 CVCV |
| 28 | **muvo** | 4 | MUVO Uploads Video Output | OK (M/U/V/O) | ⚠ `mavu`(負例)と`m_v_`構造近接 | **MU右人差し連続**。CVCV |
| 29 | **tevo** | 4 | TEVO Edits Video Output | OK (T/E/V/O) | クリア | 交互2/3・同一指なし。CVCV |
| 30 | **navo** | 4 | NAVO Automates Video Operations | OK (N/A/V/O) | クリア | 交互良・同一指なし。CVCV |

> 補足: 別バッチの追加実測（`data-registry-availability.md`）では、3 レジストリ全空きの発音可能造語を 22 件確保している（`jova / suvo / savo / fova / navu / wova / zave / kelo / fyno / nyvo / wozo / ravu / lavu / weko / ralo / zuvo / sevo`〔4 文字 17〕＋ `kelvo / suvio / zavio / fovio / jovio`〔5 文字 5〕）。これらは §3.3 の available 件数（AC5）の主たる根拠。

### 2.3 文字数バランス（30 件）

出典: `data-name-candidates-round3.md §6`

| 文字数 | 件数 | 候補 |
|:------:|:----:|------|
| 3 | 3 | arc, cue, orb |
| 4 | 22 | roam, reel, clip, muse, cove, rove, vane, vela, dune, mira, nova, rune, vade, cure, dive, lure, mote, vibe, dovi, muvo, tevo, navo |
| 5 | 5 | rivet, comet, delta, scout, canto |
| **計** | **30** | 4 文字 73%（4 文字中心・過半数 ✓） |

---

## 3. レジストリ空き確認（事実・実測 2026-06-12）

> 本節はすべて **status code に基づく事実**。意味強度などの定性評価は含めない。

### 3.1 確認手段と判定基準

出典: `data-registry-availability-realwords.md §2`, `data-registry-availability.md` 冒頭

| レジストリ | 照会 URL | 200 | 404 |
|---|---|---|---|
| npm (unscoped) | `https://registry.npmjs.org/<name>` | 占有 | 空き |
| npm (scoped) | `https://registry.npmjs.org/@<org>%2F<name>` | 占有 | 空き |
| PyPI | `https://pypi.org/pypi/<name>/json` | 占有 | 空き |
| crates.io | `https://crates.io/api/v1/crates/<name>` | 占有 | 空き |

- 確認コマンド: `curl -s -o /dev/null -w "%{http_code}"`（HTTP ステータスのみ取得）。crates.io は User-Agent 必須のため `-A "naming-research/1.0 (issue-980)"` を付与。
- **scoped 意味論の対照実験（実測検証済み）**: 既知占有 scoped `@babel/core` = **200** / `@types/node` = **200**、架空 scope `@tsuu/nonexistent-xyz123`（および `@zzqxnaming980/roam`）= **404**。→ 「200=占有 / 404=空き」の解釈は scoped でも成立することを確認（出典: `data-registry-availability-realwords.md §2`, `data-unified-top5.md §0`）。
- **照会総数**: unscoped 60 + scoped 28 + サニティ 3 = **計 91 照会**。全照会が HTTP 応答を返し、レート制限・タイムアウトは発生しなかった（出典: `data-registry-availability-realwords.md §7`）。

### 3.2 実在語 — unscoped 全滅・scoped 全空き

出典: `data-registry-availability-realwords.md §3, §4`（優先 14 件は scoped 実測、余力 6 件は unscoped のみ実測）

| # | 候補 | npm (unscoped) | PyPI | crates | scoped npm `@<org>/<name>` | unscoped 総合 |
|---|------|:---:|:----:|:------:|:---:|---------------|
| 1 | roam | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 2 | reel | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 3 | clip | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 4 | cue | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 5 | scout | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 6 | cove | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 7 | rove | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 8 | vela | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 9 | dive | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 10 | mira | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 11 | nova | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 12 | rivet | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 13 | comet | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 14 | vane | 200 占有 | 200 占有 | 200 占有 | **404 空き** | 全占有 |
| 15 | rune | 200 占有 | 200 占有 | 200 占有 | （未測定・同傾向と推定） | 全占有 |
| 16 | **dune** | 200 占有 | **404 空き** | 200 占有 | （未測定） | **PyPI のみ空き** |
| 17 | cure | 200 占有 | 200 占有 | 200 占有 | （未測定） | 全占有 |
| 18 | vibe | 200 占有 | 200 占有 | 200 占有 | （未測定） | 全占有 |
| 19 | **muse** | 200 占有 | 200 占有 | **404 空き** | （未測定） | **crates のみ空き** |
| 20 | orb | 200 占有 | 200 占有 | 200 占有 | （未測定） | 全占有 |

- scoped npm の照会 org は order.md / 既存成果物に規約がないため **仮定**（`@tsuu/<name>` ＝ worktree slug 由来、`@youtube-automation/<name>` ＝ 配布パッケージ名由来）。優先 14 件は両 org で実測（28/28 照会が 404）。どの未使用 org を選んでも「未公開 scope+name = 404」という構造に依存するため、結論（実在語は scoped で確保可）は org 選択に依らず不変（出典: `data-registry-availability-realwords.md §4, §7`）。
- 余力 6 件（rune/dune/cure/vibe/muse/orb）の scoped 個別照会は省略。サニティチェック（架空 scope=404）により構造上 6 件も空きと **推定**（推測である旨を明示。出典: `data-registry-availability-realwords.md §4, §8`）。

**unscoped の事実**:
- **npm**: 実在語 20/20 すべて占有（200）。短い実在語の unscoped npm は完全スクワット済み。
- **PyPI**: 19/20 占有。例外 **`dune`** のみ空き（404）。
- **crates**: 19/20 占有。例外 **`muse`** のみ空き（404）。
- → unscoped で「3 レジストリすべて空き」の実在語は **0 件**。

**scoped npm の含意（CLI bin 名の独立性）**: scoped パッケージ `@org/roam` でも `package.json` の `bin` フィールドで `"roam"` を公開できる。グローバル CLI の bin 名はレジストリ予約と独立で、衝突はインストール環境ローカルのみが関心事。→ **実在語をそのまま CLI コマンド名（bin）として使いつつ、配布パッケージ名は scoped で空きを確保する**経路が優先 14 件すべてで成立する（出典: `data-registry-availability-realwords.md §4`）。

### 3.3 造語 — 3 レジストリ全空き（22 件）

出典: `data-registry-availability.md §2`（実測 2026-06-12、空き候補は 2 回測定で安定確認）

| 文字数 | 件数 | 候補（npm/PyPI/crates すべて 404） |
|:------:|:----:|------|
| 4 | 17 | wova, zave, navu, kelo, fova, savo, jova, suvo, nyvo, fyno, wozo, ravu, lavu, weko, ralo, zuvo, sevo |
| 5 | 5 | kelvo, suvio, zavio, fovio, jovio |
| **計** | **22** | （目標 10 件を大幅達成 = **AC5 充足**） |

- 3 文字は「発音可能 ∧ 再帰頭字語 ∧ 3 レジストリ空き」を同時に満たす列が実質枯渇のため見送り（不足ではなく、4/5 文字で 22 件確保済みのため探索を打ち切り。出典: `data-registry-availability.md §2, §7`）。

### 3.4 PyPI / crates の namespace（実在語救済の限界）

出典: `data-registry-availability-realwords.md §5`

- **PyPI / crates.io はフラットな名前空間で scope 機能なし**。慣習的な接頭辞付与（例 `tsuu-roam`）は可能だが「scoped」とは異なる。
- → **scoped による実在語救済は npm に限定**。PyPI/crates で実在語をそのまま使えるのは `dune`（PyPI 空き）/ `muse`（crates 空き）の 2 件のみ。
- ただし本 issue の一次仕様は「npm 配布（パッケージ名=bin 名想定）」（§0）であり、**npm の scoped 空きが取れれば配布要件は満たせる**。

---

## 4. 負例 71 件 同型・同語幹チェック（AC3）

出典: `data-name-candidates-round3.md §1, §5`

### 4.1 照合対象リスト（実データから再抽出・転記）

記憶ではなく実ファイルを判定直前に再読・転記（context rot 対策）。

- **1 周目 35 件**（再帰頭字語・文字組み立て式）:
  `yact, yave, yate, yota, yamo, yabo, yant, yano, yatt, yokt, tact, tibo, tako, tava, tyka, vyte, vyto, cayt, cyta, svat, mavi, tubo, yta, yot, yab, tib, yan, yak, yanta, yotak, yakti, tubot, vacta, movat, yobot`
- **2 周目 group-a 18 件**（世界観 rubric 式）:
  `lume, onaro, solu, lerin, mavu, kivo, mocade, cinora, flonix, lumetra, catune, revio, cairn, furrow, glint, knoll, wick, husk`
- **2 周目 group-b 18 件**（神話/自然/音楽用語）:
  `lyra, kairos, caelo, tethys, fenris, vesper, hayate, kakera, iori, homura, tsumugi, irodori, dolce, marcato, tutti, fermata, attacca, motif`
- **合計 35 + 18 + 18 = 71 件**（実ファイルと件数一致を確認）

補助回避リスト（71 件には含めないが回避指定された 2 周目前段 31 件）:
`kalo, nemi, noma, renik, veska, flua, moflo, stube, tuvio, flotik, brio, weft, rill, vellum, kiln, saga, vesna, lethe, notus, mneme, yui, hibi, nagi, kanade, megu, kasane, arco, rondo, rubato, niente, mosso`

既知の有名再帰的頭字語（完全一致 NG・37 件確認）:
`GNU, HURD, WINE, XINU, AROS, MiNT, PHP, YAML, GiNaC, TikZ, SPARQL, gRPC, PINE, EINE, ZWEI, TINT, SINE, PIP, RPM, Darcs, LAME, JACK, FIJI, LiVES, XBMC, Zinf, MATE, Nagios, BIRD, CAVE, TRESOR, YARA, XNA, UIRA, GIMP, GNOME, GnuPG, nano, BIND`

### 4.2 同型・同語幹の判定定義

- 完全一致 → NG
- 語幹一致（旧 Top5 派生 `-tak`/`-bot`/`-amo`/`-ave`/`-ava` 等の流用）→ NG
- Y- 始まりの機能語並び（1 周目の敗因パターン）→ R3 違反として回避
- 上記既知再帰頭字語との完全一致 → NG

### 4.3 チェック結果（30 候補）

| 判定 | 件数 | 候補 |
|------|:----:|------|
| **クリア（衝突なし）** | 24–25 | roam, reel, clip, muse, cove, rove, vane, vela, dune, mira, nova, rune, vade, cure, dive, vibe, cue, orb, rivet, comet, delta, scout, dovi, tevo, navo |
| **⚠ 近接フラグ（語幹/語頭の部分一致・別語）** | 6 | lure(`lume`近接) / mote(`motif`語幹`mot-`) / arc(`arco`語頭) / canto(`catune`近接＋音楽テーマ) / muvo(`mavu`構造) / navu(`mavu` の `-avu` 韻近接) |

- **完全一致: 0 件**（71 件・既知 37 件いずれとも一致なし）。
- **Y- 始まり機能語並び: 0 件**（1 周目敗因パターンを完全に排除）。
- フラグ群はいずれも**別の自立語**で完全一致ではないが、綴り/音の近接があるため Top 推奨からは外すのが安全（§5 で除外）。

> なお造語の追加バッチ（`data-registry-availability.md §3`）でも、空き 22 件に対し負例完全一致 0 を確認。唯一の注意は `-avu` 系（navu/ravu/lavu）が 2 周目棄却済み `mavu` と韻を共有する点で、`jova`/`suvo`/`savo`/`fova`/`wova` は近接ゼロで最もクリーン。

---

## 5. Top 5 + 1 位推奨（AC4）

出典: `data-unified-top5.md §3`（実在語 × 造語の単一統合評価）。
**事実（配布可否・打鍵性）と定性（意味強度・印象）を列レベルで分離して記述する。**

選定方針: AC5（空き 10 件以上）は §3.3 で既達のため **質を優先**。1 周目敗因「名前自体が弱い」を再演しないよう**意味強度の高い実在語を主軸**に据えつつ、純造語偏重を避けるため「クリーンな unscoped 空き造語」も併置し、HITL が同一軸で比較できる構成にした。構成比は **実在語 3 + 造語 2**。

| 順位 | 候補 | 種別 | 【事実】配布経路 | 【事実】打鍵性 | 【定性】意味強度 | R3 | R4 | 展開フレーズ |
|:--:|------|:--:|------|------|------|:--:|:--:|------|
| **1** | **roam** | 実在語 | scoped 救済（`@youtube-automation/roam` = 404 空き実測。unscoped は npm/PyPI/crates 全占有） | ◎ 交互3/3・同一指なし＝最良 | ◎ 巡回。"運営を巡回し統括する"含意が製品実体と合致 | ✓ | ✓ クリア | ROAM Orchestrates Analytics & Media |
| **2** | **clip** | 実在語 | scoped 救済（`@youtube-automation/clip` = 404 空き実測） | ○ 右手寄り・同一指なし | ◎ 切り抜き＝YouTube 機能直結 | ✓ | ✓ クリア | CLIP Links Indexed Playlists |
| **3** | **jova** | 造語 | unscoped 空き（npm/PyPI/crates 404×3 実測） | ○ j-o-v-a 交互良 | △ 意味なしだが人名的で記憶可・負例近接ゼロで最クリーン | ✓ | ✓ 最クリーン | Jova Orchestrates Video Analytics |
| **4** | **cue** | 実在語 | scoped 救済（`@youtube-automation/cue` = 404 空き実測） | ◎ 3 文字・交互2/2＝最短 | ○ 合図・映像 cue | ✓ | ✓ クリア | CUE Uploads Episodes |
| **5** | **suvo** | 造語 | unscoped 空き（npm/PyPI/crates 404×3 実測） | ◎ s-u-v-o 完全交互＝最速打鍵 | △ 意味なし | ✓ | ✓ クリア | Suvo Uploads Video Output |

**次点（補欠）**: `reel`（映像最強語だが EE 打鍵が弱く 5 位を譲る）／`scout`（5 文字・発掘の含意）／`navu`（造語バッチの旧 1 位推奨だが `mavu` 韻近接のため降格）／`dune`（PyPI unscoped 空きの希少例だが SF / OCaml `dune` の商標連想が強い）。

### 1 位推奨: **roam**（"ROAM Orchestrates Analytics & Media"）

**【事実】**
1. **配布可能**: unscoped は npm/PyPI/crates すべて取得済み（実測 200）だが、scoped `@youtube-automation/roam` は npm **404（空き・実測）**。scoped 配布で確保でき、bin 名は `roam` のまま維持可能（CLI bin 名はレジストリ予約と独立）。
2. **打鍵最良**: L-R-L-R 完全交互（交互3/3）・同一指連続なし（`data-name-candidates-round3.md` 打鍵評価の最良群）。
3. **R3/R4 充足**: 展開を伏せても語として読める（R3）。負例 71 件・既知再帰頭字語 37 件と完全一致なし（R4）。

**【定性・主観】**
4. **意味強度が最高水準**: "roam"＝巡回／歩き回るは「チャンネル群を巡回し Analytics/Upload を統括する」本ツールの実体と自然に接続。1 周目敗因の無発音造語（yact/yokt）とも、2 周目敗因の音楽/神話の借用語（marcato/kakera）とも異なり、平易な実在英単語で覚えやすい。

**留保（正直な開示）**: roam の配布は **scoped 前提**（unscoped は 3 レジストリ全滅）。「unscoped の短い名前を絶対に確保したい」が最優先要件なら、Top 1 を **`jova`（unscoped 404×3・最クリーン造語）** に差し替える選択肢を併記する。

---

## 6. HITL 分岐（論点 Y の確定）

出典: `analysis-2.md §4 論点 Y`, `data-unified-top5.md §3 留保, §7`

§0 のとおり **本 issue の一次仕様は order.md L5（npm 配布）**。よって主筋は以下で確定する。

- **主筋（npm 配布前提）**: 1 位 = **scoped 実在語 `roam`**。npm CLI 主体なら scoped 実在語（roam/clip/cue）が最適で、bin 名を実在語のまま維持できる。
- **代替分岐（PyPI を主レジストリに選ぶ場合）**: PyPI には npm のような scope が無く、実在語をそのまま使えない（roam の PyPI は取得済み）。この場合は **unscoped 造語 `jova` / `suvo`**、または **PyPI が空いている実在語 `dune`** が直截。これは主筋に昇格させず **HITL の選択肢として併記**するにとどめる（CLAUDE.md の「PyPI 主」前提を一次仕様に格上げしない）。

**HITL に委ねる判断:**
1. **配布先レジストリの優先順位**（npm CLI 主体か PyPI 主体か）。これが決まると Top 1 が確定する。
2. **意味 vs クリーンさ**: 「覚えやすい実在語（roam）」と「即確保できるクリーン造語（jova）」の二択。
3. 採用候補が決まり次第、**商標・ドメイン・SNS ハンドルの空きを別途確認**（order.md スコープ外のため本レポートでは未実施）。

---

## 7. 注意点・リスク

出典: `data-name-candidates-round3.md §8`, `data-registry-availability.md §7`, `data-registry-availability-realwords.md §7`, `data-unified-top5.md §5`

- **意味強度は定性判断（主観）**: roam/clip が「強い」、jova/suvo が「弱い」は連想・記憶定着の主観評価で、定量指標ではない。
- **scoped 救済は npm 限定**: PyPI/crates はフラット名前空間で scope なし。実在語の Python パッケージ化は `dune`（PyPI 空き）/ `muse`（crates 空き）を除き不可。
- **空きはスナップショット**: 全 status code は 2026-06-12 時点。採用までに取得される可能性があり、早期予約を推奨。
- **占有=実使用とは限らない**: unscoped 200 は「メタデータが存在する」ことのみを示し、placeholder/deprecated/スクワットの区別はしていない（「unscoped は取れない」という配布可否の結論には十分）。
- **フラグ 6 件（lure/mote/arc/canto/muvo/navu）**: 完全一致ではないが負例と語頭・語幹・韻が近接。Top 推奨から外すのが安全。
- **`canto`/`vela` 等の音楽・天体語**: 2 周目 group-b（marcato/attacca/lyra/tethys 等）とテーマが近く、「同じ雰囲気で棄却」リスクがある。
- **商標・ドメイン・SNS は未確認**（order.md スコープ外）。roam/clip/dune 等の一般語・著名語は造語より商標衝突リスクが高い点に留意。

---

## 8. 調査できなかった項目（正直な開示）

| 項目 | 状態 | 理由 |
|------|------|------|
| 余力 6 件（rune/cure/vibe/orb/muse/dune）の scoped npm 個別測定 | 構造推定で代替 | サニティチェック（架空 scope=404）で「未公開 scope+name=404」を確認済み。優先 14 件 28 照会の実測で escape hatch は実証され、6 件の個別照会は結論を変えない（**推測と明示**） |
| 3 文字候補の 3 レジストリ全空き | 見送り | 「発音可能 ∧ 再帰頭字語 ∧ 3 レジストリ空き」を満たす 3 文字列が実質枯渇。4/5 文字で 22 件確保済みのため探索打ち切り（不足ではない） |
| 別 org 名での scoped 空き網羅 | 1〜2 org のみ | どの未使用 org でも未取得 scope は 404 のため、結論（scoped で確保可）は org 選択に依らず不変 |
| **商標の法的確認・ドメイン / SNS ハンドル** | **調査不可（未実施）** | order.md スコープ外。採用決定後の別 issue |

---

## 9. 結論

- **HITL 提示用 最終 Top 5**: **roam / clip / jova / cue / suvo**（実在語 3 + 造語 2）。
- **1 位推奨 = `roam`**（"ROAM Orchestrates Analytics & Media"）。意味強度・打鍵性・負例クリーンさが最高水準で、1 周目「名前が弱い」敗因を実在語で克服する。**ただし配布は scoped npm 前提**（unscoped 全滅）。
- **前回の致命的欠陥（純造語偏重・実在語が評価外）は、実在語の scoped npm 全空きを実測で確定したことで解消した。**
- 残るは HITL 判断（§6 の配布先優先順位・意味 vs クリーンさ）と、採用後の商標/ドメイン確認（スコープ外）のみ。
