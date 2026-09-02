## 何ができるか

automation を使い始めるためのツール環境とチャンネル設定を整えるスキルです。初回の GCP / OAuth 設定、新規 YouTube チャンネルの開設、既存チャンネルの取り込み、設定ファイルの再生成、YouTube 側への設定同期をそれぞれ独立して実行できます。フラグなしでは tool → channel を状態判定つきで進め、完了済みの工程は再実行しません。

| mode | すること | 主な成果物 |
|---|---|---|
| `--tool` | uv、GCP、OAuth、ADC などの利用環境を診断・設定 | `auth/client_secrets.json` / `auth/token.json` ほか |
| `--channel` | 新規チャンネルを聞き取りから初期設定まで立ち上げ | `config/channel/*.json` / `docs/channel/*.md` |
| `--import` | 既存 YouTube チャンネルをローカルへ取り込み | チャンネル config / localization |
| `--regenerate` | 現在の情報から config を再生成 | `config/channel/*.json` |
| `--push` | ローカル設定を確認後に YouTube へ同期 | branding / localization などの YouTube 設定 |

## 初回セットアップをまとめて進めたいとき

```
/setup
```

ツール環境を確認してから新規チャンネルの設定へ進みます。途中で止まっても、再実行時は成果物を判定して未完了の工程から再開します。OAuth や外部反映などの不可逆操作は、工程内の承認を得るまで実行しません。

## ツール環境だけ整えたいとき

```
/setup --tool
```

doctor wizard を使い、ディレクトリ、依存、GCP API、OAuth、ADC を準備します。この mode はチャンネル config を作らないため、環境構築後にチャンネルを作る場合は `--channel` を別に実行します。

## 新規チャンネルを開設したいとき

```
/setup --channel
```

チャンネルの狙いと制作条件を聞き取り、config、動画尺、persona、branding、readiness を順番に整えます。外部へ反映する直前には承認が入り、失敗時は後続工程へ進みません。

## 既存チャンネルを取り込みたいとき

```
/setup --import
```

YouTube 上ですでに運用しているチャンネルを読み込み、automation が扱えるローカル設定とドキュメントへ変換します。新規開設ではなく、既存資産から開始するときの入口です。

## config を作り直したいとき

```
/setup --regenerate
```

現在のチャンネル情報をもとに分割 config を再生成します。通常のセットアップ全体は進めず、再生成工程だけを実行します。

## ローカル設定を YouTube に反映したいとき

```
/setup --push
```

まず dry-run で変更内容を提示し、承認後に branding や localization などを同期して反映結果を確認します。ローカルとの差分確認なしに書き込むことはありません。

## つまずいたら

- **複数の mode を指定して止まる** — `--tool` などの mode は排他的です。目的に合うものを 1 つだけ指定してください
- **フラグなし実行が channel の前で止まる** — tool の prerequisite または doctor が未完了です。表示された理由を解消して同じ `/setup` を再実行してください
- **OAuth 接続で止まる** — Google Auth Platform の Branding / Audience / Clients と `client_secrets.json` を確認し、`/setup --tool` から再開してください
- **YouTube への反映前で止まる** — 外部変更の承認待ちです。dry-run の差分を確認し、反映するかを明示してください
