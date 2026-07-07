# thumbnail スキル × codex imagegen SKILL.md 準拠検討レポート

> **取得ステータス**: 参照 SKILL.md の WebFetch は成功。  
> URL: `https://raw.githubusercontent.com/openai/codex/main/codex-rs/skills/src/assets/samples/imagegen/SKILL.md`（2026-06-01 取得）

---

## 1. 構造比較表

### 1-1. YAML frontmatter

| 項目 | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|------|--------------------------|----------------|
| `name` | `"imagegen"` | `thumbnail` |
| `description` | 長文英語。「Use when」+ 「Do not use when」を 1 フィールドに同居 | 日本語トリガー文。「Use when」のみ。「Do not use when」なし |
| `allowed-tools` | 記載なし | 記載なし（frontmatter には存在しない） |
| 言語 | 英語 | 日本語 |

### 1-2. 章立て比較

| # | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|---|--------------------------|----------------|
| 1 | Top-level modes and rules | Overview |
| 2 | When to use | 前提（Prerequisites） |
| 3 | When not to use | When to Use |
| 4 | Decision tree | Quick Reference |
| 5 | Workflow（18 ステップ、番号付き） | プロバイダー切り替え |
| 6 | Transparent image requests | codex 経由の生成 |
| 7 | Prompt augmentation | Channel Adaptation |
| 8 | Specificity policy（`###`、Prompt augmentation 内 L165） | （なし） |
| 9 | Use-case taxonomy（exact slugs） | 生成モード判定 |
| 10 | Shared prompt schema | プロンプト構築（SKILL.md L150） |
| 11 | Augmentation rules（本文ラベル、Shared prompt schema 内 L236） | （なし） |
| 12 | Examples | ワークフロー（Single-Step/TTP + Two-Phase） |
| 13 | Prompting best practices | 品質チェック |
| 14 | Guidance by asset type | 視認性検証と整合性監査の役割分担 |
| 15 | gpt-image-2 guidance for CLI fallback | プロンプト保存 |
| 16 | Fallback CLI mode only | ファイル命名ルール |
| 17 | Temp and output conventions（`###`、Fallback CLI mode only 内 L309） | （なし） |
| 18 | Dependencies（`###`、Fallback CLI mode only 内 L315） | （なし） |
| 19 | Environment（`###`、Fallback CLI mode only 内 L332） | （なし） |
| 20 | Script-mode notes（`###`、Fallback CLI mode only 内 L344） | （なし） |
| 21 | Reference map | stock 退避と再利用 |
| 22 | （なし） | 長時間処理の取り扱い |
| 23 | （なし） | Next Step |

### 1-3. references 構成比較

| ファイル | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|---------|--------------------------|----------------|
| `references/prompting.md` | あり（両モード共通プロンプト原則） | なし |
| `references/sample-prompts.md` | あり（両モード共通プロンプトレシピ） | なし |
| `references/cli.md` | あり（CLI fallback 専用） | なし |
| `references/image-api.md` | あり（CLI fallback 専用） | なし |
| `references/codex-network.md` | あり（CLI fallback 専用） | なし |
| `scripts/image_gen.py` | あり（CLI fallback 専用スクリプト） | なし |
| `remove_chroma_key.py` | あり（システム共通ヘルパー、`$CODEX_HOME/skills/.system/imagegen/scripts/`） | なし |
| `references/codex-image.sh` | なし | あり（ChatGPT サブスク認証経由の codex image 生成ラッパー） |
| `references/generate_image.py` | なし | あり（`../../../../src/youtube_automation/scripts/generate_image.py` へのシンボリックリンク。CLI 引数を解釈し Gemini / OpenAI / codex プロバイダーを切り替えて画像生成を実行する実装コード） |
| `config.default.yaml` | なし | SKILL.md 内で言及（`yt-skills sync` 配布） |

---

## 2. 差分一覧

### 差分 A: モード設計思想

| 観点 | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|------|--------------------------|----------------|
| モード分類軸 | 「built-in tool（優先）」vs「CLI fallback（明示要求時のみ）」の 2 択 | `gemini` / `openai` / `codex` の 3 プロバイダーを同格で並列提示 |
| 優先順位の明示 | 「built-in by default」と明記し、fallback への切り替え条件を厳格に定義 | `config/skills/thumbnail.yaml` の `image_generation.provider` で切り替え。デフォルト優先は暗黙（設定依存） |
| 差分の性質 | **思想差**。imagegen は tool-first／config 不要を前提にした汎用設計。thumbnail は channel-config-driven の設定依存型 |

