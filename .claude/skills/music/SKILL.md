---
name: music
purpose: 作る
description: "Use when 音楽制作を状態判定付きで一括実行または一段だけ実行するとき。Suno UI 投入用の Style / プロンプト生成は --prompt、ボーカル曲の歌詞生成は --lyric を使う。「音楽制作」「Suno プロンプト」「歌詞生成」「vocal」「rap」で発動。Suno UI 投入・マスター化は後続 mode で統合予定。Lyria チャンネルは /lyria を使う"
---

## 前後工程

- `前工程`: `/channel-strategy --constraints`
- `後工程`: `/suno-helper`, `/masterup`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `collections/<id>/20-documentation/suno-patterns.yaml`, `collections/<id>/20-documentation/suno-prompts.md`, `collections/<id>/20-documentation/suno-prompts.json`, `collections/<id>/20-documentation/suno-lyrics.md`, `collections/<id>/20-documentation/suno-lyrics.json`, `collections/<id>/workflow-state.json`
- `読み込む`: `docs/channel/creative-constraints.md`, `docs/channel/personas/persona-definition.md`, `data/video_analysis/<channel>/*.json`, `data/insights.jsonl`, `config/skills/music.yaml::prompt`, `config/skills/music.yaml::lyric`

## モード判定

`$ARGUMENTS` から、下表に登録された mode flag の個数を最初に数える。同じ flag の重複も別々に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い状態判定付きで進める
- 現段で実装済みの mode は `--prompt` / `--lyric`。`--generate` / `--master` は後続段で追加する予約名であり、現段では未知の mode として停止する
- mode は最大 5 件とし、判定規則を複製しない

| mode | 読む reference |
|---|---|
| `--prompt` | `references/prompt.md` |
| `--lyric` | `references/lyric.md` |

## 共通前提

対象 collection を 1 件に確定する。確定できない場合は候補を示して停止する。`config/channel/` が存在し `load_config()` でロード可能であること。

- **新規チャンネル** → `/setup --channel` を案内
- **既存チャンネル**（設定不整合）→ `/setup --import` を案内

## 設定読み込みゲート

`--prompt` は次を deep-merge し、チャンネル上書きを優先する。

1. `.claude/skills/music/config.default.yaml::prompt`
2. `config/skills/music.yaml::prompt`（存在する場合）

loader は `load_skill_config("music.prompt")` を使う。存在しない override は勝手に作成しない。旧 `config/skills/suno.yaml` と `load_skill_config("suno")` は互換入口として維持するが、新規生成先にはしない。既存の旧 config は `uv run yt-skills migrate-config --channel-dir . --dry-run` で差分を確認し、明示 apply した場合だけ `config/skills/music.yaml::prompt` へ移す。

`--lyric` は `.claude/skills/music/config.default.yaml::lyric` と `config/skills/music.yaml::lyric` を同様に deep-merge し、`load_skill_config("music.lyric")` を使う。旧 `config/skills/suno-lyric.yaml` と `load_skill_config("suno-lyric")` は互換入口として維持し、明示 migration 時だけ `config/skills/music.yaml::lyric` へ移す。

## 一括実行

`references/music-chain-manifest.json` と `references/music-chain-state.py` を検証する。本段の chain は `prompt` → `lyric` の 2 step で、後続段が `generate` / `master` を追加する。

```bash
uv run python .claude/skills/music/references/music-chain-state.py \
  --collection-path <collection-path> --step <prompt|lyric>
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | 対象 mode の成果物が存在するため完了済みとして終了する |
| 10 | `run` | 対応する reference を読み、その一段を実行する |
| 20 | `blocked` | prerequisite / music engine / 歌詞要否の前提未達として停止する |
| その他 | `error` | manifest / collection path / script のエラーとして停止する |

実行後は同じ状態判定を再実行し、exit 0 にならなければ完了扱いにしない。途中失敗時はその段で止め、再発動時は同じ判定から安全に再開する。

## 完了条件

- フラグなし: `prompt` と、必要な場合の `lyric` が `skip` または実行後 `skip` になっている
- `--prompt`: `references/prompt.md` の完了条件を満たし、他の mode を実行していない
- `--lyric`: `references/lyric.md` の完了条件を満たし、他の mode を実行していない

実行段、skip 段、対象 collection、更新成果物を短く報告する。
