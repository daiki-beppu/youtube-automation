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
| Fallow audit | `nix develop .#extensions --command pnpm -C extensions/suno-helper run audit` |
| 配布 zip | `nix develop .#extensions --command pnpm -C extensions/suno-helper zip` |

build 後は `extensions/suno-helper/.output/chrome-mv3/manifest.json`、zip 後は `extensions/suno-helper/.output/suno-helper-<package.json の version>-chrome.zip` が生成される。build / zip と期待名 zip が唯一の 1 件であることまで一括検証する場合は、前節の `verify-extensions.sh suno-helper` を使う。

## 品質ゲートの責務

| ゲート | 責務 |
|---|---|
| Oxlint（`pnpm lint`） | 共通の `extensions/.oxlintrc.json` に基づき TypeScript / React コードを検査する |
| Prettier（`pnpm format:check`） | ソースのフォーマットが統一されていることを検査する |
| TypeScript（`pnpm compile`） | 型エラーがなく、WXT の型生成を含む compile が成功することを検査する |
| Fallow（`pnpm run audit`） | `extensions/` 全体を静的解析し、既存 baseline との差分 finding を検査する |

Fallow のローカル実行は上表のコマンドを使う。Extensions CI では pull request の base commit SHA を比較元として `pnpm run audit` を1回だけ実行する。共通設定の `audit.gate: new-only` により、base にない新規 error-severity finding がある場合だけ品質ゲートが失敗し、既存 finding や warn-severity finding だけなら成功する。

Oxlint はコード単体の lint rule 違反を検出し、Fallow は未使用ファイルなどリポジトリ差分に増えた finding を検出する。Extensions CI では両者を独立した品質ゲートとして実行する。

### React Hooks lint 契約

旧 `eslint-plugin-react-hooks@7.1.1` の `recommended` で有効だった規則は、Oxlint 1.73.0 では次のように扱う。旧 severity をそのまま保てる native rule だけを共通設定で有効化する。

| 旧規則 | 旧 severity | Oxlint 1.73.0 での扱い |
|---|---:|---|
| `rules-of-hooks` | error | `react/rules-of-hooks: error` |
| `exhaustive-deps` | warn | `react/exhaustive-deps: warn` |
| `static-components` | error | native rule なし。独立 follow-up |
| `use-memo` | error | native rule なし。独立 follow-up |
| `preserve-manual-memoization` | error | native rule なし。独立 follow-up |
| `immutability` | error | native rule なし。独立 follow-up |
| `globals` | error | native rule なし。独立 follow-up |
| `refs` | error | native rule なし。独立 follow-up |
| `set-state-in-effect` | error | native rule なし。独立 follow-up |
| `error-boundaries` | error | native rule なし。独立 follow-up |
| `purity` | error | native rule なし。独立 follow-up |
| `set-state-in-render` | error | native rule なし。独立 follow-up |
| `incompatible-library` | warn | native rule なし。独立 follow-up |
| `unsupported-syntax` | warn | native rule なし。独立 follow-up |
| `config` | error | native rule なし。独立 follow-up |
| `gating` | error | native rule なし。独立 follow-up |

非対応の14規則は黙って削除せず、同 severity の native 対応または個別 rule が利用可能になった時点で独立 follow-up として扱う。Oxlint 1.73.0 の `react/react-compiler` はこれらを個別には設定できず、旧 warn の `incompatible-library` まで error として報告する。そのため同規則を有効化して旧 warn 契約を意図せず強化しない。`reportAllBailouts` も同じ理由で有効化しない。

## unpacked ロード手順

1. `nix develop .#extensions --command pnpm -C extensions/suno-helper install --frozen-lockfile` を実行する。
2. `nix develop .#extensions --command pnpm -C extensions/suno-helper build` を実行する。
3. Chrome で `chrome://extensions` を開き、右上の **デベロッパーモード** を ON。
4. **パッケージ化されていない拡張機能を読み込む** → `extensions/suno-helper/.output/chrome-mv3/` を選択。

## release 添付方針

ビルド成果物（`.output/` / `dist/` / `node_modules/`）は **commit しない**（`.gitignore` 済み）。配布は GitHub Release への zip 添付で行う。tag push 時に `.github/workflows/release-extensions.yml` が `pnpm zip` を実行し、生成 zip を Release に添付する。Chrome Web Store への公開はスコープ外（unpacked + Release zip 配布に留める）。

リリースの実施（`extensions/<name>/package.json::version` bump → `release/ext-v<VER>` PR → merge commit への `ext-v<VER>` tag push → Release asset 確認）は `/automation-release` スキルの extension release phase（`.claude/skills/automation-release/SKILL.md` Phase E0〜E2）で一気通貫に実行する。tag 命名 `ext-v*` / バージョン独立の決定は `docs/adr/0011-extension-distribution.md`。
