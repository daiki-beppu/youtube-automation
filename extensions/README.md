# extensions/ — Chrome 拡張開発基盤

このリポジトリの Chrome 拡張は **WXT + React + TypeScript + Tailwind CSS** スタックで開発する。各拡張は `extensions/<name>/` 配下に WXT のディレクトリ規約（`entrypoints/`）で配置し、複数拡張から再利用する共通コードは `extensions/shared/` に集約する。

## 構成

```
extensions/
  shared/                 # 複数拡張で再利用する共通コード（relative import）
    constants.ts          # storage key / 配信ルート / phase 値（サーバー契約 SSOT。メッセージ種別は各拡張の lib/messaging.ts）
    origin.ts             # CORS origin allowlist（collection_serve.py と対の契約）
    api.ts                # yt-collection-serve client + PromptEntry 型
    dom.ts                # Suno UI 注入の純関数群（注入 / 完了検知 / reCAPTCHA 検知）
  suno-helper/            # Suno Custom Mode 自動投入拡張（WXT プロジェクト）
    wxt.config.ts         # manifest 自動生成（最小権限は lib/manifest.ts が SSOT）
    entrypoints/          # background / content / popup
    components/           # popup の React UI
    lib/                  # messaging / storage / manifest schema
    tests/                # Vitest unit + Playwright e2e
```

`shared/` は各拡張から相対 import（例: `../../shared/dom`）で参照する。各拡張は自己完結した `package.json` を持ち、`extensions/<name>/` 単体で install / build / zip を実行できる。

## pnpm バージョン契約

両拡張（`suno-helper` / `distrokid-helper`）のローカル検証には **pnpm 9.15.9** を使う。各 `package.json::packageManager`、pnpm 9 形式の lockfile、`pnpm.onlyBuiltDependencies` による esbuild の build-script approval、および CI の pnpm 9 を同じ契約に保つためである。

ambient `pnpm` が別の版でも `.npmrc::package-manager-strict=false` により事前拒否されないため、再現可能な検証では版数を省略せず `npx -y pnpm@9.15.9` を使う。Corepack で各 `package.json::packageManager` の版を有効化済みの場合に限り、以下の `npx -y pnpm@9.15.9` は `pnpm` に置き換えられる。

任意の `<name>`（`suno-helper` または `distrokid-helper`）を検証する標準コマンド:

```bash
npx -y pnpm@9.15.9 -C extensions/<name> install --frozen-lockfile --ignore-workspace
npx -y pnpm@9.15.9 -C extensions/<name> build
npx -y pnpm@9.15.9 -C extensions/<name> zip
```

`zip` は `extensions/<name>/.output/<name>-<version>-chrome.zip` を生成する。release 前は両拡張で上記 3 コマンドを実行し、成果物の存在と lockfile が不変であることを確認する:

```bash
test -f extensions/suno-helper/.output/suno-helper-0.2.4-chrome.zip
test -f extensions/distrokid-helper/.output/distrokid-helper-0.2.1-chrome.zip
git diff --exit-code -- extensions/suno-helper/pnpm-lock.yaml extensions/distrokid-helper/pnpm-lock.yaml
```

## 開発フロー（suno-helper を例に）

すべて `extensions/suno-helper/` で実行する。以下の `pnpm` は、前節に従って pnpm 9.15.9 を有効化済みの場合の省略形である。

| 目的 | コマンド |
|---|---|
| 依存インストール | `pnpm install` |
| 開発（HMR） | `pnpm dev` |
| 本番ビルド | `pnpm build`（`.output/chrome-mv3/` に MV3 拡張を生成） |
| 型チェック | `pnpm compile` |
| unit テスト（Vitest） | `pnpm test` |
| e2e テスト（Playwright） | `pnpm test:e2e`（初回は `pnpm exec playwright install chromium`） |
| lint / format | `pnpm lint` / `pnpm format:check` |
| 配布 zip | `pnpm zip` |

## unpacked ロード手順

1. `pnpm install && pnpm build` を実行する。
2. Chrome で `chrome://extensions` を開き、右上の **デベロッパーモード** を ON。
3. **パッケージ化されていない拡張機能を読み込む** → `extensions/suno-helper/.output/chrome-mv3/` を選択。

## release 添付方針

ビルド成果物（`.output/` / `dist/` / `node_modules/`）は **commit しない**（`.gitignore` 済み）。配布は GitHub Release への zip 添付で行う。tag push 時に `.github/workflows/release-extensions.yml` が `pnpm zip` を実行し、生成 zip を Release に添付する。Chrome Web Store への公開はスコープ外（unpacked + Release zip 配布に留める）。