### 差分 B: description のトリガー文構造

| 観点 | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|------|--------------------------|----------------|
| Use when | 英語、長文、bitmap 生成全般 | 日本語、YouTube サムネ文脈に特化 |
| Do not use when | description 末尾に明記（SVG/コード系、vector 編集など） | frontmatter に記載なし |
| 差分の性質 | **構造差**。imagegen は 1 フィールドで use/do-not-use を完結。thumbnail は do-not-use の除外条件が明示されていない |

### 差分 C: 決定木の有無

| 観点 | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|------|--------------------------|----------------|
| Intent 判定 | 「generate（新規）」vs「edit（既存画像変更）」を明示判定 | generate 一択。edit の概念なし（画像編集はフォールバックで都度手動） |
| Execution 判定 | single-asset vs batch を明示判定 | `--max-attempts N` による複数候補生成があるが、batch の概念は定義されていない |
| 差分の性質 | **構造差**。imagegen はリクエスト受信時に 2 軸で判定する構造を持つ。thumbnail はコレクション制作フローの中での位置づけで実質 generate 固定 |

### 差分 D: ワークフローの粒度・番号付き手順

| 観点 | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|------|--------------------------|----------------|
| 手順形式 | 18 ステップ、番号付き、全モードを 1 本のフローに統合 | Single-Step/TTP と Two-Phase を別セクションに分離。ステップ番号なし |
| 入力収集フェーズ | ステップ 5-7 で「入力収集 → 各画像の役割ラベル付け → ローカル画像の view_image」を定義 | 入力収集の明示フェーズなし。skill-config 読み込みが前提 |
| 出力先ポリシー | ステップ 14-16 で preview-only vs project-bound を明示し、ファイル移動ルールを明文化 | `main.png` / `thumbnail.jpg` の命名ルールテーブルで定義。ただし「preview-only」の概念なし |
| 差分の性質 | **構造差 + 手順差**。imagegen は汎用フローを 1 本に統合。thumbnail は YouTube コレクション制作フロー内の文脈に依存した分岐型 |

### 差分 E: プロンプトスキーマの形式化

| 観点 | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|------|--------------------------|----------------|
| スキーマ定義 | `Use case / Asset type / Primary request / Input images / Scene / Subject / Style / Composition / Lighting / Color / Materials / Text / Constraints / Avoid` の 14 項目 | プロンプト構築を手順で記述（`prompt_prefix` → `fixed_character` → `composition_rules` → テンプレート文字列） |
| Use-case タクソノミー | 19 スラグ（Generate 11 + Edit 8）を定義し、一貫したラベルで参照 | タクソノミーなし。「TTP」「single_step」「diff_from_reference」「two_phase」の生成モードラベルが独自定義 |
| プロンプト具体性ポリシー | `Specificity policy`（`###`、L165）でプロンプトの具体度に応じた拡張量の指針を明示（具体的なら構造化のみ・汎用なら適切に拡張）。Allowed augmentations（構図ヒント・用途ヒント・実用的なレイアウト指示・合理的な場面の具体化）と Not allowed augmentations（意図にないキャラ・ブランド名・スローガン・根拠のない配置指示等）を列挙 | なし。プロンプト構築は skill-config の値を埋め込む手順のみ。具体性に応じた分岐指針はない |
| 拡張ルール | `Augmentation rules`（本文ラベル、L236）で拡張の運用ルールを明示（短く保つ・必要な詳細のみ追加・編集時は不変要素 `change only X; keep Y unchanged` を明示・欠落時は質問してから進める） | なし。拡張の可否に関する明示的なガイドラインはない |
| 差分の性質 | **手順差 + 思想差**。imagegen は形式化されたスキーマ・具体性ポリシー・拡張ルールを組み合わせて AI への入力を構造化。thumbnail は skill-config の YAML 値を埋め込む手順型であり、プロンプト拡張の明示的なポリシーを持たない |

### 差分 F: 透過画像処理

