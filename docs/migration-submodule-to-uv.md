# 移行ガイド: submodule → uv add git+https

既存の git submodule 運用チャンネルを `uv add git+https://...` 方式へ移行する手順。

## なぜ移行するか

- submodule 運用は `automation/` ディレクトリを git 管理下に抱え、タグ固定・差分レビューに手間がかかる
- `uv add git+https://...` では `pyproject.toml` にバージョンタグを固定するだけでよく、CLI (`yt-*`) と Claude Code スキルも `yt-skills sync` で配布される
- submodule 時の互換 shim (`automation/auth/`, `automation/scripts/` 等) は維持されているが、新規チャンネルは最初から uv 方式にする

## 前提

- 既存チャンネルリポジトリに `automation/` が submodule として追加済み
- `config/channel/*.json`（v1.x なら `config/channel_config.json`）、`auth/client_secrets.json`（または `automation/auth/client_secrets.json`）が存在する
- `uv` と `git` が利用可能

## 手順

### 1. 現状のバックアップ

念のためブランチを切って作業:

```bash
cd <channel-repo>
git checkout -b migrate/uv-add
```

### 2. submodule の削除

```bash
# submodule 登録解除
git submodule deinit -f automation
git rm -f automation
# .git/modules 配下のメタデータも削除
rm -rf .git/modules/automation
```

`.gitmodules` が空になったら削除:

```bash
# ファイルが残っていて `[submodule "automation"]` 以外のエントリが無いなら
rm -f .gitmodules
git add .gitmodules 2>/dev/null || true
```

### 3. uv 環境の初期化（pyproject.toml が無い場合のみ）

```bash
uv init --no-readme --no-workspace
```

既に `pyproject.toml` がある場合はスキップ。

### 4. パッケージの追加

タグは最新の安定バージョンを推奨:

```bash
uv add "git+https://github.com/daiki-beppu/youtube-automation@v1.1.0"
```

これで `yt-*` CLI と `yt-skills` が PATH に入る。

### 5. スキルの再同期

旧 `.claude/skills/` は submodule 由来のシンボリックリンクなので、uv 方式で上書き:

```bash
yt-skills sync --force
```

### 6. 認証情報の移動（必要な場合）

旧構成で `automation/auth/client_secrets.json` に置いていた場合、新しい推奨パスへ移動:

```bash
mkdir -p auth
git mv automation/auth/client_secrets.json auth/client_secrets.json 2>/dev/null || \
  mv automation/auth/client_secrets.json auth/client_secrets.json
```

互換 shim (`<channel_dir>/automation/auth/client_secrets.json`) も引き続き動作するが、`auth/` 配下に置くのが新規推奨。`auth/token.json` も同様。

### 7. 動作確認

```bash
# ChannelConfig がロードできるか（v2.0.0 以降）
uv run python3 -c "from youtube_automation.utils.config import load_config; print(load_config().meta.channel_name)"

# OAuth が通るか
uv run yt-channel-status
```

### 8. コミット

```bash
git add -A
git commit -m "chore: submodule automation から uv add git+https へ移行"
```

## トラブルシューティング

### `yt-skills sync` が旧スキルを上書きしない

`--force` を付ける。`--symlink` 運用から実ファイルへ戻す場合は `--force` が必須。

### `ModuleNotFoundError: youtube_automation`

`uv add` が失敗しているか、`uv sync` を忘れている。`uv run <command>` 経由で実行すれば自動同期される。

### `client_secrets.json が見つかりません`

検索順は以下のとおり（`src/youtube_automation/auth/oauth_handler.py`）:

1. `CLIENT_SECRETS_DIR` 環境変数
2. `<channel_dir>/auth/client_secrets.json`
3. `<channel_dir>/automation/auth/client_secrets.json`（submodule 互換）
4. `CLIENT_SECRETS_JSON` env / 1Password (`op read`)

`YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` の場合は 4 の `op` 探索と `op read` 起動をスキップし、env/file で解決できなければ最終エラーへ進む。通常テストではこの opt-out を既定有効にし、op fallback 検証だけ明示的に解除する。

いずれかに配置する。
