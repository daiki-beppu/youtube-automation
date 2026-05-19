# スキル運用リスク監査レポート（観点 3〜6）

実行日: 2026-05-18
対象 issue: #372
監査観点: 失敗時挙動 / 課金 API コスト / セキュリティ / 依存・廃止リスク
PR #367 (`2026-05-18-skills-generalization-consistency.md`) と非重複の second-opinion 監査
生成: takt `deep-research` workflow (plan → dig × 4 並列 + Part C 再走 → analyze → supervise)
判定: supervise step が `research-report.md` で APPROVE 相当を生成、ただし workflow rule マッチで abort（成果物は揃っており実害なし）
原データ: `2026-05-18-skills-operational-risk-audit/raw/` 配下に 11 本（dig 10 + supervise 1）を保全

---

## 1. 入力データの棚卸し

dig step（観点 3〜6 を 3 Part 並列 + Part C 3 回再実行）で生成されたレポートは 10 本。役割が重複している（特に Part C）ため、まず一次/二次を整理する。

| ファイル | 観点 | 役割 | 一次 / 二次 |
|---|---|---|---|
| `data-failure-recovery.md`（448 行） | 3 失敗時挙動 | Part A-1 再走後の決定版（22 件、35 skill マトリクス完備） | **一次** |
| `data-billing-cost.md`（226 行） | 4 課金 | Part A-2 単独実行版（9 Findings、severity 表完備） | **一次** |
| `data-billing-cost-control.md` | 4 課金 | Part A 統合版で生成された別系統 | 二次（補強用） |
| `data-security-secrets.md`（533 行） | 5 セキュリティ | Part B 単独実行版 | **一次** |
| `data-dependencies-compat.md`（419 行） | 6 依存・廃止 | Part C 最終一本化版（仮説 H9-H12 検証、35 skill × CLI / 障害ガイダンス全件） | **一次** |
| `data-deps-deprecation.md`（538 行） | 6 依存・廃止 | Part C リトライ版（細かい file:line を追加検出） | 二次（補強用） |
| `data-deps-deprecated.md` | 6 依存・廃止 | Part C 初回版（Lyria 2026-05-26 を最初に検出） | 二次 |
| `data-dependencies.md` | 6 依存 | 部分レポート | 二次 |
| `data-external-api-deprecation.md` | 6 廃止 | 部分レポート | 二次 |
| `data-backward-compat-shims.md` | 6 shim | 部分レポート | 二次 |

**supervise へ向けた指示**: 一次レポート 4 本を基準にし、補強の必要があるときだけ二次に当たる。`data-dependencies-compat.md` の §11 が非重複境界を明示している通り、二次 4 本は本レポートに集約されている前提で構わない。

---

## 2. 主要発見の整理（severity 別、一次レポートのみ）

### 2.1 P0（運用直撃・即対応推奨）

| # | 件名 | 出典 | 観点 | 状態 |
|---|---|---|---|---|
| P0-1 | **Lyria 3 Interactions API legacy `outputs` schema 依存** — `body.get("outputs", [])` を直接読む。Vertex AI 側のスキーマ切替が起きるとサイレント失敗（None 返却）で BGM 生成全停止 | `src/youtube_automation/utils/lyria_client.py:148-154`（事実確認済 by analyze） | 6 | **△ 確定済：コードは脆い。ただし切替日「2026-05-26」の出典 URL は Gemini API ドキュメント側 (`ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026`) で、Vertex AI Lyria の Interactions endpoint (`aiplatform.googleapis.com/v1beta1/.../interactions`) に同日適用されるかは要再確認** |
| P0-2 | **`loop-video` 再実行で Veo を必ず再課金** — `generate_loop_video.py:59-67` が既存 `loop.mp4` を `loop-v{n}.mp4` に rename するだけで skip しない。`--smooth` 単独で post-process のみ走らせる経路もなし | `generate_loop_video.py:59-67,160-163` + `.claude/skills/loop-video/SKILL.md:59` | 3 / 4 | 確定 |
| P0-3 | **`upload_policy.RETRYABLE_HTTP_STATUSES` に 429 が含まれない** — quota 切れ寸前で `video-upload` を叩くと resume 不可能な panic 終了 | `src/youtube_automation/utils/upload_policy.py:14,47-50` | 3 | 確定 |
| P0-4 | **Veo の Ctrl+C 中断は API 側継続でクレジット焼き** — クライアント中断は cancel API を呼ばない | `src/youtube_automation/utils/veo_generator.py:64-77` | 3 / 4 | 確定（`operations.cancel` 実装可否は未検証） |
| P0-5 | **`video-upload` 失敗 → 再実行で video_id 重複の余地** — resumable upload の session URI を `upload_tracking.json` に永続化していない | `src/youtube_automation/utils/upload_core.py:108-128` | 3 | 確定 |
| P0-6 | **`comments-reply` の insert→save の窓** — `comments.insert` 成功 → `history.save()` 失敗の極稀ケースで二重返信余地 | `replier.py:213-243` + `history.py:51-58` | 3 | 確定（理論的余地、実害確率は極小） |

