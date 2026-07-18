# Sonnet-safe スキル記述規約

- **Status**: Accepted
- **Date**: 2026-07-05
- **背景**: `.claude/skills/` 全 47 スキルの Sonnet-safe 監査（2026-07-05、42 findings → 12 有効）で見つかった問題の大半は、少数の同型パターンの反復だった。強いモデルなら文脈から補完できてしまう曖昧さが、Sonnet 級の実行者では誤動作（破壊的操作の無承認実行、前提未達での続行、解決不能な参照の追跡）に化ける。本規約はその再発防止として、SKILL.md を書くときの 7 ルールを定める。

## 適用方針

- **既存スキルの一括改修を本規約で要求しない。** 新規スキルの作成時、および既存スキルの改訂時に、そのスキルに対してのみ適用する。網羅スイープは別 issue 群（sonnet-safe issue 群 / #1489〜#1493）が担う。
- 規約の狙いは「Sonnet 級の実行者でも安全に実行できる SKILL.md」。判断の余地を残さず、完了条件を機械検証可能にすることを最優先する。
- 各ルールには、リポジトリ内の**実在する良い実例**を file:line で添える。改訂時はまず実例を読み、その形に寄せる。

## ルール早見表（Hard Gates）

新規作成・改訂時、以下 7 点を満たさない SKILL.md はマージしない。

| # | ルール | 一言で |
|---|--------|--------|
| ① | 発動キーワードの相互排他・否定トリガー | 兄弟スキルとの棲み分けを `description` に書く |
| ② | 外部反映 / 破壊的操作の承認ゲート標準型 | PASS/FAIL 条件 + AskUserQuestion 明示 2 択 + 取消不可警告 |
| ③ | 前提ファイルの存在ガード標準型 | 確認 → なければ前工程を案内して停止 |
| ④ | 判断基準なき判断要求の禁止 | 「適切に」「必要なら」を数値・具体条件に置換 |
| ⑤ | 同一ロジックの散文重複禁止 | 検証・生成ロジックは `references/` へ単一ソース化 |
| ⑥ | 完了条件・Hard Gates は冒頭に | ファイル冒頭 60 行以内に配置 |
| ⑦ | 解決できない参照の地の文配置禁止 | 私有リポジトリ・未接続機能を実行手順に混ぜない |

> この規約自身もルール⑥に従い、適用方針と早見表を冒頭に置いている。

---

## 前後工程表記の統一書式

- **狙い**: スキル間の依存関係を散文から分離し、`rg` で全スキルを機械抽出・比較できるようにする。
- **配置**: frontmatter の直後に `## 前後工程` を置く。前工程・後工程がない独立スキルも省略しない。
- **標準型**: 次の 2 行だけを使い、実在するスキル名を `/skill-name` 形式の inline code で列挙する。依存がなければ `` `なし` ``、`setup` / `channel-new` のような全体共通基盤だけは `` `*`（共通基盤としてほぼ全スキル） `` と書く。

```markdown
## 前後工程

- `前工程`: `/analytics-collect`
- `後工程`: `/collection-ideate`, `/analytics-report`, `/flop-analysis`
```

- **禁止する旧表記**: 依存関係の正データを `前工程は /xxx`、`**前工程:** /xxx`、`次工程は /xxx`、行頭の `→ /xxx`、`Cross References` の `→ 前工程:` / `→ 後工程:` だけで表現しない。実行手順内で前提未達時に前工程を案内する記述や、完了後の具体的な次アクションは残してよいが、依存関係の一覧は必ず統一ブロックを正とする。
- **抽出**: `rg -n '^- `前工程`:|^- `後工程`:' .claude/skills/*/SKILL.md` で、各 SKILL.md から必ず 2 行ずつ取得できることを確認する。
- **良い実例**:
  - [.claude/skills/analytics-analyze/SKILL.md](.claude/skills/analytics-analyze/SKILL.md) — 単一の前工程と複数の後工程
  - [.claude/skills/streaming/SKILL.md](.claude/skills/streaming/SKILL.md) — 前後工程を持たない独立スキル

## ① 発動キーワードの兄弟スキル間相互排他・否定トリガー

