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
  suno-helper/            # Suno Advanced タブ自動投入拡張（WXT プロジェクト）
    wxt.config.ts         # manifest 自動生成（最小権限は lib/manifest.ts が SSOT）
    entrypoints/          # background / content / popup
    components/           # popup の React UI
    lib/                  # messaging / storage / manifest schema
    tests/                # Vitest unit + Playwright e2e
```

`shared/` は各拡張から相対 import（例: `../../shared/dom`）で参照する。各拡張は自己完結した `package.json` を持ち、`extensions/<name>/` 単体で install / build / zip を実行できる。

## pnpm バージョン契約

両拡張（`suno-helper` / `distrokid-helper`）のローカル検証には Nix extensions shell の **Node 24 / pnpm 11.12.0** を使う。各 `package.json::packageManager`、コミット済み lockfile、`pnpm-workspace.yaml::allowBuilds` による依存 build script の承認、および CI を同じ契約に保つためである。

ambient `node` / `pnpm` の版は各環境で異なり得るため、再現可能な検証では必ず `nix develop .#extensions --command` 経由で実行する。`--ignore-workspace` は `pnpm-workspace.yaml::allowBuilds` を無効化するため使用しない。

release 前検証は単一ソースのスクリプトをリポジトリ root から実行する。引数を省略すると両拡張、`<name>`（`suno-helper` または `distrokid-helper`）を渡すと対象だけを検証する:

```bash
bash .claude/skills/automation-release/references/verify-extensions.sh [<name>]
```

スクリプトは Node / pnpm の版、frozen install → build → zip、各拡張の期待名 zip が唯一の1件であること、lockfile 無差分を fail-loud に検証する。non-zero の場合は release を停止する。

## 開発フロー（suno-helper を例に）

すべてリポジトリ root で実行する。コマンドごとに Nix extensions shell を入口にするため、別途 shell へ入る必要はない。

| 目的 | コマンド |
|---|---|
| 依存インストール | `nix develop .#extensions --command pnpm -C extensions/suno-helper install --frozen-lockfile` |
| 開発（HMR） | `nix develop .#extensions --command pnpm -C extensions/suno-helper dev` |
| 本番ビルド | `nix develop .#extensions --command pnpm -C extensions/suno-helper build`（`.output/chrome-mv3/` に MV3 拡張を生成） |
| 型チェック | `nix develop .#extensions --command pnpm -C extensions/suno-helper compile` |
| unit テスト（Vitest） | `nix develop .#extensions --command pnpm -C extensions/suno-helper test` |
| Playwright browser（初回） | `nix develop .#extensions --command pnpm -C extensions/suno-helper exec playwright install --with-deps chromium` |
| e2e テスト（Playwright） | `nix develop .#extensions --command pnpm -C extensions/suno-helper test:e2e` |
| lint / format | `nix develop .#extensions --command pnpm -C extensions/suno-helper lint` / `nix develop .#extensions --command pnpm -C extensions/suno-helper format:check` |
| 配布 zip | `nix develop .#extensions --command pnpm -C extensions/suno-helper zip` |

build 後は `extensions/suno-helper/.output/chrome-mv3/manifest.json`、zip 後は `extensions/suno-helper/.output/suno-helper-<package.json の version>-chrome.zip` が生成される。build / zip と期待名 zip が唯一の 1 件であることまで一括検証する場合は、前節の `verify-extensions.sh suno-helper` を使う。

## unpacked ロード手順

1. `nix develop .#extensions --command pnpm -C extensions/suno-helper install --frozen-lockfile` を実行する。
2. `nix develop .#extensions --command pnpm -C extensions/suno-helper build` を実行する。
3. Chrome で `chrome://extensions` を開き、右上の **デベロッパーモード** を ON。
4. **パッケージ化されていない拡張機能を読み込む** → `extensions/suno-helper/.output/chrome-mv3/` を選択。

## release 添付方針

ビルド成果物（`.output/` / `dist/` / `node_modules/`）は **commit しない**（`.gitignore` 済み）。配布は GitHub Release への zip 添付で行う。tag push 時に `.github/workflows/release-extensions.yml` が `pnpm zip` を実行し、生成 zip を Release に添付する。Chrome Web Store への公開はスコープ外（unpacked + Release zip 配布に留める）。

リリースの実施（`extensions/<name>/package.json::version` bump → `release/ext-v<VER>` PR → merge commit への `ext-v<VER>` tag push → Release asset 確認）は `/automation-release` スキルの extension release phase（`.claude/skills/automation-release/SKILL.md` Phase E0〜E2）で一気通貫に実行する。tag 命名 `ext-v*` / バージョン独立の決定は `docs/adr/0011-extension-distribution.md`。
