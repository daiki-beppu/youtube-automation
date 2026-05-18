# スキル汎用化・整合性 棚卸し監査レポート

実行日: 2026-05-18
対象 issue: #353
生成: takt `deep-research` workflow (plan → dig × 3 並列 → analyze → supervise)
判定: **APPROVE**（supervise）— policy 「APPROVE 条件」3 つすべて充足
原データ: `2026-05-18-skills-generalization-consistency/raw/` 配下に保全（dig Part A/B/C, supervise, plan）

---

## 1. 統合した主要発見（観点別）

### 観点 1.1 ハードコード値（A-1〜A-4）

| 重大度 | 件数 | 代表事例 |
|---|---|---|
| 高（P1） | **6 件** | `analytics-report/SKILL.md:94-101` の HTML レポートカラーパレット 9 色（`#c8a96e` = "ブランドアクセントカラー"）／`channel-new/SKILL.md:29,64`・`channel-import/SKILL.md:20` の `~/01-dev/projects/`・`~/02-yt` 個人パス／`channel-new/SKILL.md:47,49`・`channel-import/SKILL.md:21,26`・`channel-setup/references/claude-md-template.md:71` の `daiki-beppu` 固定 GitHub owner 名 |
| 中（P2） | **約 25 件** | analytics-collect / analytics-analyze 双方の **「30 分」鮮度しきい値** が双子直書き／postmortem の比率閾値（0.5 / 0.7 / 0.9 / ±10%）／videoup の ffmpeg 解像度・CRF・サンプルレート／suno の禁止形容詞・NG ワード／streaming の `--check-threshold` 80%・`~/.ssh/yt_stream_key`／lyria 184 秒の本文再露出 |
| 低（P3） | **約 20 件** | skill-config 化済の既存値、YouTube API 仕様値（タイトル 100 文字・video_id 11 文字・バナー 2048×1152）など |

**A-1（チャンネル ID / playlist ID）リテラル検出**: **0 件**（`UC[A-Za-z0-9_-]{22}` / `PL[A-Za-z0-9_-]{16,}` の grep で完全一致なし、`@<handle>` リテラルもプレースホルダのみ）。
**A-4（API キー / トークン）リテラル検出**: **0 件**（`AIza` / `sk-` / `ya29` パターン零）。

### 観点 1.2 重複スクリプト

