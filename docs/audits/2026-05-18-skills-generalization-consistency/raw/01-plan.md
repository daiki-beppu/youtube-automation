# Research Plan — Issue #353 スキル汎用化・整合性の棚卸し監査

実行日: 2026-05-18
担当ステップ: plan (1/4)
次ステップ: dig（調査実行）→ analyze（分析）→ supervise（最終整形）

---

## 1. 依頼の分解

### What（何を知りたいか）
`.claude/skills/` 配下 35 スキル（35 件確定: `ls .claude/skills/` で確認済み）に対して、以下 2 観点 × 計 8 項目を網羅的に棚卸しした監査レポート（`docs/audits/skills-audit-2026-05-18.md`）を生成する。

- 観点 1: 汎用化・設定ファイル切り出し（1.1 ハードコード値検出、1.2 重複スクリプト共通化、1.3 skill-specific config 余地、1.4 既存 config キーへの未参照）
- 観点 2: 整合性（2.1 description ↔ 実装乖離、2.2 バトン双方向リンク、2.3 deprecated 機能参照、2.4 形式揺れ）

### Why（なぜ知りたいか・推測）
- 35 スキルの蓄積で「ハードコード残り」「重複スクリプト」「片方向バトン」「v4.0.0 で撤去した short/community への残存参照」「書式揺れ」がノイズとして溜まっている疑い
- 配布パッケージ（`yt-skills sync` 経由で他チャンネル repo に展開）の品質ガバナンスとして、定期点検レポート 1 本にまとめたい
- 「修正は別 issue」と切り分けることで、レビュー対象が肥大化することを避けたい

### Scope（どこまで調べるべきか）
- **対象**: `.claude/skills/**/SKILL.md` および `.claude/skills/**/references/**`、加えて参照される `config/channel/*.json`（実体は `examples/channel_config.example/` をテンプレ参照）と当時の設定パッケージ
- **対象外**:
  - `.claude/skills/**` への書き込み（protected paths のため禁止、order.md 41 行制約）
  - 既存ファイルの修正、レポート以外のファイル新規作成
  - 修正の実装そのもの（あくまで「文章で提案」までに留める）
- **成果物**: `docs/audits/skills-audit-2026-05-18.md` 1 ファイル新規作成 + PR 化

### 仮定（暗黙の前提・明示化）
- 「ハードコードされたチャンネル固有値」とは、特定チャンネルのジャンル名・タグ・URL・しきい値 etc. を **コード or SKILL.md に直書き** している箇所を指す（`config/channel/*.json` 経由で外部化できる値）。
- 「バトン記述」とは SKILL.md 内の「前工程は /xxx」「次工程は /yyy」表現で、双方向リンクとして閉じているかを検証する。
- 「v4.0.0 で撤去」については `CLAUDE.md` の `workflow.json` 注記から `short / community` が撤去されたと判断（"v4.0.0 で short / community 撤去"）。他に deprecated 機能の手がかりは CHANGELOG / git log から拾う必要があるが、見つからなければ `short / community` のみを対象とする。
- レポート提出形式は order.md 32 行に従い「サマリー → 観点 1.1〜1.4 → 観点 2.1〜2.4 → 優先度付き fix リスト（high/medium/low）」の固定構造。

---

## 2. 調査項目の洗い出し

order.md の「並列調査のヒント」（Part A/B/C）に沿って 3 part 構成にする。dig step は Part を順に消化、または並列実行する。

### Part A: ハードコード値検出 & config 参照漏れ（観点 1.1 + 1.4）

| ID | 調査項目 | 期待アウトプット |
|----|---------|----------------|
| A-1 | 全 SKILL.md / references/ を走査し、ジャンル名・カテゴリ ID・URL・しきい値・タグ・チャンネル名・チャンネル ID 等の **直書きリテラル** を `file:line` で抽出 | 検出リスト（file:line + 抜粋 + 推奨移行先キー） |
| A-2 | `examples/channel_config.example/*.json` の全キーを列挙し、各キーに対して「該当値が直書きされている skill」を逆引きマッピング | キー→直書き skill の対応表 |
| A-3 | `examples/channel_config.example/` に存在しない値（しきい値・マジックナンバー）について、新規 config キー追加提案（推奨セクション: `audio.json` か `youtube.json` か `analytics.json` か） | 新規 config キー提案リスト |
| A-4 | 既知シード `streaming/SKILL.md` の `--check-threshold` が config 非連動である件の具体的位置特定 | file:line 確定 |
| A-5 | 既知シード `channel-new` / `channel-direction` の初期値 `"TBD"` の出現箇所と仕様書化されていない揺れの可視化 | file:line 列挙 + 統一案 |

### Part B: 重複スクリプト & skill-specific config 余地（観点 1.2 + 1.3）

| ID | 調査項目 | 期待アウトプット |
|----|---------|----------------|
| B-1 | 既知重複 3 種（`benchmark_collector.py` × 3, `generate_image.py` × 3, `fetch_benchmark_comments.py` × 2）の **実体パス特定** と内容差分の要約（フォーク具合）。共通化先候補は `src/youtube_automation/utils/` 配下のどのモジュールか | 重複マップ + 共通化先提案 |
| B-2 | 他にも重複している references/ スクリプト（同名・類似機能）の自動検出（ファイル名 hash + 拡張子別の出現数） | 追加重複候補リスト |
| B-3 | skill ごとに「`config/skills/<skill>.yaml` 等の skill-specific config を導入したほうがよい」候補を抽出（例: 閾値・テンプレート・プロンプトを SKILL.md 内に直書きしているケース） | 候補リスト（理由付き） |
| B-4 | 既存 `load_skill_config()` を使っているスキル・使っていないスキルの仕分け（`utils/config/` 内の関数定義から逆引き grep） | 使用 skill 一覧 vs. 未使用 skill 一覧 |

