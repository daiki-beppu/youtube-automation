# generation workflow 詳細

`SKILL.md` の生成モード判定後に読む補足。実行コマンド、生成順序、コスト確認、承認・完了ゲートは `SKILL.md` を正とする。

## 参照画像の選択とローテーション

`reference_images.default` には同じベンチマークチャンネル内の別サムネイルを並べる。`--max-attempts N` では N 枚以上のユニーク参照を用意し、attempt ごとに別の 1 枚を使う。`--reference-index N` を明示したときだけ単一参照に固定し、attempt 数も 1 にする。

`path_base: "channel_dir"` の場合、設定値はチャンネルディレクトリを基準に解決する。`reference_images.dedup_recent_collections` は過去 collection の `thumbnail-prompts.md` にある `Reference Assignments` を履歴とし、参照プールが候補数より大きいときに先頭候補の早期再利用を避ける。別チャンネルや stock 画像は TTP 参照プールと別スコープにし、採用元を記録する。

## プロンプト構築

**原則: 参照画像主導 + 最小限のキーワード。** TTP では勝ちパターンを参照画像が運ぶ。プロンプトにはテーマ・主題・スタイルなど最小限のキーワードと、必要なタイトルだけを書く。

**既定の組み立て（provider 共通）:**

1. `image_generation.gemini.diff_prompt_template`（TTP 方針行 + `{title_line1}` / `{title_line2}`）のプレースホルダを置換する
2. 既定で展開する clause は `${ip_safety_clause}` の 1 つだけ（TTP で常時挿入必須）

opt-in clause（`variation_clause` / `style_lock_clause` / `anatomy_clause` / `typography_clause`）は既定空文字。必要なチャンネルだけ override に本文を設定し、自前の `diff_prompt_template` で展開する。`text_strip_clause` は textless main 再生成専用の非空既定値を持ち、`${text_strip_clause}` で展開する。複数の clause を同時に積み上げない。バリエーション、スタイル固定、テキスト除去を同時に強く指示すると、参照画像の支配力が薄れる。

**最終プロンプト例（TTP / 既定 config でプロバイダーへ渡る全文）:**

```text
TTP this reference thumbnail, then improve it into a stronger original thumbnail.
Keep the winning layout, typography feel, character scale, color mood, texture, and energy.
Make it cleaner, more readable on mobile, stronger face impact, no logos, no watermarks, no broken hands.
Use the title Midnight Jazz Rainy Tokyo Mood.
Do not reproduce any signature, autograph, handwritten name, watermark,
logo, brand mark, channel badge, copyright notice, or identifying mark
from the reference image. Keep all corners clean and free of such marks.
```

**モード別差分:**

- single_step は既定の組み立てを使う。
- textless main 再生成は承認済み `thumbnail.jpg` を参照し、`text_strip_clause` または同等の除去指示だけを足す。
- two_phase は `thumbnail_text.text_overlay_prompt` を単一の入口とする。

## Single-Step / TTP 詳細

TTP 生成方針は provider によらず共通。参照サムネを winning template とし、winning layout を維持したまま mobile readability / face impact / no logos / no watermarks / no broken hands の品質改善だけを指示する。`config.default.yaml` の既定 template と codex 既定 template はこの方針行を共有し、チャンネル側 override があればそちらを優先する。

各 provider は同じ `diff_prompt_template` とこの構築手順を共有し、ラッパーは prompt の方針を変えない。カラーテーマ、オブジェクト、タイトルの placeholder を入力から展開し、IP safety を必須にする。手や指が壊れる構図だけ `anatomy_clause` を opt-in clause として追加する。

collection 間のローテーションでは最近の `Reference Assignments` を見て参照の偏りを抑える。同じ attempt 内の重複と、候補数より少ない参照プールはエラーとする。

## Two-Phase 詳細

Phase 1 では既存画像を Phase 2 の参照素材としてだけ選び、この時点で `main.png/jpg` として確定しない。Phase 2 でテキスト付き候補を作り、Phase 3 で承認済み `thumbnail.jpg` から textless main を作る。

`thumbnail_text.text_overlay_prompt` があれば `{title_line1}` / `{title_line2}` / `{channel_name}` を置換する。未定義なら `references/sample-prompts.md` の「Two-Phase モードのテキストオーバーレイ・フォールバックプロンプト」を使う。旧個別フィールドは deprecated であり、位置・色・装飾は `text_overlay_prompt` 本文に直接書く。
