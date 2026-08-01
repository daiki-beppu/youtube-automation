# リリースノートサイトの公開

公開リリースノートは Cloudflare Pages の
[`youtube-automation-release-notes`](https://youtube-automation-release-notes.pages.dev/)
プロジェクトから配信する。

## Cloudflare Pages 設定

| 項目 | 値 |
| --- | --- |
| Git repository | `daiki-beppu/youtube-automation` |
| Production branch | `main` |
| Root directory | `site` |
| Build command | `pnpm install --frozen-lockfile && pnpm build` |
| Build output directory | `dist` |
| Build image | v3 |
| Node.js | `24`（`site/.node-version` と `NODE_VERSION`） |
| pnpm | `11.15.1`（`site/package.json::packageManager` と `PNPM_VERSION`） |
| Production deploy | `main` への push で自動実行 |
| Preview deploy | repository 内の production 以外の全 branch / pull request |
| Build watch paths | `site/**`, `docs/release-notes/**` |

Cloudflare Pages の GitHub integration が commit を取得し、production branch では
`https://youtube-automation-release-notes.pages.dev/`、それ以外では commit 固有 URL と
branch alias を生成する。fork から作成された pull request には preview URL が作られない。

`site/wrangler.jsonc` は Direct Upload で同じ出力境界を使うための設定である。Git integration
の build 設定は Cloudflare 側に保持されるため、変更時はこの表と Cloudflare Pages project
の両方を同じ値へ更新する。

## ローカル検証と手動公開

通常の build と検証は `docs/development.md` のコマンドを使う。障害復旧などで Direct Upload
が必要な場合は、Cloudflare へ認証済みの Wrangler を用いて repository root から実行する。

```bash
nix develop .#extensions --command pnpm -C site install --frozen-lockfile
nix develop .#extensions --command pnpm -C site check
nix develop .#extensions --command pnpm -C site test
nix develop .#extensions --command pnpm -C site build
nix run nixpkgs#wrangler -- pages deploy site/dist --project-name youtube-automation-release-notes --branch main
```

通常運用では Git integration による preview / production deploy を正とし、Direct Upload は
復旧・初回疎通確認に限定する。