### Part C: 整合性 4 項目（観点 2.1〜2.4）

| ID | 調査項目 | 期待アウトプット |
|----|---------|----------------|
| C-1 | 全 SKILL.md の `description:` 冒頭文 と references/ の実装機能 を突合（description にあるが実装なし／実装にあるが description にない） | 乖離リスト |
| C-2 | バトン記述（「前工程」「次工程」「/xxx」）を全 SKILL.md から抽出し、対向 skill 側に対応する記述があるかを双方向検証。`postmortem` の曖昧バトンの具体化案を含める | バトン整合マトリクス + 修正案 |
| C-3 | v4.0.0 で撤去された `short` / `community` への参照、その他 deprecated（旧 channel_config.json、撤去済み機能）への参照を全文検索 | 残存参照リスト |
| C-4 | description のトリガー語形式（「Use when ...」構文 / 末尾「〜」体言止め）、ファイル構成（references/ / templates/ / scripts/）の揺れを集計 | 形式揺れ統計 + 統一案 |

---

## 3. データソース候補

| 調査項目 | 一次データソース | 二次・補助 |
|----------|-----------------|-----------|
| A-1, A-2 | `.claude/skills/**/SKILL.md`, `.claude/skills/**/references/**/*.{py,sh,md,yaml,json}` | `examples/channel_config.example/*.json`（正規キー）、当時の設定パッケージ（dataclass 定義） |
| A-3 | 抽出された未マッピング値 | `examples/channel_config.example/` 全文 |
| A-4 | `.claude/skills/streaming/SKILL.md` と `references/` | `infra/terraform/streaming/` （命名根拠） |
| A-5 | `.claude/skills/channel-new/`, `.claude/skills/channel-direction/` | `"TBD"` の grep 結果全件 |
| B-1, B-2 | `.claude/skills/**/references/**/*.py` の同名ファイル | `src/youtube_automation/utils/` 既存ユーティリティ群 |
| B-3, B-4 | SKILL.md 本文（直書きの閾値・テンプレ）+ 設定ローダーの `load_skill_config()` 参照箇所 | `config/skills/` ディレクトリ有無 |
| C-1 | SKILL.md `description:` フィールド | `references/` ファイル一覧と中身 |
| C-2 | SKILL.md 全文の「次工程」「前工程」「/skill-name」抽出 | バトン対象 skill の SKILL.md |
| C-3 | 全 skill 配下の `short` / `community` / `channel_config.json` （旧形式）の grep | `CLAUDE.md` の deprecate 注記 |
| C-4 | SKILL.md の YAML frontmatter / description 末尾文体 / ディレクトリ構造 | 任意 skill の「正規形」サンプル（最大公約数） |

---

## 4. 優先順位

| 優先度 | 定義 | 対象項目 |
|--------|------|---------|
| **P1: 必須**（これがないと回答できない） | レポート骨格の各 section 1.1〜2.4 を埋めるのに直接必要なデータ | **A-1, A-4, A-5, B-1, C-1, C-2, C-3** |
| **P2: 重要**（あると回答の質が上がる） | レポートの説得力・修正提案の具体性を高めるデータ | **A-2, A-3, B-3, B-4, C-4** |
| **P3: あれば良い**（時間があれば） | 既知シード以外の追加発見を狙う網羅探索 | **B-2** |

### dig step への指示まとめ（並列実行推奨）

- **Part A**（A-1〜A-5）: 単独 agent で grep ベース機械検出 + 抜粋。1.1 と 1.4 を担当
- **Part B**（B-1〜B-4）: 単独 agent でファイル名 hash 集計 + load_skill_config 利用調査。1.2 と 1.3 を担当
- **Part C**（C-1〜C-4）: 単独 agent で description ↔ 実装突合とバトン双方向検証。2.1〜2.4 を担当

各 part は **独立** に実行可能（Part A/B が触る対象は重なるが、観点は直交）。dig step は Part A/B/C を **並列 1 メッセージ 3 tool call** で実行することで遅延を圧縮できる。

### 出力ファイル（dig 用）

各 part の出力は次ステップ `analyze` がマージしやすいよう、以下の構造で `reports/dig-part-<A|B|C>.md` に保存することを推奨:

```
## 概要（数行）
## 検出結果（file:line + 抜粋 + 推奨アクション）
## カバレッジ（探した範囲・除外した範囲）
## 調査不可項目（あれば「調査不可」と明記、policy 準拠）
```

---

## 5. 制約・注意

- **`.claude/skills/**` への write 禁止**（order.md 41 行・CLAUDE.md「skill 編集は takt 経由で行わない」節と整合）。dig step は **Read / Grep / Glob のみ** 使う前提
- 修正提案は文章のみ。コードには触らない
- レポート以外のファイル新規作成・既存ファイル変更は禁止（出力は `docs/audits/skills-audit-2026-05-18.md` 1 ファイルのみ）
- 各検出は `file:line` 形式で出典明示（policy「出典明記」原則）
- 調査不可項目は「調査不可」と正直に報告（policy「正直な報告」原則）
- 80% 基準で進める。完璧を求めて停滞しない（policy「80%基準」原則）