- **狙い**: 発動語が兄弟スキルと被ると、実行者は誤ったスキルを起動する。`description` に「このスキルを使わない条件」と「代わりに使う兄弟スキル」を否定トリガーとして書き、相互排他を成立させる。
- **標準型**: `description` の末尾に `〜の場合は /<sibling> を使う` を 1 文添える。棲み分けは双方向に書く（A→B と B→A の両方）。
- **悪い例**: `description: "ショートを生成する。「ショート」で発動"` のみ。collection 型 / release 型のどちらでも発動してしまう。
- **良い実例**:
  - [.claude/skills/short/SKILL.md:3](.claude/skills/short/SKILL.md:3) — `「ショート作って」「shorts」「BGM 切り抜き」で発動。release 型は /short-release`
  - [.claude/skills/short-release/SKILL.md:3](.claude/skills/short-release/SKILL.md:3) — `collection 型は /short`（逆方向の棲み分け）
  - [.claude/skills/lyria/SKILL.md:3](.claude/skills/lyria/SKILL.md:3) — `Suno 人手生成チャンネルは /suno を使う`

## ② 外部反映 / 破壊的操作の承認ゲート標準型

- **狙い**: 削除・アップロード・外部投稿など取消不可 / 外部反映を伴う操作は、実行前に必ず人間の承認を挟む。Sonnet 級の実行者が「良かれと思って」先行実行する事故を防ぐ。
- **標準型**:
  1. 実行内容（対象・件数・容量など）を PASS/FAIL 条件付きで**表示**する。
  2. `AskUserQuestion` で**明示 2 択**（実行 / 中止）を提示する。
  3. 取消不可であること（`rm` は復元不可、投稿は外部公開される等）を**警告文**として添える。
  4. 承認されるまで操作を実行しない。
- **悪い例**: 「確認のうえ削除する」とだけ書き、確認手段（AskUserQuestion）も承認前の停止も明記しない。
- **良い実例**:
  - [.claude/skills/live-clean/SKILL.md:84](.claude/skills/live-clean/SKILL.md:84) — 削除対象一覧を表示後、`AskUserQuestion でユーザーに確認を取る。承認されるまで絶対に削除を実行しない。`（直後の Step 4 で `rm -f` に限定、`rm -rf` を明示禁止）

## ③ 前提ファイルの存在ガード標準型

- **狙い**: 前工程の成果物（config / 認証 / 中間ファイル）が無いまま進むと、途中で不整合な状態を作る。冒頭で前提の**存在と妥当性**を確認し、満たさなければ前工程スキルを案内して**停止**する。
- **標準型**: 「前提を確認 → 満たさなければ前工程（`/setup` 等）を案内して停止 → 満たすまで後続 Step へ進まない」。config 生成で後から解消できる項目は「許容する fail」として明示的に切り分ける。
- **悪い例**: 前提ファイルの存在を仮定して手順を書き、無い場合の分岐を書かない。
- **良い実例**:
  - [.claude/skills/channel-new/SKILL.md:111](.claude/skills/channel-new/SKILL.md:111) — `以下の check が ok でない場合は、ここで /setup を案内して停止する`。さらに :131 以降で「後続 Step で解消するため許容する fail」を分離しており、停止すべき fail と許容する fail を混同しない好例。
  - [.claude/skills/suno-lyric/SKILL.md:56](.claude/skills/suno-lyric/SKILL.md:56) — `## Hard Gates` で「`suno-patterns.yaml` が無い場合は停止し、先に `/suno` の pattern draft を作るよう案内する」。

## ④ 「適切に」「必要なら」等の判断基準なき判断要求の禁止

- **狙い**: 「適切に」「必要なら」「いい感じに」は、実行者ごとに解釈がぶれる。判断を求めるなら**数値・具体条件・機械的な合否ライン**を与える。
- **標準型**: 曖昧な副詞を、閾値（`N 語以上`）・解像度（`320px`）・exit code（`exit 0`）などの検証可能な基準に置換する。
- **悪い例**: 「タイトルは他と被らないよう適切に付ける」。「被らない」の線引きが無い。
- **良い実例**:
  - [.claude/skills/suno/SKILL.md:148](.claude/skills/suno/SKILL.md:148) — `他コレクションのタイトルと 3 単語以上の連続一致がないこと`
  - [.claude/skills/suno-lyric/SKILL.md:117](.claude/skills/suno-lyric/SKILL.md:117) — `名言原文と連続 5 語以上一致させない`
  - [.claude/skills/thumbnail/SKILL.md:303](.claude/skills/thumbnail/SKILL.md:303) — `320px 視認性検証`（縮小時の可読性を具体解像度で規定）

## ⑤ 同一ロジックの散文重複禁止（`references/` への単一ソース化）

