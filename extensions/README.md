# extensions/ — Chrome 拡張開発基盤

このリポジトリの Chrome 拡張は **WXT + React + TypeScript + Tailwind CSS** スタックで開発する。各拡張は `extensions/<name>/` 配下に WXT のディレクトリ規約（`entrypoints/`）で配置し、複数拡張から再利用する共通コードは `extensions/shared/` に集約する。

## 構成

```
extensions/
  shared-ui/              # 3拡張共通の shadcn/ui workspace package
    src/                  # shadcn/ui primitives（Button / Switch 等）/ OverlayShell / cn / theme CSS
  shared/                 # 複数拡張で再利用する型・純関数・browser adapter
    constants.ts          # storage key / 配信ルート / phase 値（サーバー契約 SSOT。メッセージ種別は各拡張の lib/messaging.ts）
    origin.ts             # CORS origin allowlist（collection_serve.py と対の契約）
    api.ts                # yt-collection-serve client + PromptEntry 型
    asset-transfer.ts     # runtime messaging 用 Blob/File base64 wire（複数拡張で共用）
    dom.ts                # Suno UI 注入の純関数群（注入 / 完了検知 / reCAPTCHA 検知）
    community-dom.ts      # YouTube チャンネル投稿 UI の DOM 操作（本文 / 画像 / 予約日時 / 投稿）
  suno-helper/            # Suno Advanced タブ自動投入拡張（WXT プロジェクト）
    wxt.config.ts         # manifest 自動生成（最小権限は lib/manifest.ts が SSOT）
    entrypoints/          # background / content / popup
    components/           # popup の React UI
    lib/                  # messaging / storage / manifest schema
    tests/                # Vitest unit + Playwright e2e
  distrokid-helper/       # DistroKid 登録ページ用 Shadow DOM overlay 拡張
    entrypoints/          # background / draggable overlay / content runner
    lib/                  # runner / manifest 最小権限 / typed messaging
    tests/                # Vitest unit + Playwright e2e
  community-helper/       # YouTube チャンネル投稿ページ用コミュニティ投稿拡張
    entrypoints/          # Popup / extension-context fetch relay / content runner
    lib/                  # runner / manifest 最小権限 / typed messaging
    tests/                # Vitest runner contract / DOM / Popup unit tests
```

`shared/` の既存モジュールは各拡張から相対 import（例: `../../shared/dom`）で参照する。overlay state の型・純関数・key 注入型 storage adapter は package subpath `@youtube-automation/extensions-shared/overlay-state` として公開する。UI は `shared-ui/` の workspace package `@youtube-automation/ui` から import し、Button / Card / Alert / Select / Checkbox / RadioGroup / Switch / OverlayShell、`useDraggable()`、`cn()`、theme CSS の実装を単一ソースに保つ。theme CSS は info / warning / success / destructive ごとの semantic token を OS 設定に依存しないライトテーマとして提供する。各 helper の `pnpm-workspace.yaml` は `../shared` と `../shared-ui` を workspace member として明示するため、従来どおり `extensions/<name>/` 単体で frozen install / build / zip を実行できる。

共通 `OverlayShell` は title・children・state I/O・action toggle 購読を consumer から受け取り、固定 shell、drag、viewport clamp、最小化、非表示中も生存する listener を提供する。service 固有の名前・storage key・messaging・runner は各 helper 側に残す。content UI の mount は WXT 公式の `createShadowRootUi` と `cssInjectionMode: "ui"` を使い、対象ページの CSS から隔離する。

suno-helper は長時間 run の終端通知に `notifications` permission を使用する。content / overlay は privileged API を直接呼ばず、型付き message で background service worker へ委譲する。

shared UI 自体の型検査は次で行う:

```bash
nix develop .#extensions --command pnpm -C extensions/shared-ui install --frozen-lockfile
nix develop .#extensions --command pnpm -C extensions/shared-ui compile
nix develop .#extensions --command pnpm -C extensions/shared-ui check
```

各 helper は独立した frozen lockfile と workspace root を維持する。このため、WXT の既知 advisory を解消する `pnpm-workspace.yaml::overrides` は 3 workspace に同じ値を明示する。pin を更新するときは 3 ファイルと 3 lockfile を同時に更新し、各 workspace の `pnpm audit --audit-level low` と release 前検証をすべて実行する。

## pnpm バージョン契約

3拡張（`suno-helper` / `distrokid-helper` / `community-helper`）のローカル検証には Nix extensions shell の **Node 24 / pnpm 11.12.0** を使う。各 `package.json::packageManager`、コミット済み lockfile、`pnpm-workspace.yaml::allowBuilds` による依存 build script の承認、および CI を同じ契約に保つためである。