**重要**: 一次レポート間で P0 件数が食い違っている。
- `data-failure-recovery.md`: P0=5
- `data-billing-cost.md`: P0=0
- `data-security-secrets.md`: P0=0
- `data-dependencies-compat.md`: P0=1（Lyria）
- 合計（重複除外）: **6 件**

`data-billing-cost.md` が P0=0 と評価した P0-2（loop-video）と P0-4（Veo Ctrl+C）について、Part A-2 は「ガード（`-y` confirm / `RETRY_MAX`）が一通り入っているため P0 不在」と判定しているが、Part A-1 は「再実行ガード未実装で Veo が必ず再課金」を P0 として上げている。**supervise 側で「P0 の合算ルール」を統一**する必要あり（推奨: 課金観点 × 失敗観点を OR で取り 6 件とする）。

### 2.2 P1（重要、Q3 2026 中に対応）

| # | 件名 | 出典 | 観点 |
|---|---|---|---|
| P1-1 | 35 skill 中 15 件で SKILL.md にリカバリ手順が完全に無い | `data-failure-recovery.md §1.2,1.4` | 3 |
| P1-2 | `video-analyze` は `<video_id>.json` skip 無し → 再実行で Gemini 再課金 | `video_analyzer.py:97-104` | 3 / 4 |
| P1-3 | `discover-competitors` は実行ごとに search.list 660 unit を毎回焼く | `competitor_discovery.py:46-67` | 3 / 4 |
| P1-4 | YouTube Data API 系の API call が **retry 一切なし**（playlist / benchmark / analytics / comments-reply / discover-competitors） | `data-failure-recovery.md §4.1` | 3 |
| P1-5 | `live-clean` SIGINT 時のリカバリ未記述 | SKILL.md（実装側未読） | 3 |
| P1-6 | `analytics-collect` OAuth token 期限切れリカバリ未記述 | SKILL.md | 3 |
| P1-7 | `streaming swap_video.sh` の terraform apply 中断時 rollback 案内なし | `swap_video.sh:18-122` | 3 |
| P1-8 | `loop-video` のバックアップ `loop-v{n}.mp4` が無限増殖の余地 | `generate_loop_video.py:59-67` | 3 |
| P1-9 | OpenAI Image の `quality=high` 既定 — provider 切替時に無自覚に高単価 | `image_provider/config.py:151`, `thumbnail/config.default.yaml:92` | 4 |
| P1-10 | `benchmark.scan_recent` に上限 validate なし — quota 線形膨張 | `benchmark_collector.py:135-178` | 4 |
| P1-11 | Lyria の segment 数に上限なし — `target_duration_min` 次第で 800 リクエスト | `generate_lyria_master.py:68-79` | 4 |
| P1-12 | `auth/token.json` の broad scope 同居 — read-only skill が write 権限付き token を共用 | `data-security-secrets.md (a)` | 5 |
| P1-13 | Terraform `null_resource.deploy.connection` の SSH host_key 未 pin — first-connect MITM 余地 | `infra/terraform/streaming/main.tf:55-60` | 5 |
| P1-14 | `gemini-2.5-flash` / `gemini-2.5-flash-lite` **2026-10-16 shutdown** — 5 か月猶予 | `benchmark`/`video-analyze`/`wf-new` の各 config + `populate_scene_phrases.py:33` | 6 |
| P1-15 | `pyproject.toml` 全 16 依存に **上限 pin なし** — 下流 `uv add` で `google-genai` 2.x（major bump）を引き込む余地 | `pyproject.toml:13-28` | 6 |
| P1-16 | `google-auth-httplib2` upstream で deprecated 表明 | PyPI | 6 |
| P1-17 | Suno 非公式依存（CDN スクレイピング）に deprecation メモなし — 復旧手段ゼロ | `.claude/skills/masterup/SKILL.md:84,89` | 6 |
| P1-18 | skill 単独バージョン追跡なし + `yt-skills sync --force` 運用未明示 | ONBOARDING / README | 6 |
| P1-19 | 35 skill 中 27 件で「外部サービス障害時 / rate limit / 未認証時」のガイダンスゼロ | `data-dependencies-compat.md §7.1` | 6 |