- **狙い**: 検証・生成ロジックを SKILL.md 本文に散文で書くと、改訂時に片方だけ直して不整合になる。ロジックは `references/` 配下の単一スクリプト / ファイルに寄せ、本文からは**呼び出すだけ**にする。
- **標準型**: `python .claude/skills/<skill>/references/<script>.py <args>` の形で委譲し、本文には手順とその実行行だけを残す。同じ規則を複数スキルで使う場合も 1 スクリプトを共有する。
- **悪い例**: 重複判定の閾値やアルゴリズムを本文の箇条書きとスクリプトの両方に書き、後で片方だけ更新する。
- **良い実例**:
  - [.claude/skills/suno-lyric/SKILL.md:122](.claude/skills/suno-lyric/SKILL.md:122) — 曲間重複の判定は `references/check_lyric_duplication.py` に集約し、本文は `機械チェックを実行して exit 0 を確認する` と実行行のみ（宣言は :69 の References セクション）。
  - [.claude/skills/collection-ideate/SKILL.md:290](.claude/skills/collection-ideate/SKILL.md:290) — プロンプト生成を `.claude/skills/thumbnail/references/codex-prompt.py` に委譲し、複数スキルから同一スクリプトを共有。

## ⑥ 完了条件・Hard Gates は冒頭 60 行以内に配置

- **狙い**: 実行者はファイルを上から読む。成功条件・絶対制約を後方に置くと、前提を知らないまま手順を実行し始める。完了条件と Hard Gates は**冒頭 60 行以内**（frontmatter 直後〜最初のセクション付近）で宣言する。
- **標準型**: frontmatter の直後に `## Hard Gates` / `## 完了条件` / `### 前提条件チェック（hard gate）` を置き、そこで「停止条件」「成功の定義」を先出しする。
- **悪い例**: 完了条件を最終セクション（150 行目以降）に書く。手順を実行し終えるまで成功基準がわからない。
- **良い実例**:
  - [.claude/skills/suno-lyric/SKILL.md:56](.claude/skills/suno-lyric/SKILL.md:56) — `## Hard Gates` を 56 行目（冒頭 60 行以内）に配置し、停止条件 3 点を先出し。
  - [.claude/skills/suno/SKILL.md:43](.claude/skills/suno/SKILL.md:43) — `### 前提条件チェック（hard gate）` を冒頭付近に置き、`AI は genre_line を手書きしてはならない` を先に宣言。

## ⑦ 実行者が解決できない参照（私有リポジトリ・未接続機能）の地の文配置禁止

- **狙い**: 実行者（自動化エージェント）がアクセスできない私有リポジトリのパスや、まだ本番接続されていない機能を、実行手順の地の文に「実行可能なもの」として書くと、実行者はそれを追跡しようとして詰まる。
- **標準型**: そうした参照は (a) 前提ガード（ルール③）で「無ければ前工程を案内して停止」に変換する、または (b) `Status` などの**メタ情報として「未接続 / 試験導入」と隔離**し、手順本文では前提にしない。未マージの計画資料は「あれば参照、無ければ本 issue の要件のみで実装可能」とフォールバックを添える。
- **悪い例**: SKILL.md の手順に「`plans/xxx.md` の設計に従って実装する」とだけ書く（その資料が未マージ / 私有だと実行者は解決できない）。
- **良い実例**:
  - [docs/skill-design/ADR-001-thumbnail-prompt-schema.md:3](docs/skill-design/ADR-001-thumbnail-prompt-schema.md:3) — `Status: Accepted (試験導入のみ・実本番フローは未接続)`。未接続であることを Status メタに隔離し、手順本文で「本番で使える」と誤認させない。
  - [.claude/skills/channel-new/SKILL.md:140](.claude/skills/channel-new/SKILL.md:140) — `seed fetch は YouTube Data API 認証に依存するため、既存チャンネルの token コピーで代替しない`。実行者が横取りで解決できない前提を、明示的に「代替不可」と地の文で封じている。

---

## 参照

- 監査対象 / 実例元: `.claude/skills/<skill>/SKILL.md`
- subagent へ実作業を委譲する skill: [subagent 委譲オーケストレーション規約](subagent-orchestration.md)
- 関連 ADR: [docs/skill-design/ADR-001-thumbnail-prompt-schema.md](docs/skill-design/ADR-001-thumbnail-prompt-schema.md)
- frontmatter 記法（`description:` の double-quoted string 規約）: `CLAUDE.md` の「### skill frontmatter」小節
