# 運用者向けドキュメントサイトの公開

セットアップ・利用手順とリリースノートをまとめた運用者向け公開ドキュメントは、Cloudflare Pages の
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
| Build watch paths | `site/**`, `docs/release-notes/**`, `ONBOARDING.md`, `docs/oauth-setup.md`, `docs/features.md`, `docs/workflow-cheatsheet.md`, `docs/chrome-extension-install-guide.md`, `docs/dashboard.md`, `docs/channel-workspace-migration.md` |

Cloudflare Pages の GitHub integration が commit を取得し、production branch では
`https://youtube-automation-release-notes.pages.dev/`、それ以外では commit 固有 URL と
branch alias を生成する。fork から作成された pull request には preview URL が作られない。

`site/wrangler.jsonc` は Direct Upload で同じ出力境界を使うための設定である。Git integration
の build 設定は Cloudflare 側に保持されるため、変更時はこの表と Cloudflare Pages project
の両方を同じ値へ更新する。既存 project の名前、production URL、custom domain は変更しない。

### onboarding の直接配信

`/onboarding`、`/onboarding/`、`/onboarding.md`、`/onboarding.mdx` は Production / Preview とも
Cloudflare Pages の静的 asset として直接配信する。クエリパラメータ、Pages Function、環境 binding、
secret によるアクセス制御は行わない。

公開導線は従来どおり限定する。onboarding は `robots` の `noindex` を維持し、sidebar、トップページ、
検索、AI 出力、sitemap には掲載しない。運営者は通常の `/onboarding/` URL を直接開く。

Repository 変更の deploy 後、Cloudflare Dashboard に旧 gate 用の変数や secret が残っている場合は削除する。
静的配信に runtime binding は不要である。

### repository workflow と Build watch paths

`.github/workflows/site.yml` の `on.push.paths` / `on.pull_request.paths` は GitHub Actions の実行条件、
Cloudflare Pages Git integration の **Build watch paths** は Pages build の実行条件であり、別々の設定である。
片方を編集しても、もう片方へ自動同期されない。公開原本を追加・削除するときは両方を同じ変更で更新し、
次の一覧と一致することを確認する。

```text
site/**
docs/release-notes/**
ONBOARDING.md
docs/oauth-setup.md
docs/features.md
docs/workflow-cheatsheet.md
docs/chrome-extension-install-guide.md
docs/dashboard.md
docs/channel-workspace-migration.md
```

Cloudflare Dashboard で既存の `youtube-automation-release-notes` project を開き、Git integration の
Build watch paths を上記9項目へ更新して保存する。保存後は設定画面を再表示し、各項目が完全一致すること、
`docs/**` のように公開対象外まで含む広い pattern がないことを確認する。

## Preview 受け入れ確認

site を変更した pull request では、Cloudflare Pages の commit 固有 preview build が成功してから次を確認する。
fork からの pull request には preview URL が作られないため、同一 repository の branch で確認する。

- トップページと sidebar / tabs に「はじめる」「使う」「リリースノート」の3区分が表示される。
- 公開 navigation とトップページには次の6ページだけが表示される: `/oauth-setup/`、`/chrome-extension-install-guide/`、`/features/`、`/workflow-cheatsheet/`、`/dashboard/`、`/channel-workspace-migration/`。
- `/onboarding/` は直接 URL で表示でき、robots noindex を持つ一方、sidebar、トップページ、検索、AI 出力、sitemap には現れない。
- Production / Preview の `/onboarding/` はクエリパラメータなしの直接 URL で表示できる。
- `/features/` から `/workflow-cheatsheet/`、`/onboarding/` と `/oauth-setup/` の相互リンクは preview 内の route を指す。
- `/onboarding/` の Python 版から `tayk` への移行リンクは、GitHub の `docs/migration/python-to-tayk.md` 原本へ fallback する。
- `/audits/` route が生成されず、navigation と検索結果にも内部 audit が現れない。

この checklist は local build の代替ではない。pull request の commit と preview URL を記録し、上記を確認した後に
merge する。merge 後は production build と `https://youtube-automation-release-notes.pages.dev/` の表示を確認する。

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
