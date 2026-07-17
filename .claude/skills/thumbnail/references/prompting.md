# Thumbnail プロンプト構築の原則

SKILL.md「プロンプト構築」セクションの補足。具体的なプロンプトテンプレート例は `sample-prompts.md` を参照。

## 0. TTP 方針は provider 共通（#2070）

参照サムネを winning template として扱い、winning layout を維持したまま品質改善のみを指示する TTP 方針は gemini / codex で共通。正（SSOT）は SKILL.md codex 節の「既定テンプレート」と `config.default.yaml` の `image_generation.codex.default_prompt_template`。gemini 側の既定 `diff_prompt_template` はこの方針行と同期されており、チャンネル側 override（`config/skills/thumbnail.yaml`）が常に優先される。

## 1. prompt_prefix を取得

`image_generation.gemini.prompt_prefix` をプロンプト冒頭に配置。

## 2. fixed_character から活動を組み立て

`image_generation.gemini.fixed_character` がある場合:
- `outfit`: 服装描写
- `instrument`: 楽器（テーマに応じて持ち替え可なら変更）
- `face`: 顔の向き指示

## 3. composition_rules から制約を適用

既定で残る実効キーは `text_lines`（タイトル行数の制約）のみ (#1702)。旧個別キー
（`environment` / `character_size` / `character_pose` / `allowed_actions` /
`ng_actions` / `background` / `channel_branding`）は deprecated で、構図・環境の
意図はチャンネル側 override の `diff_prompt_template` 本文に短い文で直接書く。
override に残っている deprecated キーは当面 deep-merge され続けるが、config
ロード時に DeprecationWarning が出る。
