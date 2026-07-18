# takt 運用詳細

CLAUDE.md の「開発ワークフロー」節の詳細版。要点は CLAUDE.md を参照。

## workflow の使い分け（ラベル = workflow 名）

issue には実行ルートを示す `takt:*` ラベルを **1 つ** 付与し、着手時はラベルと同名の workflow で実行する（`takt add '#<N>' -w <名前>`）。判定基準の単一ソースはグローバル `/issue` スキルの workflow 判断表（`~/.claude/skills/issue/SKILL.md`）で、本表はその要約。

| ラベル | workflow（step 構成） | 対象 |
|---|---|---|
| `takt:feature` | `feature`（plan → test_design → test_design_review → write_tests(red 実証) → implement → review → scope_review） | 新規 feature（既存挙動を触らない）。セキュリティ・認証（OAuth / secrets）系、公開インターフェース・スキーマ変更を伴う変更もこちら |
| `takt:improve` | `improve`（plan → implement → review。挙動変更影響表で意図した変更と回帰を区別） | 既存機能の意図的な挙動変更・拡張（interface 変更なし） |
| `takt:diagnose-fix` | `diagnose-fix`（diagnose → fix → supervise。fix 条件未達は診断レポートを残して停止） | 原因不明のバグ（再現手順・原因が issue 本文に無い） |
| `takt:fix` | `fix`（fix → supervise の軽量 2 step。plan・テスト先行なし） | 原因特定済みの小さなバグ修正・軽微な指摘対応 |
| `takt:docs` | `docs`（implement → review の最軽量 2 step） | ドキュメント・skill のみの変更（コード変更なし） |
| `takt:lite` | `lite`（plan → implement → review。リポジトリ同梱 `.takt/workflows/lite.yaml`） | refactor / chore、既存テストで挙動確認できる軽量タスク。**迷ったらこれ（トークン節約優先）** |
| `takt:manual` | なし | takt 不要。1 行修正・誤字・設定値 1 箇所変更などの極小タスク（`/issue-direct` や手動で直接実装）、または人間の判断・対話が主となる issue |

- workflow の実体: `lite` はリポジトリ同梱（`.takt/workflows/lite.yaml`）、その他はグローバル `~/.takt/workflows/*.yaml`
- 境界の指針:
  - 影響範囲が未確定のときは `takt:feature` に寄せる（fail-safe）
  - アップロードの**対象選択・公開状態を変えるロジック**の変更（例: auto-detect の対象選択条件、publish / privacy 制御、live 移行）、複数スキル・複数モジュール横断、破壊的変更は厳格側（`takt:feature`）。preflight の**検証強化・メッセージ・しきい値調整**に留まる修正は `takt:fix` / `takt:lite` で可
  - 挙動選択に設計判断が要るもの（フォールバック方針、resume ポリシー、統計手法の整合）や後方互換設計が要るものは `takt:manual` に落とさず workflow に載せる
- 旧体系からの読み替え: `takt:default` → `takt:feature`、`takt:none` → `takt:manual`（2026-07 に世代交代。旧ラベルは削除済みで、新規付与は新ラベルのみ）
- 導入後に新しい takt バージョンへ上げた場合は `takt workflow doctor lite` で静的検証すること（step スキーマのキー名が変わる可能性がある）。加えて `uv run pytest tests/test_takt_lite_workflow_contract.py -q` で状態遷移契約を動的検証できる（下記）

### lite workflow の状態遷移 contract テスト

`tests/test_takt_lite_workflow_contract.py` は、takt の mock provider + `TAKT_MOCK_SCENARIO`（persona 別の fixture キュー）で lite workflow の状態機械を LLM なしで実走し、以下の契約を検証する（issue #2164）:

- preflight `approved` → `plan` / `blocked`・未知 verdict → ABORT
- review `approved` → COMPLETE / `needs_fix` → `implement` 差し戻し（review 応答の feedback 注入込み）/ `blocked`・未知 verdict → ABORT
- implement↔review 5 周で loop monitor judge が起動し、健全 → `implement` 継続、非生産的 → ABORT
- `max_steps: 18` 到達で ABORT
- global schema（`review-verdict`）欠損時は run / doctor とも fail-closed

運用上の注意:

