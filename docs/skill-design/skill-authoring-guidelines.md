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
| 目的で切る | skill の境界は `purpose:` で決める。出力先ディレクトリは境界の決定には使わず、検証に使う |
| 不可逆・外部反映は承認を挟む | 削除・アップロード・外部投稿・課金は、モデルの能力とは無関係にユーザーの決定事項 |
| 落とし穴だけを書く | 一般的な作法・ハーネスの保証・自明な手順は書かない（後述「書かないこと」） |
| 段階的開示 | SKILL.md 本体は入口。詳細・ロジック・長い表は `references/` へ置き、必要になった時点で読ませる |
| 例より引数 | 呼び出し例を並べる前に、CLI / スクリプトの引数自体を読んで分かる形にする。例は実行者の探索範囲を例の形へ狭める |
| spec は検証可能な形で置く | スクリプト・rubric・テストが spec になるなら、散文へ書き直さず参照する |

目的の宣言だけでは境界の正しさを機械検証できないため、成果物の writer を客観的な検算手段とする。同一の成果物ファイルを 2 つ以上の skill が書いている場合は、1 つの塊が誤って分かれている疑いが濃い。たとえば `suno-*.json` を `suno` / `suno-lyric` が書く状態が該当する。出力先が同じという理由だけで統合するのではなく、writer の重複をきっかけに目的と境界を見直す。

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
- **良い実例**: [publish clean mode](../../.claude/skills/publish/references/clean.md) — 削除対象一覧を表示後に `AskUserQuestion` で確認し、承認まで削除しない（直後の Step で `rm -f` に限定）。

### 2. 前提の存在ガード

前工程の成果物（config / 認証 / 中間ファイル）が無いまま進むと、途中で不整合な状態を作る。冒頭で前提の存在と妥当性を確認し、満たさなければ**前工程スキルを案内して停止**する。後続 Step で解消できる項目は「許容する fail」として切り分ける。

- **良い実例**: [.claude/skills/setup/SKILL.md](../../.claude/skills/setup/SKILL.md) — 停止すべき fail と、後続 Step で解消するため許容する fail を分離している。

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

### purpose（目的の宣言）

frontmatter の `purpose:` は必須であり、次の 7 語のいずれか 1 つを日本語のまま指定する。複数値や list は認めない。

| 値 | 意味 |
|---|---|
| `準備する` | 環境・認証・チャンネル設定・配布物を整える |
| `調べる` | 外（競合・市場・視聴者）を調査する |
| `決める` | チャンネルの意思・方向性を決める |
| `進める` | 制作フローを回す・状態を進める |
| `作る` | 音源・画像・動画などの成果物を生成する |
| `公開する` | YouTube・外部サービスへ反映する |
| `振り返る` | 数字・整合性を測り、次の判断材料にする |

目的が 2 つあるように見える skill も、「その skill を呼んだ直後に成果物を見て何を判断するか」で 1 つに決める。たとえば `/analytics` は数字を見るため `振り返る`、`/wf-new` は制作を進めるため `進める` とする。副次的な関係は既存の `## 前後工程` ブロックで表現し、`purpose:` は利用者がその skill を探すときに立っている場所 1 点だけを表す。

カタログは `準備する` → `調べる` → `決める` → `進める` → `作る` → `公開する` → `振り返る` の PDCA 順（準備 → Plan → Do → Check/Act）に並べる。7 語から phase は一意に導出できるため、frontmatter に `phase:` は持たず二重管理を避ける。

### mode・variant の表記

既存 skill と**目的**（利用者が何のために呼ぶか）を共有する新しい利用形態は、skill を新設する前に、既存 skill へ mode を追加できないかを先に検討する。完了条件が mode ごとに異なる場合は、それぞれの完了条件を `references/<flag>.md` に書く。完了条件の相違は skill を分ける理由にしない。目的が異なる場合の skill 新設は禁止しない。

新しい分岐は、次の優先順位で表現する。

| 順 | 手段 | 条件 |
|---:|---|---|
| 1 | 自動判定 | `config`、`workflow-state.json`、ファイルの実在から判定できる分岐。フラグを要求せず、自動判定を既定にする |
| 2 | 排他 mode | 利用者の意図でしか決まらない分岐。`--<flag>` 形式で表し、同時指定は 0〜1 個、1 skill あたり 5 個までとする |
| 3 | modifier | mode と直交する調整。`--<flag>` 形式で表し、複数指定を認め、個数の上限は設けない |

自動判定できる分岐をフラグ指定必須の設計にしない。mode は、通常の自動実行とは別に一段だけを明示実行するための上書き入口として置く。[analytics](../../.claude/skills/analytics/SKILL.md) は、フラグなしでは chain 全体を実行し、`--collect`、`--analyze`、`--report` では一段だけを実行する。[publish](../../.claude/skills/publish/SKILL.md) の `--upload` は、mode 選択後に `content_model.type` から内部経路を自動分岐する。

