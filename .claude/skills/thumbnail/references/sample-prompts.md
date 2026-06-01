# Thumbnail プロンプト例（サンプル集）

SKILL.md 内に散在していたプロンプト例を集約（内容改変なし・移動のみ）。プロンプト構築の原則は `prompting.md` を参照。

## 参照画像モードのプロンプトテンプレート（Single-Step / TTP・参照画像モード）

```
{prompt_prefix}, {表情}.
She/He/It wears {outfit}. {ポーズ・活動}. {環境描写}.
{光と雰囲気}. {face}.
No text, no words, no letters, no typography.
```

## プロンプトベースモードの末尾スタイル句

`reference_images` がない場合、スタイル句を末尾に付加する。
チャンネル `CLAUDE.md` にスタイル句指定があればそれを使用。なければデフォルト:

```
Hyper-detailed digital matte painting blending photorealism with subtle painterly
illustration touches. Widescreen 16:9 aspect ratio.
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