- グローバル設定は `TAKT_CONFIG_DIR` で `tests/fixtures/takt_global/` に差し替えるため、実行環境の `~/.takt` に依存しない。`tests/fixtures/takt_global/schemas/review-verdict.json` は dotfiles の `~/.takt/schemas/review-verdict.json` のミラー。**dotfiles 側の schema を変更したら fixture にも反映すること**（drift すると contract テストが実挙動と乖離する）
- step 直指定の `provider: codex` は CLI `--provider` より優先されるため、テストは YAML の step provider 値だけを mock に差し替えた fixture を一時リポジトリに生成して実行する（rules / loop_monitors / schema_ref は無改変）
- takt CLI が無い環境ではテストは skip する。CI の `takt-workflow-contract` job は takt を pin して `TAKT_LITE_CONTRACT_REQUIRED=1` で実行し、skip を許さない。**takt を upgrade したら CI の pin（`npm install -g takt@X.Y.Z`）も bump する**（contract テストの red で lite workflow との drift を実 run 前に検出する）
- mock provider の transition fixture は takt 本体（0.51 系）の観測仕様（persona "conductor" による phase 3 structured 判定など）に依存する。engine 側の網羅的 unit test は nrslib/takt 側の責務で、本リポジトリは repo-local lite.yaml の契約検証に限定する

## 提出前セルフ監査（pre-review-checklist）

`.takt/facets/policies/pre-review-checklist.md` は、過去の review-takt-default 指摘 371 件（183 レビュー）を全件分類して抽出した頻出 8 パターンの監査基準（issue #1508）。lite の `implement` / `review` step に `policy:` で注入され、実装者が提出前に自己監査 → reviewer が独立照合する二段構えで、post-hoc レビュー（1 回 ~15M tokens）の REJECT 再走を減らす。

- **implement step**: 8 項目を根拠（ファイル:行）付きで照合し、受入条件充足表を出力してから完了する
- **review step**: 実装者の自己監査を鵜呑みにせず独立照合。8 項目 pass + issue スコープ内欠陥なしのときのみ approved。スコープ外の改善提案は follow-up 候補として記録し verdict に影響させない（moving goalposts の防止）
- **更新手順**: レビュー REJECT の傾向が変わったら `.takt/runs/*/reports/review-summary.md` の指摘を再分類し、checklist の項目・頻出度を更新する。policy のインライン注入は 2,000 字で truncate されるため、冒頭のサマリー表に要点を収める構成を維持すること
- 機械検出可能なパターン（lint / 未使用コード / `typing.Any` grep / テスト差分ゼロ検知）は checklist ではなく lefthook / CI ゲートに委譲する方針

## トークン消費の計測（observability）

`.takt/config.yaml` で有効化済み:

```yaml
observability:
  enabled: true
  usage_events_phase: true
```

- 記録先: `.takt/runs/<run>/logs/<session>-usage-events.phase.jsonl`（step × phase × provider × model 粒度）
- **worktree 実行時の注意**: takt 自動 worktree（task の `worktree: true`）では、この `.takt/runs/` は**メインリポジトリではなく worktree 側**（`<repo-parent>/takt-worktrees/<timestamp>-<slug>/.takt/runs/`）に作られる。worktree を削除するとログも消えるため、計測を残したい run はログを先に回収すること
- 集計: takt リポジトリ同梱の `npm run analyze:usage -- <run ディレクトリ>`（`--format csv` 可）。複数 run の横断比較は同梱の `tools/token-usage.sh <takt-worktrees のパス>` が run × step 粒度で整形表示してくれる
- codex step の input tokens は agentic ループの各ターンで会話履歴全体が再送されるため累積計上され、見かけが大きくなる。実効コストは `cached_input_tokens` を差し引いた非キャッシュ input で見ること
- 消費が異常に見えたときは、まず phase JSONL で「どの step のどの phase が食っているか」を特定してから対策する

## worktree の置き場

このリポジトリの開発は必ず worktree 上で行う（メインの作業ツリーで直接ブランチを切らない）。

