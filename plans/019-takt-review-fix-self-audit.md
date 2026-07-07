# Plan 019: takt-review の fix 工程を「レビュアーと同じ視点の自己監査つき」に再設計する

> **Executor instructions**: このプランをステップ順に実行すること。各ステップ末尾の
> 検証コマンドを実行し、期待結果を確認してから次へ進む。「STOP conditions」に該当したら
> 即座に停止して報告する。完了したら `<automation-repo>/plans/README.md` の本プランの
> Status 行を更新する。
>
> **⚠ 作業対象リポジトリは dotfiles**: 編集対象は
> `~/01-dev/dotfiles/config/.claude/skills/takt-review/SKILL.md` の 1 ファイルのみ。
> `~/.claude/skills/takt-review` は dotfiles への symlink。
>
> **Drift check (run first)**:
> `cd ~/01-dev/dotfiles && git diff --stat 9a030ff..HEAD -- config/.claude/skills/takt-review/SKILL.md`
> 差分があれば「Current state」の抜粋と実ファイルを突き合わせ、不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW（プロンプト資産のみの変更。コードには触れない）
- **Depends on**: none（018 と独立）
- **Category**: dx
- **Planned at**: dotfiles `9a030ff` / automation `bf68c73d`, 2026-07-06

## Why this matters

automation リポジトリの `.takt/runs/`（review-takt-default 237 run、2026-06-17〜07-06）の
全数解析で、fix → 再レビューの成績が定量化された:

- **REJECT → 再レビューのペア 126 件中 91% が再 REJECT**
- 再 REJECT のうち **前回指摘が未解消（persists）だったのは 14% のみ** — つまり fix は
  指摘そのものはほぼ解消できている
- 再 REJECT の **77% は「前回指摘と同じファイルへの新規指摘」** — fix が指摘行だけを
  なぞって直し、同じファイル・同じ契約の周辺をレビュアーと同じ視点で監査していない

構造的な非対称が原因: レビュアーは毎回「マージベースからの累積差分全体 + 関係箇所」を
再走査するのに対し、現行の fix 工程は `review-summary.md` の指摘のみを入力に、指摘箇所だけを
修正する。fix が生む新しい差分・summary に載らなかった個別レポートの WARNING / 改善提案が、
次ラウンドの「新規指摘」として同じファイルから湧き続ける。fix 工程の入力と自己検査の範囲を
レビュアーの走査範囲に揃えることで、1 回だけ許される再レビューの通過率を上げる。

## Current state

対象: `~/01-dev/dotfiles/config/.claude/skills/takt-review/SKILL.md`（229 行）。
関連する現行記述:

