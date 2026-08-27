# ツール導入

空のチャンネル用フォルダへ automation ツールと skill を導入するための**運営者向け正本**。以下を上から順に進める。

> [!WARNING]
> 本 Python 版はメンテナンスモードである。新規導入前に [`migration/python-to-tayk.md`](migration/python-to-tayk.md) の移行方針も確認する。

## 推奨ルート: 空フォルダから `/setup --tool`

### 1. 開始条件

- macOS または Linux（Windows は WSL2 を推奨）
- Google アカウントと、セットアップ対象の YouTube チャンネル
- [Claude Code](https://claude.ai/code)
- Python 3.11 以上、FFmpeg、Google Cloud SDK (`gcloud`)
- [uv](https://docs.astral.sh/uv/)。未導入なら `/setup --tool` が公式手順を案内する
- Vertex AI を使う GCP project には Billing account が必要

作業用の空フォルダを作り、そこで Claude Code を起動する。

```bash
mkdir my-youtube-channel
cd my-youtube-channel
claude
```

`config/channel/*.json` はまだ不要であり、ここでは `/setup --channel` を実行しない。

### 2. automation と skill を導入する

Claude Code で **`/setup --tool`** と依頼する。setup は空フォルダを許容し、次を順番に実行する。

```bash
uv init
uv add git+https://github.com/daiki-beppu/youtube-automation.git
uv run yt-skills sync --asset skills --force
uv run yt-skills sync --asset claude-md
uv run yt-skills sync --asset auth-template
uv run yt-setup-dirs
uv run yt-doctor --json
```

既に作成済みの `pyproject.toml` や導入済み package は再作成しない。`yt-skills sync` により `.claude/skills/` と運営方針が同期され、`yt-setup-dirs` により `auth/` などの最小ディレクトリが作られる。doctor が示す変更 plan を確認して承認すると、setup が `uv run yt-doctor --apply --json` を進める。

## 次の工程

ツールと skill の導入が完了したら、次に [`GCP / YouTube API セットアップ`](oauth-setup.md) へ進む。
