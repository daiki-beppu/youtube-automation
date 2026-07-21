# Implementation Plans

このリポジトリの規約: 作業は必ず worktree 上で行う（`$REPO_ROOT/.worktrees/<slug>/`）。`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml` を触るプランは `CHANGELOG.md` の `[Unreleased]` 追記が必須（lefthook pre-push + CI ゲート）。docs / tests のみの変更はゲート対象外。

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) | REJECTED (with one-line rationale)

## 第 5 回監査（セキュリティ専門監査、2026-07-21、基準 commit `37b362ce`）

セキュリティ集中監査（フォーカス指定 /improve）。並列 4 subagent（シークレット/認証 / インジェクション・パス / ネットワーク・サーバー / Chrome 拡張・配布）→ 全 findings を advisor が実読 vet。
総評: **HIGH / MEDIUM 脆弱性ゼロ**。shell=True / eval / unsafe yaml / curl|bash ゼロ、全 subprocess が argv 形式、zip-slip・path traversal・CORS・CSRF・token 0o600・redact・webhook 許可リストいずれも防御済み。第 4 回以降の新サーフェス（live-chat 自動返信 daemon / streaming VPS）も、プロンプトインジェクション対策（`<viewer_input>` ラップ + stdin 渡し + `--sandbox read-only` + 出力監査 + 3 段レート制限）と systemd hardening を実装済みで健全。残ったのは LOW の hardening 3 件のみ。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 025 | 1Password フォールバックの client_secrets を tempfile 経由から in-memory 化（SIGKILL 残留解消） | P2 | M | — | [#2394](https://github.com/daiki-beppu/youtube-automation/issues/2394) | — | DONE |
| 026 | streaming VPS の stream key / webhook staging を素の /tmp から 0700 ディレクトリへ | P3 | S | — | [#2395](https://github.com/daiki-beppu/youtube-automation/issues/2395) | — | TODO |
| 027 | open / ffmpeg へ渡すパス引数の絶対パス化（defense-in-depth） | P3 | S | — | [#2396](https://github.com/daiki-beppu/youtube-automation/issues/2396) | — | TODO |

### Dependency notes

- 025〜027 は完全に独立（触るファイル非重複）。並列実行可
- 026 の `terraform apply` は実 VPS の再 provisioning を伴うためオペレーターが別途実施（プランは fmt / validate / pytest まで）

### Findings considered and rejected（再監査不要）

- **CORS 既定で任意の Chrome 拡張が collection-serve の read ルートを読める**（collection_serve.py:666-668）: by design（#896 コメントに意図明記）。第 1 回監査で同系 finding を裁定済み — `--allow-origin` lock が存在し、mutating 側は extension lock + token 必須（Plan 001）。露出は未公開プロンプト・下書きのみで受容
- **suno.com ページから拡張 bridge メッセージ（MAIN→ISOLATED postMessage）を偽装可能**: MAIN world の構造的制約で完全防御は不可能。悪用には suno.com 自体の侵害が前提、影響も自動化進捗状態の撹乱のみ。受容
- **SSH ホスト秘密鍵の cloud-init user-data 埋め込み**（infra/terraform/streaming/main.tf:66-72）: host-key pinning（provisioner の `host_key` 検証）のための意図的トレードオフ。鍵は当該サーバー自身の identity 鍵で、state / tfvars は gitignore 済み。受容
- **skill 配布（wheel → yt-skills sync）に内容署名なし**: 脆弱性ではなく trust model（wheel が trust root）。sync 自体は traversal 安全を確認済み。メンテナンスモードのリポジトリに L 工数の署名基盤は見合わない
- **`--` セパレータによる argv hardening 提案**（subagent 報告）: 手法が誤り。**ffmpeg は `--` end-of-options 非対応**。正しい対策（絶対パス化）に修正して Plan 027 とした

### クリーン確認済み領域（次回セキュリティ監査の短縮用）

- secrets.py（env → op read → ConfigError、値は stdin/ヘッダーのみ、argv 露出なし）/ oauth_handler（0o600 + `_redact`、READONLY_SCOPES 分離 #1699）/ fetch_stream_key（TTY 検知 + `::add-mask::`）/ notification（HTTPS + Discord ホスト許可リスト）
- suno ZIP 展開（zip-slip + entry 数 + サイズ上限）/ CollectionPaths・thumbnail_archive の `relative_to` 境界 / channel slug regex 検証
- collection_serve（localhost bind、mutating は extension lock + X-Serve-Token、body 上限、path traversal 防御）/ live_chat（上記総評参照）
- 拡張 manifest 最小権限（`<all_urls>` なし、CSP 緩和なし、innerHTML/eval ゼロ、background は sender 由来 tab のみ操作）/ pnpm-lock 全て registry.npmjs.org + integrity / lefthook・flake に remote fetch なし / コミット済みシークレットなし

## 第 4 回監査（Python コア本体の一般監査、2026-07-09、基準 commit `5394c378`）

初の `src/youtube_automation/`（~46K 行）本体監査。並列 4 subagent（正確性+セキュリティ / パフォ+依存 / テスト+負債 / DX+docs+方向性）→ 全 findings を advisor が実読 vet。
総評: subprocess・パス traversal・OAuth・シークレット・コメント冪等性は防御済み、クリティカルパスは 4,976 テストで実挙動検証済みと**健全**。実弾はアップロード経路のエラー処理・dead code・ツールチェーンのほつれに集中。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 020 | アップロード経路の堅牢化（tracking アトミック化 / QuotaExhaustedError 非終端化 / サムネ temp リーク） | P1 | S-M | — | — | [#1786](https://github.com/daiki-beppu/youtube-automation/pull/1786) | DONE（main マージ済み `34935fc7`） |
| 021 | bulk_update_desc の snippet 更新を read-modify-write 化（defaultAudioLanguage 消失防止） | P1 | S | — | — | [#1789](https://github.com/daiki-beppu/youtube-automation/pull/1789) | DONE（独立修正済み `fbde9a4d`） |
| 022 | analytics collect の uploads playlist 二重取得解消 + video_listing の例外/TZ 修正 | P2 | S | — | — | [#1788](https://github.com/daiki-beppu/youtube-automation/pull/1788) | DONE（main マージ済み `373f7409`） |
| 023 | dead analytics/report クラスタ 3 ファイル（1,016 行）削除 | P2 | S | — | — | [#1791](https://github.com/daiki-beppu/youtube-automation/pull/1791) | DONE（main マージ済み `d9de12f3`） |
| 024 | ツールチェーン整備（dev 依存一本化 / ruff B・RUF / seaborn 削除 / Any-gate CI / CJK フォント回帰テスト） | P2 | M | — | — | [#1790](https://github.com/daiki-beppu/youtube-automation/pull/1790) | DONE（main マージ済み `717a92b2`） |

### Dependency notes

- 020〜024 すべて main マージ済み。第 4 回監査の全プラン完了

### Findings considered and rejected（再監査不要）

- **`ci.yml` の `parallel:` ステップが不正構文疑い**: 誤り。現行 GitHub Actions の正規のステップグループ構文で、run 29001443387 で Ruff 両ステップの実行成功を確認済み
- **`collection_serve` の同時 POST `/downloaded` race**: 単一オペレーター + 単一拡張の運用モデルでは実発生確率ほぼゼロ（第 1 回監査の `write_distrokid_release` TOCTOU 棄却と同判断）。多重化するなら per-cid lock を検討
- **mypy/pyright 導入**: tayk（TS 後継、ADR-0021）移行済みのメンテナンスモードでは L+ 工数の回収期間が無い。「導入しない」を本行で明文化とする。型規律は any-usage-gate（024 で CI 化）が代替
- **`QuotaExceededError` が dormant という subagent 報告**: 二重に誤り。実名は `QuotaExhaustedError`（exceptions.py:45）で、upload_core.py:205 から raise されテスト済み。問題は「呼び出し側が握りつぶす」ことで、020 が修正する
- **`schedule.py` vs `publish_schedule.py` の重複疑い / `profile.py` 等の dead 疑い / comments の generator 3 実装**: いずれも誤検知（責務が別 / 現役 importer あり / 意図した strategy パターン）
- **CLI 起動時の pandas/matplotlib 重量 import**: 誤検知。`cli_entrypoints.py` は `import_module` の遅延 dispatcher で、重量 import は plotting 系コマンドに閉じている
- **retention の per-video Analytics クエリ**: audience retention curve にバッチ endpoint が無い API 制約。by design
- **GitHub Actions の Node 20 deprecation 注記**: 現状は自動 fallback で実害なし。actions メジャー bump は任意のついで作業

### 監査で plan 化を見送った残課題

- **doctor.py（2,650 行・61 コミット churn）の god module 分割**（L、テストは厚く安全）— TTP/branding 業務ロジックの `utils/` 移設 + GCP チェックのサブモジュール化。ユーザー未選択
- **中粒の構造整理**（M）— utils 83 モジュールの flat 化解消（suno_downloaded_* 8 分片の統合、`utils/comments/`・`utils/config/` パッケージ方式に倣う）/ metadata_generator.py（1,271 行）の 4 責務分割 / doc-contract 系テスト ~25 本への pytest marker 付与と behavioral-only fast lane。ユーザー未選択
- **PERF-02: サブ分析間の `_get_video_details` / `dimensions=video` クエリ共有**（M、collect 1 回のクォータをさらに削減）— 022 の続編として設計余地
- **`strategic_analytics.py` の `comprehensive` モード**（呼び出し元ゼロ、per-video N+1 内蔵）— 使うか消すかの判断待ち。023 のスコープ外として温存
- **japanize-matplotlib の置換移行**（S-M、MED リスク）— 024 は glyph 回帰テストの設置まで。テストが fail したら `font_manager.addfont()` 直接登録へ移行
- **Direction 3 件（ユーザー未選択、spike/design プラン候補）**: (1) Data API クォータ可観測性 — cost_tracker 相当の units 台帳 + pre-flight 見積（無人運転を止める最有力因子に事前可視性）。(2) `yt-unpublish` — 公開 3 entrypoint に対する逆操作の不在。`videos().update` の既存配管で `privacyStatus=private` 一括復帰、dry-run→confirm 必須。(3) cost_tracker の `estimated_cost_usd` null 固定（Issue #132 の意図的決定）の再訪 — 単価表 1 枚でドル換算が完成する

## 第 3 回監査（takt リジェクト多発の原因調査、2026-07-06、基準 commit `bf68c73d` / dotfiles `9a030ff`）

調査テーマ: review-takt-default の REJECT 多発（`.takt/runs/` 239 run・指摘 676 件の全数解析）。
主要結果 — (1) REJECT 率 91%（171/187）は 7 観点ゼロトレランス全員一致ゲートの数理的帰結
（各観点の個別 REJECT 率 27〜41% → 通過率 ≈9%）で品質シグナルではない。(2) fix → 再レビュー
126 ペアの 91% が再 REJECT だが、前回指摘未解消（persists）は 14% のみで、77% は「同じファイル
への新規指摘」＝ fix がレビュアーの走査範囲（累積差分全体）を自己監査していない。(3) issue 品質が
効く指摘は全体の ~11%、CI ツーリング不足は ~3% のみ。(4) 上流対策（#1508 チェックリスト・
強化 plan 指示）は 2026-07-03〜05 投入でクリーンな効果測定サンプル 0 件。

**注意: 018 / 019 の変更対象は dotfiles リポジトリ（`~/01-dev/dotfiles/config/.claude/skills/`）**。
プランファイルだけが本リポジトリにある。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 019 | takt-review の fix を累積差分の自己監査 + finding_id 解消根拠表つきに再設計 | P1 | M | — | — | — | DONE（dotfiles main マージ済み `71d453f`） |
| 018 | issue / to-issues / takt-issue テンプレに「兄弟入口・貫通先」列挙を必須化 | P2 | S | — | — | — | DONE（dotfiles main マージ済み `3dbd88e`） |

### Findings considered and rejected（再監査不要）

- **「issue の内容が悪いから REJECT される」説**: 主因ではない。要求解釈系の指摘は 676 件中 75 件（11%）。issue 本文の長さ・テンプレ準拠と REJECT 回数に相関なし（2,105 字・影響ファイル記載ありの #1141 でも 14 REJECT）。
- **「CI / lint ツーリング不足」説**: 機械捕捉可能クラス（未使用コード・依存脆弱性・型）は指摘の ~3%。knip / oxlint / tests は機能している。
- **「/issue・/to-issues に受入条件・スコープ外が無い」**: 2026-07-05 のスキル改訂で導入済み（takt-issue の preflight 正規化も同日導入済み）。残ギャップは「兄弟入口・貫通先」の観点のみ → Plan 018。
- **takt 本体（builtin review policy のゼロトレランス設計・7 観点一致）の変更**: ユーザー前提により対象外（takt は据え置き）。

### 監査で plan 化を見送った残課題

- **効果測定基盤**（`.takt/runs` から verdict / persists / High 件数 / 欠陥クラス別の自動集計を常設し、#1508 チェックリストと本監査 018/019 の効果を 20〜30 run で判定）— 提案済み・ユーザー未選択
- **自己申告ゲートの機械化**（変更行カバレッジゲート、config キーの定義⇔loader⇔使用の貫通チェック CLI）— 指摘最頻 2 クラスの CI 昇格。効果測定の結果を見てから判断
- **運用指標の変更**（REJECT 数ではなく persists 数 + High 件数を見る）— ドキュメント化のみの小変更だが docs/takt-operations.md の改訂はユーザー確認待ち

## 第 2 回監査（スキル全般の Sonnet-safe 化、2026-07-05、基準 commit `8deb3f02`）

監査テーマ: `.claude/skills/` 全 47 スキルを「Sonnet 級のより弱いモデルが実行しても作者の期待とズレなく解釈できるか」の観点で監査（TRIGGER / AMBIG / DRIFT / ROBUST の 4 ディメンション、並列 4 subagent + 全 findings を advisor が実読 vet）。42 件の生 findings から 12 件を有効と判定し、規約 1 本 + 個別修正 12 本に plan 化した。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 005 | Sonnet-safe スキル記述規約を docs/skill-design/ に制定 | P1 | M | — | [#1512](https://github.com/daiki-beppu/youtube-automation/issues/1512) | [#1529](https://github.com/daiki-beppu/youtube-automation/pull/1529) | DONE |
| 006 | comments-reply / pinned-comment に dry-run→apply 承認ゲート追加 | P1 | S | 005 (soft) | [#1513](https://github.com/daiki-beppu/youtube-automation/issues/1513) | [#1537](https://github.com/daiki-beppu/youtube-automation/pull/1537) | DONE |
| 007 | analytics-report の CTR 解釈記述をコード実態（百分率 float）に修正 | P1 | S | — | [#1514](https://github.com/daiki-beppu/youtube-automation/issues/1514) | [#1536](https://github.com/daiki-beppu/youtube-automation/pull/1536) | DONE |
| 008 | 兄弟スキル間の frontmatter 矛盾・発動キーワード衝突を解消 | P1 | S | 005 (soft) | [#1515](https://github.com/daiki-beppu/youtube-automation/issues/1515) | [#1538](https://github.com/daiki-beppu/youtube-automation/pull/1538) | DONE |
| 009 | 工程チェーンの前提条件ガードを 4 スキルに追加 | P2 | S-M | 005 (soft) | [#1516](https://github.com/daiki-beppu/youtube-automation/issues/1516) | [#1551](https://github.com/daiki-beppu/youtube-automation/pull/1551) | DONE |
| 010 | channel-new のペルソナ生成前に TTP 中間ゲート追加 | P2 | S | — | [#1517](https://github.com/daiki-beppu/youtube-automation/issues/1517) | [#1533](https://github.com/daiki-beppu/youtube-automation/pull/1533) | DONE |
| 011 | live-clean の削除承認を明示的 2 択 + 取消不可警告に固定 | P2 | S | 005 (soft) | [#1518](https://github.com/daiki-beppu/youtube-automation/issues/1518) | [#1541](https://github.com/daiki-beppu/youtube-automation/pull/1541) | DONE |
| 012 | stale/freshness 判定を freshness-rules.md へ単一ソース化 | P2 | S | — | [#1519](https://github.com/daiki-beppu/youtube-automation/issues/1519) | [#1546](https://github.com/daiki-beppu/youtube-automation/pull/1546) | DONE |
| 013 | suno のモード判定を decision tree 化 | P2 | S | — | [#1520](https://github.com/daiki-beppu/youtube-automation/issues/1520) | [#1543](https://github.com/daiki-beppu/youtube-automation/pull/1543) | DONE |
| 014 | suno-helper → masterup の部分ダウンロード検知手順を明文化 | P2 | S | — | [#1521](https://github.com/daiki-beppu/youtube-automation/issues/1521) | [#1549](https://github.com/daiki-beppu/youtube-automation/pull/1549) | DONE |
| 015 | postmortem の閾値調整ルーブリック追加 | P3 | S | — | [#1522](https://github.com/daiki-beppu/youtube-automation/issues/1522) | [#1542](https://github.com/daiki-beppu/youtube-automation/pull/1542) | DONE |
| 016 | setup の project ID truncate 手順を一義化 | P3 | S | — | [#1523](https://github.com/daiki-beppu/youtube-automation/issues/1523) | [#1545](https://github.com/daiki-beppu/youtube-automation/pull/1545) | DONE |
| 017 | thumbnail の外部リポジトリ参照をオペレーター向け注記に隔離 | P3 | S | — | [#1524](https://github.com/daiki-beppu/youtube-automation/issues/1524) | [#1544](https://github.com/daiki-beppu/youtube-automation/pull/1544) | DONE |

全 13 件、2026-07-05〜07-06 に main へマージ済み（スポットチェックで #1529 / #1537 / #1551 の diff を実読し、要件との整合を確認済み）。

### 既存 issue との関係

- **#1489〜#1493「[skill-quality] AI 可読性改善」（親 #1487）**: 同テーマの網羅スイープ。両立方針 — 確定修正（本監査の 13 issue）を先行させ、スイープ側は適用済み修正を尊重する（各 issue にコメント済み、2026-07-05）
- **#1499（channel-new ヒアリング TTP 特化）**: #1517 と同ファイルを触るため順序注意（#1517 の issue 本文に明記）

### Dependency notes

- **005 を最初に**実行することを推奨。006 / 008 / 009 / 011 は 005 の規約（承認ゲート標準型・発動条件相互排他・前提ガード標準型）の実装例になる。ただし各 plan は自己完結しており 005 未完了でも実行可能（soft dependency）。
- 006〜017 は互いに独立（触るファイルが重複しない）。並列実行可。例外: 012 と 009 はどちらも wf 系に近いが対象ファイルは非重複。
- `.claude/skills/` を触る plan（006〜017 すべて）は CHANGELOG 追記必須。**複数 plan を連続実行する場合、CHANGELOG の [Unreleased] で追記が conflict しやすい**ので、実行順に rebase すること。

### Findings considered and rejected（再監査不要）

- **「CLAUDE.md §6 が存在しない」（wf-* の参照切れ疑い）**: 誤り。`.claude/CLAUDE.template.md:171` に「## 6. Claude が判断に迷ったら参照すべきスキル一覧」が実在し、`docs/workflow-cheatsheet.md` も wheel force-include + `yt-skills sync --asset workflow-cheatsheet` で配布される正当な参照。
- **「yt-launch-curve / yt-thumbnail-correlate / yt-theme-compare / yt-channel-trend が未登録の可能性」**: 全 4 CLI が `pyproject.toml::[project.scripts]` に実在。
- **「channel-new の description に廃止スキル channel-import のトリガー残存」**: by design。旧名で呼ぶユーザーを統合先へルーティングする意図的な alias。
- **「automation-release の awk が大文字小文字厳密で false positive」**: by design。`### Migration` の完全一致は `docs/changelog-contract.md` の契約仕様。
- **「thumbnail prompt-schema 試験導入の誤用リスク」**: 本文に「実本番フローからは未接続」と明示済み。
- **「wf-new / wf-next / wf-status のトリガー衝突」「analytics-collect / analyze / report のトリガー衝突」**: 各 description に相互の否定トリガー（「既存の進行は /wf-next」「/analytics-analyze の前段」等）が既に記述済み。
- **「video-analyze / community-post の設定読み込みゲート文言が矛盾」**: 文言は冗長だが「存在しない override は未設定として扱い、勝手に作成しない」「fallback 元としては使わない」と一義的に書かれており誤読の余地は小さい。
- **「suno-helper 拡張 ID の形式説明不足」「ペーシング定義値が SKILL.md に無い」**: Cross References で `extensions/shared/constants.ts::BALANCED_RUN_PACING` への参照が明示済み。情報の置き場所として妥当。
- **「community-draft の poll deprecated が frontmatter 未記載」**: 本文の型一覧表に DEPRECATED と移行ガイドが明記済み。frontmatter は現行型のみ列挙しており誤誘導なし。

### Plan 作成時の再 vet による縮小（監査 finding との差分）

- **010（channel-new）**: 監査は「完了条件が埋没・Step 3 が混在」と主張したが、実読では TTP 完了条件は冒頭 48-60 行に在り、Step 3 は停止 17 チェックと許容 4 fail を理由付きで分離済み。実ギャップは「ペルソナ生成前の中間ゲート欠如」のみに縮小（M → S）。
- **014（masterup）**: 監査は「DL 状態管理の責務不明」と主張したが、責務分離は masterup:10 / suno-helper:130-131 に明文化済み。実ギャップは「部分ダウンロード検知」のみに縮小（M → S）。

### 監査で plan 化を見送った残課題

- **発動キーワード重複の機械検出**（`test_skill_docs_consistency.py` 系譜で「同一鉤括弧キーワードが複数 description に出たら fail」）— 規約 005 の合意後に検討
- **`assets.music_downloaded` の曲数型への拡張**（bool → `{downloaded, expected}`。014 の機械化。スキーマ変更のため別判断）
- **巨大 SKILL.md（collection-ideate 673 行 / automation-update 672 行）の構造分割** — 参照関係は明示されておりリスクの割に益が薄いと判断
- **automation-update の Migration 欠落 fallback の要約手順詳細化**（M、LOW-MED）
- **metadata-audit の issue 種別 → 対応スキル対応表**（S、LOW）
- **streaming の ssh-agent 毎セッション再登録の前提セクション昇格**（S、LOW）
- **修正後スキルの実測検証**: dotfiles の `empirical-prompt-tuning` スキル（バイアスを排した実行者に実行させ両面評価）で、006 / 011 / 013 など解釈が分かれやすい修正の受け入れ検証を行う選択肢がある（オペレーター判断）

---

## 第 1 回監査（distrokid-helper 本体 + yt-collection-serve、2026-06-12、基準 commit `fa296fe`）

| Plan | Title | Priority | Effort | Depends on | Issue | Status |
|------|-------|----------|--------|------------|-------|--------|
| 001 | POST /distrokid/releases の入力検証 + POST body サイズ上限 | P1 | S | — | [#953](https://github.com/daiki-beppu/youtube-automation/issues/953) | DONE |
| 002 | distrokid-helper の dev ツールチェーンを suno-helper と統一 | P2 | M | — | [#954](https://github.com/daiki-beppu/youtube-automation/issues/954) | DONE |
| 003 | distrokid-helper に lint / format ゲート + CI パリティ | P2 | M | 002 | [#955](https://github.com/daiki-beppu/youtube-automation/issues/955) | DONE |
| 004 | サーバー URL 既定値を shared/constants.ts に集約 | P3 | S | — | [#956](https://github.com/daiki-beppu/youtube-automation/issues/956) | DONE |

### Dependency notes

- 003 は 002 の後に実行する（両方が package.json と pnpm-lock.yaml を編集するため conflict）→ 両方 DONE
- 001 と 004 は完全に独立

### Findings considered and rejected

- **App.tsx:128 の「stale closure バグ」**: by design。コメント（App.tsx:113-114）が意図を明記済み
- **`write_distrokid_release` の TOCTOU race**: 単一オペレーター設計で実発生確率ほぼゼロ
- **CORS の `chrome-extension://` scheme 全許可**: `--allow-origin` が既に存在。Plan 001 で POST 側を緩和
- **`/distrokid/assets` の拡張子 whitelist**: 脅威前提が非現実的
- **`_send_json_error` のメッセージ切り詰め**: 信頼クライアント（自前拡張）のみ。実害なし
- **StatusBanner の XSS**: React JSX 自動エスケープで安全

### 監査で plan 化を見送った残課題

- **popup（App.tsx 301 行）のユニットテスト新設**（テスト, M）
- **README 運用エッジケース補強**（docs, S）
- **`waitForRemoval` のエラーメッセージ修正**（正確性, S）
- **Direction: セレクタ pre-flight check / fill 後検証チェックリスト**（M）
