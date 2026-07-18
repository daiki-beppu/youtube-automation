# TypeScript 5.9.3 と 7.0.2 の compile 性能比較（issue #2016）

#1881 の第 3 slice。#2146（TypeScript 7.0.2 移行）の性能主張「TypeScript 7 の
ネイティブ `tsc` で型検査レーンが高速化する」を、同一環境・同一依存条件・
warm cache・複数回計測で検証した記録。

## 結論

**高速化主張は成立する。** 両 Chrome 拡張とも、中央値ベースで TypeScript 7.0.2 の
`tsc --noEmit` は 5.9.3 の **約 7〜13 倍高速**（最も保守的なセット同士の比較でも
suno-helper で 6.7 倍、distrokid-helper で 11.0 倍）。

## 計測条件

| 項目 | 値 |
|---|---|
| マシン | Apple M4 / 16 GB RAM / macOS 26.5.2 |
| 実行環境 | Nix extensions shell（`nix develop .#extensions`）: Node 24.14.0 / pnpm 11.12.0 |
| TypeScript 7.0.2 | main の現行構成（`pnpm-lock.yaml` の frozen install） |
| TypeScript 5.9.3 | 現行構成から `typescript` のみ 5.9.3 へ差し替え（`ni -D typescript@5.9.3`。他の依存は現行と同一） |
| 計測対象 | 各 helper の `tsc --noEmit`（`pnpm compile` の型検査レーン。`wxt prepare` は計測前に 1 回だけ実行し計測から除外） |
| 計測方法 | `extensions/compile-bench.sh` — tsc バイナリを直接実行（pnpm 起動オーバーヘッド除外）、warmup 1 回を捨てて 10 回計測、`/usr/bin/time -p` の real の中央値 |
| cache | warm（warmup 実行後。依存 install・`wxt prepare` 済み） |
| セット数 | 各バージョン × 各 helper で 2 セット（計 20 run ずつ） |

## 測定値

各 run の wall-clock（秒）と中央値。

### suno-helper

| TypeScript | set | runs | 中央値 |
|---|---|---|---|
| 5.9.3 | 1 | 3.05, 1.97, 1.96, 2.12, 2.20, 1.98, 1.78, 2.16, 2.20, 1.76 | **2.050** |
| 5.9.3 | 2 | 2.03, 2.15, 2.49, 2.25, 2.18, 2.12, 2.37, 2.29, 2.32, 2.91 | **2.270** |
| 7.0.2 | 1 | 0.27, 0.26, 0.34, 0.26, 0.27, 0.27, 0.28, 0.30, 0.28, 0.30 | **0.275** |
| 7.0.2 | 2 | 0.28, 0.29, 0.37, 0.40, 0.29, 0.31, 0.34, 0.29, 0.30, 0.33 | **0.305** |

→ セット中央値の比: 2.050 / 0.305 ≈ **6.7 倍** 〜 2.270 / 0.275 ≈ **8.3 倍**

### distrokid-helper

| TypeScript | set | runs | 中央値 |
|---|---|---|---|
| 5.9.3 | 1 | 2.05, 1.70, 1.67, 2.25, 2.54, 3.12, 2.01, 3.50, 3.00, 1.99 | **2.150** |
| 5.9.3 | 2 | 4.23, 4.77, 3.17, 2.38, 2.10, 1.96, 1.84, 2.04, 2.75, 2.19 | **2.285** |
| 7.0.2 | 1 | 0.21, 0.21, 0.21, 0.19, 0.19, 0.18, 0.19, 0.19, 0.20, 0.20 | **0.195** |
| 7.0.2 | 2 | 0.18, 0.20, 0.17, 0.18, 0.17, 0.18, 0.17, 0.19, 0.19, 0.19 | **0.180** |

→ セット中央値の比: 2.150 / 0.195 ≈ **11.0 倍** 〜 2.285 / 0.180 ≈ **12.7 倍**

## 計測ノート（結果の解釈に必要な注意）

- **5.9.3 側のばらつき**: 5.9.3 の run には背景負荷起因とみられる揺らぎ
  （distrokid-helper set 2 の最大 4.77s など）が混入した。中央値は外れ値に頑健な
  ため記録として採用し、全 run の生値も上表に残した。最小値同士
  （5.9.3 の 1.67s vs 7.0.2 の 0.17s）で比較しても結論は変わらない。
- **同一依存条件の担保**: 5.9.3 側は移行前コミットの復元ではなく、現行構成から
  `typescript` のみを差し替えた。移行コミット `33250036` の前後で package.json の
  差分は `typescript` の 1 行のみだが、その後 #2154（ultracite 移行）で他の依存が
  動いているため、丸ごと復元すると TypeScript 以外の差が混入する。
- **計測対象は型検査レーンのみ**: `pnpm compile` は `wxt prepare && tsc --noEmit`
  だが、`wxt prepare` は WXT のコード生成でありどちらの版でも共通のため、
  計測前に 1 回だけ実行して計測から除外した。
- **TypeScript 7 はネイティブバイナリ（typescript-go）**のため Node バージョンの
  影響を受けにくい。5.9.3 は Node 上で動くため、再現時は Nix extensions shell
  （Node 24）を使うこと。

## 再現手順

```bash
# 0. 依存 install
nix develop .#extensions --command bash -c 'cd extensions/suno-helper && ni --frozen'
nix develop .#extensions --command bash -c 'cd extensions/distrokid-helper && ni --frozen'

# 1. 現行（TypeScript 7.0.2）を計測
nix develop .#extensions --command ./extensions/compile-bench.sh suno-helper 10
nix develop .#extensions --command ./extensions/compile-bench.sh distrokid-helper 10

# 2. typescript のみ 5.9.3 へ差し替えて計測（他の依存は現行のまま）
nix develop .#extensions --command bash -c 'cd extensions/suno-helper && ni -D typescript@5.9.3'
nix develop .#extensions --command bash -c 'cd extensions/distrokid-helper && ni -D typescript@5.9.3'
nix develop .#extensions --command ./extensions/compile-bench.sh suno-helper 10
nix develop .#extensions --command ./extensions/compile-bench.sh distrokid-helper 10

# 3. 現行構成へ戻す
git checkout -- extensions/*/package.json extensions/*/pnpm-lock.yaml
nix develop .#extensions --command bash -c 'cd extensions/suno-helper && ni --frozen'
nix develop .#extensions --command bash -c 'cd extensions/distrokid-helper && ni --frozen'
```

`extensions/compile-bench.sh` は helper の node_modules/.bin の tsc を自動検出する
ため、`typescript` の差し替えだけで両版を同一手順で計測できる。
