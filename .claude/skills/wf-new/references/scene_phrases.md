# `yt-populate-scene-phrases` リファレンス

コレクションの `workflow-state.json.scene_phrases` を多言語翻訳で投入する CLI。
翻訳文の生成は Claude Code のメインエージェントが Agent ツールでサブエージェントに委譲し、
この CLI は生成済み JSON の検証と `workflow-state.json` への書き込みだけを行う。

`/wf-new` の Phase 2a-2 から自動で呼ばれるが、以下のケースでは単体実行する:

- 既存コレクションへの再投入（過去に欠落・劣化した翻訳を補完）
- `theme_scenes` 未定義テーマで `--en` を明示指定して投入
- Agent 生成 JSON の精査のため `--dry-run` でプレビュー

## Usage

```bash
uv run yt-populate-scene-phrases <collection-dir-name> [options]
```

`<collection-dir-name>` は `collections/planning/` または `collections/live/` 配下のディレクトリ名（例: `20260322-rjn-city-collection`）。

### Options

| オプション | 説明 |
|---|---|
| `--en <text>` | 英語フレーズを明示指定。省略時は `content.json::title.theme_scenes[<theme>].scene` を longest-match で解決 |
| `--overwrite` | 既に `scene_phrases` が存在する場合も上書きする |
| `--dry-run` | 翻訳結果を表示するだけで `workflow-state.json` を更新しない |
| `--translations-json <json>` | Agent が生成した翻訳 JSON object（`en` 以外の言語を含む） |
| `--translations-file <path>` | Agent が生成した翻訳 JSON object を保存したファイル |

## 振る舞い

1. `config/localizations.json::supported_languages` を取得
2. **1 言語以下なら no-op で正常終了**（多言語対応していないチャンネルでは scene_phrases 不要のため）
3. 既存 `scene_phrases` がある場合、`--overwrite` 無指定ならスキップ
4. 英語ソース取得: `--en` 優先、なければ `content.json::title.theme_scenes` から longest-match
5. `--translations-json` / `--translations-file` の JSON を検証（`en` 以外の `supported_languages` 全件）
6. `{"en": <source>, <lang>: <translation>, ...}` を `workflow-state.json.scene_phrases` に書き込み

## 出力例

```bash
$ uv run yt-populate-scene-phrases 20260322-rjn-city-collection \
  --translations-json '{"ja":"深夜のネオン街、雨と街灯の間に流れるジャズ","ko":"..."}'
✅ 20260322-rjn-city-collection: scene_phrases に 16 言語を書き込みました
```

```bash
$ uv run yt-populate-scene-phrases 20260322-rjn-city-collection \
  --translations-file /tmp/scene-phrases.json \
  --dry-run
{
  "en": "Late-night neon city, jazz between rain and streetlights",
  "ja": "深夜のネオン街、雨と街灯の間に流れるジャズ",
  ...
}

--dry-run: collections/.../workflow-state.json には書き込みません
```

## エラーハンドリング

| 状況 | 終了コード | 対応 |
|---|---|---|
| `<collection-dir-name>` が存在しない | 1 | コレクション名を確認 |
| `theme_scenes[<theme>]` 未定義 + `--en` 未指定 | 1 | `--en` で明示指定、または `content.json::title.theme_scenes` に該当 theme を追加 |
| `--translations-json` / `--translations-file` 未指定 | 1 | Agent ツールで翻訳 JSON を生成して渡す |
| 翻訳 JSON 不正 / 言語欠落 | 1 | エラーに表示されるプロンプトで Agent に JSON を再生成させる |

## 関連

- 検証: `yt-metadata-audit` は `workflow-state.json` 自体を常に検証し、`supported_languages` が 2 言語以上のチャンネルでのみ `scene_phrases` の `supported_languages` 完全性を検証する
- メタデータ生成: `metadata_generator.py::_load_scene_phrases` が `workflow-state.json` から読み込んでタイトル・localizations を生成する
- アップロード時 preflight: `youtube_auto_uploader.py` が多言語チャンネルで `scene_phrases` の `supported_languages` 分の言語欠落を検出すると upload が中断する。単一言語チャンネルでは populate と同じ判定で `scene_phrases` を要求しない
