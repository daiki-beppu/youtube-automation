# Dashboard frontend

起動時に最新化された Analytics を表示する React / Vite / shadcn/ui frontend です。Python の `yt-dashboard` が全登録チャンネルの収集後に `src/youtube_automation/dashboard_dist/` の build asset と JSON API を同一 origin で配信します。OAuth のない E2E では `--skip-refresh` を使います。

```bash
nix develop .#extensions --command pnpm -C dashboard install --frozen-lockfile
nix develop .#extensions --command pnpm -C dashboard lint
nix develop .#extensions --command pnpm -C dashboard typecheck
nix develop .#extensions --command pnpm -C dashboard test
nix develop .#extensions --command pnpm -C dashboard build
nix develop .#extensions --command pnpm -C dashboard test:e2e
```

component は Base UI / Tailwind CSS v4 の shadcn/ui registry から追加します。追加前に `shadcn info`、registry 検索、公式 docs の確認が必要です。
