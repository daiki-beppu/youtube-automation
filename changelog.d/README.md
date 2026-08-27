# Changelog fragments

変更ごとに `<issue番号>-<slug>.<type>.md` を追加し、CHANGELOG に載せる
bullet（`- ` で始まる行）を記述します。issue 番号がない場合は PR 番号または
日付を使えます。

利用可能な type は `added`、`changed`、`deprecated`、`removed`、`fixed`、
`security`、`migration` です。

type 文字列が不正な fragment と、`- ` で始まらない行を含む fragment は、PR CI の
changelog job（`.github/scripts/validate-changelog-fragments.py`）が
`yt-changelog-compile` と同じ実装で検出して fail します。

リリース時に `yt-changelog-compile` が fragment を type 別に
`CHANGELOG.md` の `[Unreleased]` へ集約し、集約済みファイルを削除します。
詳細なセクション契約は [docs/changelog-contract.md](../docs/changelog-contract.md) を
参照してください。
