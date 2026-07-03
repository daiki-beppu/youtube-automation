# takt 運用詳細

CLAUDE.md の「開発ワークフロー」節の詳細版。要点は CLAUDE.md を参照。

## workflow の使い分け（default / lite）

- **`lite`**（`.takt/workflows/lite.yaml`、リポジトリ同梱）: 小〜中規模 issue 用の軽量 3 step（plan → implement → review）。各 step でプロジェクトコンテキスト（CLAUDE.md + skill descriptions 等）が再注入されるため、step 数の削減がそのままトークン削減になる。`takt add` 時に workflow として `lite` を指定する
- **組み込み `default`**（9 step: plan → write_tests → implement → ai-antipattern → 並列 review → supervisor）: 以下に該当する issue は必ず default を使う
  - セキュリティ・認証（OAuth / secrets）・アップロード系に触れる変更
  - 複数スキル・複数モジュールを横断する変更、破壊的変更
  - テスト戦略の設計が必要な新機能
- 導入後に新しい takt バージョンへ上げた場合は `takt workflow doctor lite` で静的検証すること（step スキーマのキー名が変わる可能性がある）

## トークン消費の計測（observability）

`.takt/config.yaml` で有効化済み:

```yaml
observability:
  enabled: true
  usage_events_phase: true
```

- 記録先: `.takt/runs/<run>/logs/<session>-usage-events.phase.jsonl`（step × phase × provider × model 粒度）
- 集計: takt リポジトリ同梱の `npm run analyze:usage -- .takt/runs/<run>`（`--format csv` 可）
- 消費が異常に見えたときは、まず phase JSONL で「どの step のどの phase が食っているか」を特定してから対策する

## worktree の置き場

このリポジトリの開発は必ず worktree 上で行う（メインの作業ツリーで直接ブランチを切らない）。

- **takt 自動生成**: `<repo-parent>/takt-worktrees/<timestamp>-<N>-<slug>/`（takt が自動管理）
- **手動 `git worktree add`**: `$REPO_ROOT/.worktrees/<slug>/`（リポジトリ内・gitignore 済み・`parallel` スキルと共通）
- `<repo-parent>/automation-worktrees/` 等のリポジトリ外手動置き場は非推奨（過去の残骸のみ）

## takt 設定の継承構造

リポジトリ固有 `.takt/config.yaml` は `draft_pr: false` / `base_branch: main` / `provider: codex` / `persona_providers`（coder / planner → codex）/ observability を上書きし、model・language はグローバル `~/.takt/config.yaml` を継承する。**takt は全 persona codex で運用する**（レビュー系も codex。lite workflow は各 step の `provider:` 直指定でも codex を明示しており、step 直指定は persona_providers / global より優先されるため確実）。全 codex 運用では **Claude 側の 5h レートリミットを takt は消費しない**（消費は codex 側クォータ）。

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
- 組み込み default は全 step にレポート契約 + 自然言語 rules を持つため Phase 2 / Phase 3 のコストが構造的に乗る。大型 issue で default を選ぶのは品質優先の判断として妥当

### session resume と worktree

takt の自動 worktree（task の `worktree: true`）では **step 間のセッション resume が無効化される**（実行 cwd がプロジェクト cwd と異なるため。ディレクトリ間汚染の防止ガード）。この場合、同一 persona の step 再訪（review⇄implement ループの implement 再訪など）でも毎回新規セッションになり、リポジトリ再探索コストがかかる。

回避策: **手動で worktree を作り、その中で `takt add` → `takt run`（task の `worktree` 指定を省略 = カレントディレクトリ実行）** にすると `cwd === projectCwd` となり resume が有効化される。リポジトリの worktree ポリシーも手動 worktree で満たせる。ただし auto-commit / push / auto_pr は worktree 実行時のフローなので、カレント実行では commit・PR 作成を手動（`commit-convention` / `pr` スキル）で行うこと。

### 計測との突き合わせ

改善の効果は usage JSONL（下記）の `phase3_*` イベントの有無と step × provider 別トークンで確認する。lite の想定は「全 step codex・`phase3_*` イベントなし・Phase 2 なし」。

## skill 編集と takt の関係

`.claude/skills/**` を含む `.claude/` 配下は Claude Code の **protected paths**（`acceptEdits` モードでも write 時に必ず prompt が出る領域）に該当する。takt は Claude Agent SDK を `settingSources: ['project']` + `permissionMode: 'acceptEdits'` で呼ぶため prompt に答える人間がおらず、**Claude provider が走る persona から** `.claude/skills/<name>/SKILL.md` 等への Edit/Write は `Claude requested permissions to write to ..., but you haven't granted it yet.` で deny される（`permissions.allow` ルールでは bypass 不可、`bypassPermissions` のみが bypass）。

ただし、**実装を担う `coder` persona を codex provider にしている（グローバル設定から継承）ため**、実装ファイルへの編集は Codex CLI 経由で行われ Claude Code の protected paths 制約を回避できる（Codex は独自のサンドボックスで動作し、`$REPO_ROOT/.agents/skills` を探索パスに含む）。レビュー系 persona は opus（Claude）だが書き込みは行わないため影響しない。そのため、**skill 配下を変更する issue も takt から問題なく回せる**。実際の運用例として、`.claude/skills/videoup/references/generate_videos.sh` 等の skill 配下スクリプト修正も takt 経由で完走実績がある。

逆に `coder` を Claude provider に戻している環境では、従来通り skill 配下の Edit が deny される。その場合は通常の Claude Code 対話セッション（cmux pane 等）で直接編集し、コミット・PR 作成は `commit-convention` / `pr` スキル経由で実施する。

## Codex 共用時の skill 表記読み替え

`.claude/skills/**` は Claude Code / Codex CLI 共用だが、既存 SKILL.md には Claude Code 固有表現が残る。Codex で実行するときは、`AskUserQuestion` は通常のユーザー確認、`Read ツール` は画像/ファイル閲覧手段、`Bash ツール run_in_background=true` は長時間コマンドを非同期 session で起動して進捗を poll、`TodoWrite` は Codex の plan/checklist 更新として読み替える。これらの表記が残っていても実装不整合とは扱わず、同等の Codex 機能で実行する。

## リリース

`/automation-release` スキルで Release PR パターンを自動化（prepare → リリース PR → publish の 2 フェーズ）。post-release の運営者向けガイドと下流追従 issue は `/release-notes` が担当。
