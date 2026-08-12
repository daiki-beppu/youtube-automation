---
name: setup
description: "Use when ツール導入と GCP / OAuth の API 設定をセットアップ・再診断するとき、または新規 YouTube チャンネルを Step 1〜10 で開設するとき。「セットアップして」「環境構築」「新チャンネル」「チャンネル追加」「チャンネル開設」「/setup」「旧 /onboard」で発動。フラグなしは状態判定付きで進め、排他的な --tool / --channel mode を使える"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `*`（共通基盤としてほぼ全スキル）

## モード判定

`$ARGUMENTS` から mode flag（`--tool` / `--channel`）の出現数を、reference の Read や成果物確認・変更より先に次の read-only guard で数える。

```bash
uv run python .claude/skills/setup/references/setup-mode-guard.py $ARGUMENTS
```

guard が exit 2 を返したら、その出力だけを提示して即時停止する。

- 2 個以上なら、同じ flag の重複を含めて排他違反として停止し、1 つだけ指定するよう促す。この拒否経路では reference を Read せず、ファイル作成・更新、repo 初期化、API call、stage / commit を一切行わない
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い tool を状態判定付きで進める

| mode | 読む reference |
|---|---|
| `--tool` | `references/tool.md` |
| `--channel` | `references/channel-mode.md` |

`--tool` は `uv run yt-setup-dirs` を含む現行 doctor wizard をそのまま実行し、GCP / OAuth / ADC bootstrap の唯一の正規入口とする。Google Auth Platform の Branding / Audience / Clients 設定と `client_secrets.json` の既存契約も `references/tool.md` で維持する。手動 script / Terraform を明示的に選ぶ上級者向け資産は同じ owner の `references/gcp-bootstrap.md` に置く。`--tool` では `config/channel/*.json` を生成しない。運用設定の `workflow.post-publish.skip_approvals` も `references/tool.md` の既存インタビューで扱う。

`--channel` は `references/channel-mode.md` を唯一の正として読み、旧 `/channel-new` 新規開設モードと同じ Step 1〜10 を実行する。TTP hearing、seed confirmation、config、duration、persona、branding、readiness、initial save の順序、success / failure / blocked / resume / idempotency、不可逆操作前の承認 gate と成果物契約を変えない。既存チャンネル取り込み、分析、方向性検討、再生成、設定 push は residual `/channel-new` の責務であり、`--channel` に吸収しない。

## 一括実行

`references/setup-chain-manifest.json` と `references/setup-chain-state.py` が存在し、manifest の `chainId`、step 順、step mode、approval gate、状態判定 script が妥当であることを確認する。欠損、未知・重複 step、複数 mode、`approvalGate.skip != true` があれば停止する。旧 `enabled` だけの gate は `skip = not enabled` として解決し、`skip` と `enabled` の同時指定は拒否する。

最初の bootstrap で `uv`、`pyproject.toml`、automation package のいずれかが無く状態判定 script を起動できない場合は、`tool` を `run` として `references/tool.md` を実行する。起動可能ならチャンネルルートで manifest 順に次を実行する。

```bash
uv run python .claude/skills/setup/references/setup-chain-state.py \
  --channel-dir . --step tool
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | setup 済みとして終了する |
| 10 | `run` | `references/tool.md` を読み、現行の診断 wizard を実行する |
| その他 | `error` | doctor / script のエラーとして停止する |

実行後は同じ状態判定を再実行し、exit 0 にならなければ停止する。既存の stale analytics 完了例外も exit 0 とする。途中失敗時はその段で止め、再発動時は状態判定から再開する。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API（oauth_token 手順の接続テスト） | 約 1 call | OAuth 認証の実行有無 |
| YouTube Reporting API | 数 call（quota 課金なし） | Reporting job の作成有無 |
| Vertex AI（Gemini / Veo / Lyria） | 0 | API 有効化のみで生成呼び出しなし |

- 上限 / 承認: `--tool` とフラグなし chain は、`references/tool.md` の既存の変更 plan・承認 gate・API 上限をそのまま適用する

## 完了条件

- フラグなし: tool が `skip` または実行後 `skip` になっている
- `--tool`: `references/tool.md` の完了条件だけを満たしている
- `--channel`: `references/channel-mode.md` の Step 1〜10 と完了条件をすべて満たしている

実行または skip と、状態判定の `reason` を短く報告する。
