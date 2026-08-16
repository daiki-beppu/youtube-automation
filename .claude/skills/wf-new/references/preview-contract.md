# Preview contract

Phase 4 の設定解決、候補の内容、コスト見積もり、生成後チェックはこのファイルを正とする。実行順、承認境界、実行コマンドは `../SKILL.md` に従う。

## Preview 設定

`config.default.yaml` と `config/skills/collection-ideate.yaml` を deep-merge し、`preview` を一度だけ解決する。

| key | 既定値 | 契約 |
|---|---:|---|
| `thumbnail_mode` | `parallel` | `parallel` は合意した候補を全枚生成、`sequential` はテキスト候補から選んだ1枚だけを生成する |
| `candidate_count` | `3` | テキスト候補数。`parallel` の生成枚数にも使い、`sequential` の生成枚数は常に1 |
| `skip_cost_confirm` | `false` | `false` は課金 call 前に `confirm_cost`、`true` は確認だけを省略して見積条件を記録する |
| `session_id_bytes` | `2` | preview session ID のランダム byte 数 |
| `stock_archive` | `true` | `parallel` で不採用画像を stock へ退避するかを決める |

`config/skills/thumbnail.yaml` も同じ deep-merge 規則で解決する。`candidate_count` を変えた場合は候補ラベル、生成回数、比較対象を同じ数にそろえる。既定値や生成枚数を暗黙に補正しない。

## 候補 schema

各候補は次をひとまとまりとして提示し、画像生成にも同じ prompt を使う。

- テーマ
- タイトル
- オブジェクト定義（名前とストーリーを含む）
- 本番用 thumbnail prompt 全文
- `ttp_mode: true` の場合は転写元、転写する構造・パターン・型、参照元が満たす欲求、企画の欲求整合根拠

Phase 4-1 の prompt は英語 1 段落、誇張表現禁止、16:9 構図、テキスト除外を共通の出力契約とし、`config/skills/thumbnail.yaml` の provider 設定を正とする。Gemini では `prompt_prefix`、`composition_rules`、`single_step.anatomy_clause`（キャラクターの手が写る場合）、`single_step.ip_safety_clause` を適用する。IP safety clause は署名、透かし、ロゴ、brand mark を除外し、clean corners を要求する。

Gemini の `generation_mode: single_step` は `diff_prompt_template` を prompt source とし、`object-design-examples.md` を参照する。`ttp_mode: false` のみ swappable slot で差別化し、`ttp_mode: true` は転写元から得た値だけを使う。それ以外の generation mode は Phase 4-1 のプロンプト全文をそのまま再利用し、生成時に再構築しない。

Codex provider では `image_generation.codex.default_prompt_template` と `thumbnail/references/codex-prompt.py` を正とし、タイトル引数には画像へ焼く見出しと短いサブタイトルだけを渡す。動画タイトル全文、composition rule、legend、楽器を重複注入しない。候補ごとに別の benchmark 参照画像を1枚割り当て、必要枚数に満たなければ生成せず停止する。TTP strict preview に stock 参照を混ぜない。

## コスト計算契約

生成前に mode から課金 call 数を確定する。`parallel` は `candidate_count` 枚、`sequential` は1枚で、各画像につき生成1 call。セルフチェックを実施する場合は各画像につき Vision check 1 call を別に数える。生成しない場合は画像系 call は0。

見積もりは解決済み provider、model / quality、画像サイズと `config/skills/thumbnail.yaml` の `cost_per_image_usd` を使う。Codex provider は GCP 課金なしとして表示する。単価未設定時は金額を推測せず「不明」と表示し、実コストは GCP Cloud Console の Billing を正とする。

`skip_cost_confirm: false` は見積もりを表示して `confirm_cost` の y/N を待つ。拒否時は画像生成を完全にスキップし、テキスト候補だけで続行する。`true` は確認を省略できるが、生成枚数、provider、model / quality、画像サイズ、単価または単価未設定、想定 call 数を実行ログと `20-documentation/plan_proposals.json` candidate へ保存する。保存失敗時は生成せず停止する。

例: 単価 `$0.101`、`parallel`、候補3件なら生成見積もりは `3 枚 × $0.101 = $0.303`。同じ候補数の `sequential` は `1 枚 × $0.101 = $0.101`。

## セルフチェック契約

`self_check.enabled` の既定値は `true`。生成後、ユーザー提示前に `yt-thumbnail-check --json` を実行する。`objects.fixed` と `no_logo_guard` を JSON の YES/NO checklist で検査し、終了コード0を全画像合格、1を1件以上不合格として扱う。

不合格時は `self_check.max_regeneration_attempts` が1以上なら該当候補だけを再生成し、0なら警告を表示してユーザー承認へ進む。`objects.fixed` が未定義なら `no_logo_guard` だけを検査する。`self_check.enabled: false` は check を省略する。調査時は `--print-prompt` で課金 call なしに prompt を確認でき、追加の `--check` で検査対象を絞れる。
