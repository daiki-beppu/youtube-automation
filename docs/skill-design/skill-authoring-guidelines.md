# スキル記述規約

- **Status**: Accepted
- **Date**: 2026-07-26（2026-07-05 の「Sonnet-safe スキル記述規約」を全面改訂）
- **背景**: 旧版は Sonnet 級の実行者を想定し、「判断の余地を残さず、完了条件を機械検証可能にする」ことを最優先に 7 ルールを定めていた。Claude 5 世代ではこの前提が逆転する。重複した指示・自明な手順・ハーネスが既に保証している事項を書き並べると、実行者はそれらの突き合わせに思考を費やし、かえって精度が落ちる。本規約は「何を書かないか」を含めて定義し直したものである。

## 適用方針

- **既存スキルの一括改修を本規約で要求しない。** 新規作成時、および既存スキルの改訂時に、そのスキルに対してのみ適用する。
- SKILL.md は**軽量なガイド**である。実行者が文脈から導けることは書かない。書くのは、実行者がこのリポジトリを読んでも分からない**落とし穴**と、外部世界の制約に由来する**不可逆性**だけ。
- 各ルールにはリポジトリ内の**実在する良い実例**を添える。改訂時はまず実例を読み、その形に寄せる。

## 設計原則

| 原則 | 意味 |
|---|---|
| 不可逆・外部反映は承認を挟む | 削除・アップロード・外部投稿・課金は、モデルの能力とは無関係にユーザーの決定事項 |
| 落とし穴だけを書く | 一般的な作法・ハーネスの保証・自明な手順は書かない（後述「書かないこと」） |
| 段階的開示 | SKILL.md 本体は入口。詳細・ロジック・長い表は `references/` へ置き、必要になった時点で読ませる |
| 例より引数 | 呼び出し例を並べる前に、CLI / スクリプトの引数自体を読んで分かる形にする。例は実行者の探索範囲を例の形へ狭める |
| spec は検証可能な形で置く | スクリプト・rubric・テストが spec になるなら、散文へ書き直さず参照する |

---

## 必ず守る 3 点

この 3 点は実行者の判断力の問題ではなく、外部世界（取消不可能性・前提の不在・配布先のファイル構成）に由来する。判断に委ねてはならない。

### 1. 不可逆 / 外部反映操作の承認ゲート

削除・アップロード・外部投稿・課金を伴う API 呼び出しは、実行前に人間の承認を挟む。

1. 実行内容（対象・件数・容量・費用など）を**表示**する
2. `AskUserQuestion` で**明示 2 択**（実行 / 中止）を提示する
3. 取消不可であること（`rm` は復元不可、投稿は外部公開される等）を**警告**として添える
4. 承認されるまで実行しない

- **悪い例**: 「確認のうえ削除する」とだけ書き、確認手段も承認前の停止も明記しない。
- **良い実例**: [.claude/skills/live-clean/SKILL.md](../../.claude/skills/live-clean/SKILL.md) — 削除対象一覧を表示後に `AskUserQuestion` で確認し、承認まで削除しない（直後の Step で `rm -f` に限定）。

### 2. 前提の存在ガード

前工程の成果物（config / 認証 / 中間ファイル）が無いまま進むと、途中で不整合な状態を作る。冒頭で前提の存在と妥当性を確認し、満たさなければ**前工程スキルを案内して停止**する。後続 Step で解消できる項目は「許容する fail」として切り分ける。

- **良い実例**: [.claude/skills/channel-new/SKILL.md](../../.claude/skills/channel-new/SKILL.md) — 停止すべき fail と、後続 Step で解消するため許容する fail を分離している。

### 3. 配布先で解決できる参照だけを書く

`.claude/skills/` は wheel に同梱され `yt-skills sync` で下流チャンネルリポジトリへ配布されるが、**`docs/skill-design/` は配布されない**（同梱対象は `pyproject.toml` の `[tool.hatch.build.targets.wheel.force-include]` が正。`docs/` からは `workflow-cheatsheet.md` と `features.md` のみ）。

