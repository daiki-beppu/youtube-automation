# クラウドでの実行

> **実験的機能です。** まず手動実行で対象チャンネルの動作を確認し、失敗通知を受け取れる状態で利用してください。すべての制作工程がクラウドへ移るわけではありません。

クラウド実行は、下流チャンネルリポジトリの制作工程を GitHub Actions で定期実行する機能です。人間のブラウザ操作が必要な工程だけをローカルに残し、前後の自動化可能な工程をクラウドへ移します。

## 全体像

Suno を使う標準的な制作は、次の **cloud → local → cloud** のサンドイッチ構造です。

1. **cloud**: GitHub Actions が企画と音楽プロンプトを作成する
2. **local**: operator が Suno のブラウザで楽曲を生成・ダウンロードし、完了した音源を Cloudflare R2 へ引き渡す
3. **cloud**: GitHub Actions が音源を検証し、軽量な動画生成と公開工程を進める

工程間の状態はチャンネルリポジトリの `workflow-state.json`、メディアの引き渡しは Cloudflare R2 が正本です。クラウドジョブは開始時に Git と R2 から作業ディレクトリを再構成し、終了時に成果物と状態を反映します。R2 の manifest がない、checksum が一致しない、Git の push が競合する、といった場合は自動で推測・マージせず停止します。

## クラウドで動く工程

現時点でクラウド実行に対応しているのは次の範囲です。

- **AI 工程**: コレクションの企画と、music engine ごとのプロンプト生成
- **軽量メディア工程と公開**: `overlays.enabled: false` で、映像を再エンコードせず stream copy できるチャンネル

AI 工程は Claude Code の headless 実行を標準経路にしています。日次 workflow は状態を見て、最古の制作中コレクションを一段進めます。企画と music engine 別 prompt の検証済み pair を作成し、`planning.generated` と `assets.music_prompts` を確定した時点で `phase: planning` のまま停止します。この cloud 完了点に GCP ADC は不要です。thumbnail / loop-video 生成（Vertex AI 経路では ADC が必要）と `phase: prepared` への遷移はローカルで再開します。すでに cloud 完了点または後続のローカル工程へ到達していれば、同じ工程を重複実行せず waiting で終了します。

## ローカルに残る工程

- **Suno のブラウザ工程**: 楽曲生成、ダウンロード、音源の R2 への引き渡し。人間の UI 操作が必要なため、クラウドでは実行しません。
- **重量メディア工程と公開**: `overlays.enabled: true` で、全尺の映像再エンコードが必要なチャンネル。GitHub Actions のディスクと実行時間の制約から、動画生成に続く `publishAt` upload までを当面ローカルで実行します。

したがって、重量メディアのチャンネルは **cloud（企画）→ local（Suno、メディア、公開）** となります。OAuth、ffmpeg、メディアファイルを使うこと自体はローカル判定の理由ではありません。

## 始める前の確認

次を準備してください。

- セットアップ済みの private チャンネルリポジトリと、既定 branch への push 権限
- GitHub Actions を利用でき、Actions の失敗通知を受け取れる GitHub アカウント
- GitHub CLI（`gh`）で対象リポジトリへ認証済みの信頼できるローカル端末
- ローカル端末でログイン済みの Claude Code と、`claude setup-token` を実行できる Claude サブスクリプション
- Cloudflare R2 の bucket と、下流 workflow に設定する R2 credential
- workflow の実行結果を受け取る Discord webhook URL
- Suno 工程を実行するローカル環境（Suno を利用するチャンネルのみ）

公開工程も自動化する場合は YouTube credential をクラウドへ渡す必要があります。公開を許可する `allow_external_publish: true` は、対象と頻度を確認して明示的に承認した場合だけ有効にしてください。

## 始め方

### 1. 配布資産を更新する

対象チャンネルリポジトリで automation を最新リリースへ更新します。

```text
/automation --update
```

クラウド用 workflow がまだない場合は、配布済み CLI から同期します。

```bash
uv run yt-skills sync --asset channel-workflow --force
```

これにより `.github/workflows/youtube-automation.yml` が配置されます。workflow YAML を手で複製・改変するのではなく、以後も同期コマンドを正規入口にしてください。

### 2. Claude の OAuth token を登録する

信頼できるローカル端末で `claude setup-token` を実行し、対象チャンネルリポジトリで次を実行します。

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN
gh secret list
```

最初のコマンドの非表示 prompt に token を貼り付けます。token をファイル、shell 変数、コマンド引数、チャット、issue、ログへ保存しないでください。`planning` / `post-publish` stage は media handoff を使わないため、R2 credential を登録せずに実行できます。media handoff を使う `pipeline` stage では、配布 workflow に合わせて `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_API_TOKEN` を Actions secrets、`R2_BUCKET` を Actions variable として登録します。`DISCORD_WEBHOOK_URL` と、チャンネル識別子や対象 collection などの `YTA_*` repository variables も workflow の入力に必要です。公開工程を動かす場合だけ、追加で YouTube credential を Actions secret に設定します。

### 3. スケジュールを設定する

チャンネルリポジトリで次を実行し、`github-actions` backend の dry-run、実行時刻、対象工程、外部公開の可否を確認してから承認します。

```text
/wf-new --schedule
```

この入口が `config/channel/workflow.json::workflow.scheduled_automation` と配布 workflow の管理区間を同期します。workflow の cron を直接編集しないでください。同じチャンネルで local scheduler と GitHub Actions を同時に有効化せず、切り替える場合は旧 backend を先に停止します。

### 4. 手動実行で確認する

定期実行を待たず、既定 branch を指定して 1 回実行します。

```bash
gh workflow run youtube-automation.yml --ref <default-branch>
gh run list --workflow youtube-automation.yml --limit 1
```

job が成功し、対象工程の `workflow-state.json` と期待する成果物が同じ commit に反映されたことを確認してから定期運用を始めます。失敗時は次で原因を確認します。

```bash
gh run view <run-id> --log-failed
```

token 未設定・失効、agent の非 0 終了、R2 manifest 不整合、容量や実行時間の上限超過では fail-closed で停止し、同じ job 内で自動再試行しません。

## 制約と既知の課題

- GitHub Actions の private repository 無料枠は AI 工程とメディア工程で共有します。支出上限 $0 を前提とし、無料枠を使い切ると次の実行まで停止します。
- 軽量メディア工程でも runner のディスク余裕は小さく、長尺化やビットレート増加で停止する可能性があります。
- GitHub Actions の `schedule:` は開始が遅延したり、まれに実行されなかったりします。公開時刻は `publishAt` で指定しますが、引き渡し後の処理開始時刻は保証されません。
- `overlays.enabled: true` の重量メディア工程は未対応です。クラウドで動く理想手順として扱わず、ローカル工程を維持してください。
- Claude のサブスクリプション OAuth token は長命 credential です。認証失敗時は schedule を停止して token をローテーションし、手動実行が成功するまで再開しません。
- cloud / local の工程所有者を同時に動かす分散ロックはありません。`workflow-state.json` が示す担当工程に従い、別 backend の多重起動を避けてください。

クラウド実行で停止した場合は、成果物を手動で補完して状態だけ進めるのではなく、Actions の失敗ログ、R2 manifest、Git の競合、現在の workflow phase を確認してから再実行してください。
