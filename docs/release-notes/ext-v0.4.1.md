---
title: "Chrome 拡張 ext-v0.4.1"
version: ext-v0.4.1
released_at: 2026-09-10
kind: extension
summary: "Sunoの曲採用、停止、Studio Libraryの読み込みを修正。3拡張のZIPを配布"
sidebar:
  order: -2026091001
---

## 30 秒サマリー

- Suno Helper 0.4.1、DistroKid Helper 0.3.1、Community Helper 0.3.0 を収録しています。
- Sunoの曲採用での取りこぼしや重複、停止後に処理が進む問題を修正しました。
- DistroKid Helper と Community Helper は現行版の同梱です。

## アップデート方法

各チャンネルリポジトリで実行します。

```text
/extension
```

導入状態とリリース版数を比較し、必要なインストールや更新を案内します。手動取得が必要な場合は、[拡張インストールガイド](/chrome-extension-install-guide/)を参照してください。

## 新機能

今回のリリースは既存機能の修正が中心です。

## 改善

- 選択曲の採用とPlaylist選択の走査は、全体で60秒を上限とします。長い一覧では対象曲の一覧を開き直すよう案内します。
- 3拡張のChrome用ZIPを同じGitHub Releaseから取得できます。

## 直った不具合

- 狭い曲一覧でも対象曲を飛ばさず、タイトル照合後の二重計上と画面外の余剰選択を検出するようにしました。
- 選択曲の採用を同時に実行できないようにしました。停止後に再採用でき、中断時に部分結果を成功として返しません。
- ダウンロード監視の準備中に停止した場合は、Studio export を開始せず監視を解除します。
- Studio Libraryの遅延読み込みを待ち、曲数が多いと対象曲が見つからずMultitrack exportが止まる問題を修正しました。

## 詳しい変更内容

[ext-v0.4.1 の GitHub Release](https://github.com/daiki-beppu/youtube-automation/releases/tag/ext-v0.4.1) を参照してください。