| 観点 | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|------|--------------------------|----------------|
| 透過出力 | chroma-key → local removal → alpha 検証の全手順を定義。CLI fallback への切り替え条件も明記 | 透過処理の概念なし（YouTube サムネは不透明 JPEG が前提） |
| 差分の性質 | **独自仕様差**。YouTube サムネ用途では透過不要のため、この章の内容は thumbnail にはそもそも不要 |

### 差分 G: references 構成の疎密

| 観点 | 参照 SKILL.md（imagegen） | 既存 thumbnail |
|------|--------------------------|----------------|
| 共通 references | `prompting.md`、`sample-prompts.md` | なし |
| 実装 references | `cli.md`、`image-api.md`、`codex-network.md`、`scripts/image_gen.py` | `codex-image.sh`（codex プロバイダー専用ラッパー）、`generate_image.py`（`src/youtube_automation/scripts/generate_image.py` へのシンボリックリンク。マルチプロバイダー画像生成実装） |
| 差分の性質 | **構造差**。imagegen は「共通」「fallback専用」を明確に分類。thumbnail は実装コード（`generate_image.py` symlink）と codex 専用ラッパー（`codex-image.sh`）の 2 ファイルを持つが、プロンプト知識系（`prompting.md` / `sample-prompts.md`）は存在せず疎な状態 |

---

## 3. 独自仕様の棚卸し

既存 thumbnail に存在し、参照 SKILL.md（imagegen）に存在しない要素を以下に整理する。

### 3-1. TTP（Trace-Imitate Pattern）/ CTR 最適化

| 観点 | 詳細 |
|------|------|
| 概要 | 高再生ベンチマークサムネイルを参照画像に使い、差分のみ指示して再現する YouTube 固有の生成戦略 |
| 実装箇所 | SKILL.md「Single-Step / TTP モード」セクション、`generation_mode: "single_step"` |
| YouTube 固有か | ✅ **固有**。YouTube CTR を最大化するための実績ベース模倣手法であり、汎用 imagegen には存在しない概念 |
| 汎用化できるか | 「高スコア参照画像からバリエーション生成」という概念は汎用化可能だが、TTP・CTR という YouTube 用語は固有 |
| 削っても運用が回るか | ❌ **削除不可**。現チャンネルはこのモードを標準として運用しており、削除すると品質保証の仕組みが失われる |

### 3-2. skill-config（`config/skills/thumbnail.yaml`）

| 観点 | 詳細 |
|------|------|
| 概要 | チャンネルごとの画像生成設定を外部 YAML で管理し、スキル実行時にロードする深マージ方式 |
| 実装箇所 | SKILL.md「Channel Adaptation」セクション、`config.default.yaml` による配布 |
| YouTube 固有か | ✅ **固有**（このリポジトリのチャンネル管理アーキテクチャ固有） |
| 汎用化できるか | 設定外部化の考え方は汎用だが、`load_skill_config()` や `yt-skills sync` はこのリポジトリ固有の API |
| 削っても運用が回るか | ❌ **削除不可**。複数チャンネルで異なるスタイル・キャラ・プロバイダーを管理する基盤。これがなければチャンネルごとのカスタマイズが不可能になる |

### 3-3. コレクション連携（`collections/planning/` 構造）

| 観点 | 詳細 |
|------|------|
| 概要 | コレクションディレクトリ（`10-assets/`）への出力、`workflow-state.json` 更新、Next Step への誘導 |
| 実装箇所 | SKILL.md「ワークフロー」各セクション、「Next Step」 |
| YouTube 固有か | ✅ **固有**。このリポジトリのコレクション管理構造に完全依存 |
| 汎用化できるか | 「出力先をプロジェクト構造に配置する」という概念は imagegen のワークフロー（ステップ 15）と一致しており、原則は共通 |
| 削っても運用が回るか | ❌ **削除不可**。コレクションフローと統合されており、削除すると出力先・次工程誘導が失われる |

### 3-4. ファイル命名規則（`main.png` / `thumbnail.jpg`）

