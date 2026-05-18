# 調査レポート

## 調査概要

Issue #353「chore(skills): スキル汎用化・整合性の棚卸し監査レポート生成」の supervise ステップとして、analyze ステップが出力した `analysis-1.md` を order.md の 8 観点 + 既知シード 4 件に照らして評価し、最終レポート `docs/audits/skills-audit-2026-05-18.md` の骨格として採用可能か判定した。

## 主要な発見

- analysis-1.md は order.md の全 8 観点（1.1〜1.4 / 2.1〜2.4）を `file:line` 付きで網羅しており、policy の出典明記要件を充足。
- 既知シード 4 件（重複スクリプト 3 種・`streaming --check-threshold`・`TBD` 統一・`postmortem` バトン）はすべて検証完了。うち `.py` 重複と `TBD` は **seed 側の前提誤認 / 既に解決済み**と判定され、最終レポートで短く言及するだけで足りる状態。
- 3 つの dig 報告書（Part A 第 1/2 版・Part B・Part C 第 1/2 版）間で重要発見の矛盾なし。観点定義の差分は supervise の整形で吸収可能。
- 「修正対象」と「正当な設計判断」の境界が `N-1〜N-7` として明示否定されており、policy「事実と推測の分離」要件を充足。
- 残存ギャップ G-1〜G-4 は重要度が低〜中で、いずれも本 issue（棚卸し監査）のスコープ内で「要確認マーク付き記載」または「別 issue 化提案」で処理可能。追加調査は不要。
- 判定: **APPROVE**。policy の APPROVE 条件 3 つすべて充足、REJECT 条件のいずれにも該当せず、80% 基準を超過。

## 調査結果

### トピック 1: 元依頼の各要件カバレッジ

order.md 「スコープ（必ず全てカバーすること）」 8 項目との突合せ結果:

| order.md 要件 | analysis-1.md 該当節 | 検出件数 / 内容 | 評価 |
|---|---|---|---|
| 1.1 ハードコード値の `file:line` 列挙 + 推奨移行先併記 | §1 観点 1.1 / §5 P1（H-2/H-4/H-5）+ P2（M-6）+ P3（L-10/L-12/L-13） | P1=6 / P2≈25 / P3≈20 件。移行先（`meta.json::channel.brand_color` / `config/skills/<skill>.yaml::<key>` 等）併記 | OK |
| 1.2 重複スクリプト共通化候補（`benchmark_collector`/`generate_image`/`fetch_benchmark_comments` 既知シード含む） | §1 観点 1.2 / §5 P1（H-6）/ §3 検証済み懸念 | `scripts/gcp-bootstrap.sh` ≡ `channel-setup/references/gcp-bootstrap.sh`（MD5 `e421...606a`）、`scripts/gcp-terraform-apply.sh` ≡ `channel-setup/references/gcp-terraform-apply.sh`（MD5 `358b...244`）の 2 ペア確定。`.py` 重複は **seed 配置誤認**として独立 grep で否定（実体は `src/youtube_automation/scripts/` 配下に各 1 件のみ） | OK |
| 1.3 skill-specific config 余地 | §1 観点 1.3 / §5 P2（M-1〜M-6） | 既存 `config.default.yaml` 9 スキル / 新規候補（小）11 件 / （中〜大）5 件 | OK |
| 1.4 既存 config 未参照（直書きしている箇所） | §1 観点 1.4 / §5 P1（H-1/H-3）+ P2（M-7〜M-10） | P1=4（旧 namespace `channel_config.tags.themes` 等）/ P2≈9（`category_id: "10"` の 3 ファイル重複、`privacy_status` 矛盾、`config/channel/*.json` 7 ファイル → 8 ファイル更新漏れ等） | OK |
| 2.1 description ↔ references/ 実装乖離 | §1 観点 2.1 / §5 P1（H-7/H-9）+ P3（L-11） | Major 1 件（`video-analyze` の `/lyria`・`/channel-direction` 事実誤認）/ Minor 2 件（`video-upload` single_release 言及欠落 等） | OK |
| 2.2 バトン双方向整合（`postmortem` の曖昧バトン具体化案含む） | §1 観点 2.2 / §5 P1（H-8）+ P2（M-11〜M-14）+ P3（L-7/L-8） | 双方向成立 14 ペア / 片方向要修正 4 ペア / 意図的 fan-out 10 ペア。`postmortem` は意図的メタスキルとして明示否定 N-3 | OK |
| 2.3 v4.0.0 deprecated（short/community）参照 | §1 観点 2.3 / §5 P1（H-10） | 真の残存 1 件（`video-description/config.default.yaml:6` のコメント内 `short`）/ 偽陽性 18 件除外 | OK |
| 2.4 形式揺れ（trigger 語形式・Use when 構文・ファイル構成） | §1 観点 2.4 / §5 P2（M-15/M-16）+ P3（L-9） | frontmatter/開始句/kebab-case 命名は 100% 統一（35/35）/ description 末尾指示語 5 系統 / 本文見出し 3 系統 / テンプレ命名 3 様式 | OK |

