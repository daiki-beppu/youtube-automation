---
name: channel-strategy
purpose: 決める
description: "Use when チャンネル戦略を状態判定付きで一括実行または一段だけ実行するとき。第一ペルソナは --persona、視聴シーンは --scene、制作制約への翻訳は --constraints、開設後の方向性・ポジショニング・差別化の再検討は --direction を使う。「ペルソナ設定」「視聴者像」「ターゲット層」「視聴シーン」「利用シーン」「シーン分析」「制作制約」「creative constraints」「制約リスト」「方向性決めたい」「ポジショニング」「差別化」「ブレスト」「チャンネル戦略」で発動。視聴者インサイト抽出は channel-research の voice mode、市場比較は market mode を使う"
---

## 前後工程

- `前工程`: `/setup --channel`, `/channel-research --voice`, `/channel-research --market`
- `後工程`: `/setup --regenerate`, `/wf-new`
- `委譲先`: `なし`

## 成果物

- `書き込む`: 検証済み JSON+HTML pair `docs/channel/personas/persona-definition.{json,html}`, `docs/plans/viewing-scene-matrix.{json,html}`, `docs/channel/creative-constraints.{json,html}`, `docs/channel/channel-direction.{json,html}`
- `読み込む`: 検証済み `docs/plans/viewer-voice-analysis.json`, `docs/plans/viewing-scene-matrix.json`, `docs/channel-research.json`, `docs/channel/personas/persona-definition.json`, `docs/channel/creative-constraints.json`, `docs/channel/ttp-seed-confirmation.md`, `docs/channel/competitor-branding-snapshot.json`, `data/benchmark_*.json`

## モード判定

`$ARGUMENTS` から strategy mode flag の個数を最初に数える。同じ flag の重複も別々に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個が `--persona` なら `references/persona.md` を読み、その一段だけを実行する。残りの引数は persona mode の引数として扱う
- 1 個が `--scene` なら `references/scene.md` を読み、その一段だけを実行する。残りの引数は scene mode の引数として扱う
- 1 個が `--constraints` なら `references/constraints.md` を読み、その一段だけを実行する。残りの引数は constraints mode の引数として扱う
- 1 個が `--direction` なら `references/direction.md` を読み、その一段だけを実行する。残りの引数は direction mode の引数として扱う
- 0 個なら chain manifest に従い状態判定付きで進める
- mode はこの表の 4 件を正とし、判定規則を複製しない。未知の mode flag は停止する

| mode | 読む reference |
|---|---|
| `--persona` | `references/persona.md` |
| `--scene` | `references/scene.md` |
| `--constraints` | `references/constraints.md` |
| `--direction` | `references/direction.md` |

## 共通前提

`config/channel/` が存在し、`load_config()` でロード可能であること。満たさない場合は、新規チャンネルなら `/setup --channel`、既存チャンネルなら `/setup --import` を案内して停止する。

戦略文書の保存・再読込は `references/structured-documents.md` を正とする。writer/consumer は検証済み JSON だけを扱い、HTML または旧 Markdown を直接 parse しない。

統合した旧 owner は `config.default.yaml` / `config/skills/*.yaml` を持たなかったため、`channel-strategy` の新しい設定キーや下流 override を先行作成しない。

## 一括実行

`references/channel-strategy-chain-manifest.json` と `references/channel-strategy-chain-state.py` を検証し、manifest の順序どおり `persona` → `scene` → `constraints` を進める。方向性検討は立ち上げ後の見直し工程なので `direction` を chain に含めない。

```bash
uv run python .claude/skills/channel-strategy/references/channel-strategy-chain-state.py \
  --channel-dir . --step persona
```

`persona` が完了したら同じコマンドの `--step` を `scene`、次に `constraints` へ替えて判定する。

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | その段の成果物が揃っているため次の段へ進む |
| 10 | `run` | 対応する reference を読み、同じ一段を実行する |
| 20 | `blocked` | 不足している前提と解消方法を表示して停止する |
| その他 | `error` | manifest / script のエラーとして停止する |

実行後は状態判定を再実行し、exit 0 にならなければ完了扱いにしない。途中失敗時はその段で止め、再発動時は同じ判定から安全に再開する。

## 完了条件

- フラグなし: `persona` → `scene` → `constraints` がそれぞれ `skip` または実行後 `skip` になっている
- `--persona`: `references/persona.md` の完了条件を満たしている
- `--scene`: `references/scene.md` の完了条件を満たしている
- `--constraints`: `references/constraints.md` の完了条件を満たしている
- `--direction`: `references/direction.md` の Step D1〜D5 を完了し、検証済み `docs/channel/channel-direction.json` + `.html` pair を保存している

実行段、skip 段、前提不足、更新成果物を短く報告する。

## 想定 API call 数

各 mode の詳細は対応する reference を正とする。ローカル成果物の状態判定は外部 API を呼ばない。Web 調査を行う場合は検索前に対象と目的を示し、接続済み一次情報を優先する。