mode と modifier は次のように分けて記載する。

- mode は `## モード判定` 節の `| mode | 読む reference |` 表に載せる
- mode ごとの手順は skill ディレクトリからの相対パス `references/<flag>.md` に 1 mode 1 ファイルで置く。`<flag>` は `--` を除いたフラグ名と一致させ、複数 mode で共有しない
- SKILL.md 本体には mode 判定と全 mode 共通の前提・完了条件を残し、mode 固有の手順と完了条件は対応する reference を必要になった時点で読む
- modifier は `## 修飾フラグ` 節の別表に載せ、mode 表には載せない
- 両者とも `--` 前置を必須とし、`mode=<name>` 形式や bare word の名前を新規に導入しない。本リポジトリの skill は日本語の自然言語引数を取るため、bare word は通常の引数と衝突し、静的に判別できない
- 値を伴う variant も名前付き引数として表現する

- mode の実例: [analytics の `--collect`](../../.claude/skills/analytics/SKILL.md)
- modifier の実例: [publish の `--batch`](../../.claude/skills/publish/SKILL.md)（`--community` mode の生成方法を修飾）
- 値を伴う variant の実例: [analytics flop mode の `--since <N>`](../../.claude/skills/analytics/SKILL.md)

### description（スキル選択の API）

実行者はまず `description` だけを見てスキルを選ぶ。ここが唯一の選択インターフェースなので、**発動条件と否定条件の両方**を書く。

- skill が mode・variant を持つ場合は、対応する引数（`--batch`、`--since <N>` など）を `description` に列挙する。本文だけに記載してもスキル選択時には見えないため、本文を `description` の代わりにしない。
- 標準型: 用途 + 発動キーワード + `〜の場合は /<sibling> を使う`。棲み分けは双方向に書く（A→B と B→A の両方）。
- frontmatter の記法規約（`description:` の double-quote 等）は `CLAUDE.md`「### skill frontmatter」を正とし、ここでは再掲しない。検証は `uv run yt-skills lint`。
- **良い実例**: [.claude/skills/short/SKILL.md](../../.claude/skills/short/SKILL.md) — `content_model.type` から collection / release を自動分岐し、利用者に型の選択を求めない。

### 前後工程

スキル間の依存関係を散文から分離し、`rg` で機械抽出できるようにする。frontmatter の直後に置き、依存がなくても省略しない。

```markdown
## 前後工程

- `前工程`: `/analytics --collect`
- `後工程`: `/wf-new`, `/analytics --report`, `/analytics --flop`
- `委譲先`: `/wf-new`, `/publish`
```

`前工程` / `後工程` はユーザーが前後に実行する skill、`委譲先` は実行中に直接呼び出す skill を表し、両者を混同しない。委譲しない場合も `委譲先` 行を省略せず `` `なし` `` と書く。委譲深さは 1 以下とし、委譲先を持つ skill の委譲先がさらに別 skill へ委譲してはいけない。`uv run yt-skills lint` は深さ 2 以上を最長経路つきの違反として扱い、`uv run yt-skills delegation` は exit 0 の報告コマンドとして各 skill の深さ・最長経路と全体集計を表示する。

深さ 2 以上の構成が必要に見える場合は skill 間の多段委譲を増やさず、[chain-manifest-schema.md](chain-manifest-schema.md) の薄いインタープリタ方式へ寄せる。manifest は順序と委譲先だけを宣言し、状態判定と各工程のロジックは owning skill に残す。

前後工程の依存がなければ `` `なし` ``、`setup` のような全体共通基盤だけは `` `*`（共通基盤としてほぼ全スキル） `` と書く。実行手順内で前提未達時に前工程を案内する記述は残してよいが、依存関係の一覧はこのブロックを正とする。

