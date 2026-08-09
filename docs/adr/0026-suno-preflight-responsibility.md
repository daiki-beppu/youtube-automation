# Suno Style 検証と collection 骨格検証の責務分離

## Status

accepted (2026-08-10, #3155)

## Context

collection 固有の `suno-patterns.yaml` が channel 設定の `genre_line` や
`style_variants` を上書きできるようになり、Style 文字数上限などの検証には
両方を解決した effective config が必要になった。一方、
`yt-collection-preflight` は collection の必須ディレクトリと
`workflow-state.json` の初期構造を検証・補完する入口であり、Suno 設定や
生成 artifact を読み込まない。

## Decision

`yt-collection-preflight` は標準ディレクトリ骨格と `workflow-state.json` の
初期構造だけを検証する。Suno の設定解決、`suno-patterns.yaml`、
`suno-prompts.json`、`suno-lyrics.json` の内容、および collection ごとの
effective Style は `yt-suno-verify` が検証する。

したがって、patterns 側の Style がある場合も `yt-collection-preflight` に
重複した Style 検査を追加しない。Suno artifact の生成後に
`yt-suno-verify` を実行し、その単一の解決結果で Style 契約を判定する。

## Consequences

- collection の初期化直後や Suno artifact の生成前でも、骨格の補完を独立して実行できる。
- Style の上書き優先順位と検証対象が複数入口へ複製されない。
- `yt-collection-preflight` の成功は Suno artifact の妥当性を保証しない。Suno 工程の完了条件には `yt-suno-verify` の成功が必要になる。

## Considered Options

- **`yt-collection-preflight` に Style 検査を追加する**: effective Style の解決と
  Suno artifact の読み込みを骨格検証へ複製し、artifact が未生成の初期化工程でも
  Suno 固有の前提を持ち込むため不採用。
- **channel config の Style だけを `yt-collection-preflight` で検査する**:
  patterns override を反映しない結果が `yt-suno-verify` と食い違うため不採用。

## Related

- #2998
- #3152
- `src/youtube_automation/commands/collections/collection_preflight.py`
- `src/youtube_automation/commands/suno/suno_verify.py`