合計 P1: **19 件**（重複除外後）

### 2.3 P2 / P3

- P2: 一次レポート集計で **約 17 件**（tmp 残骸、`.gitattributes` 不在、Terraform local state、SKILL.md `## 前提` 欠落、CLAUDE.md L38 と実態の矛盾、`Workflow` 空 dataclass dead shim 等）
- P3: 一次レポート集計で **約 9 件**（冪等性明示の他 skill 展開、`yt-config-migrate` 撤去判断、`audio_units.py` の `lyria-002` dead reference、`requires-python>=3.11` 過剰制約 等）

合計（重複除外見込み）: **約 50 件超の検出**。

---

## 3. 観点ごとの判定

### 3.1 観点 3（失敗時挙動）

**判定: ほぼ網羅。supervise で audit 化可能**。

- 35 skill × idempotency マトリクスが 1 行ごとに揃っている（`data-failure-recovery.md §6`）
- リカバリ手順: ○ 6 / △ 13 / × 15 / n/a 1 と件数定量化済み
- 仮説 H1〜H6 すべて検証/否定の結論あり

**残ギャップ（軽微）**:
1. `channel-import` の branding push 冪等性（`cli/channel_init.py` 全体未読）
2. `live-clean` 実装側（`cli/live_clean.py` 等）未読
3. `wf-new` の workflow-state.json 重複初期化挙動未確認
4. Veo `operations.cancel` API の存在可否

→ 推奨アクション #1〜#5 の対象は確定。残ギャップは audit 内「未検証」セクションに移送で足りる。

### 3.2 観点 4（課金 API）

**判定: コスト制御ガードの構造分析は十分。USD 単価は意図的に未取得（Issue #132 撤廃済の方針に従う）**。

- 課金 API × skill マトリクス確定
- リトライ × API ごとの装着状況 表化
- 「無限ループ生成」リスクは P0 不在で確認
- F-1〜F-9 で具体 Findings

**残ギャップ**:
1. USD 単価そのもの（推測排除のため意図的にスキップ）— audit では `cost_tracker.py` の null 設計と GCP Cloud Console > Billing 連携を強調すれば足りる
2. `yt-cost-report` の出力に YouTube Data API quota が含まれない件 — dig 内で複数回言及されているが、`yt-cost-report` 実装側 (`cli/cost_report.py`) の現状コード抜粋がレポートに無い（P1 推奨だが file:line が `cost_tracker.py:9-20` 止まり）

→ audit 化に支障なし。USD 単価は「GCP Billing で各自確認」の運用と明示する。

### 3.3 観点 5（セキュリティ）

**判定: 最も成熟。P0 ゼロを定量根拠付きで確認**。