- SKILL.md から参照してよいのは、同じスキルの `references/`、他スキルの `references/`、配布対象の docs に限る。書き手向けの規約（本ファイルを含む）へは SKILL.md からリンクしない。
- 私有リポジトリのパスや未接続機能は、手順の地の文に混ぜない。`Status` 等のメタ情報として「未接続 / 試験導入」と隔離するか、前提ガード（2）で「無ければ停止」に変換する。
- **良い実例**: [docs/skill-design/ADR-001-thumbnail-prompt-schema.md](ADR-001-thumbnail-prompt-schema.md) — `Status: Accepted (試験導入のみ・実本番フローは未接続)` と隔離し、手順本文で「本番で使える」と誤認させない。

---

## 書かないこと

以下は実行者が文脈から判断できるか、ハーネスが既に保証している。書けばトークンを消費し、他の指示と衝突して判断を鈍らせる。

| 書かない | 理由 |
|---|---|
| `run_in_background=true` の強制、`sleep` / `until` ポーリングの禁止 | Claude Code は background 実行の完了時に自動で再呼び出しする。所要時間の目安だけ書けば実行者が判断できる |
| 「必ず Read で開く」「記憶から推測しない」 | 設定値が必要なら実行者は読む。**どのファイルがどう合成されるか**（`config.default.yaml` + `config/skills/<skill>.yaml` の deep-merge）だけが書く価値のある情報 |
| 一般的なツール作法（ファイル編集前に読む、パスを確認する等） | ハーネスとシステムプロンプトが保証する |
| 同一内容の再掲・強調のための反復 | 1 箇所に書く。重要度は配置順で表す |
| 手順内で自明な中間ステップの逐次指示 | 目的と完了条件を書けば経路は実行者が決められる |
| CLI フラグの意味・全オプションの列挙 | `argparse` の `help=` と `--help` が正。SKILL.md へ写すと両方を更新する必要が生まれ、片方が必ず腐る |
| 同じコマンドの網羅的な呼び出し例 | 代表 1 本で足りる。バリエーションは `choices=` と `--help` から実行者が組み立てる |

**例外**: 直感に反する事実は書く。「`--plan` は upload API を叩かないが予約日時計算のため read API を呼ぶ」のような、実行者が推測すると間違える挙動は落とし穴であり、書く価値がある。

## 判断を委ねる / 委ねない

- **外部仕様に基づく数値は書く** — YouTube タイトルの 100 codepoint 上限、サムネの 320px 視認性、`exit 0` の合否。これらは実行者が知り得ない事実。
- **質的な判断は委ねる** — 「タイトルが他と被らないか」「概要欄が魅力的か」のような判断に、恣意的な閾値を発明して縛らない。ただし**機械チェックが既に存在するなら**その閾値を正として書く（例: `references/check_lyric_duplication.py` の連続一致判定）。
- 「適切に」「必要なら」が曖昧に見えるときは、数値へ置換するより先に**そもそもその指示が必要か**を問う。不要なら削る。

## インターフェース設計

### description（スキル選択の API）

実行者はまず `description` だけを見てスキルを選ぶ。ここが唯一の選択インターフェースなので、**発動条件と否定条件の両方**を書く。

- 標準型: 用途 + 発動キーワード + `〜の場合は /<sibling> を使う`。棲み分けは双方向に書く（A→B と B→A の両方）。
- frontmatter の記法規約（`description:` の double-quote 等）は `CLAUDE.md`「### skill frontmatter」を正とし、ここでは再掲しない。検証は `uv run yt-skills lint`。
- **良い実例**: [.claude/skills/short/SKILL.md](../../.claude/skills/short/SKILL.md) と [.claude/skills/short-release/SKILL.md](../../.claude/skills/short-release/SKILL.md) — collection 型 / release 型を互いに否定トリガーで排他している。

### 前後工程

スキル間の依存関係を散文から分離し、`rg` で機械抽出できるようにする。frontmatter の直後に置き、依存がなくても省略しない。

