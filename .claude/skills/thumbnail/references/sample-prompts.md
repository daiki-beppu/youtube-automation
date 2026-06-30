# Thumbnail プロンプト例（サンプル集）

SKILL.md 内に散在していたプロンプト例を集約（内容改変なし・移動のみ）。プロンプト構築の原則は `prompting.md` を参照。

## Single-Step / TTP の短い差分プロンプト

```
Use the reference thumbnail as the winning template.
Create a stronger original thumbnail for {title}.
Keep the readable layout, scale, lighting, and energy.
Change the subject details, concrete objects, colors, and marks.
No logos, signatures, watermarks, brand marks, or near-copy.
```

## Two-Phase モードのテキストオーバーレイ・フォールバックプロンプト

`thumbnail_text.text_overlay_prompt` が未定義の場合のフォールバック:

```
Add text to this image. Add two lines of text in a classic serif font.
First line smaller: '<Title Line 1>' in light weight.
Second line larger and bolder: '<Title Line 2>' directly below with
almost no line spacing. Both lines in <color>.
Below the title, add '<channel_name>' in very small spaced-out small
caps, slightly more transparent. No decorations — only clean text.
Do not change the background image in any way.
```