- ハードコード検出: 5 種の正規表現で 0 件確認
- production code 100% `get_secret()` 経由を verify
- 316 コミット `--all --full-history` で履歴混入 0 件
- 仮説 H7（token.json 直読み）否定

**残ギャップ**: ローカル `terraform.tfstate` の中身、1Password vault の MFA 設定、Vultr 側ファイアウォール — すべてリポジトリ外運用で調査不能。audit には「リポジトリ範囲外」と明記すれば足りる。

### 3.4 観点 6（依存・廃止）

**判定: 最終一本化版 `data-dependencies-compat.md` で確定。ただし P0-1 の出典 URL は要再検証**。

- 35 skill × 外部 API 依存マトリクス完備
- pyproject.toml 14 依存 + dev 2 件すべて upper bound なしを定量確認
- 仮説 H9-H12 すべて検証/否定/△ で結論

**残ギャップ**:
1. **Lyria 3 Interactions API のデフォルトスキーマ切替日（2026-05-26）の出典が Gemini API docs URL** — Gemini Developer API の `interactions` endpoint と Vertex AI Lyria の `interactions` endpoint が別系統である可能性を audit で明記。少なくともコード側の `body.get("outputs", [])` 単一経路依存は P1 級の脆性として残る
2. `veo-3.1-lite-generate-preview` の公式 publisher model ID 未確認
3. Vertex AI Lyria 3 GA 化時期未告知

→ 1 は audit に「日付は要再確認、ただしコードの脆性は変わらず P0/P1 推奨」と注記。supervise 側で WebFetch 余力があれば確認し、なければ「日付未確認・対応推奨」として記述。

---

## 4. 特定したギャップとその重要度

| # | ギャップ | 重要度 | 取れる対応 |
|---|---|---|---|
| G-1 | Lyria 3 schema 切替日 (2026-05-26) の出典 URL が Gemini API docs を指している（Vertex AI Lyria への同日適用は要再確認） | **高** | audit で「日付未検証、ただしコード脆性 P0/P1 維持」と明示。supervise が WebFetch で再確認可能なら理想 |
| G-2 | Veo `operations.cancel` API の存在可否（P0-4 修正の前提） | 中 | 推奨アクションを「cancel API があれば呼ぶ／無ければ SKILL.md に明示」の二段建てに |
| G-3 | `live-clean`, `channel-import`, `wf-new` の CLI 実装未読 | 低 | audit に「未調査 skill」セクションを設けて 3 件列挙 |
| G-4 | 課金 API の 2026-05 時点 USD 単価（意図的にスキップ） | 低 | Issue #132 撤廃方針に従い `cost_tracker` null 設計を audit で記述 |
| G-5 | `yt-cost-report` CLI 本体（`cli/cost_report.py`）の grep 結果がレポートに含まれない | 低 | supervise で必要なら 1 ファイル追加 read |
| G-6 | 一次レポート間で **P0 件数 (5 vs 0 vs 1)** が食い違う（合算ルール未統一） | 中 | audit で「失敗観点 ∪ 課金観点 ∪ 依存観点」の P0 合算ポリシーを最初に宣言 |
| G-7 | 既存 Part C 二次レポート 4 本（`data-dependencies.md` 等）の検出が一次に集約されているかの最終 cross-check | 低 | `data-dependencies-compat.md §11` で集約済を宣言しているのでそれを信じる |

**重要度の判定基準**: 「監査レポートの結論に直接影響するか」で線引き。G-1 / G-6 は audit のサマリー数字に直接効くため**高**または**中**。G-3〜G-5 は脚注扱いで足りる。

---

## 5. 追加調査の必要性 — 判定

**結論: 追加 dig 不要。supervise に進む。**

