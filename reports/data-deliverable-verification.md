# 成果物検証レポート: docs/research/naming-round3.md（dig.verify-deliverable）

- 検証日: 2026-06-12
- 対象: `docs/research/naming-round3.md`（write-deliverable パート作成）
- 検証種別: 軽量検証（再調査なし。判断直前に実ファイル・コマンドを再実行）
- 統合元 reports: `.takt/runs/20260612-141536-implement-using-only-the-files-w44j1l/reports/`

---

## 1. ファイル存在確認

| 確認項目 | 結果 |
|---|---|
| `ls -la docs/research/naming-round3.md` | **存在**（29670 bytes, 2026-06-12 23:47） |
| `git status` | `?? docs/research/`（未追跡＝正常。commit はシステム側で実施） |

→ **PASS**。実リポジトリに配置済み。

---

## 2. AC 充足チェック（本文 naming-round3.md を読了）

| AC | 内容 | 充足箇所 | 判定 |
|---|---|---|---|
| AC1 | 再帰頭字語 20〜30 件（語先・展開後） | §2 候補一覧：主ティア 26 件＋造語ティア 4 件＝**30 件**（§2.3 文字数バランスで計 30 を再掲、3字3/4字22/5字5） | **PASS** |
| AC2 | 各候補に展開・文字数・打鍵性・npm/PyPI/crates 空き | §2 各行に「文字数・再帰展開・自己参照・負例照合・打鍵性メモ」、§3.2/§3.3 にレジストリ status code（npm/PyPI/crates／scoped）が揃う | **PASS** |
| AC3 | 負例 71 件との同型・同語幹チェック、完全一致 0・近接 6 件 | §4：35+18+18=**71 件**を実リスト転記、§4.3 で**完全一致 0 件**・**近接フラグ 6 件**（lure/mote/arc/canto/muvo/navu）明記 | **PASS** |
| AC4 | Top5＋1位推奨を理由付き・事実/定性分離 | §5：Top5（roam/clip/jova/cue/suvo）を【事実】配布経路・打鍵性／【定性】意味強度の列分離で提示、1位 roam を事実4点・定性1点＋留保付きで推奨 | **PASS** |
| AC5 | available 10 件以上 | §3.3：造語 3 レジストリ全空き **22 件**（目標 10 を大幅超過）＋ §3.2 実在語 scoped 空き 14 件 | **PASS** |
| AC6 | レジストリ実測の出典（実測日・照会数・status code） | §3.1：実測日 **2026-06-12**、照会総数 **91**（unscoped60＋scoped28＋サニティ3）、curl コマンド・status code 判定基準（200=占有/404=空き）、scoped 対照実験（@babel/core=200, @types/node=200, 架空scope=404）を明記 | **PASS（核心）** |

---

## 3. データ忠実性チェック（本文 vs 統合元 reports 抜き取り照合）

| 主要数値 | 本文 | 統合元 report | 一致 |
|---|---|---|---|
| 候補総数 30 | §2.3「計 30」 | `data-name-candidates-round3.md §6`「計 30」 | ✓ |
| 負例 71 | §4「35+18+18=71」 | `data-name-candidates-round3.md`「合計 35+18+18=71」 | ✓ |
| 近接 6 件 | §4.3「6」(lure/mote/arc/canto/muvo/navu) | candidates §2 で 5 フラグ + availability で navu → 合算 6（整合） | ✓ |
| available 22 件（造語全空き） | §3.3「計 22」 | `data-registry-availability.md`「fully available = 22 件」（実カウント `**空き**`=22 行） | ✓ |
| scoped 実在語 空き 14 件 | §3.2「優先14件 28/28 照会が404」 | `data-registry-availability-realwords.md §4`「14/14（28照会全404）」 | ✓ |
| 照会総数 91 | §3.1「unscoped60+scoped28+サニティ3=91」 | `data-registry-availability-realwords.md §7`「60+28+3=91」 | ✓ |
| scoped 対照実験 200/404 | §3.1（@babel/core=200, @types/node=200, 架空scope=404） | realwords §2（@babel/core, @types/node=200, @tsuu/nonexistent=404）＋ unified-top5 §0（@zzqxnaming980/roam=404） | ✓ |
| Top5 構成 | roam/clip/jova/cue/suvo（実在語3+造語2） | `data-unified-top5.md §3`「roam/clip/jova/cue/suvo」 | ✓ |
| 実測日 2026-06-12 | §3 全体 | 3 データファイルすべて取得日2026-06-12 | ✓ |

→ **改変・捏造なし**。本文の数値はすべて統合元 reports と一致。出典ファイル名も各節に正しく明記されている。

### 補足（軽微・問題なし）
- §3.2 の「unscoped: 実在語20件中 PyPI例外=dune／crates例外=muse」は realwords report のマトリクスと一致。
- 本文 §0 で order.md(npm) vs CLAUDE.md(PyPI) の食い違いを「order.md 優先」と明示し、`analysis-2.md §4` を出典に HITL 分岐(§6)へ正しく振り分け。データ忠実性・トレーサビリティ良好。

---

## 4. 総合判定

**PASS** — 核心 AC#6（レジストリ実測の出典＝実測日2026-06-12・照会91・status code）達成。AC#1〜#5 も本文で充足、主要数値はすべて統合元 reports と一致し改変・捏造なし。ファイルは `docs/research/naming-round3.md` に実配置済み（未追跡だが正常）。
