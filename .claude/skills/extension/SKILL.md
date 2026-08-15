---
name: extension
purpose: 準備する
description: "Use when Chrome 拡張（suno-helper / distrokid-helper / community-helper）の導入・更新、または拡張向け collection server の起動・停止を行うとき。「拡張入れて」「extension 更新」「サーバー起動」で発動。排他的な --install / --update / --serve / --stop mode と対象を絞る --suno / --distrokid / --community modifier を使える"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `/music --generate`, `/distrokid-helper`, `/publish --community`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `~/chrome-extensions/<name>/`
- `読み込む`: `~/chrome-extensions/<name>/manifest.json`, GitHub Release `ext-v*`

## モード判定

reference を読む前、またはファイル・process を変更する前に `$ARGUMENTS` を guard へ渡す。

```bash
uv run python .claude/skills/extension/references/extension-mode-guard.py $ARGUMENTS
```

guard が exit 2 を返したら出力を提示して停止する。同じ mode flag の重複を含め、mode が 2 個以上なら排他違反とする。mode が 1 個なら対応 reference の一段だけを実行する。mode が 0 個なら `auto` として `install.md` の状態判定を 3 拡張へ行い、未導入は install、旧版は update、最新版は skip とする。

| mode | 読む reference |
|---|---|
| `--install` | `references/install.md` |
| `--update` | `references/update.md` |
| `--serve` | `references/serve.md` |
| `--stop` | `references/stop.md` |

## 修飾フラグ

modifier は対象拡張だけを絞り、mode を増やさない。`--install` / `--update` / `auto` では複数指定可、省略時は 3 拡張全件を対象とする。`--serve` / `--stop` は引数が拡張ごとに異なるため、modifier をちょうど 1 個必須とする。

| modifier | 効果 |
|---|---|
| `--suno` | `suno-helper` |
| `--distrokid` | `distrokid-helper` |
| `--community` | `community-helper` |

## 共通前提

- install / update は `gh` CLI の認証と `ext-v*` release を確認する。利用できなければ release page からの手動取得を案内して停止する
- Chrome の Load unpacked / reload は user の手動操作とし、agent がブラウザ操作を代行しない
- serve / stop は channel root と対象拡張を確定し、`references/serve.md` の共有契約だけを実行する

## 完了条件

- `auto`: 3 拡張または指定対象が install / update / skip のいずれかへ決定され、install / update 対象の manifest version が release version と一致する
- `--install`: 指定対象を展開し、Chrome で Load unpacked するディレクトリを提示する
- `--update`: 指定対象を置換し、manifest version の一致を確認して Chrome reload を案内する
- `--serve`: 既存 server の再利用または新規起動後、対象別の疎通確認がすべて通る
- `--stop`: 対象 port の server を停止し、対象 process が残っていない

mode、対象、実行 / skip、version または server URL を短く報告する。
