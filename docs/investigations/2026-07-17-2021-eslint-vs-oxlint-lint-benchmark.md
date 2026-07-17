# ESLint と Oxlint の lint 性能比較（issue #2021）

#1882 の第 4 slice。#2102（Oxlint 移行）の性能主張「Oxlint は ESLint より高速」を、
同一環境・warm cache・複数回計測で検証した記録。

## 結論

**高速化主張は成立する。** 両 Chrome 拡張とも、中央値ベースで Oxlint は ESLint の
**約 30〜90 倍高速**（最も保守的なセット同士の比較でも 30 倍以上）。

## 計測条件

| 項目 | 値 |
|---|---|
| マシン | Apple M4 / 16 GB RAM / macOS 26.5.2 |
| 実行環境 | Nix extensions shell（`nix develop .#extensions`）: Node 24.14.0 / pnpm 11.12.0 |
| Oxlint | 1.73.0（main の現行構成: `extensions/.oxlintrc.json`） |
| ESLint | 9.39.4 + typescript-eslint 8.60.1 + eslint-plugin-react-hooks 7.1.1（移行前コミット `554e9808^` の構成を復元） |
| lint 対象 | suno-helper: `suno-helper` + `shared` / distrokid-helper: `distrokid-helper`（package.json の `lint` script と同一） |
| 計測方法 | `extensions/lint-bench.sh` — linter バイナリを直接実行（pnpm 起動オーバーヘッド除外）、warmup 1 回を捨てて 10 回計測、`/usr/bin/time -p` の real の中央値 |
| cache | warm（warmup 実行後。依存 install・`wxt prepare` 済み） |
| セット数 | 各 linter × 各 helper で 2 セット（計 20 run ずつ） |

## 測定値

各 run の wall-clock（秒）と中央値。

### suno-helper（対象: suno-helper + shared）

| linter | set | runs | 中央値 |
|---|---|---|---|
| ESLint | 1 | 3.46, 4.53, 36.00, 6.56, 4.37, 20.49, 7.62, 7.56, 24.38, 19.54 | **7.590** |
| ESLint | 2 | 6.15, 4.67, 14.33, 5.12, 4.22, 4.91, 4.04, 3.72, 4.47, 4.61 | **4.640** |
| Oxlint | 1 | 0.06, 0.08, 0.07, 0.07, 0.06, 0.05, 0.04, 0.04, 0.04, 0.04 | **0.055** |
| Oxlint | 2 | 0.16, 0.11, 0.11, 0.10, 0.09, 0.08, 0.08, 0.08, 0.08, 0.08 | **0.085** |

→ セット中央値の比: 4.640 / 0.085 ≈ **55 倍** 〜 7.590 / 0.055 ≈ **138 倍**

### distrokid-helper（対象: distrokid-helper）

| linter | set | runs | 中央値 |
|---|---|---|---|
| ESLint | 1 | 10.54, 3.65, 3.78, 5.91, 3.74, 4.05, 3.40, 1.80, 2.49, 2.44 | **3.695** |
| ESLint | 2 | 1.52, 1.54, 1.77, 3.13, 2.20, 3.21, 4.46, 2.85, 1.95, 2.37 | **2.285** |
| Oxlint | 1 | 0.09, 0.08, 0.07, 0.06, 0.07, 0.06, 0.07, 0.07, 0.06, 0.08 | **0.070** |
| Oxlint | 2 | 0.07, 0.07, 0.08, 0.08, 0.08, 0.08, 0.07, 0.07, 0.07, 0.07 | **0.070** |

→ セット中央値の比: 2.285 / 0.070 ≈ **33 倍** 〜 3.695 / 0.070 ≈ **53 倍**

### 参考: ambient 環境（Node 25.4.0、nix shell 外）

| helper | ESLint 中央値 | Oxlint 中央値 | 比 |
|---|---|---|---|
| suno-helper | 2.895 | 0.165 | ≈ 18 倍 |
| distrokid-helper | 1.470 | 0.160 | ≈ 9 倍 |

環境が変わっても方向は同じ（Oxlint が 1 桁倍以上高速）。

## 計測ノート（結果の解釈に必要な注意）

- **ESLint 側の外れ値**: ESLint の run には背景負荷起因とみられる外れ値（最大 36s）が
  混入した。中央値は外れ値に頑健なため記録として採用し、全 run の生値も上表に残した。
  外れ値をすべて除外した最小値同士（ESLint 3.40s vs Oxlint 0.04s）で比較しても
  結論は変わらない。
- **ESLint 側の 1 error**: 移行コミット #2102 で disable コメントが oxlint 形式へ
  変更済みのため、現行ソースを旧 ESLint 構成で lint すると
  `content-playlist-error.test.ts` に `no-unused-vars` が 1 件報告される。
  全ファイルの lint 作業自体は完走しており、計測値としては有効。
- **Oxlint は Rust バイナリ**のため Node バージョンの影響を受けない。ESLint は
  Node 上で動くため、再現時は Nix extensions shell（Node 24）を使うこと。

## 再現手順

```bash
# 1. 現行（Oxlint）を計測
nix develop .#extensions --command bash -c 'cd extensions/suno-helper && ni --frozen'
nix develop .#extensions --command bash -c 'cd extensions/distrokid-helper && ni --frozen'
nix develop .#extensions --command ./extensions/lint-bench.sh suno-helper 10
nix develop .#extensions --command ./extensions/lint-bench.sh distrokid-helper 10

# 2. 移行前（ESLint）構成を復元して計測
for h in suno-helper distrokid-helper; do
  git show 554e9808^:extensions/$h/package.json     > extensions/$h/package.json
  git show 554e9808^:extensions/$h/pnpm-lock.yaml   > extensions/$h/pnpm-lock.yaml
  git show 554e9808^:extensions/$h/eslint.config.js > extensions/$h/eslint.config.js
done
nix develop .#extensions --command bash -c 'cd extensions/suno-helper && ni --frozen'
nix develop .#extensions --command bash -c 'cd extensions/distrokid-helper && ni --frozen'
nix develop .#extensions --command ./extensions/lint-bench.sh suno-helper 10
nix develop .#extensions --command ./extensions/lint-bench.sh distrokid-helper 10

# 3. 現行構成へ戻す
git checkout -- extensions/*/package.json extensions/*/pnpm-lock.yaml
rm extensions/*/eslint.config.js
```

`extensions/lint-bench.sh` は node_modules/.bin の oxlint（優先）または eslint を
自動検出するため、構成の切り替えだけで両者を同一手順で計測できる。