```markdown
## 前後工程

- `前工程`: `/analytics-collect`
- `後工程`: `/collection-ideate`, `/analytics-report`, `/flop-analysis`
```

依存がなければ `` `なし` ``、`setup` / `channel-new` のような全体共通基盤だけは `` `*`（共通基盤としてほぼ全スキル） `` と書く。実行手順内で前提未達時に前工程を案内する記述は残してよいが、依存関係の一覧はこのブロックを正とする。

- 抽出: ``rg -n '^- `前工程`:|^- `後工程`:' .claude/skills/*/SKILL.md`` で各 SKILL.md から 2 行ずつ取得できること。

### 実行系のインターフェース（CLI / スクリプト）

呼び出し例を並べる前に、**引数そのものを読んで意図が分かる形**にする。取りうる値・既定値・`--dry-run` の有無は、それ自体が使い方の指示として働く。

- **列挙で意図を閉じる**: `--engine veo|omni`（[commands/media/generate_loop_video.py](../../src/youtube_automation/commands/media/generate_loop_video.py)）、`--existing ask|update|skip`（[commands/youtube/captions_upload.py](../../src/youtube_automation/commands/youtube/captions_upload.py)）のように `choices=` で値域を閉じれば、散文で選択肢を説明する必要が消える。
- **例を足したくなったら引数が曖昧なサイン**。SKILL.md に呼び出し例を増やす前に、引数名・`choices`・`help=` を直せないかを先に見る。手順書側の記述量は、インターフェースの設計不足の指標として読む。
- SKILL.md に残すのは「どのコマンドをどの順で呼ぶか」まで。各フラグの意味は `--help` を単一ソースとし、二重に書かない。

## spec を置く形

「どう作るか」を散文で説明する前に、**検証できる形で置けないか**を見る。実行者は検証可能な spec のほうを確実に守れる。

| 形 | 使いどころ | 実例 |
|---|---|---|
| スクリプト | 合否を機械判定できる | [suno-lyric/references/check_lyric_duplication.py](../../.claude/skills/suno-lyric/references/check_lyric_duplication.py) — 連続一致で歌詞重複を判定 |
| rubric | 質的判断だが評価観点は固定したい | [comments-reply/references/review-rubric.md](../../.claude/skills/comments-reply/references/review-rubric.md) — reviewer の入力境界と必須フィールドを規定 |
| checklist | 人間が完了を確認する不可逆手順 | [automation-release/references/publish-checklist.md](../../.claude/skills/automation-release/references/publish-checklist.md) |
| テスト | 契約が壊れたら CI で落としたい | `tests/test_*_skill_contract.py` |

- 同じ制約を散文と spec の両方に書かない。spec があるなら SKILL.md には**いつ回すか**だけを書く。
- 質的な判断を縛りたくなったら、閾値を発明する前に rubric を置けないかを検討する（前節「判断を委ねる / 委ねない」と対になる）。

## 段階的開示

SKILL.md が長くなったら、実行者が毎回全文を読む状態を避けて分割する。

- **本体に残す**: 完了条件、承認が要る操作、モード判定などの分岐、実行するコマンド行。
- **`references/` へ移す**: 生成・検証ロジック、長い語彙リストや対照表、プロンプトテンプレート、トラブルシュート事例。
- 同じロジックを複数スキルで使う場合は 1 ファイルを共有し、本文からは呼び出すだけにする（例: `.claude/skills/thumbnail/references/codex-prompt.py` を `collection-ideate` からも利用）。
- 完了条件と承認が要る操作は、対応する手順より**前**に書く。行数で位置を規定はしない。

---

## 参照

- 実例元: `.claude/skills/<skill>/SKILL.md`
- subagent へ実作業を委譲する skill: [subagent 委譲オーケストレーション規約](subagent-orchestration.md)
- 関連 ADR: [ADR-001 thumbnail prompt schema](ADR-001-thumbnail-prompt-schema.md)
