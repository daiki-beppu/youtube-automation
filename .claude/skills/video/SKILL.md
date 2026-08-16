---
name: video
purpose: 作る
description: "Use when 音源と画像からマスター動画と YouTube 概要欄を作るとき。フラグなしは generate→describe を状態判定付きで進め、一段だけは排他的な --generate / --describe を使う。YouTube へのアップロードは公開系 skill の責務"
---

## 前後工程

- `前工程`: `/wf-new`, `/music --master`, `/music --generate`, `/thumbnail --loop`
- `後工程`: `/publish --upload`, `/audit --metadata`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `collections/<id>/01-master/*.mp4`, `collections/<id>/20-documentation/descriptions.json`, `collections/<id>/20-documentation/descriptions.html`, `collections/<id>/workflow-state.json`
- `読み込む`: `collections/<id>/01-master/<master-audio>`, `collections/<id>/10-assets/main.png`, `collections/<id>/10-assets/main.jpg`, `collections/<id>/10-assets/loop.mp4`, 検証済み `collections/<id>/20-documentation/suno-prompts.json`, `data/benchmark_*.json`, 検証済み `docs/benchmarks/benchmark-report.json`, `config/channel/*.json`, `config/skills/video.yaml`

## モード判定

`$ARGUMENTS` から `--generate` と `--describe` の指定個数を最初に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い状態判定付きで進める

| mode | 読む reference |
|---|---|
| `--generate` | `references/generate.md` |
| `--describe` | `references/describe.md` |

## 設定読み込みゲート

skill-config は次を deep-merge する。

1. `.claude/skills/video/config.default.yaml`
2. `config/skills/video.yaml`（存在する場合）

合成規則は `load_skill_config("video")` と同じで、チャンネル上書きを優先する。生成 mode は `generate:`、概要欄 mode は `describe:` 節を使う。存在しない override は未設定として扱い、勝手に作成しない。互換 loader key `load_skill_config("videoup")` / `load_skill_config("video-description")` はそれぞれ同じ default の `generate:` / `describe:` 節を返す。旧 `config/skills/videoup.yaml` または `config/skills/video-description.yaml` が残っている場合は、`yt-skills migrate-config --channel-dir <channel-dir>` で `video.yaml` の対応節へ移行してから実行する。

## 一括実行

`references/video-chain-manifest.json` と `references/video-chain-state.py` の存在と、manifest の `chainId`、step、mode、approval gate、状態判定 script を検証する。欠損、未知・重複 step、複数 mode、`approvalGate.skip != true` があれば停止する。

manifest 順に各 step を対象 collection で実行する。

```bash
uv run python .claude/skills/video/references/video-chain-state.py \
  --collection-dir <collection-path> --step <generate|describe>
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | 完了済みとして終了する |
| 10 | `run` | step に対応する `references/generate.md` / `references/describe.md` を読み、成果物を生成する |
| 20 | `blocked` | `reason` と不正な state を提示して停止する |
| その他 | `error` | state / manifest / script のエラーとして停止する |

実行後は同じ状態判定を再実行し、exit 0 にならなければ停止する。次 step は直前 step が exit 0 の場合だけ開始する。途中失敗時は成果物を完了扱いせず、再発動時に同じ判定から再開する。

## 完了条件

- フラグなし: generate → describe の両方が `skip` または実行後 `skip` になっている
- `--generate`: `references/generate.md` の完了条件を満たし、他 mode を実行していない
- `--describe`: `references/describe.md` の完了条件を満たし、他 mode を実行していない

実行段、skip 段、生成した master video / descriptions.json + descriptions.html pair のパスを短く報告する。