| 観点 | 詳細 |
|------|------|
| 概要 | `main.png`（背景）・`main-vN.jpg`（候補）・`thumbnail-vN.jpg`（テキスト付き候補）・`thumbnail.jpg`（最終承認）の 4 段階命名 |
| 実装箇所 | SKILL.md「ファイル命名ルール」セクション |
| YouTube 固有か | ✅ **固有**。チャンネル運用フロー（動画背景 ↔ サムネ最終版）に依拠した命名 |
| 汎用化できるか | imagegen の「`hero-v2.png` のようなバージョン付きファイル名」という原則と概念は共通だが、具体名は固有 |
| 削っても運用が回るか | ❌ **削除不可**。`/collection-ideate` など他スキルが `main.png` の存在を前提に動作する |

### 3-5. stock 退避と再利用（`assets/stock/`）

| 観点 | 詳細 |
|------|------|
| 概要 | 不採用候補画像をメタデータ付きで退避し、将来の参照画像プールとして再利用する仕組み |
| 実装箇所 | SKILL.md「stock 退避と再利用」「クリーンアップ」セクション |
| YouTube 固有か | ✅ **固有**。`yt-stock-archive` / `resolve_stock_refs()` はこのリポジトリ固有のツール |
| 汎用化できるか | 「discarded variants を保持する」という考え方は imagegen ステップ 16 に「Discarded variants do not need to be kept unless requested」と逆方向の方針があり、思想が異なる |
| 削っても運用が回るか | △ **短期は可**。stock がないと参照画像プールが減り、長期的に TTP のバリエーション品質が低下する可能性があるが、機能停止にはならない |

### 3-6. 複数プロバイダー切り替え（gemini / openai / codex）

| 観点 | 詳細 |
|------|------|
| 概要 | `image_generation.provider` で 3 プロバイダーを切り替え可能にし、各プロバイダーの認証・API・特徴差を管理 |
| 実装箇所 | SKILL.md「プロバイダー切り替え」「codex 経由の生成」セクション |
| YouTube 固有か | ✅ **固有**（このリポジトリ固有のプロバイダー抽象化 `ImageProvider`） |
| 汎用化できるか | imagegen は「built-in（gpt-image-2）」vs「CLI fallback（gpt-image-1.5 等）」の 2 軸でモデル切り替えを管理しており、構造は異なる |
| 削っても運用が回るか | ❌ **削除不可**。GCP 課金なしで運用したい場合の codex 経路、CJK 文字描画が必要な場合の openai 経路が失われる |

### 3-7. 固定キャラ（`fixed_character`）設計

| 観点 | 詳細 |
|------|------|
| 概要 | キャラクターの服装・楽器・顔の向きをコレクション間で統一するための設定セット |
| 実装箇所 | SKILL.md「プロンプト構築」§2 |
| YouTube 固有か | ✅ **固有**（キャラクターが登場するチャンネル固有の仕様） |
| 汎用化できるか | imagegen の「identity-preserve」タクソノミーと概念が近いが、skill-config YAML での定義方法は固有 |
| 削っても運用が回るか | △ **チャンネル依存**。キャラなしチャンネルには不要。キャラありチャンネルには必須 |

### 3-8. Two-Phase モード（既存参照 → thumbnail → textless main）

| 観点 | 詳細 |
|------|------|
| 概要 | Phase 1 で既存参照を選び、Phase 2 でテキスト付き `thumbnail.jpg` を確定し、Phase 3 で承認済み `thumbnail.jpg` から textless `main.png/jpg` を再生成するフォールバック |
| 実装箇所 | SKILL.md「Two-Phase モード」セクション |
| YouTube 固有か | ✅ **固有**。YouTube サムネのテキスト＋背景合成ワークフローに特化 |
| 汎用化できるか | imagegen の「edit（inpainting / compositing）」と概念は近いが、2 フェーズに分けた YouTube 専用フロー |
| 削っても運用が回るか | △ **Single-Step が安定していれば代替可**。ただしフォールバックとして残す価値あり |

### 3-9. 視認性検証（`/thumbnail-compare`）/ 整合性監査（`/alignment-check`）

