# `.takt-templates/` — downstream 配布用 takt テンプレ置き場

このディレクトリは upstream（youtube-channels-automation）で管理し、`yt-skills sync --asset takt` で downstream のチャンネルリポジトリに `.takt/` として展開するための **テンプレ集** を置く場所です。

## 配布の流れ

```
upstream                                        downstream
─────────────────────────────────────────       ─────────────────────────
.takt-templates/                                .takt/
├── config.yaml          ─── wheel 同梱 ───►   ├── config.yaml
├── workflows/           ─── _takt/ へ ────►   ├── workflows/
└── ...                                        └── ...
                                               (yt-skills sync で展開)
```

| 項目 | 値 |
|------|-----|
| wheel 内パス | `youtube_automation/_takt/` |
| force-include 設定 | `pyproject.toml` `[tool.hatch.build.targets.wheel.force-include]` |
| 配布コマンド | `yt-skills sync --asset takt --target <downstream-repo>` |

## 何を置くか

- **downstream のチャンネルリポで起動する workflow**（例: 将来の wf-new / wf-next 等）
- **複数チャンネルで再利用する facet**（persona / instruction / policy / knowledge）

## 何を置かないか

- **upstream でのみ起動する workflow**（例: `channel-new-pipeline`） → upstream の `.takt/workflows/` に直置き
- **個人マシン依存の設定**（例: API キー） → `~/.takt/config.yaml`
- **チャンネル固有の override** → downstream `.takt/workflows/`（takt の解決順序で project が最優先）

## 解決順序（takt 0.38.x）

```
project (.takt/) → user (~/.takt/) → builtin
```

downstream に `yt-skills sync --asset takt` で展開された `.takt/` は project 扱いになり、user / builtin より優先される。

## issue 参照

- #86 takt PoC: channel-new 4 スキルパイプラインの workflow 化（配布インフラの初期化）
- #64 takt OSS 導入可否の技術調査
