# ts-rewrite PoC (#730)

`feat/ts-rewrite` epic (#727) の**撤退判定ゲート**。bun runtime 上で、本 epic が前提とする
主要 npm 依存が動作するかを最小コードで確認する。

## 検証対象

| 依存 | 確認内容 |
|------|---------|
| `googleapis` | import + 空 auth で `youtube.channels.list` を呼び、認証拒否エラー（401 / 403 PERMISSION_DENIED）になること（lib load 成功確認） |
| `sharp` | import + メモリ上で生成した PNG を resize できること（native binding load 確認） |
| `@modelcontextprotocol/sdk` | import + `Server` オブジェクトを生成できること |

## 実行方法

`nix develop`（bun を含む devShell）に入ってから:

```bash
cd poc/ts-rewrite
bun install
bun run smoke      # 3 依存を順に実行しサマリ + go/no-go を表示
bun test           # bun:test による smoke 検証
bun run typecheck  # tsc --noEmit による型チェック
```

## 実行結果（2026-06-02 / bun 1.3.13・nix develop 経由 bun 1.3.11）

```
PASS googleapis: code=403 message=Method doesn't allow unregistered callers ...
PASS sharp: 64x64 -> 16x16
PASS mcp-sdk: Server インスタンス生成: 成功

PoC verdict: GO (継続)
```

- `bun test`: 4 pass / 0 fail（3 依存の smoke + 撤退判定サマリ契約の回帰テスト）
- `bun run typecheck`: 型エラーなし
- `nix develop --command bun --version`: `1.3.11`（flake.nix の bun が解決できることを確認）

## 判定

3 依存すべて bun で動作。googleapis は空 auth で期待どおり 403（PERMISSION_DENIED 相当）を返し、
ライブラリのロード・リクエスト構築が機能していることを確認。**撤退条件（致命的に動かない依存）には該当せず、継続 (GO)**。

最終的な go/no-go 判定は PR review 時に人間が行う（order.md の設計）。