| 観点 | 詳細 |
|------|------|
| 概要 | 承認前の 320px 縮小視認性検証と、公開後のコレクション整合性監査を役割分担する外部スキル連携 |
| 実装箇所 | SKILL.md「視認性検証と整合性監査の役割分担」セクション |
| YouTube 固有か | ✅ **固有**。YouTube サムネの表示サイズ・CTR に関するチェック基準 |
| 汎用化できるか | 「生成後バリデーション → 反復改善」の概念は imagegen ステップ 12-13 と共通だが、320px 縮小・CTR はYouTube固有指標 |
| 削っても運用が回るか | △ **削除は非推奨**。品質担保の仕組みが失われるが、手動確認で代替は可能 |

### 3-10. 長時間処理（`run_in_background` / cmux 連携）

| 観点 | 詳細 |
|------|------|
| 概要 | 10〜30 秒のブロッキング API 呼び出しを `run_in_background=true` で非同期化し、cmux ステータス表示と組み合わせる |
| 実装箇所 | SKILL.md「長時間処理の取り扱い」セクション |
| YouTube 固有か | △ **実装固有**（cmux は別ツール。`run_in_background` は Claude Code 固有の機能） |
| 汎用化できるか | 「非同期処理 + 完了通知」という概念は汎用だが、具体的な実装（`run_in_background=true`・cmux）はこの環境固有 |
| 削っても運用が回るか | △ **削除は非推奨**。削除するとブロッキング実行になり UX が悪化するが、機能は維持される |

### 3-11. プロンプト保存（`20-documentation/thumbnail-prompts.md`）

| 観点 | 詳細 |
|------|------|
| 概要 | 使用したプロンプト・プロバイダー・参照画像をコレクション内のドキュメントとして保存する運用ルール |
| 実装箇所 | SKILL.md「プロンプト保存」セクション |
| YouTube 固有か | ✅ **固有**（コレクションディレクトリ構造に依拠） |
| 汎用化できるか | imagegen ステップ 18「final prompt を報告する」と目的は共通だが、ファイル保存まで要求する点は固有 |
| 削っても運用が回るか | △ **短期は可**。再生成時の参照材料が失われるため、長期運用では品質低下リスクあり |

---

## 4. 準拠提案

各差分項目について「寄せる（imagegen 構造に準拠）」「維持する（thumbnail 独自仕様を保持）」「一部寄せる（ハイブリッド）」の 3 択で提案する。  
**最終判断はユーザーが行う前提で、選択肢とトレードオフを両論併記する。**

---

### 提案 1: description の「Do not use when」追加（差分 B）

| | 内容 |
|---|------|
| 対象 | YAML frontmatter の `description` フィールド |
| 寄せた場合のメリット | スキルルーター（AI）が誤起動を防げる。imagegen に準じた除外条件（「サムネ不要な場面では使わない」等）を明示できる |
| 寄せた場合のデメリット | 記述量が増え、日本語・英語の混在または英語化が必要になる。現在の日本語トリガー文から文体が変わる |
| **推奨** | **一部寄せる** — 既存の日本語トリガー文を維持しつつ、末尾に「Do not use when」を 1〜2 行追加するだけで効果を得られる。記述コストが低く、誤起動リスクも下がるため採用を推奨 |

---

### 提案 2: モード優先順位の明示（差分 A）

| | 内容 |
|---|------|
| 対象 | 「プロバイダー切り替え」セクションのプロバイダー並列記述 |
| 寄せた場合のメリット | どのプロバイダーをデフォルトにすべきかが一目でわかる。AI が設定なしで迷わず動作できる |
| 寄せた場合のデメリット | channel-config が優先されるアーキテクチャでは「デフォルト固定」が設定と矛盾する可能性がある |
| **推奨** | **一部寄せる** — 「config 未設定時のデフォルトは `gemini`」という記述を明示する。imagegen の「built-in preferred」に対応する宣言として有効。config が設定されている場合は config 優先、という既存挙動は変えない |

---

### 提案 3: ワークフローの番号付き統合（差分 D）

| | 内容 |
|---|------|
| 対象 | Single-Step/TTP・Two-Phase に分かれたワークフローセクション |
| 寄せた場合のメリット | 決定から実行までのフローが 1 本になり、AI が手順を追いやすくなる。imagegen の 18 ステップに対応する構造 |
| 寄せた場合のデメリット | Single-Step と Two-Phase は手順が全く異なるため、統合すると各分岐が深くなり可読性が下がる可能性がある。現状の「モードごとに独立したセクション」の方が操作単位は明確 |
| **推奨** | **維持する** — YouTube 固有の 2 モード分岐は、統合フローに押し込むより現在の分離構造の方が可読性が高い。imagegen との思想差（汎用 vs YouTube 専用）が顕著な部分のため、無理に統合しない方がよい |

