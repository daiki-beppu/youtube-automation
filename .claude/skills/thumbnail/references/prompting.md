# Thumbnail プロンプト構築の原則

SKILL.md「プロンプト構築」セクションから移植（内容改変なし・移動のみ）。具体的なプロンプトテンプレート例は `sample-prompts.md` を参照。

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
