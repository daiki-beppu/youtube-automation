# thumbnail codex 経路における JSON/Nix-first プロンプト指示の品質効果 実験レポート

- **Issue**: #2078
- **Date**: 2026-07-17
- **Status**: 完了（単発実験レポート）
- **Related**: `docs/skill-design/ADR-001-thumbnail-prompt-schema.md` / `docs/skill-design/thumbnail-codex-imagegen-diff-report.md`

## 背景と目的

「GPT-5.x 系モデルで画像生成する際、プロンプトを先に JSON 形式で出力させると品質が大きく向上する。Nix 形式ならさらに向上する」という言説がある。thumbnail スキルの codex プロバイダ経路（`@openai/codex` CLI + ChatGPT サブスク認証の `image_generation` tool）は `image_generation.codex.default_prompt_template`（TTP プロンプト）で直接画像生成しており、中間プロンプトの構造化ステップは無い。この言説が本当なら template 改善や ADR-001（14 項目 Shared prompt schema、試験導入済み・本番未接続）の本番接続の判断材料になるため、出典調査と実生成の比較実験を行った。

## 1. 情報源調査（要件 1）

### 1-1. 主張 A: 「JSON 形式でプロンプトを出力してから画像生成すると品質が大きく向上する」

**日本語圏での直接の拡散元は実験後に特定できた**: X のタツキ氏（@gibkun1）による 2026-06-22 の投稿「ChatGPT で画像を生成するとき、『JSON形式でプロンプトを出力してから画像生成して』伝えるだけでクオリティが段違いに上がる」（化粧品広告の before/after 比較画像付き。「GPT5.6 で〜」と言い換えた引用ポストで再拡散。ユーザー提供のスクリーンショットで確認、本文は左右の生成条件・プロンプト全文を示していない）。ただし言説自体の初出はこの投稿ではなく、2024 年半ばに散発的に現れ、2025 年に「JSON prompting」として X / TikTok / SEO ブログでミーム化した拡散パターンの一部である。