ambient `node` / `pnpm` の版は各環境で異なり得るため、再現可能な検証では必ず `nix develop .#extensions --command` 経由で実行する。`--ignore-workspace` は `pnpm-workspace.yaml::allowBuilds` を無効化するため使用しない。

release 前検証は単一ソースのスクリプトをリポジトリ root から実行する。引数を省略すると3拡張、`<name>`（`suno-helper` / `distrokid-helper` / `community-helper`）を渡すと対象だけを検証する:

```bash
bash .claude/skills/automation-release/references/verify-extensions.sh [<name>]
```

スクリプトは Node / pnpm の版、frozen install → build → zip、各拡張の期待名 zip が唯一の1件であること、lockfile 無差分を fail-loud に検証する。non-zero の場合は release を停止する。

## 開発フロー（suno-helper を例に）

すべてリポジトリ root で実行する。コマンドごとに Nix extensions shell を入口にするため、別途 shell へ入る必要はない。

| 目的 | コマンド |
|---|---|
| 依存インストール | `nix develop .#extensions --command pnpm -C extensions/suno-helper install --frozen-lockfile` |
| 共有 lint toolchain インストール（check / fix の前提） | `nix develop .#extensions --command pnpm -C extensions install --frozen-lockfile`（`oxlint.config.ts` / `oxfmt.config.ts` の ultracite import を `extensions/node_modules` で解決する） |
| 開発（HMR） | `nix develop .#extensions --command pnpm -C extensions/suno-helper dev` |
| 本番ビルド | `nix develop .#extensions --command pnpm -C extensions/suno-helper build`（`.output/chrome-mv3/` に MV3 拡張を生成） |
| 型チェック | `nix develop .#extensions --command pnpm -C extensions/suno-helper compile` |
| unit テスト（Vitest） | `nix develop .#extensions --command pnpm -C extensions/suno-helper test` |
| Playwright browser（初回） | `nix develop .#extensions --command pnpm -C extensions/suno-helper exec playwright install --with-deps chromium` |
| e2e テスト（Playwright） | `nix develop .#extensions --command pnpm -C extensions/suno-helper test:e2e` |
| lint + format 検査 / 自動修正 | `nix develop .#extensions --command pnpm -C extensions/suno-helper check` / `nix develop .#extensions --command pnpm -C extensions/suno-helper fix` |
| Fallow audit | `nix develop .#extensions --command pnpm -C extensions/suno-helper run audit` |
| 配布 zip | `nix develop .#extensions --command pnpm -C extensions/suno-helper zip` |

build 後は `extensions/suno-helper/.output/chrome-mv3/manifest.json`、zip 後は `extensions/suno-helper/.output/suno-helper-<package.json の version>-chrome.zip` が生成される。build / zip と期待名 zip が唯一の 1 件であることまで一括検証する場合は、前節の `verify-extensions.sh suno-helper` を使う。

## 品質ゲートの責務

| ゲート | 責務 |
|---|---|
| Oxlint + Oxfmt（`pnpm check`） | ultracite preset を extends した共通の `extensions/oxlint.config.ts` / `extensions/oxfmt.config.ts` に基づき lint とフォーマットを一括検査する（自動修正は `pnpm fix`） |
| TypeScript 7（`pnpm compile`） | `wxt prepare` で WXT の型を生成した後、固定版 TypeScript 7.0.2 の `tsc --noEmit` で型エラーがないことを検査する。成果物は生成しない |
| WXT（`pnpm build` / `pnpm zip`） | `wxt build` で実行可能な拡張を生成し、`wxt zip` で配布用 archive を生成する。TypeScript の型検査とは別レーン |
| Fallow（`pnpm run audit`） | `extensions/` 全体を静的解析し、既存 baseline との差分 finding を検査する |

Fallow のローカル実行は上表のコマンドを使う。Extensions CI では pull request の base commit SHA を比較元として `pnpm run audit` を1回だけ実行する。共通設定の `audit.gate: new-only` により、base にない新規 error-severity finding がある場合だけ品質ゲートが失敗し、既存 finding や warn-severity finding だけなら成功する。

Extensions CI でも `pnpm compile` と `pnpm build` は独立した step として実行する。TypeScript 5.9.3 と 7.0.2 の比較では、`wxt prepare` を事前実行して除外した `tsc --noEmit` の型検査部分だけが、同一環境・同一依存条件・warm cache の中央値で suno-helper は 6.7〜8.3 倍、distrokid-helper は 11.0〜12.7 倍高速だった。この結果は WXT の `build` / `zip` 全体の性能を示すものではない。条件と生値は [TypeScript 5.9.3 と 7.0.2 の compile 性能比較](../docs/investigations/2026-07-18-2016-typescript7-compile-benchmark.md) を参照する。

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