- **takt 自動生成**: `<repo-parent>/takt-worktrees/<timestamp>-<N>-<slug>/`（takt が自動管理）
- **手動 `git worktree add`**: `$REPO_ROOT/.worktrees/<slug>/`（リポジトリ内・gitignore 済み・`parallel` スキルと共通）
- `<repo-parent>/automation-worktrees/` 等のリポジトリ外手動置き場は非推奨（過去の残骸のみ）
- 親 checkout / worktree の初回は `bash .lefthook/setup-worktree.sh` を実行する。direnv があれば `.envrc` を allow し、なければ `nix develop` を使って、shellHook と `.lefthook/install.sh` により fail-closed hook wrapper まで再生成する。takt agent / 非対話 shell のコマンドは `bash .lefthook/setup-worktree.sh uv run pytest` のようにラッパー経由で実行する。診断は `bash .lefthook/setup-worktree.sh sh -c 'command -v lefthook && lefthook version'`、直接の Nix 再生成は `nix develop --command bash .lefthook/install.sh`。
- devShell 入場時に shellHook が `.lefthook/worktree-tmpdir.sh` で `TMPDIR` を worktree ごとに分離するため、`concurrency > 1` の並列 run が共有 TMPDIR で干渉しない（issue #2088）。takt worker は takt core が注入する `<worktree>/.takt/.runtime/tmp` が優先され、そのまま尊重される。詳細は `docs/development.md` の「TMPDIR の worktree 分離」。
- 同様に、devShell 入場（`.envrc` / `.lefthook/setup-worktree.sh`）は `NIX_CACHE_HOME` を worktree 分離 TMPDIR 配下へ export するため、並列 run のレビュー step が同一 fingerprint の flake を同時評価しても Nix の eval-cache SQLite が競合しない（issue #2089）。詳細は `docs/development.md` の「Nix キャッシュの worktree 分離」。

## takt 設定の継承構造

リポジトリ固有 `.takt/config.yaml` は `draft_pr: false` / `base_branch: main` / runtime prepare / observability だけを上書きし、provider・model・language・concurrency・persona_providers はグローバル `~/.takt/config.yaml` を継承する。`persona_providers` は project と global の辞書が deep merge されず project 側が丸ごと優先されるため、部分的な再宣言は禁止する。各 workflow の step に provider / model の直指定がある場合はそちらが優先される。repo-local `lite` workflow は、グローバル版と同じく各 step の `provider: codex` 直指定を維持する。

## トークン消費の内部構造と削減指針

takt（v0.49 時点）の 1 step は最大 3 phase の LLM 呼び出しで構成される。workflow を書く・直すときは以下のコストモデルを前提にすること。

### phase コストモデル

| phase | 発生条件 | コスト特性 |
|---|---|---|
| Phase 1（本体実行） | 必ず 1 回 | previous_response / knowledge / policy はインライン注入 2,000 字で truncate され、全文はファイル参照に誘導される |
| Phase 2（レポート生成） | `output_contracts` があるファイル数分 | Phase 1 のセッションを resume するため追加送信は小さい。**契約が無ければ 0 回** |
| Phase 3（状態判定） | **自然言語 condition の rules があると起動** | **新規セッションに Phase 1 応答の全文を再送**して判定。structured → tag → ai_judge の最大 3 回。**rules が 1 個だけなら auto_select で LLM 0 回** |

### rules 設計指針（判定コストの回避）

1. **分岐が 1 つの step は自然言語 condition で OK**（judge は auto_select になり LLM を呼ばない）
2. **複数分岐の step は `structured_output`（schema は `.takt/schemas/*.json`）+ deterministic `when:` 式で書く**。`when: structured.<step名>.<field> == "値"` の形式なら判定が in-code で完結し Phase 3 が丸ごとスキップされる（lite の review step が実例）。最後に `when: "true"` → ABORT の安全網を置く
3. **`output_contracts` は本当にレポートが要る step だけに付ける**（Phase 2 の呼び出しがファイル数分増える）
4. codex step の推論量は `provider_options.codex.reasoning_effort`（minimal / low / medium / high / xhigh）で調整できる

### 制約事項（設定では変えられないもの）

- Claude provider の `settingSources: ['project']` はハードコード。CLAUDE.md / `.claude/skills` の description は Claude step の全 phase で毎回注入されるため、**注入量を減らす唯一の手段はリポジトリ側ドキュメント・description を薄く保つこと**
- 状態判定（Phase 3）だけを別モデルにする設定は無い（判定は step と同じ provider/model。唯一の例外は `loop_monitors[].judge` の provider/model 指定）
- 厳格系 workflow（`feature` 等、レポート契約 + 自然言語 rules を持つ step が多いもの）は Phase 2 / Phase 3 のコストが構造的に乗る。大型 issue で `feature` を選ぶのは品質優先の判断として妥当

### session resume と worktree