### トピック 2: 既知シード 4 件の検証

order.md 「既知のシード」節との突合せ:

| シード | analyze 結論 | 検証手段 | 評価 |
|---|---|---|---|
| 重複スクリプト 3 種（`benchmark_collector.py × 3` / `generate_image.py × 3` / `fetch_benchmark_comments.py × 2`） | **配置誤認**。`.claude/skills/**/references/` には Python ファイル 0 個、実体は `src/youtube_automation/` 配下に各 1 件のみ。コード重複は存在しない | analyze §3 で `Grep` による独立再検証 | OK（seed 誤認を明記） |
| `streaming/SKILL.md` の `--check-threshold` が config 非連動 | 検出済（3 報告書一致）。`config/skills/streaming.yaml::bandwidth_threshold_ratio` 新設を提案 | Part A 第 1 版 #5.18 / Part A 第 2 版 A1-3 / Part B 候補 #11 で三重検出 | OK |
| `channel-new` / `channel-direction` 初期値 `"TBD"` 仕様未統一 | **既に解決済み**。`TBD` 出現は `channel-new/SKILL.md:107` の 1 箇所のみで CLI 既定値説明として明文化。`/channel-direction` で実値上書きフローも明記 | analyze §3 で `Grep "TBD"` による独立再検証 | OK（解決済みを明記） |
| `postmortem` のバトン記述曖昧 | 検出済。意図的 fan-out メタスキルとして 4 検証 skill 側に back-ref を強要しない方針として明文化を推奨 | Part C 第 1/2 版双方で検出、明示否定 N-3 として整理 | OK |

### トピック 3: policy 適合性評価

| policy 項目 | analysis-1.md の状態 | 評価 |
|---|---|---|
| 自律行動（質問しない、仮定明示） | ユーザーへの問い合わせなし、観点定義差は「第 1 版優先」と仮定を明示 | OK |
| 事実と推測の分離 | H-8（master 命名不整合）に「実害判定要再現」と留保、G-2/G-4 は「実装側読みが必要」と明示 | OK |
| 定量優先 | P1=10 / P2=16 / P3=14 / 明示否定 7 件、双方向 14 ペア / 片方向 4 ペア / 35 ファイル等、すべて数値記載 | OK |
| 出典明記 | 全検出に `file:line` 形式の出典（例: `analytics-report/SKILL.md:94-101`、`channel-new/SKILL.md:107`） | OK |
| 正直な報告 | 残存ギャップ G-1〜G-4 を §4 で明示、調査不可項目（実装側コード読み）はスコープ外と理由明記 | OK |
| 80% 基準 | 8 観点 + 既知シード 4 件すべて検出済み、追加調査の限界効用が小さい | OK |
| 結論 + 根拠 + 分析 | §5 fix 一覧（結論）+ 出典列（根拠）+ §2 観点別判断（分析）で揃う | OK |

### トピック 4: 残存ギャップの supervise レポート生成への影響

analysis §4 で特定された G-1〜G-4 の処理方針:

| ID | ギャップ内容 | 重要度 | supervise 整形時の処理 |
|---|---|---|---|
| G-1 | Part A 第 1 版 vs 第 2 版の観点定義差（A-1〜A-5 カテゴリ区分） | 低 | 第 1 版（A-1=ID リテラル限定）の用語を採用し、第 2 版の件数差は脚注扱い |
| G-2 | `video-description/SKILL.md` ハッシュタグ 13 個 vs `config-generation-rules.md` 5 個の数値矛盾 | 中 | M-10 として「要確認マーク」付きで列挙、別 issue 化を「次に取るべきアクション」節で提案 |
| G-3 | Part C 片方向バトン件数差（14 中 4 vs 9 中 P1=3〜4） | 低 | 顔ぶれが一致しているため、supervise 整形で件数表記を統一 |
| G-4 | `lyria`/`masterup` 出力 ↔ `videoup/generate_videos.sh` 検出パターン不一致の実害判定 | 中〜高 | H-8 として記載、修正案 a/b/c を提示、別 issue 化を提案 |