---

### 提案 4: Use-case タクソノミースラグの導入（差分 E）

| | 内容 |
|---|------|
| 対象 | プロンプト構築手順のラベル体系 |
| 寄せた場合のメリット | imagegen の 19 スラグとの互換性ができ、cross-skill 参照が容易になる。「YouTube サムネは `product-mockup` の派生」のように位置づけられる |
| 寄せた場合のデメリット | 既存の「TTP」「single_step」「diff_from_reference」ラベルは YouTube 独自のコンセプトであり、汎用スラグに置き換えると意味が薄れる |
| **推奨** | **一部寄せる** — SKILL.md に `Use case: product-mockup (YouTube thumbnail variant)` のような 1 行マッピングを注記するだけで互換性を示せる。既存ラベルは維持しつつ、imagegen タクソノミーとの対応を明記する |

---

### 提案 5: Shared prompt schema の導入（差分 E）

| | 内容 |
|---|------|
| 対象 | プロンプト構築セクション全体 |
| 寄せた場合のメリット | imagegen の 14 項目スキーマに揃えることで、Codex が prompt を構造化しやすくなる。他スキルとの整合性も向上 |
| 寄せた場合のデメリット | 現在の手順型記述（skill-config の YAML 値を埋める方式）はチャンネル設定と密結合しており、スキーマ形式への移行には skill-config との対応マッピングが必要になる。移行コストが高い |
| **推奨** | **維持する（ただし将来的に寄せる余地あり）** — 現状の skill-config 依存型プロンプト構築は thumbnail スキルの核心機能。短期では移行コストに見合わない。将来 skill-config の管理方法を見直す際に、schema 形式への移行を検討する |

---

### 提案 6: references の整理・拡充（差分 G）

| | 内容 |
|---|------|
| 対象 | `.claude/skills/thumbnail/references/` ディレクトリ |
| 現状の references | `codex-image.sh`（codex プロバイダー専用ラッパー）と `generate_image.py`（`src/youtube_automation/scripts/generate_image.py` へのシンボリックリンク）の 2 ファイルが存在する。実装コードは symlink 先で分離されており、SKILL.md には手順ドキュメントのみが内包されている |
| 寄せた場合のメリット | `prompting.md`（YouTube サムネ向けプロンプト原則）・`sample-prompts.md`（サムネ別プロンプトレシピ）を追加することで、SKILL.md「プロンプト構築」セクションをそちらに移動できる。imagegen 構造に準拠し、SKILL.md の肥大化を抑制できる |
| 寄せた場合のデメリット | 現状は SKILL.md 内にプロンプト構築の手順ドキュメントが内包されており、`references/prompting.md` に分割するとコンテキスト参照時に 2 ファイルを辿る必要が生じる。ファイル数が増えるほど AI のコンテキスト追跡コストが上がる |
| **推奨** | **一部寄せる** — imagegen に倣い `references/prompting.md` と `references/sample-prompts.md` を追加することを推奨。SKILL.md の「プロンプト構築」セクションを `references/prompting.md` に移し、SKILL.md をスリム化できる。実装コードは `generate_image.py` symlink にすでに分離されているため、このパターンとの整合性もある。実装は別タスクで |

---

### 提案 7: 透過処理セクション（差分 F）

| | 内容 |
|---|------|
| 対象 | 透過画像処理の手順 |
| 寄せた場合のメリット | YouTube サムネ以外の用途（例：チャンネルアイコン、オーバーレイ素材）に拡張する場合に備えた準備ができる |
| 寄せた場合のデメリット | 現状の YouTube サムネ用途では透過不要であり、記述を追加してもすぐに使われない可能性が高い。SKILL.md が膨らむ |
| **推奨** | **維持する（追加不要）** — YouTube サムネは不透明 JPEG が前提であり、透過処理セクションは不要。用途が拡張した時点で追加を検討する |

---

### 提案 8: TTP / CTR 最適化（差分 A・独自仕様 3-1）

