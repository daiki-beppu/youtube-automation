# Thumbnail プロンプト構築の原則

SKILL.md「プロンプト構築」セクションから移植（内容改変なし・移動のみ）。具体的なプロンプトテンプレート例は `sample-prompts.md` を参照。

## 0. TTP 方針は provider 共通（#2070）

参照サムネを winning template として扱い、winning layout を維持したまま品質改善のみを指示する TTP 方針は gemini / codex で共通。正（SSOT）は SKILL.md codex 節の「既定テンプレート」と `config.default.yaml` の `image_generation.codex.default_prompt_template`。gemini 側の既定 `diff_prompt_template` はこの方針行と同期されており、チャンネル側 override（`config/skills/thumbnail.yaml`）が常に優先される。

## 1. prompt_prefix を取得

`image_generation.gemini.prompt_prefix` をプロンプト冒頭に配置。

## 2. fixed_character から活動を組み立て

`image_generation.gemini.fixed_character` がある場合:
- `outfit`: 服装描写
- `instrument`: 楽器（テーマに応じて持ち替え可なら変更）
- `face`: 顔の向き指示

## 3. composition_rules から環境・制約を適用

- `environment`: 許可される環境
- `allowed_actions`: 使える活動
- `ng_actions`: 禁止パターン
- `brightness`: 明るさルール