- **Step 4「fix（REJECT 時）」冒頭（L155-164）** — fix の入力が summary のみ:

  ```markdown
  ### 4. fix（REJECT 時）

  `review-summary.md` の指摘事項に基づき、**worktree 内で直接コードを修正** する。

  1. `review-summary.md` の全文を読む:

  ```bash
  RUN_SLUG=$(ls -t .takt/runs/ | head -1)
  cat .takt/runs/${RUN_SLUG}/reports/*review-summary.md
  ```
  ```

  実際の run の `reports/` には summary の他に 7 個別レポート
  （`architecture-review.md` / `security-review.md` / `qa-review.md` / `testing-review.md` /
  `ai-antipattern-review.md` / `pure-review.md` / `coding-review.md`）が存在するが、
  現行手順はこれらを読まない。summary は 7 レポートを表 1 行ずつに圧縮したもので、
  ブロッキングに至らなかった警告・改善提案の多くが落ちる。

- **L172-188** — 根本原因分解の指針（「レビュー文面をなぞった表面的な修正で終わらせない」
  「同型箇所を探す」等）は既にある。**足りないのは修正後の自己監査ゲート**で、現行手順は
  修正 → commit → push → PR コメント → 即再レビューと進む。

- **L198-218** — PR コメントのテンプレは「修正内容 / 根本原因・横展開 / 検証」の 3 見出しで、
  **finding_id 単位の解消根拠表がない**。レビュアー側（takt builtin の review policy）は
  persists / resolved の判定に「前回根拠 / 今回根拠（ファイル:行）」を要求するため、
  fix 側が finding_id ごとの解消根拠を提示しないと resolved 判定を取りこぼしやすい。

- **L222-229 Gotchas** — 「fix は 1 回のみ」「review ログは全文読まない（`tail -80`）。
  `review-summary.md` だけ全文読んでよい」という制約がある。7 個別レポートは各数 KB の
  Markdown であり、この token guard の趣旨（巨大 jsonl ログの抑制）とは別物。

- **レビュアー側の走査範囲**（参考・変更対象外）: takt builtin の review policy は
  「タスク開始時点（ベース）からの累積差分全体をレビューする。直前イテレーションの修正分だけを
  対象にしない」と定めている。また automation リポジトリには
  `.takt/facets/policies/pre-review-checklist.md`（提出前セルフ監査 8 項目 — 受入条件充足表 /
  挙動⇔テスト 1:1 / 実経路テスト / 兄弟入口貫通 / ドキュメント突き合わせ / 失敗を成功に
  見せない / 既存契約の退行禁止 / スコープ検査）が存在し、lite workflow の implement /
  review step が使っている。fix 工程はこれを参照していない。

dotfiles の規約: 日本語 Conventional Commits（例: `fix(skills): Codex 実行時の完了検知をブロッキング待機に統一`）。テストスイート・CI ゲートなし。

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Drift check | `cd ~/01-dev/dotfiles && git diff --stat 9a030ff..HEAD -- config/.claude/skills/takt-review/SKILL.md` | 差分なし、または抜粋と一致 |
| 構造検証 | `rg -c '解消根拠' config/.claude/skills/takt-review/SKILL.md` | 1 以上 |
| YAML frontmatter 検証 | `python3 -c "import yaml,pathlib; t=pathlib.Path('config/.claude/skills/takt-review/SKILL.md').read_text(); yaml.safe_load(t.split('---')[1])"` | エラーなし |

## Scope

**In scope**:
- `~/01-dev/dotfiles/config/.claude/skills/takt-review/SKILL.md` のみ

**Out of scope**（触らない）:
- takt 本体・builtin workflow / policy（`~/.bun/install/cache/takt@*` 配下）— 読み取り参照のみ
- automation リポジトリの `.takt/` 配下（`pre-review-checklist.md` を含む）— fix 工程から
  「存在すれば読む」参照先であり、本プランでは変更しない
- 「fix は 1 回のみ」のループ上限 — 変更しない（上限緩和はトークンコストと停止性の
  トレードオフでユーザー判断事項。本プランは 1 回の fix の質を上げる）
- takt-issue / issue / to-issues スキル（Plan 018 の担当）

## Git workflow

- リポジトリ: `~/01-dev/dotfiles`（ブランチを切る場合は `feat/takt-review-fix-self-audit`）
- コミット例: `feat(skills): takt-review の fix に累積差分の自己監査と解消根拠表を追加`
- push / PR はオペレーターの指示がない限り行わない

## Steps

### Step 1: fix の入力を 7 個別レポートまで拡張する

Step 4 の手順 1（L159-164 付近）を次の形に置き換える:

```markdown
1. `review-summary.md` の全文と、7 個別レポートの指摘部分を読む:

```bash
RUN_SLUG=$(ls -t .takt/runs/ | head -1)
cat .takt/runs/${RUN_SLUG}/reports/review-summary.md
# 個別レポート（各数 KB の Markdown。jsonl ログとは別物なので全文読んでよい）
cat .takt/runs/${RUN_SLUG}/reports/{architecture,security,qa,testing,ai-antipattern,pure,coding}-review.md
```

summary の指摘（new / persists）に加えて、個別レポートから次の 2 種を拾い、fix 対象リストに含める:

- **今回修正するファイルと同じファイルへの警告・非ブロッキング指摘** — 次ラウンドで
  新規指摘に昇格しやすい（実測: 再 REJECT の 77% が前回と同じファイルへの新規指摘）
- **改善提案のうち PR スコープ内で数分で対応できるもの** — スコープ外のものは対応せず、
  PR コメントで「対応しない理由」を 1 行ずつ明記する
```

ファイル名 glob は実際の reports/ の命名（`architecture-review.md` 等）に合わせること。
存在しないレポートがあっても続行してよい（`cat` の個別失敗は無視）。

**Verify**: `rg -n 'ai-antipattern,pure,coding' ~/01-dev/dotfiles/config/.claude/skills/takt-review/SKILL.md` → 1 箇所ヒット

### Step 2: 修正後・再レビュー前の自己監査ゲートを追加する

Step 4 の手順 2（修正の実行）と手順 3（コミット・push）の間に、新しい手順を挿入する:

```markdown
3. **自己監査（再レビュー前ゲート）**: レビュアーは「マージベースからの累積差分全体 +
   関係箇所」を毎回再走査する。fix した行だけでなく、自分の fix を含めた累積差分全体を
   レビュアーと同じ視点で監査してから再レビューに出す:

   ```bash
   # レビュアーが見るのと同じ差分を取る
   git diff $(git merge-base origin/main HEAD)..HEAD
   ```

   - リポジトリに `.takt/facets/policies/pre-review-checklist.md` が存在する場合は、
     その監査 8 項目（挙動⇔テスト 1:1、兄弟入口の貫通、ドキュメント突き合わせ等）を
     累積差分全体に対して照合する。存在しないリポジトリでは次の最低限 4 点を照合する:
     1. 変更した観測可能な挙動それぞれに対応するテストがあるか
     2. 変更した契約（データ形式・config キー・API）が同責務の全入口に貫通しているか
     3. 変更内容と矛盾するドキュメント・コメント・CHANGELOG の旧記述が残っていないか
     4. fix で追加した catch / fallback が失敗を握りつぶしていないか
   - fix によって未使用になったコード（import・引数・変数）が残っていないか累積差分を確認する
   - リポジトリのテスト・lint を全実行して green を確認する（コマンドはリポジトリの
     CLAUDE.md / package.json / pyproject.toml から特定する）
   - 自己監査で見つけた問題は、この時点で fix に含める（再レビュー後に直す機会はない）
```

以降の手順番号（コミット・push が 4、PR コメントが 5）を振り直す。

**Verify**: `rg -n '自己監査（再レビュー前ゲート）' ~/01-dev/dotfiles/config/.claude/skills/takt-review/SKILL.md` → 1 箇所ヒット

### Step 3: PR コメントに finding_id 単位の解消根拠表を追加する

PR コメントのテンプレ（現行 L201-217 の heredoc）を次の形に置き換える:

```markdown
```bash
gh pr comment "${PR_NUM}" --body "$(cat <<COMMENT
## 🔧 fix

### 指摘ごとの解消根拠
| finding_id | 原因 | 修正（ファイル:行 / commit） | 検証 |
|---|---|---|---|
| SUM-NEW-... | (根本原因 1 文) | \`path/to/file.ts:42\` | (追加・更新したテスト名 or 実行した確認) |

### 個別レポートの警告・改善提案への対応
- 対応済み: (同一ファイルの警告で fix に含めたもの)
- 対応しない: (改善提案のうちスコープ外としたもの — 理由を 1 行ずつ)

### 自己監査
- 累積差分（merge-base 起点）に対するチェックリスト照合: (結果)
- test / lint: (実行コマンドと結果)

再レビューを 1 回だけ実行します。
COMMENT
)"
```
```

狙い: レビュアー側の resolved / persists 判定は finding_id と「今回根拠（ファイル:行）」の
突き合わせで行われるため、fix 側が同じ形式で解消根拠を提示すると resolved 判定を
取りこぼしにくくなる。**表の finding_id は review-summary.md の表記をそのまま使うこと**
（`SUM-NEW-*` / `ARCH-*` / `PURE-*` などレビューごとに形式が異なるが、変換しない）。

**Verify**: `rg -n '指摘ごとの解消根拠' ~/01-dev/dotfiles/config/.claude/skills/takt-review/SKILL.md` → 1 箇所ヒット

### Step 4: Gotchas の token guard を実態に合わせて修正する

Gotchas の「**review ログは全文読まない**: `tail -80` で末尾のみ。`review-summary.md` だけ
全文読んでよい」の行を次に置き換える:

```markdown
- **review ログ（jsonl / trace.md）は全文読まない**: `tail -80` で末尾のみ。
  `reports/` 配下の Markdown（summary + 7 個別レポート）は各数 KB なので全文読んでよい
```

**Verify**: `rg -n 'summary \+ 7 個別レポート' ~/01-dev/dotfiles/config/.claude/skills/takt-review/SKILL.md` → 1 箇所ヒット

### Step 5: 整合確認とコミット

SKILL.md 全体を読み直し、手順番号の連番（Step 4 内の 1〜5）と、Step 3「判定 → fix」の
フロー図・Gotchas の記述が新手順と矛盾していないことを確認する。frontmatter の
`description:` は変更していないこと（発動条件を変えない）。

**Verify**:
- `python3 -c "import yaml,pathlib; t=pathlib.Path('config/.claude/skills/takt-review/SKILL.md').read_text(); yaml.safe_load(t.split('---')[1])"` → エラーなし
- `cd ~/01-dev/dotfiles && git status --short` → `config/.claude/skills/takt-review/SKILL.md` のみ変更

## Test plan

プロンプト資産のためテストスイートはない。各 Step の rg / python 検証が構造チェックを担う。
実地検証（推奨・本プランの完了条件には含めない）: 次に REJECT が出た PR で本スキルを起動し、
(1) fix 前に 7 個別レポートが読まれる、(2) 再レビュー前に累積差分の自己監査が走る、
(3) PR コメントに解消根拠表が載る、の 3 点を観測する。効果測定は
`.takt/runs/` の再レビュー verdict（本プラン適用後の fix → 再レビュー通過率が実測 9% から
改善するか）で行う。

## Done criteria

- [ ] `rg -c 'ai-antipattern,pure,coding' config/.claude/skills/takt-review/SKILL.md` = 1
- [ ] `rg -c '自己監査（再レビュー前ゲート）' config/.claude/skills/takt-review/SKILL.md` = 1
- [ ] `rg -c '指摘ごとの解消根拠' config/.claude/skills/takt-review/SKILL.md` = 1
- [ ] `rg -c 'summary \+ 7 個別レポート' config/.claude/skills/takt-review/SKILL.md` = 1
- [ ] frontmatter が有効な YAML のまま（Step 5 の python 検証が exit 0）
- [ ] 「fix は 1 回のみ」の記述が Step 3 / Gotchas に残っている（ループ上限は不変）:
      `rg -c 'fix は 1 回のみ' config/.claude/skills/takt-review/SKILL.md` ≥ 2
- [ ] `git status --short` で対象 1 ファイル以外に変更がない
- [ ] automation リポジトリの `plans/README.md` の 019 行を DONE に更新

## STOP conditions

以下の場合は停止して報告する:

- Drift check で Step 4（fix）節の現行文面が Current state の抜粋と一致しない
  （スキルが既に改訂されている）
- `~/.claude/skills/takt-review` が symlink ではなく実体ディレクトリになっている
- 変更の過程で「fix ループを複数回にする」「takt の builtin workflow を変える」必要が
  あると判断した場合（どちらも本プランのスコープ外 — ユーザー判断事項として報告する)

## Maintenance notes

- 本プランは「1 回の fix の質」を上げる施策。適用後 10〜20 件の fix → 再レビューで
  通過率（実測ベースライン 9%）が改善しなければ、次の一手は fix 側ではなく
  レビューの verdict 設計（重大度閾値）かループ上限の見直しで、それはユーザー判断事項
- automation リポジトリの `.takt/facets/policies/pre-review-checklist.md` の 8 項目が
  改訂されたら、Step 2 で挿入した fallback 4 点との乖離を確認すること
- レビュー時の注視点: Step 4 内の手順番号の振り直し漏れ、heredoc 内のバッククォート
  エスケープ（`\``）の崩れ
