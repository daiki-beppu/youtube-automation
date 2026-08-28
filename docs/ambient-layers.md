# 環境音レイヤーを重ねる

完成したマスター音源に、雨音などの環境音を重ねられます。音楽だけでは空間が静かすぎるときや、作業・睡眠向けの雰囲気を加えたいときに、マスターを作り直さず仕上げの工程で環境音を合成できます。

チャンネル全体で共通の音量を使う方法と、Audio Studio でファイルごとに調整する方法があります。

## できること

- 雨音などの WAV をマスター音源の長さに合わせて重ねる
- チャンネル共通の音量とフェードインを skill-config で調整する
- Audio Studio で環境音ごとの値を調整し、マスターを再出力する
- 環境音が用意されていないチャンネルでは、従来どおりマスター音源をそのまま使う

## 始める前に

チャンネルリポジトリの `branding/rain_layers/` に、`rain_*.wav` という名前の環境音ファイルを配置します。たとえば `branding/rain_layers/rain_window.wav` が対象になります。

対象ファイルが 0 件、またはディレクトリが無い場合、finalize は正常終了し、`master.mp3` を変更しません。環境音レイヤーを使わないチャンネルへの影響はありません。

探索先のディレクトリ名とファイル名のパターンは skill-config の `audio.finalize.ambient_layers.dirname` と `audio.finalize.ambient_layers.glob` で変更できます。

## `/music --master` で重ねる

環境音を配置したら、コレクションのマスター化を `/music --master` で実行します。この工程では内部で `yt-finalize-master` が呼ばれ、環境音を合成した結果で `01-master/master.mp3` を更新します。

```text
/music --master
```

コマンドを直接使う場合は、コレクションディレクトリで次を実行します。

```bash
uv run yt-finalize-master
```

別の場所から実行するときは、対象コレクションのパスを引数に渡します。

```bash
uv run yt-finalize-master <collection-path>
```

## 音量とフェードインを調整する

チャンネル共通の仕上がりは、skill-config の `audio.finalize.ambient_layers.*` で調整します。主に使う値は次のとおりです。

- `volume_db`: すべての環境音に適用する音量
- `fadein_s`: 再生開始時のフェードイン時間
- `fadein_curve`: フェードインのカーブ
- `layers.<filename>`: 特定の WAV だけに適用する上書き値

設定できる全項目、既定値、記述例は [music skill のマスター化手順](../.claude/skills/music/references/master.md#step-55-ambient-レイヤー整音オプション)を参照してください。

ファイルごとに聞き比べながら調整したい場合は Audio Studio を使います。Audio Studio で環境音ごとの音量やフェードインを変更して保存すると、`20-documentation/audio-adjustments.json` の `finalize` に値が記録され、その内容からマスターを再出力できます。

Audio Studio に保存された `audio-adjustments.json::finalize` の値は skill-config より優先されます。まず skill-config でチャンネル共通の基準を決め、個別に整えたいコレクションだけ Audio Studio で上書きすると、どの設定が使われるかを判断しやすくなります。