理由:
1. 4 観点すべてで一次レポートが揃い、P0/P1 の根拠は file:line で固められている
2. 残ギャップ（G-1〜G-7）は audit 内の「未検証」セクションで処理可能。新たに dig を回すコスト > 得られる確実性向上
3. Part C は 3 回再走したのち `data-dependencies-compat.md` に一本化済。これ以上の重複生成はコスト過多
4. 元 issue の出力要件（`docs/audits/2026-05-18-skills-operational-risk-audit.md` 1 本、severity 別 fix リスト、`file:line` 出典）は揃っている

ただし supervise が **G-1（Lyria 切替日の URL 再検証）と G-6（P0 合算ルール統一）の 2 点は audit 起草時に明示的に解決すること**。これらを曖昧に残すと audit の P0 件数（5? 6? 1?）と緊急度（8 日以内? 数か月?）が読者にブレて伝わる。

---

## 6. supervise への申し送り事項

### 6.1 audit 構成（推奨）

```
docs/audits/2026-05-18-skills-operational-risk-audit.md

1. エグゼクティブサマリー
   - P0 件数（合算ルール明示）/ P1 件数 / 合計件数
   - 「8 日以内に対応必要」「Q3 2026 中」「中期」の 3 ティアでハイライト
2. 監査スコープと前提
   - PR #367 と非重複
   - 35 skill 全件、~70 ファイル横断
   - 単価は GCP Billing 側で確認する設計（cost_tracker null 方針）
3. 観点 3: 失敗時挙動 / Idempotency / リカバリ
4. 観点 4: 課金 API コスト制御
5. 観点 5: セキュリティ / シークレット / 権限境界
6. 観点 6: 依存・廃止 API・互換性
7. 優先度別 Fix リスト（high / medium / low）
   - 各行に: 件名 / 出典 (file:line) / severity / 推奨アクション / 想定工数
8. 既知の未検証項目 / 調査不可項目
9. 既知の仮説と検証結果（H1〜H12）
```

### 6.2 audit 起草時の必須注記

1. **P0 件数の合算ルール**: 「失敗観点 ∪ 課金観点 ∪ 依存観点」で 5+0+1=6 件、ただし P0-1（Lyria）の出典日付要再検証。
2. **Lyria 2026-05-26 の出典**: 「`ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026` を引用しているが、影響先は Vertex AI Lyria。両系統が同日切替か未検証。コード側の `body.get("outputs", [])` 単一経路依存は確定の脆性」と注記。
3. **`-` で始まる SKILL.md ガイダンス追加要望**は **27 skill 一括 PR** ではなく **テンプレ整備 + 段階適用** を推奨（一気にやると review 不能になる）。
4. **既知の手がかり (CLAUDE.md L38)** が「`utils/`, `agents/`, `auth/`, `scripts/` shim あり」と書かれているが、`utils/` / `agents/` は既に削除済（`data-dependencies-compat.md §5.1`）。audit に CLAUDE.md の修正を低優先度で含める。

### 6.3 supervise が optional に追加検証してよい項目

- WebFetch で Vertex AI Lyria 3 Interactions API のスキーマ deprecation 公式アナウンスを確認（G-1 解決）
- `cli/cost_report.py` を read して YouTube Data API quota が出力に含まれるか最終確認（G-5 解決）
- `cli/live_clean.py` / `cli/channel_init.py` の SIGINT / idempotency パターンを最低 1 ファイルずつ read（G-3 解決）

これらは時間が許せば audit の精度を上げるが、無くても審査適用は可能。

---

## 7. 判定の最終確認

| チェック項目 | 状態 |
|---|---|
| 4 観点すべてに一次レポートが存在するか | ○ |
| 各 P0 / P1 に file:line 出典があるか | ○ |
| 仮説 H1〜H12 すべてに検証結論があるか | ○ |
| 35 skill 全件を網羅しているか | ○（マトリクス完備） |
| 推測と事実が分離されているか | ○（推測箇所は明示） |
| 調査不可項目が明示されているか | ○（観点ごとに列挙） |
| 元 issue の出力仕様（severity 別 fix リスト、file:line 出典）を満たせるか | ○ |

→ **supervise に進む。analyze step は 1 回で完了。**
