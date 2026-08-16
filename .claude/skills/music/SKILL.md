---
name: music
purpose: 作る
description: "Use when 音楽制作を状態判定付きで一括実行または一段だけ実行するとき。Suno UI 投入用の Style / プロンプト生成は --prompt、Suno / MiniMax ボーカル曲の歌詞生成は --lyric、music_engine に応じた音源生成は --generate、Suno 音源の一括 DL とマスター化は --master を使う。「音楽制作」「Suno プロンプト」「歌詞生成」「Suno 連続生成」「MiniMax vocal」「Lyria」「マスター化」「vocal」「rap」で発動"
---

## 前後工程

- `前工程`: `/channel-strategy --constraints`
- `後工程`: `/video --generate`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `collections/<id>/20-documentation/suno-patterns.yaml`, `collections/<id>/20-documentation/suno-prompts.json`, `collections/<id>/20-documentation/suno-prompts.html`, `collections/<id>/20-documentation/suno-lyrics.md`, `collections/<id>/20-documentation/suno-lyrics.json`, `collections/<id>/20-documentation/lyria-prompt.json`, `collections/<id>/20-documentation/lyria-prompt.html`, `collections/<id>/02-Individual-music/*`, `collections/<id>/01-master/master.mp3`, `collections/<id>/workflow-state.json`
- `読み込む`: 検証済み `docs/channel/creative-constraints.json`, `docs/channel/personas/persona-definition.json`, `data/video_analysis/<channel>/*.json`, `data/insights.jsonl`, `config/channel/youtube.json::music_engine`, `config/skills/music.yaml::prompt`, `config/skills/music.yaml::lyric`, `config/skills/music.yaml::generate`, `config/skills/suno-helper.yaml`, `config/skills/lyria.yaml`

## モード判定

`$ARGUMENTS` から、下表に登録された mode flag の個数を最初に数える。同じ flag の重複も別々に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い状態判定付きで進める
- 現段で実装済みの mode は `--prompt` / `--lyric` / `--generate` / `--master`
- mode は最大 5 件とし、判定規則を複製しない

| mode | 読む reference |
|---|---|
| `--prompt` | `references/prompt.md` |
| `--lyric` | `references/lyric.md` |
| `--generate` | `references/generate.md` |
| `--master` | `references/master.md` |

## 共通前提

対象 collection を 1 件に確定する。確定できない場合は候補を示して停止する。`config/channel/` が存在し `load_config()` でロード可能であること。

prompt文書の保存・表示・既存Markdown移行・state更新は `references/music-prompt-documents.md` を正本とする。Suno/Lyriaとも verify と semantic review の成功前にHTMLまたは `assets.music_prompts` を成功扱いで更新しない。

- **新規チャンネル** → `/setup --channel` を案内
- **既存チャンネル**（設定不整合）→ `/setup --import` を案内

## 設定読み込みゲート

`--prompt` は次を deep-merge し、チャンネル上書きを優先する。

1. `.claude/skills/music/config.default.yaml::prompt`
2. `config/skills/music.yaml::prompt`（存在する場合）

loader は `load_skill_config("music.prompt")` を使う。存在しない override は勝手に作成しない。旧 `config/skills/suno.yaml` と `load_skill_config("suno")` は互換入口として維持するが、新規生成先にはしない。既存の旧 config は `uv run yt-skills migrate-config --channel-dir . --dry-run` で差分を確認し、明示 apply した場合だけ `config/skills/music.yaml::prompt` へ移す。

`--lyric` は `.claude/skills/music/config.default.yaml::lyric` と `config/skills/music.yaml::lyric` を同様に deep-merge し、`load_skill_config("music.lyric")` を使う。`music_engine` が `suno` または `minimax` のボーカル collection で実行し、`lyria` と instrumental collection は歌詞不要として停止する。旧 `config/skills/suno-lyric.yaml` と `load_skill_config("suno-lyric")` は互換入口として維持し、明示 migration 時だけ `config/skills/music.yaml::lyric` へ移す。