takt の自動 worktree（task の `worktree: true`）では **step 間のセッション resume が無効化される**（実行 cwd がプロジェクト cwd と異なるため。ディレクトリ間汚染の防止ガード）。この場合、同一 persona の step 再訪（review⇄implement ループの implement 再訪など）でも毎回新規セッションになり、リポジトリ再探索コストがかかる。

**実測結果（2026-07、#1484 の default workflow で resume OFF/ON を A/B 比較）: review⇄fix ループを持つ workflow では resume 有効化は逆効果**。非キャッシュ input が OFF ≈ 7.2M → ON ≈ 19.3M と約 2.7 倍に増えた。原因は「resume でスレッド履歴が周回ごとに肥大する」×「プロンプトキャッシュの TTL（数分）より review⇄fix の 1 周（10〜25 分）が長い」の組み合わせで、周回のたびに失効した長履歴がほぼ丸ごと非キャッシュで再課金されるため。リポジトリ再探索の節約（〜100K/回）では相殺できない。

resume が効くのは**キャッシュ TTL 内に次 step が始まる隣接 step のみ**（同実験で write_tests→implement の非キャッシュ input が 187K → 102K に減少するのを確認）。したがって:

- ループを持つ workflow（default 等）は **resume 無効のまま（= takt デフォルト挙動）が安い**。このガードはコスト面では防御として機能している
- 手動 worktree 内で `takt add` → `takt run`（task の `worktree` 指定を省略 = カレント実行）にすれば `cwd === projectCwd` となり resume は有効化できるが、検討に値するのは**ループのない短い直列 workflow だけ**。この場合 auto-commit / push / auto_pr は worktree 実行時のフローなので、commit・PR 作成は手動（CLAUDE.md「開発ワークフロー」の commit 規約 + `gh pr create`）で行うこと

### 計測との突き合わせ

改善の効果は usage JSONL（下記）の `phase3_*` イベントの有無と step × provider 別トークンで確認する。lite の想定は「全 step codex・`phase3_*` イベントなし・Phase 2 なし」。

## skill 編集と takt の関係

skill の編集 → 検証 → 配布（下流反映）の一連手順は `docs/development.md` の「skill 開発ループ」を参照。本節はそのうち「takt から編集できるか」の分岐だけを詳述する。

`.claude/skills/**` を含む `.claude/` 配下は Claude Code の **protected paths**（`acceptEdits` モードでも write 時に必ず prompt が出る領域）に該当する。takt は Claude Agent SDK を `settingSources: ['project']` + `permissionMode: 'acceptEdits'` で呼ぶため prompt に答える人間がおらず、**Claude provider が走る persona から** `.claude/skills/<name>/SKILL.md` 等への Edit/Write は `Claude requested permissions to write to ..., but you haven't granted it yet.` で deny される（`permissions.allow` ルールでは bypass 不可、`bypassPermissions` のみが bypass）。

ただし、**実装を担う `coder` persona を codex provider にしている（グローバル設定から継承）ため**、実装ファイルへの編集は Codex CLI 経由で行われ Claude Code の protected paths 制約を回避できる（Codex は独自のサンドボックスで動作し、`$REPO_ROOT/.agents/skills` を探索パスに含む）。レビュー系 persona は opus（Claude）だが書き込みは行わないため影響しない。そのため、**skill 配下を変更する issue も takt から問題なく回せる**。実際の運用例として、`.claude/skills/videoup/references/generate_videos.sh` 等の skill 配下スクリプト修正も takt 経由で完走実績がある。

逆に `coder` を Claude provider に戻している環境では、従来通り skill 配下の Edit が deny される。その場合は通常の Claude Code 対話セッション（cmux pane 等）で直接編集し、コミット・PR 作成は CLAUDE.md「開発ワークフロー」の規約に従い手動で実施する。

## Codex 共用時の skill 表記読み替え

`.claude/skills/**` は Claude Code / Codex CLI 共用だが、既存 SKILL.md には Claude Code 固有表現が残る。Codex で実行するときは、`AskUserQuestion` は通常のユーザー確認、`Read ツール` は画像/ファイル閲覧手段、`Bash ツール run_in_background=true` は長時間コマンドを非同期 session で起動して進捗を poll、`TodoWrite` は Codex の plan/checklist 更新として読み替える。これらの表記が残っていても実装不整合とは扱わず、同等の Codex 機能で実行する。

## リリース

`/automation-release` スキルで Release PR パターンを自動化（prepare → リリース PR → publish の 2 フェーズ）。post-release の運営者向けガイドと下流追従 issue は `/release-notes` が担当。
