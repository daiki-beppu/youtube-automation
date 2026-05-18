# 調査レポート

## 調査概要
Issue #372「スキル運用リスク監査」の調査結果（dig step 10 本のデータレポート + analyze step の批判的分析）を supervise 観点で評価し、Phase 2 の audit レポート起草に進めるかを判定した。判定: **APPROVE**。

## 主要な発見

- **4 観点すべてに一次レポートが揃っている**: 観点 3（失敗時挙動）= `data-failure-recovery.md`、観点 4（課金 API）= `data-billing-cost.md`、観点 5（セキュリティ）= `data-security-secrets.md`、観点 6（依存・廃止）= `data-dependencies-compat.md`
- **検出件数は約 50 件超**: P0 = 6 件 / P1 = 19 件 / P2 ≈ 17 件 / P3 ≈ 9 件
- **35 skill の全件マトリクスが完備**: idempotency / リカバリ / API 依存 / 障害ガイダンスを skill 単位で評価済
- **仮説 H1〜H12 すべてに「検証済 / 否定 / 未検証」の結論あり**: issue 要件「既知のリスク仮説を 3 分類」を充足
- **主要発見すべてに `file:line` 出典あり**: 例 `lyria_client.py:148-154` / `upload_policy.py:14,47-50` / `generate_loop_video.py:59-67`
- **3 つの重要なギャップ**を残存項目として特定（Lyria 切替日の出典問題、P0 件数の合算ルール未統一、CLAUDE.md L38 の事実誤認）

## 調査結果

### 観点 3: 失敗時挙動 / Idempotency / リカバリ
**判定: OK（ほぼ網羅）**

- 35 skill × idempotency マトリクスが 1 行ごとに揃っている（`data-failure-recovery.md §6`）
- リカバリ手順の記載状況: ○ 6 件 / △ 13 件 / × 15 件 / n/a 1 件
- 仮説 H1〜H6 すべて検証/否定の結論あり
- **残ギャップ（軽微）**: `live-clean` / `channel-import` / `wf-new` の CLI 実装側未読、Veo `operations.cancel` API の存在可否未確認

### 観点 4: 課金 API コスト制御
**判定: OK（コスト制御ガードの構造分析は十分）**

- 課金 API × skill マトリクス確定（Veo / Gemini / Lyria / OpenAI / Suno / YouTube Data API / Vertex AI / Vultr）
- リトライ装着状況を API 単位で表化
- F-1〜F-9 の具体的 Findings
- 「無限ループ生成」リスクは P0 不在で確認
- **残ギャップ**: USD 単価は意図的にスキップ（Issue #132 撤廃方針に従い `cost_tracker.py` の null 設計 + GCP Billing 連携で対応）。`yt-cost-report` 本体 (`cli/cost_report.py`) の grep 結果は未取得

### 観点 5: セキュリティ / シークレット
**判定: OK（最も成熟、P0 = 0 を定量根拠で確認）**

- ハードコード検出: 5 種の正規表現で 0 件
- production code 100% `get_secret()` 経由を verify
- 316 コミット `--all --full-history` で履歴混入 0 件
- 仮説 H7（token.json 直読み）否定
- **残ギャップ**: ローカル `terraform.tfstate` の中身 / 1Password vault の MFA 設定 / Vultr 側ファイアウォール — リポジトリ範囲外で調査不能（audit に「範囲外」と明記すれば足りる）

### 観点 6: 依存・廃止
**判定: △（最終一本化版で確定。ただし P0-1 出典 URL は要再検証）**

- 35 skill × 外部 API 依存マトリクス完備
- `pyproject.toml` 14 依存 + dev 2 件すべて upper bound なしを定量確認
- 仮説 H9〜H12 すべて検証/否定/△ で結論
- **残ギャップ**: Lyria 3 Interactions API のスキーマ切替日「2026-05-26」の出典が Gemini Developer API docs を指している（Vertex AI Lyria への同日適用は未確認）。コード側の `body.get("outputs", [])` 単一経路依存は出典に関わらず P0/P1 級の脆性として残る

### 主要 P0 発見（合算 6 件）

| # | 件名 | 出典 | 観点 |
|---|---|---|---|
| P0-1 | Lyria 3 Interactions API legacy `outputs` schema 単一経路依存 | `lyria_client.py:148-154` | 6 |
| P0-2 | `loop-video` 再実行で Veo を必ず再課金 | `generate_loop_video.py:59-67,160-163` | 3 / 4 |
| P0-3 | `upload_policy.RETRYABLE_HTTP_STATUSES` に 429 不在 | `upload_policy.py:14,47-50` | 3 |
| P0-4 | Veo の Ctrl+C 中断は API 側継続でクレジット焼き | `veo_generator.py:64-77` | 3 / 4 |
| P0-5 | `video-upload` 失敗 → 再実行で video_id 重複の余地（session URI 未永続化） | `upload_core.py:108-128` | 3 |
| P0-6 | `comments-reply` の insert→save 窓で二重返信余地 | `replier.py:213-243` + `history.py:51-58` | 3 |

### Phase 2 への申し送り（必須注記 4 点）