`--generate` は `music_engine` を先に一度だけ解決し、`load_skill_config("music.generate")` の結果から engine 節を一度だけ選ぶ。Suno は `.claude/skills/music/config.default.yaml::generate.suno` と旧 `config/skills/suno-helper.yaml`、Lyria は `::generate.lyria` と旧 `config/skills/lyria.yaml`、MiniMax は `::generate.minimax` と `config/skills/music.yaml::generate.minimax` を deep-merge する。互換入口 `load_skill_config("suno-helper")` / `load_skill_config("lyria")` を維持し、存在しない override は勝手に作成しない。

`--master` も `music_engine` を先に一度だけ解決する。Lyria / MiniMax は `--generate` が `01-master/master.mp3` を直接生成するため完了済みとして skip する。Suno は `.claude/skills/music/config.default.yaml::master` と旧 `config/skills/masterup.json`（優先）または `config/skills/masterup.yaml` を deep-merge し、互換入口 `load_skill_config("masterup")` を維持する。

Suno 経路の server lifecycle は `extension/references/serve.md` を直接読み、起動済み server の再利用を含む `--suno` 契約を実行する。`/extension` への委譲や手順の複製は行わない。

## 一括実行

`references/music-chain-manifest.json` と `references/music-chain-state.py` を検証する。chain は `prompt` → `lyric` → `generate` → `master` の 4 step。Suno / MiniMax の instrumental collection では不要な `lyric` の blocked 判定を完了済みとして扱い、`generate` へ進む。MiniMax vocal は `lyric` の検証済み成果物を `generate` に渡す。Lyria は `music_engine` により `generate` へ直接分岐し、Lyria / MiniMax の `master` は完了済みとして skip する。

```bash
uv run python .claude/skills/music/references/music-chain-state.py \
  --collection-path <collection-path> --step <prompt|lyric|generate|master>
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | 対象 mode の成果物が存在するため完了済みとして終了する |
| 10 | `run` | 対応する reference を読み、その一段を実行する |
| 20 | `blocked` | prerequisite / music engine / 歌詞要否の前提未達として停止する |
| その他 | `error` | manifest / collection path / script のエラーとして停止する |

実行後は同じ状態判定を再実行し、exit 0 にならなければ完了扱いにしない。途中失敗時はその段で止め、再発動時は同じ判定から安全に再開する。

## 完了条件

- フラグなし: `prompt`、必要な場合の `lyric`、`generate`、必要な場合の `master` が `skip` または実行後 `skip` になっている
- `--prompt`: `references/prompt.md` の完了条件を満たし、他の mode を実行していない
- `--lyric`: `references/lyric.md` の完了条件を満たし、他の mode を実行していない
- `--generate`: `references/generate.md` の engine 別完了条件を満たし、他の mode を実行していない
- `--master`: Suno は `references/master.md` の完了条件を満たし、Lyria / MiniMax は完了済みとして skip し、他の mode を実行していない

実行段、skip 段、対象 collection、更新成果物を短く報告する。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| Suno UI | entry 数分の Generate（1 Generate = 2 clips） | 選択 entry 数、duration guard 再生成、resume 状態 |
| Vertex AI Lyria 3（yt-generate-lyria-master） | N call、N = ceil((audio.target_duration_min + duration_padding_min) × 60 / 184)（上限 60） | 目標尺、padding、retry。既存 segment は resume で skip |
| MiniMax Music（yt-generate-minimax-master） | instrumental は N call、N = ceil((audio.target_duration_min + duration_padding_min) × 60 / 300)（上限 60）。vocal は 1 call | 目標尺、padding、retry、`--lyrics`。既存 segment / vocal master は resume で skip |

- 上限 / 承認: Suno はログイン・CAPTCHA・credit 確認を自動突破しない。Lyria は `skip_generation_approval: false`、MiniMax は生成条件とcall数の提示後に明示承認し、どちらも 60 segment hard cap を維持する。
