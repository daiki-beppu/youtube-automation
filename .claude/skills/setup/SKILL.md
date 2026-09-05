---
name: setup
purpose: 準備する
description: "Use when ツール導入と GCP / OAuth の設定、新規 YouTube チャンネル開設、既存チャンネル取り込み、config 再生成、または YouTube 側設定同期を行うとき。「セットアップして」「環境構築」「新チャンネル」「既存チャンネル」「チャンネル取り込み」「config 再生成」「設定反映」「チャンネル設定更新」「branding push」「ローカライゼーション同期」「meta.json を YouTube に反映」「/setup」「旧 /onboard」で発動。排他的な --tool / --channel / --import / --regenerate / --push mode を使える"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `*`（共通基盤としてほぼ全スキル）
- `委譲先`: `/channel-research --benchmark`, `/channel-research --discover`, `/channel-research --voice`, `/channel-strategy --persona`, `/channel-strategy --scene`

## 成果物

- `書き込む`: `auth/client_secrets.json`, `auth/token.json`, `config/channel/*.json`, `config/localizations.json`, `docs/channel/*.md`
- `読み込む`: `pyproject.toml`, `config/channel/*.json`

## モード判定

`$ARGUMENTS` から mode flag（`--tool` / `--channel` / `--import` / `--regenerate` / `--push`）の出現数を、reference の Read や成果物確認・変更より先に次の read-only guard で数える。

```bash
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'STOP: setup mode guardにはPython 3が必要です。runtimeを用意してから再実行してください。' >&2
  exit 2
fi
python3 .claude/skills/setup/references/setup-mode-guard.py $ARGUMENTS
```

guardは標準ライブラリだけを使い、uv・pyproject.toml・automation packageを必要としない。Python未導入・起動失敗を含め非0なら、その出力だけを提示して即時停止する。runtime不足時にguardを省略したり、ファイル作成・repo初期化・インストールを始めたりしない。

- 2 個以上なら、同じ flag の重複を含めて排他違反として停止し、1 つだけ指定するよう促す。この拒否経路では reference を Read せず、ファイル作成・更新、repo 初期化、API call、stage / commit を一切行わない
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い `tool` → `channel` を状態判定付きで進める

guardが成功した後、uv未導入なら選択modeの成果物操作より先に `references/tool.md` のbootstrap手順へ進む。導入後は元の引数でmode guardから再開し、指定modeを変えない。フラグなしの場合も後述の一括実行のtool bootstrapへ進む。

| mode | 読む reference |
|---|---|
| `--tool` | `references/tool.md` |
| `--channel` | `references/channel-mode.md` |
| `--import` | `references/import-mode.md` |
| `--regenerate` | `references/regeneration-mode.md` |
| `--push` | `references/push-mode.md` |

`--tool` は `uv run yt-setup-dirs` を含む現行 doctor wizard をそのまま実行し、GCP / OAuth / ADC bootstrap の唯一の正規入口とする。Google Auth Platform の Branding / Audience / Clients 設定と `client_secrets.json` の既存契約も `references/tool.md` で維持する。手動 script / Terraform を明示的に選ぶ上級者向け資産は同じ owner の `references/gcp-bootstrap.md` に置く。`--tool` では `config/channel/*.json` を生成しない。運用設定の `workflow.post_publish.skip_approvals` も `references/tool.md` の既存インタビューで扱う。

`--channel` は `references/channel-mode.md` を唯一の正として読み、移設前の新規開設 Step 1〜10 と同じ契約を実行する。TTP hearing、seed confirmation、config、duration、persona、branding、readiness、initial save の順序、success / failure / blocked / resume / idempotency、不可逆操作前の承認 gate と成果物契約を変えない。

`--import` / `--regenerate` / `--push` はそれぞれ対応 reference を唯一の正として読み、移設前の取り込み Step 1 前段〜Step 8、Step R1〜R8、設定同期の dry-run・承認・反映・失敗停止契約を変えずに実行する。市場・収集済みデータ分析は `/channel-research --market`、方向性検討は `/channel-strategy --direction` が所有し、ここへ吸収しない。

## 一括実行

`references/setup-chain-state.py` は `references/setup-chain-manifest.json` を実行前に strict 検証する。`chainId`、`tool` → `channel` の順序、未知・重複 step、prerequisite / output artifact、approval gate、状態判定 script のいずれかが不正なら `error` で停止する。旧 `enabled` だけの gate は `skip = not enabled` として解決し、`skip` と `enabled` の同時指定は拒否する。

最初の bootstrap で `uv`、`pyproject.toml`、automation package のいずれかが無く状態判定 script を起動できない場合は、`tool` だけを `run` として `references/tool.md` を実行する。script が起動可能になったら先頭から状態判定を再開する。起動可能ならチャンネルルートで manifest 順に各 step を判定する。

```bash
uv run python .claude/skills/setup/references/setup-chain-state.py \
  --channel-dir . --step <tool|channel>
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | 完了済みとして次の step へ進む。最終 step なら終了する |
| 10 | `run` | `tool` は `references/tool.md`、`channel` は `references/channel-mode.md` を読み、その一段だけ実行する |
| 20 | `blocked` | prerequisite 未完了として停止し、後段を実行しない |
| 2 | `error` | manifest / doctor / script のエラーとして停止し、後段を実行しない |

各 step の実行後は同じ状態判定を再実行し、exit 0 にならなければ停止する。`tool` 完了済みなら `channel` から再開し、`channel` 完了済みならどの副作用も再実行しない。既存の stale analytics 完了例外も `tool` の exit 0 とする。途中失敗時はその段で止め、後段を実行せず、再発動時は状態判定から再開する。

明示 mode はこの一括実行へ入らない。選択した reference の完了条件だけを実行・判定し、もう一段を暗黙実行しない。各 reference 内の不可逆操作・外部反映の承認 gate は chain の `approvalGate.skip` では省略されない。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API（oauth_token 手順の接続テスト） | 約 1 call | OAuth 認証の実行有無 |
| YouTube Reporting API | 数 call（quota 課金なし） | Reporting job の作成有無 |
| Vertex AI（Gemini / Veo / Lyria） | 0 | API 有効化のみで生成呼び出しなし |

- 上限 / 承認: `--tool` とフラグなし chain は、`references/tool.md` の既存の変更 plan・承認 gate・API 上限をそのまま適用する

## 完了条件

- フラグなし: `tool` と `channel` が manifest 順にどちらも `skip` になっている
- `--tool`: `references/tool.md` の完了条件だけを満たしている
- `--channel`: `references/channel-mode.md` の Step 1〜10 と完了条件をすべて満たしている
- `--import`: `references/import-mode.md` の取り込み Step 1 前段〜Step 8 を満たしている
- `--regenerate`: `references/regeneration-mode.md` の Step R1〜R8 を満たしている
- `--push`: `references/push-mode.md` の dry-run、承認、反映後確認を満たしている

実行または skip と、状態判定の `reason` を短く報告する。