1. **P0 件数の合算ルールを冒頭宣言**: 一次レポート間で食い違う（失敗 5 / 課金 0 / セキュリティ 0 / 依存 1）。supervise としては「失敗 ∪ 課金 ∪ 依存」の和集合 = **6 件** を採用
2. **Lyria 2026-05-26 切替の出典問題を明示**: Gemini Developer API docs を引用しているが影響先は Vertex AI Lyria。両系統が同日切替か未検証。ただしコードの脆性は出典に関わらず維持
3. **SKILL.md 27 件のガイダンス欠落（P1-19）は段階適用を推奨**: 一括 PR は review 不能になる。テンプレ整備 + 段階適用を推奨アクションに
4. **CLAUDE.md L38 の事実誤認**: 「`utils/`, `agents/`, `auth/`, `scripts/` shim あり」と書かれているが `utils/` / `agents/` は削除済。P3 領域に含める

## データソース

| # | ソース | 種別 | 信頼度 |
|---|--------|------|--------|
| 1 | `.takt/runs/20260518-090446-issue-372-chore-skills/reports/data-failure-recovery.md`（448 行、22 件、35 skill マトリクス） | コードベース調査結果 | High |
| 2 | `.takt/runs/20260518-090446-issue-372-chore-skills/reports/data-billing-cost.md`（226 行、9 Findings、severity 表） | コードベース調査結果 | High |
| 3 | `.takt/runs/20260518-090446-issue-372-chore-skills/reports/data-security-secrets.md`（533 行、316 コミット履歴検証） | コードベース調査結果 | High |
| 4 | `.takt/runs/20260518-090446-issue-372-chore-skills/reports/data-dependencies-compat.md`（419 行、H9-H12 検証） | コードベース調査結果 | High |
| 5 | `.takt/runs/20260518-090446-issue-372-chore-skills/reports/analysis-1.md`（analyze step 出力） | 批判的分析 | High |
| 6 | `data-billing-cost-control.md` / `data-deps-deprecation.md` / `data-deps-deprecated.md` / `data-dependencies.md` / `data-external-api-deprecation.md` / `data-backward-compat-shims.md`（二次レポート 6 本） | 補強用コードベース調査 | Medium |
| 7 | `.takt/runs/20260518-090446-issue-372-chore-skills/context/task/order.md`（Issue #372 元仕様） | 要件定義 | High |

## 結論と推奨

### 結論
調査は **policy の 80% 基準を十分に超過**しており、Phase 2 の audit レポート生成（`docs/audits/2026-05-18-skills-operational-risk-audit.md`）に進める状態。元 issue (Issue #372) の出力要件は以下のとおりすべて素材が揃っている。

| 要件 (order.md) | 充足状況 |
|---|---|
| 観点 3: 失敗時挙動 / Idempotency (3.1-3.5) | ○ |
| 観点 4: 課金 API コスト制御 (4.1-4.5) | ○ |
| 観点 5: セキュリティ / シークレット (5.1-5.6) | ○ |
| 観点 6: 依存・廃止 (6.1-6.5) | ○ |
| 各検出に `file:line` 出典 | ○ |
| 仮説の「検証済 / 否定 / 未検証」分類 | ○（H1〜H12 完備） |
| PR #367 と非重複 | ○（観点 1.x / 2.x 不在を確認） |

### 推奨
Phase 2 の audit 起草時に、analyze step が申し送った **必須注記 4 点**（P0 合算ルール宣言 / Lyria 出典の注記 / SKILL.md 段階適用 / CLAUDE.md L38 修正）を必ず反映すること。これらを曖昧に残すと audit の P0 件数（5? 6? 1?）と緊急度（8 日以内? 数か月?）が読者にブレて伝わる。

audit 構成（推奨）:
1. エグゼクティブサマリー（P0 合算ルール明示 + 3 ティア緊急度）
2. 監査スコープと前提（PR #367 と非重複、35 skill 全件、~70 ファイル横断）
3. 観点 3 / 4 / 5 / 6 の本文
4. 優先度別 Fix リスト（high / medium / low、件名 / 出典 / severity / 推奨アクション / 想定工数）
5. 既知の未検証項目 / 調査不可項目
6. 既知の仮説と検証結果（H1〜H12）

## 残存ギャップ

- **G-1（高）**: Lyria 3 Interactions API のスキーマ切替日「2026-05-26」の出典 URL が Gemini Developer API docs 側を指しており、Vertex AI Lyria への同日適用は要再確認。audit には「日付未検証、ただしコード側 `body.get("outputs", [])` 単一経路依存は P0/P1 級として維持」と明記すること
- **G-2（中）**: Veo `operations.cancel` API の存在可否未確認（P0-4 修正の前提）。推奨アクションを「cancel API があれば呼ぶ／無ければ SKILL.md に明示」の二段建てに
- **G-3（低）**: `live-clean` / `channel-import` / `wf-new` の CLI 実装側未読（`cli/live_clean.py` 等）
- **G-4（低）**: 課金 API の 2026-05 時点 USD 単価（Issue #132 撤廃方針に従い意図的にスキップ）
- **G-5（低）**: `cli/cost_report.py` 本体の grep 結果がレポートに未収録（YouTube Data API quota が出力に含まれるかの最終確認）
- **G-6（中）**: 一次レポート間で P0 件数が食い違う（5 vs 0 vs 1）→ supervise として「失敗 ∪ 課金 ∪ 依存」= 6 件で確定。audit 冒頭で合算ポリシーを宣言すること
- **G-7（低）**: 二次レポート 4 本の検出が一次に集約済かの最終 cross-check（`data-dependencies-compat.md §11` で集約宣言済のため信用）
- **範囲外**: ローカル `terraform.tfstate` の中身、1Password vault の MFA 設定、Vultr 側ファイアウォール — リポジトリ外運用のため調査不能。audit に「リポジトリ範囲外」と明記すれば足りる