---
title: "Chrome 拡張 ext-v0.2.5"
version: ext-v0.2.5
released_at: 2026-07-10
kind: extension
summary: "Suno の日本語表示で入力欄やスライダーを検出できない問題を修正"
sidebar:
  order: -2026071001
---

## 30 秒サマリー

- Suno Helper を更新しました。DistroKid Helper は前回から変更ありません。
- Suno を日本語表示で使うと入力欄やスライダーを検出できず、実行が止まる問題を修正しました。
- 初回インストールも更新も、チャンネルリポジトリで `/ext-install` を実行すれば案内されます。

## アップデート方法

ご自身のチャンネルリポジトリで次を実行してください。

```text
/ext-install
```

導入済みの拡張と最新リリースを確認し、必要なファイルの取得、展開、Chrome での読み込みや更新後の動作確認まで案内します。

## 新機能

新しい操作の追加はありません。今回は Suno Helper の日本語表示対応を安定させるリリースです。

## 改善

- Suno Helper を更新対象とし、DistroKid Helper は既存バージョンをそのまま利用できます。
- 日本語と英語のどちらの表示でも同じ操作手順を使えるようにしました。

## 直った不具合

- Suno を日本語表示にすると、Exclude Styles の入力欄を見つけられず停止する問題を修正しました。
- Weirdness と Style Influence のスライダーを、日本語表示のラベルでも検出できるようにしました。

更新後も動作が変わらない場合は、Chrome の拡張機能画面で Suno Helper をリロードしてから再実行してください。

## 詳しい変更内容

[GitHub Release でダウンロードと変更内容を確認する](https://github.com/daiki-beppu/youtube-automation/releases/tag/ext-v0.2.5)
