# Audio Studio で音を調整する

> **実験的機能です。** 原本の退避を確認し、少数の音源で仕上がりを比較してから利用範囲を広げてください。

マスター音源を作ったあとに曲ごとの音量差や質感が気になったら、Audio Studio のローカル web UI で音を聴きながら調整できます。個別の曲と完成した `master.mp3` を同じ画面から確認し、設定を保存して再出力できます。

## できること

- 曲ごとに EQ・音量補正などを即時プレビューする
- 曲ごとの設定を保存し、その曲だけマスター化時の既定値から差分上書きする
- master 全体の EQ・loudnorm・limiter を調整する
- 保存した master 全体の設定を、退避済みの原本から何度でも適用し直す

## 始める前に

マスター化まで進めたコレクションを用意してください。曲単位の調整には `02-Individual-music/` の音源、master 全体の調整には `01-master/master.mp3` を使います。

Audio Studio は手元の PC だけで動く web UI です。公開サーバーへアップロードする必要はありません。

## Audio Studio を使う

コレクションディレクトリで次を実行します。

```bash
uv run yt-audio-studio
```

別の場所から起動する場合はコレクション path を指定します。path を省略したときは、現在の作業ディレクトリ（CWD）が対象です。

```bash
uv run yt-audio-studio <collection-path>
```

必要に応じて次のオプションを選べます。

- `--port <番号>`: 使用する port を変更する
- `--no-open`: 起動時にブラウザを自動で開かない
- `--stop`: 同じコレクションと port で動いている Audio Studio を停止する

## 曲単位で調整する

曲を選び、再生しながら EQ などを調整して保存します。設定は `20-documentation/audio-adjustments.json` の `tracks.<filename>` に記録され、マスター化の cleanup では対象の曲だけ skill-config の設定を差分上書きします。

UI の EQ は Web Audio による即時プレビューです。保存した設定を音源へ確定するときは、マスター化工程で表示・実行される ffmpeg filter が正になります。詳しい適用手順と設定値は [master 化の手順](../.claude/skills/music/references/master.md)を参照してください。

## master 全体を調整する

master 全体の EQ・loudnorm・limiter を調整して保存しただけでは、`master.mp3` の音は変わりません。保存後に次を実行して設定を適用します。

```bash
uv run yt-master-adjust
```

別の場所から実行する場合は、コレクション path を指定できます。

```bash
uv run yt-master-adjust <collection-path>
```

初回適用前の master は `01-master/originals-pre-adjust/master.mp3` へ退避されます。再適用するときも常にこの原本から出力するため、調整は累積せず、繰り返すたびに音が痩せることはありません。

設定の保存場所、ambient レイヤーとの適用順、失敗時の挙動は [master 化の手順](../.claude/skills/music/references/master.md)を参照してください。