いずれも本 issue（棚卸し監査レポート生成）のスコープ内で処理可能。修正実装は本 issue の責務外であり、analysis の整理で十分。

## データソース

| # | ソース | 種別 | 信頼度 |
|---|--------|------|--------|
| 1 | `.takt/runs/20260518-074104-issue-353-chore-skills-claude/reports/analysis-1.md` | コードベース（analyze ステップ出力） | High |
| 2 | `.takt/runs/20260518-074104-issue-353-chore-skills-claude/context/task/order.md` | コードベース（issue 仕様書） | High |
| 3 | `.takt/runs/20260518-074104-issue-353-chore-skills-claude/context/policy/supervise.1.20260518T083944Z.md` | コードベース（policy 定義） | High |
| 4 | `.takt/runs/20260518-074104-issue-353-chore-skills-claude/context/knowledge/supervise.1.20260518T083944Z.md` | コードベース（knowledge 定義） | High |
| 5 | analysis §3 が引用する独立検証（`Grep "benchmark_collector\|fetch_benchmark_comments\|generate_image"`、`Grep "TBD"`、`ls .claude/skills/`） | コードベース（analyze による再検証） | High |
| 6 | 3 つの dig 報告書（Part A 第 1/2 版・Part B・Part C 第 1/2 版） | コードベース（dig ステップ出力、analysis §2.1 で相互整合性確認済み） | High |

## 結論と推奨

### 判定: APPROVE（承認）

analysis-1.md は order.md の 8 観点すべてを `file:line` 出典付きで網羅し、既知シード 4 件をすべて検証（うち 2 件は seed 自体の誤認/解決済みと判定）。policy「APPROVE 条件」3 つ（明確な回答 / 十分な根拠 / 重大な調査漏れなし）をすべて充足、REJECT 条件のいずれにも該当しない。Planner への差し戻しは不要。

### supervise レポート生成への引き継ぎ指示

最終レポート `docs/audits/skills-audit-2026-05-18.md` の生成時、analysis-1.md の §5（P1〜P3 fix 一覧 + 明示否定）と §6（全体サマリー）をそのまま骨格として採用してよい。整形時の処理は以下 2 点のみ:

1. **観点定義の統一**: Part A 第 1 版（A-1=ID リテラル限定の用語）を採用。第 2 版の件数差（A-1=14 件等）は脚注で補足扱い。
2. **要確認マーク + 別 issue 化提案**: M-10（ハッシュタグ 13 vs 5 のドキュメント間矛盾）と H-8（`lyria`/`masterup` master 命名 ↔ `videoup` 検出パターン不一致）は「実装側コード読みが必要」と明記の上、最終レポートの「次に取るべきアクション」節で別 issue 化を提案。

### レポート構造（order.md 32 行の指定通り）

1. サマリー
2. 観点 1.1〜1.4（汎用化・設定ファイル切り出し）
3. 観点 2.1〜2.4（整合性）
4. 優先度付き fix リスト（high=P1 10 件 / medium=P2 16 件 / low=P3 14 件 / 明示否定 7 件）

## 残存ギャップ（あれば）

- **G-2（ハッシュタグ 13 個 vs 5 個の矛盾）**: 実装側 `metadata_generator.py` を読まないとどちらが正か確定できない。本 issue のスコープ（`.claude/skills/**` の棚卸し監査）を超えるため、最終レポートで「要確認」マーク付き記載 + 別 issue 化提案で処理。
- **G-4（`lyria`/`masterup` 出力 ↔ `videoup` 検出パターン不一致）**: 実害判定には実行ログ・統合テストが必要。本 issue のスコープ外。最終レポートで修正案 a（generate_videos.sh 検出拡張）/ b（出力名統一）/ c（Next Step に明記）の 3 案を提示 + 別 issue 化提案。
- **修正実装の責務範囲**: order.md 制約「修正提案は文章で書くだけ、コードには触らない」「`.claude/skills/**` への write 禁止」に従い、本 issue では実際の fix 適用は行わず、最終レポートを成果物とする。fix の実施は別 issue にバトンする前提。