# review 用 HTML で音源と動画を確認する

制作 workflow の途中では、マスター音源やマスター動画を採用する前に、ブラウザで開く review 用 HTML が生成されます。このページは成果物そのものではなく、候補の情報を見比べて合否を判断するための表示専用ビューアです。

音源 review と動画 review のどちらも、表示された内容を確認して同じ実行セッションへ選択・合否を返します。HTML を編集したり保存したりしても、制作状態や成果物は更新されません。

## できること

- マスター音源の候補 ID、source、duration、loudness 検査、選曲情報を一覧で比較する
- 動画の preview または full を再生し、完成前後の見た目と再生情報を確認する
- ブラウザで判断材料を確認してから、採用する音源や動画の合否を workflow へ返す
- 正本を変更せず、同じ時点の情報から review 画面を再生成する

## 始める前に

review 用 HTML は表示専用の snapshot です。音源側の正本は音声ファイル、loudness receipt、selection log、`workflow-state.json` であり、`tmp/reviews/master-audio.html` は `yt-master-audio-review` の実行ごとに再生成されます。

安全のため、HTML やブラウザ側から任意の path、command、state patch は受け付けません。画面を保存・共有しても制作状態は保存されず、ブラウザ上の操作だけで正規 master が置き換わることもありません。合否は、review を開始した Codex / Claude の同じセッションへ返してください。

## 音源を review する

`/wf-next` で prepared から mastered へ進むとき、`yt-master-audio-review` が `tmp/reviews/master-audio.html` を生成します。

```text
/wf-next
```

HTML には候補 ID、source、ファイル名、形式、duration、size、loudness 検査、選曲情報が並びます。音量検査の結果と選曲の意図を見比べ、採用する候補を選んで同じセッションへ返します。worktree と main に同名候補がある場合も、source の表示で区別できます。

詳しい検査項目、失敗時の扱い、ブラウザを使えない場合の手順は[マスター音源 review の運用手順](../.claude/skills/music/references/master-audio-review.md)を参照してください。

## 動画を review する

`/video --generate` は `generate.review.preview_required` の設定に従い、短尺の preview または完成した full を `yt-master-video-review` へ渡します。

```text
/video --generate
```

`preview_required: true` では全尺生成前の preview を確認し、承認後に full の生成へ進みます。動画 review の HTML では動画を再生し、duration、resolution、codec、filesize、背景経路、effect、overlay などを確認できます。full では完成動画として問題がないかを確認し、合否を同じセッションへ返します。

preview / full の保存場所、承認時の状態更新、terminal fallback の詳細は[マスター動画 review の運用手順](../.claude/skills/video/references/master-video-review.md)を参照してください。

## review の進め方を調整する

まずは `/wf-next` または `/video --generate` が提示する HTML のリンクを開き、表示された確認項目に沿って判断してください。ブラウザを利用できない環境では、review を開始した同じセッションへその旨を伝えると terminal 経路で確認できます。ブラウザを開けないことを理由に、自動承認として扱うことはありません。

preview の有無などを変える場合は、画面そのものではなく workflow の設定を変更します。設定値や承認スキップを含む詳細な運用手順は、このガイドではなく上記の各 skill reference を正本としてください。
