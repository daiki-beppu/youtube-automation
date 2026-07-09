# チャンネルリポジトリのディレクトリ構造

`/channel-new`（新規開設 / 再生成 / 既存チャンネル取り込みモード）から共通参照する正準ディレクトリ構造。

## 正準構造

```
<channel-repo>/
├── config/                      # 設定ファイル
├── auth/                        # OAuth 認証（client_secrets.json / token.json）
├── data/                        # ベンチマーク・コメント・分析データ
├── docs/
│   ├── benchmarks/              # 競合チャンネル分析レポート
│   ├── channel/                 # TTP メモ・方向性・branding snapshot
│   │   └── personas/            # ペルソナ定義
│   └── plans/                   # 企画ドキュメント（viewer-voice 等の出力）
├── collections/
│   ├── planning/                # 制作中コレクション
│   └── live/                    # 公開済みコレクション
├── reports/                     # Analytics レポート
├── research/                    # リサーチメモ
├── branding/                    # アイコン・バナー等
└── .claude/                     # Claude Code 設定（yt-skills sync が展開）
```

`auth/` `branding/` `collections/` `data/` `docs/channel/personas/` `docs/benchmarks/` `research/` は `/setup` の `uv run yt-setup-dirs` が冪等に作成する（setup 用最小セット）。

## 作成コマンド

```bash
mkdir -p config auth data \
  docs/benchmarks docs/channel/personas docs/plans \
  collections/planning collections/live \
  reports research branding .claude
```

## オプションディレクトリ

必要に応じて追加:

| ディレクトリ | 用途 |
|---|---|
| `tools/` | チャンネル固有スクリプト |
| `tests/` | チャンネル固有テスト |

## 備考

- `config/skills/` はチャンネル固有の skill-config 上書きがある場合に作成（なくてもよい）
- `.claude/skills/` は `yt-skills sync` で自動生成されるため手動作成不要
- `auth/` は gitignored（`.gitignore` でルートから除外）