| 出典 | 日付 | 著者 | 種別 |
|---|---|---|---|
| [note「JSONを使って画像生成AIを使うと解像度が高いという話」](https://note.com/kujirahand/n/n1671c007bc9b) | 2024-06-25 | kujirahand（クジラ飛行机） | 日本語圏の早期拡散元。OpenAI Facebook グループの投稿に着想を得た自己実験 |
| [DEV Community「JSON Style Guides for Controlled Image Generation with GPT-4o and GPT-Image-1」](https://dev.to/worldlinetech/json-style-guides-for-controlled-image-generation-with-gpt-4o-and-gpt-image-1-36p) | 2025 | Worldline Tech | 技術ブログ。「品質向上」ではなく一貫性・制御性を主張 |
| [TikTok #json-prompt-image-chatgpt 群](https://www.tiktok.com/discover/json-prompt-image-chathgpt)、[Medium (Zypa.in)](https://medium.com/@zypa.official/chatgpt-json-image-generation-stunning-prompts-easy-guide-82a14e0ed135) 等 | 2025 以降 | 多数の匿名アカウント | バイラル拡散層。相互引用され初出特定不能 |

よく引かれる根拠は「LLM はコードで学習しているので構造化データの方が理解しやすい」だが、これ自体に一次的裏付けはない。

**OpenAI 公式の裏付け: 無し（形式は無差別と明言）。** [OpenAI Cookbook「GPT Image Generation Models Prompting Guide」](https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide)（2026-04-21、対象: gpt-image-2 / 1.5 / 1 / 1-mini）は次のとおり述べる:

> "Minimal prompts, descriptive paragraphs, JSON-like structures, instruction-style prompts, and tag-based prompts can all work well as long as the intent and constraints are clear."

つまり公式は JSON を許容するが優位性は主張しておらず、品質要因は「意図と制約の明確さ」としている。「GPT-5.x で JSON プロンプトが有効」と明示した公式文書も見つからなかった。

**第三者検証**（いずれも「品質が一律に上がる」を支持しない）:

- 否定: [Chase Jarvis「Does JSON Prompting Actually Work?」](https://chasejarvis.com/blog/does-json-prompting-actually-work-tested-with-nano-banana/) — JSON と自然言語の A/B 比較で「差なし」、JSON はプラセボと結論
- 条件付き: [302.AI「Comparing JSON and NL Prompts in AIGC」](https://medium.com/@302.AI/the-art-of-instructions-comparing-json-and-nl-prompts-in-aigc-5e82432cf6c7)（2025-08-05、Veo 3-Fast） — 単純タスクは自然言語で十分、複雑な多要素制御では構造化が有利
- 条件付き: [すたじおこんぶ「自然言語 vs JSON 徹底比較」](https://scombu.com/2025/12/18/gemini-image-prompt-styles/)（2025-12-18、Nano Banana Pro） — 直接的な品質差は薄く、利点は再利用性・要素修正の効率

**信頼性評価**: 「品質が大きく向上」はバイラル由来の伝聞であり、一次情報源（OpenAI 公式・査読研究）に品質向上の裏付けは無い。実測した第三者の一致した結論は「品質そのものは上がらない。一貫性・再利用性・複雑な指定の制御には有効な場合がある」。

### 1-2. 主張 B: 「Nix 形式ならさらに品質が上がる」

**出典が見つからなかった（実在する主張として確認できず）。** 英語・日本語の複数クエリ（`"Nix" prompt image generation JSON better quality` / `Nix言語 プロンプト 画像生成 品質 JSONより` / ジョーク・ミーム検索を含む）で X・Reddit・ブログ・YouTube を検索したが、真面目な主張もジョークも発見できなかった。見つかったのは Nix 言語一般の解説（[nix.dev](https://nix.dev/tutorials/nix-language.html)）のみ。

技術的にも、画像生成モデルの学習コーパスにおける Nix コード量は JSON より圧倒的に少なく、「構造化データの方が理解しやすい」とする（すでに疑わしい）根拠すら適用できない。「JSON prompting」ミームのパロディ、または伝聞過程での記憶違いの可能性が高い。**引用可能な一次情報源は存在しない。**

## 2. 実験設計（要件 2）

### 2-1. 実験環境

| 項目 | 値 |
|---|---|
| codex CLI | v0.144.1（`@openai/codex`、ChatGPT サブスク認証 `Logged in using ChatGPT`） |
| 生成経路 | `codex exec --json --sandbox workspace-write --image <reference>`（`references/codex-image.sh` と同一の起動形態・末尾ガード文） |
| 画像生成実体 | codex agent が `$CODEX_HOME/skills/.system/imagegen` スキル経由で `image_generation` tool を呼ぶ（JSONL の command_execution で確認） |
| 題材チャンネル | 2ch-deepfocus365（`image_generation.provider: codex` の本番運用チャンネル） |
| 題材 collection | `20260714-df365-twilight-focus-state-collection`（title テキスト: `TWILIGHT ZONE`） |
| 参照画像 | `data/analytics/thumbnails/PTCnJjtLhFo.jpg`（自チャンネル勝ちパターン。本番 attempt 1 と同一の割り当て） |
| 実施日 | 2026-07-17 |

### 2-2. 条件設計

3 条件 × 各 3 枚 = 9 枚。全条件で同一の参照画像・同一の末尾ガード文（`codex-image.sh` が自動付与する「新画像を生成 / reference を copy するな / 生成後 path を echo」）を使い、差分は「構造化プロンプトを先に出力せよ」という追加指示のみ。

- **baseline**: `image_generation.codex.default_prompt_template` を本番経路（`references/codex-prompt.py`）でレンダリングした現行プロンプトそのまま
- **JSON-first**: baseline 末尾に以下を追加

  ```
  Before calling the image_generation tool, first output in an agent message the complete image
  prompt you will use, formatted as a single structured JSON object (keys: subject, composition,
  camera, environment, lighting, color_palette, text_overlay, style, negative_constraints).
  Then call the image_generation tool with a prompt faithfully derived from that JSON object.
  ```

- **Nix-first**: 同上だが `formatted as a single Nix expression (an attribute set with attributes: ...)` として Nix 属性セットでの出力を指示

### 2-3. baseline プロンプト全文（レンダリング結果）

```
TTP this reference thumbnail, then improve it into a stronger original thumbnail.
Keep the winning layout, typography feel, character scale, color mood, texture, and energy.
Make it cleaner, more readable on mobile, stronger face impact, no logos, no watermarks, no broken hands.
Use the title TWILIGHT ZONE.


Composition rules (must follow; these override the reference subject):
{"allowed_actions": "車両 1 台のみの静止構図。...", "background": "single car on pure black reflective wet floor, ...", "channel_branding": "車のメーカーロゴ非表示、unbranded prototype concept として表現", "character_pose": "n/a (no human characters)", "character_size": "n/a (no human characters)", "environment": "pure black studio/showroom floor with reflective wet surface, ...", "ng_actions": "航空機の登場..., 人物の登場, 実車メーカーロゴ..., ハイキー背景..., シアン主光源..., セリフ細字 FOCUS テキスト...", "text_lines": "2 語ムードフレーズのみ (例: DARK FLOW, LOCKED IN)"}
```

（`Composition rules` の値は 2ch の `config/skills/thumbnail.yaml` override 由来。全文は同 override を参照）

**重要な前提**: 本番レンダリング結果は既に「自由文 4 行 + JSON ブロック（Composition rules）」のハイブリッドであり、baseline は「完全な自由文プロンプト」ではない。本実験は「その上でさらに、モデル自身に中間プロンプトを JSON / Nix で書き出させるステップを挟む効果」を測るものである。

## 3. 生成結果と中間プロンプト

### 3-1. 生成メタデータ

全 9 run 成功（失敗・リトライ・reference cp failure mode 検出なし）。生成物とログ（JSONL 全量・sha256）は `~/02-yt/yt-research/experiments/2078-codex-json-first/` にローカル保管（画像はリポジトリにコミットしない。影響ファイルを docs 1 本に限定する issue 方針のため）。

| run | 生成時間 | サイズ | sha256 (先頭 12) |
|---|---:|---:|---|
| baseline-1 | 106s | 1,629,827 B | `bc189b9f7c7d` |
| baseline-2 | 105s | 1,261,771 B | `692605a9e8e6` |
| baseline-3 | 110s | 1,396,118 B | `13c14f2ca4ee` |
| json-first-1 | 172s | 1,369,943 B | `446080073323` |
| json-first-2 | 124s | 1,481,345 B | `cc5f236520a7` |
| json-first-3 | 112s | 1,329,917 B | `1f82472696f6` |
| nix-first-1 | 138s | 1,458,918 B | `ef66362972da` |
| nix-first-2 | 112s | 1,673,224 B | `cf27ffe09648` |
| nix-first-3 | 90s | 1,308,332 B | `be9aecd757af` |

平均生成時間: baseline 107s / JSON-first 136s (+27%) / Nix-first 113s (+6%)。中間プロンプト出力ステップの分だけ JSON/Nix 条件はやや遅く、ChatGPT サブスクの fair-use 消費も増える。全画像 1672×941（16:9、1280×720 基準を満たす）。

### 3-2. 中間プロンプト（JSON-first 条件、モデル出力の全文）

JSON-first の 3 run すべてで、モデルは指示どおり単一 JSON オブジェクトを agent message として出力してから生成した。キー構成は 3 run とも指示した 9 キーに準拠。

<details>
<summary>json-first-1 の中間 JSON（全文）</summary>

```json
{"subject":"A single unbranded futuristic grand-touring prototype coupe, no manufacturer identity, shown as a pristine sculptural automotive hero object with crisp body lines, deep gloss-black paint, dark glass, realistic wheels, and no visible badges or logos.","composition":"16:9 YouTube thumbnail. Preserve the reference’s winning visual hierarchy without copying its vehicle design: one car only in a static full side-profile, spanning roughly 78% of the frame width and occupying the lower 58%; generous pure-black negative space above; centered, balanced silhouette; wet-floor reflection kept controlled and uncluttered. No people or extra objects.","camera":"Low eye-level automotive studio camera, perfectly broadside side profile, long-lens compression around 85mm, minimal perspective distortion, entire car sharp, clean silhouette separation, premium commercial-photography finish, composed for strong readability at mobile thumbnail size.","environment":"Pure black seamless studio/showroom with a glossy rain-wet reflective black floor; no visible walls, horizon scenery, runway, airport, aircraft, street, skyline, props, or background clutter; overall midtone value at or below 30%.","lighting":"Dramatic high-contrast rim lighting tracing the roofline, shoulders, wheel arches, and lower body; strong warm amber/orange key accent along the rear roofline and upper flank; subtle warm taillight glow and amber reflection on the wet floor; restrained cool-neutral white edge light at the front only; deep blacks preserved, with no cyan-dominant illumination.","color_palette":"Near-black, charcoal, gunmetal, subtle neutral white highlights, and selective amber/orange-gold accents; dark cinematic mood with warm energy; no blue/cyan monochrome treatment.","text_overlay":"Exact text: \"TWILIGHT ZONE\". Two words only, set on one line across the upper third. Large bold high-contrast condensed display sans-serif capitals with refined wide tracking, clean modern luxury feel, warm ivory-white fill, subtle optical kerning, no outline, no glow, no shadow, no extra text. Make every letter perfectly spelled, highly legible, and readable on mobile.","style":"Freshly generated original PNG; photorealistic premium automotive campaign thumbnail; cinematic, minimal, mysterious, focused, nocturnal, polished yet tactile; realistic glossy paint, rubber, glass, wet-floor texture, sharp micro-contrast, clean negative space, strong visual energy. Use the provided image only as high-level inspiration for layout, scale, dark mood, reflective texture, and typographic placement—not as an edit or replica.","negative_constraints":"Do not reproduce the reference car or any identifiable real production model. Exactly one vehicle. No humans, faces, hands, aircraft, airport, runway, road, scenery, bright sky, high-key background, cyan main light, all-cool palette, extra vehicles, manufacturer grille signature, emblem, badge, logo, license-plate branding, watermark, signature, border, illegible typography, misspelled text, extra words, thin serif FOCUS styling, broken geometry, warped wheels, malformed tires, duplicate parts, open doors, motion blur, or cropped car."}
```

</details>

json-first-2 / json-first-3 も同一キー構成の JSON を出力（全文は保管先の `out/json-first-2.jsonl` / `out/json-first-3.jsonl`）。内容の差分は表現の揺れ（車幅 78〜82%、タイポグラフィ指定が sans-serif / serif で揺れる等）に留まる。

### 3-3. 中間プロンプト（Nix-first 条件、モデル出力の全文）

Nix-first の 3 run すべてで、モデルは正しい構文の Nix 属性セット（`{ attr = "value"; }` 形式、nix-first-2 は `''` インデント文字列も使用）を出力してから生成した。

<details>
<summary>nix-first-1 の中間 Nix 式（全文）</summary>

```nix
{
  subject = "A single unbranded futuristic grand-touring prototype coupe, entirely original in body design, shown as a clean full side profile with a long low silhouette, sculpted shoulders, flush surfaces, dark glass, realistic tires, and no visible manufacturer identity.";
  composition = "16:9 YouTube thumbnail. One stationary car only, filling roughly the lower 55% of the frame, centered horizontally with the complete vehicle visible and generous black negative space above. Preserve the reference's proven car-profile-plus-headline hierarchy, but create new geometry and details rather than copying the reference. The headline is the sole graphic element and must dominate at mobile size.";
  camera = "Low eye-level automotive studio camera, near-perfect orthographic side view, subtle 85mm compression, crisp silhouette, wheels circular and correctly aligned, no motion blur.";
  environment = "Pure black seamless studio/showroom with a glossy wet reflective floor; no horizon scenery, runway, airport, aircraft, architecture, props, or additional vehicles. Overall midtone value at or below 30%, with controlled reflections and clean negative space.";
  lighting = "Dramatic low-key studio lighting: restrained cool-neutral edge definition on the front and roofline, plus a mandatory strong amber-orange rim light tracing the rear shoulder, roof arc, and lower body line. Warm taillight glow and a warm amber reflection pool on the wet floor. Deep blacks, high contrast, readable silhouette, no cyan-only lighting.";
  color_palette = "Near-black, charcoal, graphite, muted steel, warm amber, burnt orange, and tiny clean white highlights; dark cinematic mood with warm accents clearly present.";
  text_overlay = "Render exactly \"TWILIGHT ZONE\" in uppercase as two words on one line across the upper third. Use a large bold high-contrast condensed modern sans-serif display face with subtle wide tracking, bright warm-white letters, clean kerning, strong mobile readability, and ample safe margins. No other text.";
  style = "Premium photorealistic automotive campaign photography, cinematic luxury noir, polished but believable materials, crisp 3D realism, subtle wet-floor texture, clean thumbnail hierarchy, intense controlled energy, and an original concept-car design.";
  negative_constraints = "Do not reproduce or trace the reference car. No logos, emblems, badges, trademarks, license plates, watermarks, signatures, people, faces, hands, aircraft, runway, airport, extra vehicles, extra objects, bright sky, high-key background, blue/cyan monochrome treatment, missing warm accent, thin serif typography, tiny text, misspelled text, duplicate text, extra words, distorted wheels, broken geometry, cropped car, excessive bloom, clutter, or motion.";
}
```

</details>

nix-first-2 / nix-first-3 も同等の属性セットを出力（全文は保管先の `out/nix-first-2.jsonl` / `out/nix-first-3.jsonl`）。

### 3-4. 中間プロンプトの内容に関する所見

- **JSON と Nix で中間プロンプトの意味内容はほぼ同一**。形式が変わっただけで、記述される制約・構図・照明指定は同じ語彙に収束した。「Nix の方がより良い構造化になる」という兆候は無い
- 3 run とも中間プロンプトに **自発的な「Do not reproduce the reference car」制約**が追加された。現行テンプレの TTP 意図（勝ちテンプレの複製 + 改善）と緊張関係にあるが、出力画像のレイアウト逸脱は観察されなかった
- 中間プロンプトはテンプレの `Composition rules` JSON（config 由来）の内容を英訳・詳細化して再構成しており、情報の追加というより**言い換え**に近い

## 4. 目視比較（要件 3）

評価方法: 全 9 枚をフルサイズで目視確認し、加えて 320px 相当の 3×3 モンタージュ（`out/montage-320.png`）とテキスト領域の等倍クロップ縦積み（`out/text-crops.png`）で比較した。評価は単一評価者（実験実施エージェント）による。

### 4-1. 個別評価表

◎=優 / ○=良 / △=弱い（サムネとして不採用級の破綻は 9 枚とも無し）

| run | 320px 視認性 | 文字破綻 | 構図安定性 | 備考 |
|---|:-:|:-:|:-:|---|
| baseline-1 | ◎ | なし | ◎ | 極太コンデンス sans、画面幅一杯。9 枚中最強の視認性 |
| baseline-2 | △ | なし | ◎ | 細身セリフ・ワイドトラッキング。320px で線が痩せる |
| baseline-3 | ○ | なし | ◎ | 太 sans。バランス良好 |
| json-first-1 | ○ | なし | ◎ | 中太 sans・超ワイドトラッキング。やや線が細い |
| json-first-2 | ○ | なし | ◎ | 太セリフ。読める |
| json-first-3 | △ | なし | ◎ | 細めセリフ・小さめ。中間 JSON は「bolder than thin fashion lettering」を明示したのに反映が弱い |
| nix-first-1 | ○ | なし | ◎ | 太コンデンス sans |
| nix-first-2 | ◎ | なし | ◎ | 極太コンデンス sans・暖色ホワイト |
| nix-first-3 | ○ | なし | ◎ | 太セリフ・大きめ |

### 4-2. 観点別サマリ

- **320px 視認性**: baseline ◎1/○1/△1、JSON-first ○2/△1、Nix-first ◎1/○2。**条件間の差は条件内のばらつきと同程度**で、優劣を主張できない。最強（baseline-1）と最弱（baseline-2 / json-first-3）が条件をまたいで分布する
- **文字破綻**: 9 枚とも綴り「TWILIGHT ZONE」が正確、グリフ崩れ・余計なテキスト無し。**全条件で 0 件**（差なし）
- **構図安定性**: 9 枚とも「単一車両サイドプロファイル + 上部タイトル + 純黒背景 + ウェット床反射 + アンバーリムライト」の勝ちパターンを維持。車体破綻・ホイール変形・ロゴ出現・航空機/人物の混入は無し。**全条件で満点**（差なし）
- **副次観察**: タイポグラフィの書体選択（sans / serif、太さ）は 3 条件とも run 間で揺れており、中間プロンプトで書体を明示的に指定した JSON/Nix 条件でも揺れは解消しなかった（json-first-3 は中間 JSON の指定と逆行する細字を出力）。**中間プロンプトの構造化は出力の一貫性すら担保しなかった**

### 4-3. 天井効果についての注意

現行 baseline は既に (1) TTP 参照画像、(2) 構造化済みの `Composition rules` JSON、(3) `codex-image.sh` の末尾ガード文を持つ強いプロンプトであり、本実験の 9 枚はいずれも採用可能な品質だった。ベースラインが弱い（自由文だけの短いプロンプト等）環境では構造化の効果が観測される余地があるが、**本リポジトリの codex 経路に限れば改善余地そのものが小さい**。

## 5. 結論と次アクション（要件 4）

### 5-1. 総合判定: **効果なし**

| 主張 | 出典調査 | 実測 | 判定 |
|---|---|---|---|
| JSON-first で品質向上 | 一次情報源なし（バイラルミーム）。OpenAI 公式は「形式は無差別」と明言 | 3 観点すべてで baseline と差なし。生成時間 +27%、一貫性の改善も無し。バイラル投稿型の高密度日本語広告題材でも差なし（§6） | **効果なし** |
| Nix-first でさらに向上 | 出典が存在しない（捏造/記憶違いの可能性大） | JSON-first と同内容の言い換えに収束。差なし | **効果なし** |

判定の根拠:

1. 320px 視認性・文字破綻・構図安定性のいずれでも条件間の系統的な差が観測されなかった（条件間差 < 条件内分散、n=3/条件）
2. 外部調査でも「品質そのものの向上」は第三者実測で再現されておらず、OpenAI 公式ドキュメントは形式の優劣を否定している。実測結果は外部調査と整合する
3. 本リポジトリの codex 経路は既に「TTP 参照画像 + Composition rules の JSON ブロック + ラッパーのガード文」という構造化・制約済みプロンプトであり、中間プロンプトステップは情報を追加せず言い換えるだけだった。むしろ生成時間と fair-use 消費を増やし、自発的な「reference を複製するな」制約で TTP 意図と緊張を生む副作用がある

制約（判断保留にしなかった理由も含む）: サムネ題材 1 件 + 追加検証 2 題材（§6）× n=3/条件 × 単一評価者の小規模実験であり統計的検定はしていない。ただし「大きく向上する」という元の主張に対しては、計 21 枚の実測で向上の兆候が 1 つも観測されず外部検証とも一致したため、「判断保留」ではなく「効果なし」と結論する。

### 5-2. 次アクション

- **`default_prompt_template` の変更 issue は起票しない**。JSON/Nix-first 指示の追加は品質向上のエビデンスが無く、生成時間・fair-use 消費の増加と TTP 意図との緊張という明確なコストがある
- **ADR-001（Shared prompt schema）の本番接続は再検討をトリガーしない**。「モデルに中間プロンプトを構造化させると品質が上がる」という仮説はスキーマ本番接続の後押し材料にならないことが確認された。ADR-001 は既存の Trigger（skill-config 管理見直し epic 等）を待つ現状維持とする。なお本実験は「schema で prompt を組み立てる」こと自体を否定するものではない — 外部調査が支持する構造化の利点（一貫性・再利用性・要素修正の効率）は運用面の利点であり、現行テンプレの `Composition rules` JSON ブロックはまさにその形で既に構造化されている
- 将来同種の言説を検証する場合は、天井効果を避けるため「参照画像なし・短い自由文プロンプト」のような弱いベースラインとの比較設計を推奨する

## 6. 追加検証: バイラル投稿型の高密度日本語広告題材（Round 2）

Round 1 の題材（2 語のみのサムネ）は、拡散元投稿の例（日本語コピー多数の広告ビジュアル）より単純であり、第三者検証が「複雑な多要素制御では構造化が有利な場合がある」としていたことから、拡散元の条件に寄せた追加実験を行った。

### 6-1. 設計

- **題材 A（不動産）**: 新築分譲マンション広告チラシ（見出し・駅徒歩 5 分・3LDK・4,980 万円台・ZEH・路線アクセス・内装写真・共用施設アイコン・資料請求ボタンを指定）— 拡散元の引用ポスト例の再現
- **題材 B（化粧品）**: 化粧水広告（メインコピー・日本人女性モデル・商品ボトル・ポイント表示・注記を指定）— 拡散元オリジナル投稿例の再現
- **条件**: baseline（要素を列挙した日本語自然文のみ）/ JSON-first（同文 + 拡散元とほぼ同じ言い回し「まず、使用する完全な画像生成プロンプトを JSON 形式で出力してから、その JSON に忠実に画像生成して」）の 2 条件 × 各 3 枚 × 2 題材 = 12 枚。参照画像なし（拡散元の利用形態に合わせる）。Nix は出典なしと確定済みのため省略
- 生成経路は Round 1 と同一（`codex exec --json` + 末尾ガード文）。プロンプト・JSONL・生成物は `round2/` として同じ保管先に格納

### 6-2. 結果

全 12 run 成功（1 run は codex agent の cp 失敗により `~/.codex/generated_images/` から回収）。平均生成時間: 不動産 baseline 約 221s / JSON-first 約 250s（+13%）、化粧品 baseline 約 170s / JSON-first 約 234s（+38%）。JSON-first 条件は 6 run すべてで有効な中間 JSON を出力した（全文は保管先 JSONL）。

| 観点 | baseline (6 枚) | JSON-first (6 枚) | 差 |
|---|---|---|---|
| 大見出し・メインコピーの文字破綻 | 0 件 | 0 件 | なし |
| 注記・スペック表など微細日本語の破綻 | ほぼなし（等倍で判読可能） | ほぼなし（等倍で判読可能） | なし |
| 指定要素の充足（見出し/価格/アイコン等） | 全枚数でほぼ充足 | 全枚数でほぼ充足 | なし |
| レイアウトの広告らしさ・情報密度 | 高い | 高い（QR コード・物件概要表など「足していない要素」の自発的追加が 3/6 枚でやや多い） | 系統差といえるほどではない |

「段違いに上がる」は再現されなかった。両条件とも拡散元投稿の「良い方（右）」に相当する品質が安定して出ており、拡散元の「悪い方（左）」に相当する崩れは一度も発生しなかった。

### 6-3. 解釈: バイラル例の差はフォーマットではなく情報量で説明できる

本実験の baseline は「必要要素を列挙した詳細な自然文」であり、それだけで JSON-first と同等の結果が得られた。拡散元投稿は左右の生成プロンプト全文を示していないため、あの比較の「悪い方」は要素指定の少ない短文プロンプト由来である可能性が高い。「JSON を書かせる」指示の実効は、モデルに要素を網羅させる**プロンプト詳細化の強制**にあり、それは詳細な自然文でも同等に達成できる — これは OpenAI 公式の「意図と制約が明確ならどの形式でも良い」と完全に整合する。

なお thumbnail スキル運用への示唆も同じで、codex 経路のテンプレは既に `Composition rules` として要素を網羅しているため、JSON-first ステップを足しても網羅性は増えず、生成時間だけが増える（Round 1 の結論を補強）。

## 付録: 再現手順

生成物・JSONL ログ・実験スクリプト・3 条件のプロンプト全文は `~/02-yt/yt-research/experiments/2078-codex-json-first/` に保管。`run_experiment.sh` は `codex-image.sh` と同一の起動形態（`codex exec --json --sandbox workspace-write --image <ref>` + 末尾ガード文）で、中間プロンプト記録のため JSONL 全量を保存する点だけが異なる。