- 抽出: ``rg -n '^- `前工程`:|^- `後工程`:|^- `委譲先`:' .claude/skills/*/SKILL.md`` で各 SKILL.md から 3 行ずつ取得できること。

### 成果物

skill が作成・更新するファイルと、処理の前提として読むファイルを機械抽出できるようにする。frontmatter 直後の宣言領域に `## 成果物` を置き、成果物がなくても省略しない。

```markdown
## 成果物

- `書き込む`: `collections/<id>/thumbnail.jpg`, `collections/<id>/main.png`
- `読み込む`: `config/channel/identity.json`, `collections/<id>/concept.md`
```

`書き込む` は skill が作成または更新するパス、`読み込む` は入力や判断材料として参照するパスを表す。対象がない側は `` `なし` `` と書く。collection 名や channel 名のように実行時に決まる部分は `<id>` / `<channel>` などの placeholder で表し、同じ論理成果物が skill 間で同じ文字列になるように揃える。

writer の重複は直ちに違反とは限らない。`uv run yt-skills artifacts` は `書き込む` だけを集計して writer 一覧と重複数を表示し、`--duplicates-only` では複数 skill が書くパスだけを表示する。どちらも設計判断の材料を報告するコマンドで、重複自体を lint エラーにはしない。`uv run yt-skills lint` は `## 成果物` と `書き込む` 行の欠落を拒否する。

### 実行系のインターフェース（CLI / スクリプト）

呼び出し例を並べる前に、**引数そのものを読んで意図が分かる形**にする。取りうる値・既定値・`--dry-run` の有無は、それ自体が使い方の指示として働く。

- **列挙で意図を閉じる**: `--engine veo|omni`（[commands/media/generate_loop_video.py](../../src/youtube_automation/commands/media/generate_loop_video.py)）、`--existing ask|update|skip`（[commands/youtube/captions_upload.py](../../src/youtube_automation/commands/youtube/captions_upload.py)）のように `choices=` で値域を閉じれば、散文で選択肢を説明する必要が消える。
- **例を足したくなったら引数が曖昧なサイン**。SKILL.md に呼び出し例を増やす前に、引数名・`choices`・`help=` を直せないかを先に見る。手順書側の記述量は、インターフェースの設計不足の指標として読む。
- SKILL.md に残すのは「どのコマンドをどの順で呼ぶか」まで。各フラグの意味は `--help` を単一ソースとし、二重に書かない。

## spec を置く形

「どう作るか」を散文で説明する前に、**検証できる形で置けないか**を見る。実行者は検証可能な spec のほうを確実に守れる。

| 形 | 使いどころ | 実例 |
|---|---|---|
| スクリプト | 合否を機械判定できる | [music/references/check_lyric_duplication.py](../../.claude/skills/music/references/check_lyric_duplication.py) — 連続一致で歌詞重複を判定 |
| rubric | 質的判断だが評価観点は固定したい | [reply/references/review-rubric.md](../../.claude/skills/reply/references/review-rubric.md) — reviewer の入力境界と必須フィールドを規定 |
| checklist | 人間が完了を確認する不可逆手順 | [automation-release/references/publish-checklist.md](../../.claude/skills/automation-release/references/publish-checklist.md) |
| テスト | 契約が壊れたら CI で落としたい | production-importing test は鏡像規則、repository-only 契約は `tests/repo/` |

- 同じ制約を散文と spec の両方に書かない。spec があるなら SKILL.md には**いつ回すか**だけを書く。
- 質的な判断を縛りたくなったら、閾値を発明する前に rubric を置けないかを検討する（前節「判断を委ねる / 委ねない」と対になる）。

## 段階的開示

SKILL.md が長くなったら、実行者が毎回全文を読む状態を避けて分割する。

- SKILL.md 本体が **250 行を超えたら**、詳細を `references/` へ切り出すことを検討する。250 行は規約上の目安であり、機械検証の対象にはしない。
- SKILL.md 本体は **400 行を超えてはならない**。400 行を超える場合は、必要になった時点で読む詳細を `references/` へ切り出す。機械検証は 400 行超をエラーにする 1 段だけとする。
- 行数には SKILL.md 本体だけを数え、`references/` 配下は含めない。`references/` は必要になった時点でだけ読まれ、スキルの呼び出しごとに全文を読む量には含まれないためである。
- **本体に残す**: 完了条件、承認が要る操作、モード判定などの分岐、実行するコマンド行。
- **`references/` へ移す**: 生成・検証ロジック、長い語彙リストや対照表、プロンプトテンプレート、トラブルシュート事例。
- 同じロジックを複数スキルで使う場合は 1 ファイルを共有し、本文からは呼び出すだけにする（例: `.claude/skills/thumbnail/references/codex-prompt.py` を `collection-ideate` からも利用）。
- 完了条件と承認が要る操作は、対応する手順より**前**に書く。行数で位置を規定はしない。

最後の規則は情報の**位置**を行数で固定しないという意味であり、本体の**総量**を行数で規定する 250 行・400 行の基準とは両立する。位置は行数で規定しないが、総量は行数で規定する。

---

## 参照

- 実例元: `.claude/skills/<skill>/SKILL.md`
- subagent へ実作業を委譲する skill: [subagent 委譲オーケストレーション規約](subagent-orchestration.md)
- 関連 ADR: [ADR-001 thumbnail prompt schema](ADR-001-thumbnail-prompt-schema.md)
