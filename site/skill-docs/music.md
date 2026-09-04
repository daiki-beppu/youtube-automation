## 何ができるか

音楽制作の 4 工程 — プロンプト生成 → 歌詞 → 音源生成 → マスター化 — を、collection の進み具合を見ながら自動で進めるスキルです。チャンネルの `music_engine`（Suno / Lyria）を読み取り、その engine に必要な段だけを実行します。すでに終わっている段は自動で skip されるので、途中で失敗しても同じ呼び出しで安全に再開できます。

| mode | すること | 主な成果物 |
|---|---|---|
| `--prompt` | Suno UI 投入用の Style / プロンプトを生成 | `suno-prompts.json` / `suno-prompts.html` ほか |
| `--lyric` | Suno ボーカル曲の歌詞を生成 | `suno-lyrics.md` / `suno-lyrics.json` |
| `--generate` | `music_engine` に応じた音源生成 | `02-Individual-music/*`（Lyria は `master.mp3` まで） |
| `--master` | Suno 音源の一括 DL とマスター化 | `01-master/master.mp3` |

## 使いどころ

- **新しい collection の音楽をまとめて作りたい** — フラグなしの `/music` で、状態判定つきの一括実行に任せる
- **Suno に貼るプロンプトだけ作り直したい** — `/music --prompt` で一段だけやり直す
- **ボーカル曲の歌詞を先に固めたい** — `/music --lyric`（instrumental の collection では不要と判定されて止まります）
- **音源だけ再生成したい・マスターだけ作り直したい** — `/music --generate` / `/music --master`

## 実行例

```
/music             # 状態判定つき一括実行。必要な段だけ進める
/music --prompt    # Suno UI 投入用のプロンプトだけ生成する
/music --lyric     # ボーカル曲の歌詞だけ生成する
/music --generate  # engine に応じた音源生成だけ実行する
/music --master    # Suno 音源の一括 DL とマスター化だけ実行する
```

## つまずいたら

- **blocked と言われて止まる** — 前提の `creative-constraints.json` や persona が未整備です。先に `/channel-strategy --constraints` を実行してください
- **`--lyric` が「歌詞不要」と言って止まる** — instrumental の collection と Lyria では歌詞は使いません。そのまま `--generate` に進んで問題ありません
- **`--master` が何もしない** — Lyria は `--generate` が `master.mp3` まで直接作るため、マスター化は完了済みとして skip されます
- **どの collection が対象か聞かれる** — 対象 collection を 1 件に確定できないときは候補を提示して止まります。collection を指定して再実行してください
