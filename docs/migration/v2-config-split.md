# v2.0.0 移行ガイド — `channel_config` 責務別分割

`youtube-channels-automation` v1.4.x → **v2.0.0** への移行手順。旧 `config/channel_config.json`
単一ファイル構成から、責務別に 7 ファイルへ分割された新 `config/channel/*.json` 構成へ移行する。

> **所要時間の目安**: 5〜15 分（チャンネル固有の拡張キーの量による）

## 前提確認

以下のチャンネルリポジトリで作業することを想定:

- `config/channel_config.json` が存在する（旧構造）
- `auth/`, `.claude/skills/`, `collections/` 等は従来通り
- `pyproject.toml` の依存で `youtube-channels-automation` を pin している

## ステップ 1 — automation を v2.0.0 に pin-bump

チャンネルリポジトリの `pyproject.toml` で automation のバージョンを v2.0.0 に上げる:

```toml
# 例（git+https インストールの場合）
dependencies = [
    "youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@v2.0.0",
]
```

`uv sync` を走らせて新バージョンを取得:

```bash
uv sync --extra dev
```

> **このステップ直後は、`config/channel_config.json` がまだあるため、**`yt-config-migrate`
> **以外のすべての `yt-*` コマンドが `ConfigError` で起動失敗する。**次ステップで migrate を実行すること。

## ステップ 2 — dry-run で分割結果を確認

```bash
uv run yt-config-migrate diff
```

出力例:

```
File              Keys
meta.json         channel, youtube_channel
content.json      genre, tags, descriptions, title
youtube.json      youtube, music_engine, content_model
analytics.json    analytics, benchmark
playlists.json    playlists
workflow.json     post_upload, short
audio.json        audio
(unmapped)        suno  ← 未マップキーがあれば表示
```

`(unmapped)` 行が出た場合は、automation の `SECTION_MAP` に未登録のチャンネル独自キー。
**そのキーは `channel_config.json.bak` に退避されるだけで、新 `config/channel/` には移らない**。
チャンネル固有のカスタムスクリプトで参照しているなら、手動で新ファイルへ追記する必要がある。

続けて dry-run（default）で書き出し予定を確認:

```bash
uv run yt-config-migrate migrate
```

問題なければ次ステップへ。

## ステップ 3 — `--apply` で実書き込み

```bash
uv run yt-config-migrate migrate --apply
```

default の挙動:

- `config/channel/meta.json` 等の分割ファイル群を作成
- `config/channel_config.json` を `config/channel_config.json.bak` にバックアップ
- 元の `config/channel_config.json` は**残す**（削除されない）

元ファイルを同時に削除したい場合:

```bash
uv run yt-config-migrate migrate --apply --delete-source
```

未マップキーがある場合に中止したい場合:

```bash
uv run yt-config-migrate migrate --apply --strict
```

### `localization` キーを持つチャンネル（例: rjn）

旧 `channel_config.json` のトップレベルに **単数形 `localization`** キーがある場合、
migrate は以下の挙動をとる（`config/localizations.json` は**複数形**のまま固定）:

| 既存 `localizations.json` | 挙動 |
|---|---|
| 存在しない | `localization` の内容を `localizations.json` として新規作成 |
| 存在し、値が完全一致 | no-op（warning のみ出力） |
| 存在し、値不一致 | **`ConfigError` で中止**（キー単位で差分表示、手動統合が必要） |

## ステップ 4 — verify で動作確認

```bash
uv run yt-config-migrate verify
```

期待出力:

```
OK: ChannelConfig loaded (meta.channel_name='...')
```

exit code 0 なら新 loader が読み込めている。

試しに他の `yt-*` コマンドも起動確認:

```bash
uv run yt-channel-status     # channel_name が表示されれば OK
```

## ステップ 5 — カスタムスクリプトの API 書き換え

チャンネルリポジトリに `scripts/` 等で automation API を直接呼ぶカスタムコードがある場合、
属性アクセスを新 API へ書き換える。

### 旧 API → 新 API

```python
# 旧 (v1.x)
from youtube_automation.utils.channel_config import ChannelConfig

config = ChannelConfig.load()
print(config.channel_name)
print(config.category_id)
print(config.tags["base"])
```

```python
# 新 (v2.0)
from youtube_automation.utils.config import load_config

config = load_config()
print(config.meta.channel_name)
print(config.youtube.api.category_id)
print(config.content.tags.base)
```

完全な属性マッピング早見表は [CHANGELOG.md](../../CHANGELOG.md#属性マッピング早見表) を参照。

### テストコードのシングルトンリセット

```python
# 旧
from youtube_automation.utils.channel_config import ChannelConfig
ChannelConfig.reset()

# 新
from youtube_automation.utils.config import reset
reset()
```

## トラブルシューティング

### `ConfigError: 旧 channel_config.json が残っています`

ステップ 3 を実行せずに他の `yt-*` コマンドを叩いた場合に発生。`yt-config-migrate migrate --apply` を実行。

### `ConfigError: config/channel/ ディレクトリが見つかりません`

`--apply` 実行前の dry-run 状態。ステップ 3 を実行。

### `ConfigError: config/channel/ に JSON ファイルが 1 つもありません`

`config/channel/` は作られたが中身が空。`yt-config-migrate migrate --apply` を再実行（旧ファイルが残っている必要あり）。

### `ConfigError: トップレベルキー 'X' が a.json と b.json の両方に存在します`

手動編集で両ファイルに同じキーを書いてしまった場合。重複を排除して再 verify。

### `.bak` を戻したい（ロールバック）

```bash
cp config/channel_config.json.bak config/channel_config.json
rm -rf config/channel/
# automation の pin も v1.4.1 へ戻す
```

## チェックリスト

移行完了の最終確認:

- [ ] `config/channel/meta.json` / `content.json` / `youtube.json` が存在
- [ ] `yt-config-migrate verify` が exit 0
- [ ] `yt-channel-status` 等の任意の `yt-*` コマンドが起動する
- [ ] `config/channel_config.json` を削除または `.bak` のみ残す
- [ ] チャンネル固有のカスタム Python コードを新 API に書き換え（該当する場合）
- [ ] コミット + push