| | 内容 |
|---|------|
| 対象 | Single-Step / TTP モード全体 |
| 寄せた場合のメリット | imagegen の「style-transfer」タクソノミーと共通点を見出せる。「参照画像を使ったバリエーション生成」という汎用構造に整理できる |
| 寄せた場合のデメリット | TTP（Trace-Imitate Pattern）はチャンネル運用に固有の CTR 最適化戦略であり、汎用化すると本質的なコンセプトが薄まる。ベンチマーク設定・ローテーション・TTP チェックリストは全部失われる |
| **推奨** | **維持する** — TTP は thumbnail スキルの中核価値。imagegen に準じた構造化（タクソノミー注記など）は行いつつも、TTP 手順そのものは全量維持する |

---

### 提案 9: stock 退避と再利用（独自仕様 3-5）

| | 内容 |
|---|------|
| 対象 | stock 退避・`yt-stock-archive` 連携 |
| 寄せた場合のメリット | imagegen ステップ 16「Discarded variants do not need to be kept」に近い方針に統一でき、シンプルになる |
| 寄せた場合のデメリット | stock は TTP の参照画像プールを豊かにするための長期投資機能。廃止すると TTP のバリエーション品質が低下する |
| **推奨** | **維持する** — imagegen と思想が逆方向（削除 vs 退避・再利用）だが、YouTube チャンネル運営では「過去の不採用画像を参照に使う」ことに明確な価値がある。削除方針への同調は不要 |

---

### 提案 10: 長時間処理の `run_in_background` 指示（独自仕様 3-10）

| | 内容 |
|---|------|
| 対象 | 「長時間処理の取り扱い」セクション |
| 寄せた場合のメリット | imagegen は実行中 UX について記述していないため、この知見を参照 SKILL.md へフィードバックする形でも有益 |
| 寄せた場合のデメリット | `run_in_background` と cmux は Claude Code / cmux 固有の機能であり、imagegen（Codex CLI 向け）には直接移植できない |
| **推奨** | **維持する** — Claude Code 環境で thumbnail スキルを動かす限り必要な知識。imagegen への寄せは不要 |

---

## 付録: 準拠推奨サマリー

| 差分 | 推奨 | 優先度 |
|------|------|-------|
| A. モード優先順位の明示 | 一部寄せる（config 未設定時のデフォルトを明記） | 中 |
| B. description の Do-not-use 追加 | 一部寄せる（1〜2 行追記） | 高 |
| C. 決定木 | 維持する（YouTube 固有のフロー） | 低 |
| D. ワークフロー番号付き統合 | 維持する（分離構造の方が可読性高） | 低 |
| E-1. タクソノミースラグ注記 | 一部寄せる（対応表を 1 行追加） | 低 |
| E-2. Shared prompt schema 導入 | 維持する（短期移行コスト高） | 低 |
| F. 透過処理セクション | 維持する（不要） | 対象外 |
| G. references 分割拡充 | 一部寄せる（prompting.md / sample-prompts.md 追加） | 中 |
| TTP / CTR（独自 3-1） | 維持する（中核価値） | 対象外 |
| skill-config（独自 3-2） | 維持する（アーキテクチャ基盤） | 対象外 |
| コレクション連携（独自 3-3） | 維持する | 対象外 |
| ファイル命名（独自 3-4） | 維持する | 対象外 |
| stock 退避（独自 3-5） | 維持する | 対象外 |
| プロバイダー切り替え（独自 3-6） | 維持する（一部寄せる：デフォルト明示） | 中 |
| 固定キャラ（独自 3-7） | 維持する | 対象外 |
| Two-Phase モード（独自 3-8） | 維持する（フォールバックとして価値あり） | 対象外 |
| 視認性検証連携（独自 3-9） | 維持する | 対象外 |
| 長時間処理（独自 3-10） | 維持する | 対象外 |
| プロンプト保存（独自 3-11） | 維持する | 対象外 |

---

*本レポートは読み取り専用調査の成果物です。SKILL.md 本体・references の編集は別タスクで行います。*

*数値出典（スラグ数 19・ステップ数 18・スキーマ項目数 14 / `gpt-image-2` / `gpt-image-1.5` の言及）は参照 SKILL.md を WebFetch で取得し、verbatim で確認済みです。*