| 重複種別 | 件数 | 詳細 |
|---|---|---|
| **強重複（MD5 完全一致）** | **2 ペア** | `scripts/gcp-bootstrap.sh` ≡ `channel-setup/references/gcp-bootstrap.sh`（252 行、MD5 `e421...606a`）／`scripts/gcp-terraform-apply.sh` ≡ `channel-setup/references/gcp-terraform-apply.sh`（109 行、MD5 `358b...244`）。CLAUDE.md 規約「単一 skill からしか呼ばれないものを `scripts/` に残すな」と明確に矛盾 |
| **弱重複（共通スニペット）** | **3 ファイル** | bash の `log/ok/warn/error` ANSI ログヘルパー（`gcp-bootstrap.sh` / `gcp-terraform-apply.sh` / `streaming/references/swap_video.sh`）。共通化は配布の単純さを壊すため **非推奨** |
| **Python 重複 in references/** | **0 件** | `.claude/skills/**/references/*.py` は 0 ファイル。order.md 既知シード「`benchmark_collector.py × 3` / `generate_image.py × 3` / `fetch_benchmark_comments.py × 2`」は **配置誤認**で、実体は `src/youtube_automation/scripts/` 配下に **各 1 件のみ**（重複なし）。SKILL.md 本文で複数 skill から CLI として参照されているが、コード重複ではない（後述「3. 検証済みの懸念」参照） |

### 観点 1.3 skill-config 余地

| 状況 | 件数 | 詳細 |
|---|---|---|
| 既存 `config.default.yaml` 保有 | **9 スキル** | benchmark / collection-ideate / loop-video / lyria / masterup / suno / thumbnail / video-analyze / video-description |
| 新規外出し候補（移行コスト「小」） | **11 件** | analytics-collect・analytics-analyze の 30 分鮮度／discover-competitors と channel-new の共有 API パラメータ／live-clean の削除/保護パターン／streaming の cron タイミング／thumbnail-compare の評価軸 8 軸・320×180px／metadata-audit の `<3 / >12` チャプター数／playlist の挿入順 など |
| 新規外出し候補（移行コスト「中〜大」） | **5 件** | analytics-report HTML テーマ／channel-direction 議論ポイント 7 項目／postmortem 四分位閾値／streaming `healthcheck.sh` 状態分類 4 値／streaming 帯域目安テーブル |

### 観点 1.4 既存 config 未参照

| 重大度 | 件数 | 代表事例 |
|---|---|---|
| 高（P1） | **4 件** | `analytics-analyze/SKILL.md:64` の v1.x 名残り **`channel_config.tags.themes`**（v2.0.0 では `content.tags.themes`）／`analytics-report/SKILL.md` のブランド色 → `meta.json::channel.brand_color` 新設要求／`video-description/references/description-templates.md:36,43-44` の英語固定コピー（`usage_attribution_lines` skill-config と二重管理） |
| 中（P2） | **約 9 件** | `category_id: "10"` が 3 テンプレファイルで重複／`privacy_status` の `"public"` vs `"private"` 矛盾／`comments.json` が「7 ファイル」列挙から漏れている（実は 8 ファイル）／localizations と content.title.template の二重管理／`analytics.collection_filter_keywords` を使わず `#Shorts` 直書きしている analytics-report |

### 観点 2.1 description ↔ 実装乖離

| 重大度 | 件数 | 内容 |
|---|---|---|
| Major | **1 件** | `video-analyze/SKILL.md` の「呼び出し側スキル」セクションが `/lyria` と `/channel-direction` を「`bgm_arc` を読み取る現役の利用者」と書いているが、両 SKILL.md にその実装記述・トリガー記述が無い（grep で完全 0 ヒット） |
| Minor | **2 件** | `video-upload` の description が `collection` 型のみ前提に読めて `single_release` 型に言及なし（実装は対応）／`analytics-report` description は「表示・閲覧」のみ書いて HTML レポート「新規生成」のトリガー語がない |

### 観点 2.2 バトン双方向整合

| 整合状態 | 件数 | 主要不整合の所在 |
|---|---|---|
| 双方向成立 | **約 14 ペア** | suno↔masterup・analytics-collect↔analytics-analyze・wf-new↔wf-next・channel-new↔channel-research↔channel-direction↔channel-setup・viewer-voice↔audience-persona↔viewing-scene・loop-video↔videoup など、主要動線は良好 |
| **片方向（要修正）** | **4 ペア** | (A) `video-analyze ↔ lyria` 事実誤認／(B) `video-analyze ↔ channel-direction` 事実誤認／(C) `thumbnail → /suno` 単独で `/lyria` 分岐欠落／(D) **`lyria` 出力 `master.wav` / `masterup` 出力 `master.mp3` が `videoup/generate_videos.sh` の検出パターン `master-mix.{wav,m4a,aac,mp3,flac}` + `*-Master.mp3` のいずれにもマッチしない**（実害候補） |
| 片方向（意図的・許容） | **10 ペア** | `wf-new / wf-next / postmortem` 等のオーケストレータからの fan-out 案内。double-binding は冗長 |

### 観点 2.3 v4.0.0 deprecated（short / community）

| 真の deprecated 参照 | **1 件** |
|---|---|
| `video-description/config.default.yaml:6` の YAML コメント | `metadata_generator / short / upload 等から参照される横断属性` という記述。`short` skill は v4.0.0 で撤去済 / `.claude/skills/short/` は存在しない。コメント文を `metadata_generator / upload 等` に縮めるべき |
| 偽陽性として除外 | 18 件（`meta.json::channel.short` 11 件・YouTube Shorts 動画フォーマット 3 件・英文 short/community 2 件・歌詞 1 件・其他 1 件） |

### 観点 2.4 形式揺れ

| 要素 | 揺れ状況 |
|---|---|
| frontmatter（`name` / `description`）| **完全統一**（35/35） |
| description 開始句 `Use when …` | **完全統一**（35/35） |
| ディレクトリ名（kebab-case） | **完全統一**（35/35） |
| **description 末尾指示語** | **5 系統に分散**: (A) 「必ず使用すること」14 件 / (B) 「使用すること」5 件 / (C) cross-ref 締め 9 件 / (D) ワークフロー序列 3 件 / (E) アクション動詞 4 件 |
| **本文見出し** | **3 系統に分散**: `Cross References`（11 件）vs `関連ファイル`（8 件）vs `Next Step`（13 件）／`Instructions`（15 件）vs `実行フロー`（7 件）／`When to Use`（9 件）vs `いつ使うか`（suno のみ） |
| **テンプレ命名** | `claude-md-template.md`（単数 md）vs `description-templates.md`（複数 md）vs `config-template/`（単数ディレクトリ） — 3 様式併存 |
| description 文字数 | 最短 75 字（video-upload）〜 最長 約 280 字（channel-setup）、約 3.7× の幅 |

---

## 2. 分析の観点と統合判断

### 2.1 各 dig 報告書間の整合性確認

| 観点 | Part A 第 1 版 | Part A 第 2 版 | Part B | Part C 第 1 版 | Part C 第 2 版 | 整合 |
|---|---|---|---|---|---|---|
| ハードコード総件数 | 63 件（A-1〜A-5 通算）| A-1=14 / A-2=11 / A-3=22 / A-4=6 / A-5=0（観点定義が違う）| — | — | — | **△ 観点定義差**（第 1 版は A-1 を ID リテラル限定、第 2 版は数値全般を A-1 に統合）→ supervise で **第 1 版の観点定義を採用**するのが order.md 用語と一致 |
| analytics-{collect,analyze} 「30 分」鮮度 | 検出 ✓ | 検出 ✓ | 検出 ✓（B-3 候補 #1, #2）| — | — | ✓ 3 報告書一致 |
| analytics-report ブランド色 | 検出 ✓（高）| 検出（HTML 色 8 色）| B-3 候補 #3 | — | — | ✓ 一致 |
| postmortem 閾値 | 検出 ✓（中）| 検出 ✓ | B-3 候補 #9 | — | — | ✓ 一致 |
| GCP bootstrap 重複 | — | — | **検出 ✓ MD5 一致** | — | — | ✓ Part B 単独で確定 |
| `video-description/config.default.yaml:6` の `short` | A-5 では未指摘 | — | — | C-1-①, C-3-① で検出 | C-1-①, C-3-① で検出 | ✓ Part C で確定 |
| `video-analyze ↔ lyria / channel-direction` 事実誤認 | — | — | — | 検出 ✓（C-1.1） | 検出 ✓（C-2 #34, #35） | ✓ 一致 |
| lyria/masterup master ファイル命名 vs videoup 検出パターン | — | — | — | 検出 ✓（C-2 #11, #12） | 検出（C-2 #2, #3）| ✓ 一致 |
| バトン片方向数 | — | — | — | 14 組中 4 要修正 | 9 リンク中 P1=3 P2=4 | △ 件数の数え方は違うが、要修正候補（lyria/videoup/video-description/metadata-audit/thumbnail/suno 等）の **顔ぶれは一致** |

3 つの Part 間で **重要発見の不一致は無い**。Part A 第 1 版と第 2 版の「件数差」は **観点定義の差**であり、対象物の認識は同じ。supervise では第 1 版を主、第 2 版を補助として統合する方針が合理的。

### 2.2 「修正対象」と「正当な設計判断」の境界

dig 段階で false positive リスクとして明示された境界:

| 検出 | 状態 | 判断 |
|---|---|---|
| YouTube タイトル長制限 100 文字 / video_id 11 文字 / バナー 2048×1152 | プラットフォーム仕様 | **修正対象外**（外出ししても意味がない） |
| Vertex AI Lyria 184 秒 / Veo 8 秒 | API 物理制約 | **修正対象外**（ただし定数化はしてよい） |
| `category_id: "10"` （Music） | BGM チャンネル前提・テンプレ既定 | **テンプレ 3 ファイル重複は修正対象**、値そのものはチャンネル依存 |
| postmortem 閾値（0.5 / 0.7 / 0.9） | 「文脈調整可」と SKILL.md 内で明記 | **skill-config 化対象**（「文脈調整可」記述を残す） |
| `daiki-beppu` GitHub owner | 配布パッケージとしては問題 | **`{{REPO_OWNER}}` プレースホルダ化対象**（fork 運用への影響） |
| postmortem → 4 検証 skill 片方向 | postmortem はメタスキル（fan-out 案内が責務） | **修正対象外**（意図的） |

### 2.3 既知シードの最終照合（order.md「既知のシード」節）

| シード | 対応観点 | 結論 |
|---|---|---|
| **重複スクリプト 3 種**（`benchmark_collector.py × 3`, `generate_image.py × 3`, `fetch_benchmark_comments.py × 2`）| 1.2 | **配置誤認の seed**。実体は `src/youtube_automation/scripts/{benchmark_collector,fetch_benchmark_comments,...}.py` および `src/youtube_automation/utils/image_provider/composition.py` に **各 1 件のみ**。`.claude/skills/**/references/` には Python ファイル 0 個。SKILL.md からの CLI 呼び出し参照箇所が複数あるだけで、**コード重複は存在しない**。報告書では「`.py` 重複 0 件」と確定報告し、別途「scripts/ ↔ references/ の `.sh` 重複（gcp-bootstrap.sh, gcp-terraform-apply.sh）が CLAUDE.md 規約違反として残っている」を主要発見として位置づける |
| **streaming `--check-threshold` config 非連動** | 1.1 / 1.4 | 検出済（Part A 第 1 版 #5.18、Part A 第 2 版 A1-? 関連、Part B B-3 候補 #11）。`config/skills/streaming.yaml::bandwidth_threshold_ratio` 新設を提案 |
| **channel-new / channel-direction の `"TBD"` 仕様未統一** | 1.1 | 検証の結果、**`"TBD"` 出現は `channel-new/SKILL.md:107` の 1 箇所のみ**（grep `TBD` で確認）。これは `yt-channel-init --genre/--style/--context` の **CLI 既定値の説明**で、`/channel-direction` で実値に上書きするフローが SKILL.md 105 行に明記されている。**仕様統一は既に取れている**ため、最終レポートでは「seed として挙がっていたが現状問題なし」と短く記載 |
| **postmortem のバトン記述曖昧** | 2.2 | Part C 双方が検出（postmortem→4 検証 skill は意図的 fan-out、4 skill 側に back-ref を強要しない方針として明文化を推奨） |

---

## 3. 検証済みの懸念（analyze ステップで自前確認）

以下、dig 結果の信頼性確認のため analyze 内で追加検証した内容:

| 検証項目 | 検証コマンド | 結果 |
|---|---|---|
| `benchmark_collector.py` / `generate_image.py` / `fetch_benchmark_comments.py` の実体配置 | `Grep "benchmark_collector\|fetch_benchmark_comments\|generate_image"` worktree 全範囲 | `.claude/skills/**/references/` には 1 つも存在せず、`src/youtube_automation/scripts/` 配下に各 1 ファイル。`.claude/skills/{wf-new,viewer-voice,thumbnail,postmortem,collection-ideate,benchmark}/SKILL.md` は **CLI 経由で参照しているだけ**（コードコピーは無い）。Part B の「.py 重複 0」は **正しい**と確認 |
| `TBD` の出現箇所 | `Grep "TBD" .claude/skills/` | `channel-new/SKILL.md:107` の 1 箇所のみ。`channel-direction/SKILL.md` には出現せず（`デフォルト` などの単語のみヒット）。Part A が「TBD」を発見済ハードコードとして列挙しなかったのは **適切な判断**（CLI 既定値の説明文に過ぎず修正対象でない） |
| スキル総数 | `ls .claude/skills/ | wc -l` | **35** ファイル。全 dig 報告書が走査主張する件数と一致 |

---

## 4. 特定したギャップと重要度

### 4.1 残存ギャップ（重要度: 低）

| # | ギャップ | 影響度 | 追加調査するか |
|---|---|---|---|
| G-1 | Part A 第 1 版 vs 第 2 版の **観点定義差**（A-1〜A-5 のカテゴリ区分が違う）に基づく **件数集計の二重化** | 低（最終レポートで第 1 版の観点定義に統一すれば解消）| **しない**（supervise の整形作業で吸収可能）|
| G-2 | `video-description/SKILL.md` の「ハッシュタグ **13 個**」と `channel-setup/references/config-generation-rules.md` の「`hashtags` は **5 個** 程度」の **数値矛盾**（dig Part A 第 2 版 A4-2/A4-3 で言及）| 中（実装側 `metadata_generator.py` がどちらに従っているか未確認）| **しない**（実装側コード読みは order.md スコープ外 `.claude/skills/**` 範囲を超える。最終レポートで「要確認」とマーク）|
| G-3 | Part C の **片方向バトン件数差**（第 1 版「14 組中 4 要修正」 vs 第 2 版「9 リンク中 P1 3〜4」）の数え方差 | 低（どちらの数え方でも修正候補の顔ぶれは一致）| **しない**（supervise の表記統一で解消）|
| G-4 | `videoup/generate_videos.sh` の master 検出パターン (`master-mix.*` + `*-Master.mp3`) が `lyria` (`master.wav`) / `masterup` (`master.mp3`) のいずれにもマッチしない件の **実害判定**（`/wf-next` 経由なら 2-B 検出ロジックが救うが、`/lyria`・`/masterup` の Next Step「→ /videoup」を素直に従うと素材ヒットしない可能性）| 中〜高 | **しない**（実害判定には実行ログ・統合テストが必要で order.md スコープ外。最終レポートで「実害判定要再現」とマーク、修正案 a/b/c を提示）|

### 4.2 重要度の判定根拠

ギャップ G-1 / G-3: **形式的な集計差**であり、supervise の整形で吸収可能。観点別の検出顔ぶれは一致しているため、追加調査は不要。

ギャップ G-2: 実装側を読まないと「13 個と 5 個のどちらが正か」は確定できないが、本 issue の依頼は「**棚卸し監査レポート**」であって「修正実装」ではない。「矛盾しているという発見」を高優先度で記載すれば責務を果たせる。

ギャップ G-4: 実害判定には実行統合テストが必要だが、これも本 issue のスコープ外。最終レポートで「修正案 a〜c のいずれを採るか別 issue で判断」と書く形で OK。

---

## 5. 判断: 追加調査は不要

### 判断根拠

1. **観点 1.1 / 1.2 / 1.3 / 1.4 / 2.1 / 2.2 / 2.3 / 2.4 の 8 項目すべてで `file:line` 形式の検出が確定済み**。
2. **既知シード 4 項目**（重複 .py / streaming threshold / TBD / postmortem バトン）はいずれも検証完了（うち 2 件は「seed 自体が誤認・解決済み」と判定でき、最終レポートで短く言及するだけで足りる）。
3. **3 つの Part 間で重要発見の矛盾なし**（観点定義差はあるが、対象物の認識は一致）。
4. **dig 報告書は file:line 出典明記・false positive リスク明示・カバレッジ宣言・調査不可項目明示の policy 4 要件をすべて満たしている**。
5. **政策上の 80% 基準**を超過しており、これ以上の追加調査は限界効用が小さい。

### supervise ステップへの引き継ぎ事項

supervise は本 analysis を踏まえ、`docs/audits/skills-audit-2026-05-18.md` を 1 ファイル新規作成する。構造は order.md 32 行の指定通り「サマリー → 観点 1.1〜1.4 → 観点 2.1〜2.4 → 優先度付き fix リスト（high / medium / low）」とする。

#### 取り込むべき P1（high）fix 一覧（supervise が最終レポートで必ず取り上げるべき項目）

| ID | 観点 | 内容 | 出典 |
|---|---|---|---|
| H-1 | 1.4 | `analytics-analyze/SKILL.md:64` の旧 namespace `channel_config.tags.themes` → `content.tags.themes` への修正 | Part A 第 1 版 #5.1 |
| H-2 | 1.1 / 1.4 | `analytics-report/SKILL.md:94-101` のブランド色 9 色（`#c8a96e` 含む）→ `meta.json::channel.brand_color` 新設または skill-config `analytics-report.yaml::theme.colors` 新設 | Part A 第 1 版 #2.11 / #5.2 / Part B B-3 #3 |
| H-3 | 1.4 | `video-description/references/description-templates.md:36,43-44` の英語固定コピー 2 行 → skill-config `usage_attribution_lines` への一元化（二重管理解消） | Part A 第 1 版 #5.4 / #5.5 |
| H-4 | 1.1 | `channel-new/SKILL.md:29,64`・`channel-import/SKILL.md:20` の `~/01-dev/projects/`・`~/02-yt` 個人パス → `<your-projects-dir>` / `<your-channels-parent>` プレースホルダ化 | Part A 第 1 版 #3.1, #3.2, #3.3 |
| H-5 | 1.1 | `channel-new/SKILL.md:47,49`・`channel-import/SKILL.md:21,26`・`channel-setup/references/claude-md-template.md:71` の `daiki-beppu/...` GitHub owner 固定 → `{{REPO_OWNER}}` プレースホルダ化または README/CLAUDE.md installation 節への一元化 | Part A 第 1 版 #4.4, #4.5, #4.6 |
| H-6 | 1.2 | `scripts/gcp-bootstrap.sh` / `scripts/gcp-terraform-apply.sh` の **削除**（`.claude/skills/channel-setup/references/` と MD5 完全一致、CLAUDE.md 規約違反）+ `gcp-bootstrap.md` の Usage 案内を `SKILL_REF` 経由に統一 | Part B クラスタ 1 |
| H-7 | 2.1 / 2.2 | `video-analyze/SKILL.md` の「呼び出し側スキル」セクション中 `/lyria` および `/channel-direction` 行の事実誤認 → 削除 or 下流実装追加（要 git log 確認）| Part C 第 1 版 C-1.1, C-2 #34, #35 / Part C 第 2 版 — |
| H-8 | 2.2 | `lyria` 出力 `master.wav` / `masterup` 出力 `master.mp3` が `videoup/generate_videos.sh` の検出パターンにマッチしない → 実害判定要再現の上、(a) generate_videos.sh 検出拡張 / (b) 各スキルの出力名統一 / (c) SKILL.md Next Step に「`master-mix.{ext}` リネーム後 /videoup」明記、の 3 案 | Part C 第 1 版 C-2 #11, #12 / Part C 第 2 版 #2, #3 |
| H-9 | 2.1 | `video-upload/SKILL.md` description に `single_release` 型のトリガー語追記 | Part C 第 1 版 C-1.2 |
| H-10 | 2.3 | `video-description/config.default.yaml:6` のコメント中 `short` 削除（v4.0.0 で撤去済スキル名残） | Part C 第 2 版 C-1-① / C-3-① |

#### 取り込むべき P2（medium）fix 一覧

| ID | 観点 | 内容 | 出典 |
|---|---|---|---|
| M-1 | 1.3 | analytics-collect / analytics-analyze の **30 分鮮度しきい値** を `config/skills/analytics.yaml::freshness_minutes` などに集約（双方で完全に同じ値の直書き重複）| 3 報告書一致 |
| M-2 | 1.3 | `discover-competitors` に `config.default.yaml` 新設 + `channel-new` Step 5 の API パラメータも同じ config を参照（min_subscribers / max_subscribers / posted_within_days / top / per_keyword の **完全重複**）| Part B 候補 #6, #7 |
| M-3 | 1.3 | `live-clean` に `config.default.yaml` 新設（削除/保護パターン外出し）| Part B 候補 #8 |
| M-4 | 1.3 | `postmortem` に `config.default.yaml::thresholds.{ratio_vs_median, neutral_band_pct}` 新設（0.5 / 0.7 / 0.9 / ±10% を外出し、「文脈調整可」記述は残す）| Part A 第 1 版 #5.16 / Part B 候補 #9 |
| M-5 | 1.3 | `video-upload` に `config.default.yaml` 新設（`selfDeclaredMadeForKids` / `containsSyntheticMedia` / NG ワード外出し）| Part B 候補 #14 |
| M-6 | 1.1 / 1.3 | `streaming` の `notify timeout`（5/10 秒）/ `1Password ボルトパス` / `--check-threshold` の 80% を `config/skills/streaming.yaml` に外出し | Part A 第 1 版 #5.18, #3.5, Part A 第 2 版 A1-3 / Part B 候補 #10〜12 |
| M-7 | 1.4 | `category_id: "10"` が `channel-setup/references/{config-template/youtube.json, upload-settings-template.json, schedule-template.json}` の 3 ファイルに重複 → Single Source 化 | Part A 第 2 版 A4-4 |
| M-8 | 1.4 | `upload-settings-template.json:4` `"public"` と `schedule-template.json:9` `"private"` の `privacy_status` 矛盾解消 | Part A 第 2 版 A4-5 |
| M-9 | 1.4 | `channel-setup/references/claude-md-template.md:13` / `channel-new/SKILL.md:100` の「`config/channel/{...} 計 7 ファイル`」を **8 ファイル**（`comments.json` 追加）に更新 | Part A 第 2 版 A4-12, A4-13 |
| M-10 | 1.4 | `video-description/SKILL.md:89,107` の「ハッシュタグ 13 個」と `config-generation-rules.md:36-37` の「5 個」のドキュメント間矛盾 → どちらが正か実装側で確認の上統一 | Part A 第 2 版 A4-2, A4-3 |
| M-11 | 2.2 | `videoup/SKILL.md` に「前工程」ブロックを追加し `/masterup`（Suno 系）+ `/lyria`（Lyria 系）の両方を明示（C-2 #2, #3 解消） | Part C 第 2 版 #2, #3 |
| M-12 | 2.2 | `thumbnail/SKILL.md` Next Step に「Lyria チャンネルでは `/lyria <theme>`」分岐を追加（`/wf-new` Phase 2c には分岐があるが `/thumbnail` 単独実行時に欠落）| Part C 第 1 版 C-2 #9 |
| M-13 | 2.2 | `video-description/SKILL.md` に「前工程: `/videoup`」を Cross References に追記 | Part C 第 2 版 #4 |
| M-14 | 2.2 | `metadata-audit/SKILL.md` の Cross References に「前工程: `/video-upload`」追記 | Part C 第 2 版 #6 |
| M-15 | 2.4 | description 末尾指示語の 5 系統揺れ → ガイドライン化（`.claude/skills/CONTRIBUTING.md` 仮 or CLAUDE.md 追加節）| Part C 第 1 版 5.2 |
| M-16 | 2.4 | 本文見出しの 3 系統揺れ（`Cross References` / `関連ファイル` / `Next Step`、`Instructions` / `実行フロー`、`When to Use` / `いつ使うか`）→ いずれかへ統一方針宣言 | Part C 第 2 版 5.2 |

#### 取り込むべき P3（low）fix 一覧

| ID | 観点 | 内容 |
|---|---|---|
| L-1 | 1.4 | `video-description/config.default.yaml:44-52` の `theme_emoji` を `content.json::title.theme_emoji` に集約（既存 `theme_activities` / `theme_scenes` と一元化） |
| L-2 | 1.4 | `channel-setup/references/{config-template/content.json, upload-settings-template.json, schedule-template.json, localizations-template.json}` の英語/日本ロケール固定 → プレースホルダ化 |
| L-3 | 1.4 | `analytics-report/SKILL.md:73,123` の `#Shorts` 文字列固定 → `analytics.collection_filter_keywords` 統合 |
| L-4 | 1.3 | `analytics-report` HTML KPI カード枚数（4）/ max-width（1200px）を skill-config 化 |
| L-5 | 1.3 | `playlist` の `"all"` プレイリスト挿入順（head/tail）を `playlists.json` スキーマに追加 |
| L-6 | 1.3 | `audience-persona` / `viewing-scene` の WebSearch クエリテンプレを `config.default.yaml` に外出し（AI 指示文と機械パラメータの切り分け前提）|
| L-7 | 2.2 | `analytics-analyze/SKILL.md` 前提セクションに「`/wf-next` から T+7 日後に呼ばれる」追記 |
| L-8 | 2.2 | `suno/SKILL.md` Cross References に「前工程: `/thumbnail`」追記 |
| L-9 | 2.4 | `channel-setup/references/config-template/` → `config-templates/` ディレクトリ複数形リネーム |
| L-10 | 1.1 | `videoup/references/generate_videos.sh` の ffmpeg 解像度・ビットレート・CRF を `config/skills/videoup.yaml` に外出し |
| L-11 | 2.1 | `analytics-report/SKILL.md` description にトリガー語「ビジュアル」「ダッシュボード」「HTML レポート生成」を追記 |
| L-12 | 1.1 | `suno` の禁止形容詞 17 語・NG/OK ワード 10 語超を skill-config の `scene_phrase_ng_words` に新設 |
| L-13 | 1.1 | `metadata-audit` の `< 3` / `> 12` チャプター数閾値を skill-config 化 |
| L-14 | 1.4 | `localizations-template.json::*.title_template` と `content.json::title.template` の重複統合 |

#### 取り込まない / 明示否定すべき項目

| ID | 内容 | 理由 |
|---|---|---|
| N-1 | shell helper（`log/ok/error` ANSI / `usage()` idiom）の共通化 | 配布の単純さを壊す（Part B 明言）|
| N-2 | `videoup/generate_videos.sh` と `streaming/run-ffmpeg.sh` の ffmpeg 経路統合 | 用途・実行環境が完全に異なる（Part B 明言）|
| N-3 | `postmortem → 4 検証 skill` の片方向バトンを「双方向化」修正 | postmortem は意図的な fan-out メタスキル（Part C 双方明言、設計判断）|
| N-4 | `wf-new / wf-next / channel-new / channel-import / channel-setup` のオーケストレータ系 fan-out 片方向（合計 10 ペア） | 双方向化は冗長化のみで利得なし（Part C 第 1 版「意図あり 10」分類）|
| N-5 | YouTube API 仕様値（タイトル 100 文字・video_id 11 文字・バナー 2048×1152・Music カテゴリ id 10）| プラットフォーム制約。skill-config 化しても更新権限がない |
| N-6 | 「seed として挙がっていた `TBD` の仕様未統一」を fix 候補に入れる | 検証の結果、`channel-new/SKILL.md:107` の 1 箇所のみで CLI 既定値説明として明文化済。修正不要 |
| N-7 | 「seed として挙がっていた `.py` 重複 3 種」を fix 候補に入れる | 検証の結果、`.claude/skills/**/references/` に Python ファイルは 0 件、`src/youtube_automation/scripts/` に各 1 件のみ。**重複は存在しない**ため、最終レポートで「seed の配置誤認、実態は重複なし」と短く明記する |

---

## 6. 全体サマリー（supervise への引き継ぎ用 1 段落版）

35 スキルの監査結果として、(A) 観点 1.1〜1.4 の汎用化系では「**画像生成・解析モデル名やしきい値は skill-config 化が大きく進んでおり ID リテラルや API キー直書きはゼロ**」だが、「`analytics-report` のブランド色 9 色、`channel-new`/`channel-import`/`channel-setup` の **`daiki-beppu` GitHub owner 固定** および `~/01-dev/`・`~/02-yt` 個人パス、`analytics-analyze` の **v1.x 旧 namespace `channel_config.*` 残骸**、`scripts/gcp-{bootstrap,terraform-apply}.sh` の **MD5 完全一致 CLAUDE.md 規約違反**」が P1 として残存。(B) 観点 2.1〜2.4 の整合性系では「**frontmatter / 開始句 / kebab-case 命名は 100% 統一**」「**主要バトン 14 ペアは双方向成立**」と良好だが、「`video-analyze` の `/lyria`・`/channel-direction` への事実誤認」「`lyria`/`masterup` 出力 ↔ `videoup/generate_videos.sh` 検出パターン不一致（実害候補）」「description 末尾指示語と本文見出しの 3〜5 系統揺れ」が改善対象。**v4.0.0 deprecated `short` / `community` の真の残存は 1 箇所のみ**（`video-description/config.default.yaml:6` コメント内）で、コード本体には残骸なし。

---

## 7. 結論

- **追加調査の必要なし**。次ステップ `supervise` は本 analysis の §5.「P1〜P3 fix 一覧」と §6.「全体サマリー」をそのまま `docs/audits/skills-audit-2026-05-18.md` へ整形・配置できる。
- supervise 側で考慮すべきは「Part A 第 1 版と第 2 版の **観点定義の差**をどう吸収するか（第 1 版優先で統合する）」と、「ハッシュタグ 13 個 vs 5 個の矛盾（M-10）と videoup master 命名不整合（H-8）を **要確認マーク付きで明記**するか別 issue にバトンするか」の 2 点。前者は最終レポート内処理可能、後者は最終レポートの **「次に取るべきアクション」節**で別 issue 化を提案する形が綺麗。
