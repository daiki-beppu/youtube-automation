# ツール導入

空のチャンネル用フォルダへ automation ツールと skill（Claude Code に作業手順を教えるファイル）を導入するための**運営者向け正本**。コマンドの意味が分からなくても、以下を上から順に進めればよい。

> [!WARNING]
> 本 Python 版はメンテナンスモードである。新規導入前に [`migration/python-to-tayk.md`](migration/python-to-tayk.md) の移行方針も確認する。

## 推奨ルート: Claude Code に導入を任せる

### 1. 作業フォルダを開く

**目的:** このチャンネル専用のファイルを、他の作業と混ざらない場所に置く。

事前に用意するもの:

- macOS または Linux（Windows は WSL2 を推奨）
- Google アカウントと、セットアップ対象の YouTube チャンネル
- [Claude Code](https://claude.ai/code)
- Python 3.11 以上、FFmpeg（動画・音声を処理するツール）、Google Cloud SDK（Google Cloud を操作するツール）
- Vertex AI（Google Cloud の AI サービス）を使う GCP（Google Cloud Platform）project には Billing account（課金先）が必要

空のフォルダを作り、そこで Claude Code を起動する。

```bash
mkdir my-youtube-channel
cd my-youtube-channel
claude
```

`config/channel/*.json` はまだ不要である。

### 2. 導入プロンプトを貼る

**目的:** 必要なツールと skill を、Claude Code に正しい順序で導入させる。

uv（Python ツールの導入と実行を管理するアプリ）を含め、必要な確認とコマンド実行は Claude Code に任せる。次のプロンプトをそのまま貼る。

```text
この空のチャンネル用フォルダに YouTube automation ツールを導入してください。

1. まず uv が入っているか確認し、入っていなければ uv の公式手順 https://docs.astral.sh/uv/getting-started/installation/ に従って導入してください。
2. `uv init` で Python project を初期化してください。
3. `uv add git+https://github.com/daiki-beppu/youtube-automation.git` で automation package を追加してください。
4. 次の 3 コマンドを順に実行し、skill、Claude Code 用の運営方針、認証ファイルのひな形を同期してください。
   - `uv run yt-skills sync --asset skills --force`
   - `uv run yt-skills sync --asset claude-md`
   - `uv run yt-skills sync --asset auth-template`
5. `uv run yt-setup-dirs` で必要な作業フォルダを作ってください。
6. `uv run yt-doctor --json` で導入状態を診断し、結果を要約してください。ここでは `--apply` を実行せず、診断だけで止めてください。

既に完了している手順は再作成せず、エラーが出たら原因と次に必要な操作を日本語で説明してください。
```

### 3. Claude Code を新しいセッションで開き直す

**目的:** 同期した skill を Claude Code に読み込ませる。

Claude Code は project の skill をセッション開始時に検出するため、同期しただけでは現在のセッションに新しいコマンドが現れない場合がある。必ず現在のセッションを終了して `claude` を再実行するか、Claude Code を再起動する。

### 4. 認証セットアップを始める

**目的:** GCP、OAuth（YouTube へ安全にアクセスするための認証）、ADC（Google Cloud ツールが使うローカル認証情報）を対話形式で設定する。

新しいセッションで **`/setup --tool`** と依頼する。セットアップが診断結果を読み、必要な操作だけを順に案内する。

## 手動コマンド（補助）

<details>
<summary>Claude Code に任せず、ターミナルへ自分で入力する場合</summary>

**目的:** 推奨プロンプトと同じ導入処理を手動で行う。

uv が無い場合は、先に [uv の公式導入手順](https://docs.astral.sh/uv/getting-started/installation/) に従う。その後、作業フォルダで次を順に実行する。

```bash
uv init
uv add git+https://github.com/daiki-beppu/youtube-automation.git
uv run yt-skills sync --asset skills --force
uv run yt-skills sync --asset claude-md
uv run yt-skills sync --asset auth-template
uv run yt-setup-dirs
uv run yt-doctor --json
```

実行後は、推奨ルートの「Claude Code を新しいセッションで開き直す」と「認証セットアップを始める」へ進む。

</details>

## 次の工程

ツールと skill の導入が完了し、認証セットアップを開始したら、[`GCP / YouTube API セットアップ`](oauth-setup.md) の画面別手順も参照する。
