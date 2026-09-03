# ツール導入

空のチャンネル用フォルダへ automation ツールと skill（Claude に作業手順を教えるファイル）を導入するための**運営者向け正本**。ターミナルのコマンドを利用者が入力するのではなく、Claude デスクトップアプリへ作業を依頼する。

## 推奨ルート: Claude デスクトップアプリに導入を任せる

### 1. 作業フォルダを開く

**目的:** このチャンネル専用のファイルを、他の作業と混ざらない場所に置く。

事前に用意するもの:

- macOS または Linux（Windows は WSL2 を推奨）
- Google アカウントと、セットアップ対象の YouTube チャンネル
- [Claude デスクトップアプリ](https://claude.ai/download)
- Python 3.11 以上、FFmpeg（動画・音声を処理するツール）、Google Cloud SDK（Google Cloud を操作するツール）
- Vertex AI（Google Cloud の AI サービス）を使う GCP（Google Cloud Platform）project には Billing account（課金先）が必要

Finder などで空のフォルダを作る。Claude デスクトップアプリを開き、ファイルアクセスを許可したうえで、そのフォルダを作業対象として選ぶ。ターミナルから `claude` を起動する手順は前提にしない。

`config/channel/*.json` はまだ不要である。

### 2. 導入プロンプトを貼る

**目的:** 必要なツールと skill を、Claude に正しい順序で導入させる。

uv（Python ツールの導入と実行を管理するアプリ）を含め、必要な確認とコマンド実行は Claude に任せる。次のプロンプトをそのまま貼る。プロンプト内のコマンドは Claude が実行するものであり、利用者がターミナルへ転記する必要はない。

```text
この空のチャンネル用フォルダに YouTube automation ツールを導入してください。

1. まず uv が入っているか確認し、入っていなければ uv の公式手順 https://docs.astral.sh/uv/getting-started/installation/ に従って導入してください。
2. `uv init` で Python project を初期化してください。
3. `uv add git+https://github.com/daiki-beppu/youtube-automation.git` で automation package を追加してください。
4. 次の 3 コマンドを順に実行し、skill、Claude 用の運営方針、認証ファイルのひな形を同期してください。
   - `uv run yt-skills sync --asset skills --force`
   - `uv run yt-skills sync --asset claude-md`
   - `uv run yt-skills sync --asset auth-template`
5. `uv run yt-setup-dirs` で必要な作業フォルダを作ってください。
6. `uv run yt-doctor --json` で導入状態を診断し、結果を要約してください。ここでは `--apply` を実行せず、診断だけで止めてください。

既に完了している手順は再作成せず、エラーが出たら原因と次に必要な操作を日本語で説明してください。
```

### 3. Claude を新しいチャットで開き直す

**目的:** 同期した skill を Claude に読み込ませる。

同期した skill は新しいチャットの開始時に検出される。導入を依頼したチャットを閉じ、Claude デスクトップアプリで同じフォルダを対象に新しいチャットを開始する。skill が表示されない場合は、アプリを一度終了して開き直す。

### 4. 認証セットアップを始める

**目的:** GCP、OAuth（YouTube へ安全にアクセスするための認証）、ADC（Google Cloud ツールが使うローカル認証情報）を対話形式で設定する。

新しいセッションで **`/setup --tool`** と依頼する。セットアップが診断結果を読み、必要な操作だけを順に案内する。

## 導入に失敗した場合

<details>
<summary>診断用プロンプトを表示する</summary>

利用者がコマンドを一つずつ試すのではなく、同じチャットへ次のプロンプトを貼る。

```text
先ほどの YouTube automation ツール導入が完了しているか診断してください。
`uv run yt-doctor --json` を実行し、失敗している項目だけを特定してください。
修正前に原因と実行予定の操作を日本語で説明し、ファイルの上書き、認証情報の変更、外部サービスの変更が必要なら私の確認を待ってください。
私にターミナルコマンドの実行を求めず、実行できる操作はあなたが行ってください。
```

診断後は「Claude を新しいチャットで開き直す」と「認証セットアップを始める」へ進む。

</details>

## 次の工程

ツールと skill の導入が完了し、認証セットアップを開始したら、[`GCP / YouTube API セットアップ`](oauth-setup.md) の画面別手順も参照する。
