# Thumbnail プロンプト例（サンプル集）

TTP 参照からテキスト付き thumbnail 候補を生成し、承認済み thumbnail から textless 背景を再生成するための短いプロンプト例。プロンプト構築の原則は `prompting.md` を参照。

## Single-Step / TTP の短い差分プロンプト

```
Use the reference thumbnail as the winning template.
Create a stronger original YouTube thumbnail for {title}.
Keep the winning layout, scale, lighting, color mood, texture, typography feel, and energy.
Render the title text clearly for mobile readability.
Do not reproduce logos, signatures, watermarks, brand marks, or broken hands.
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
