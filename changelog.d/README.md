# Changelog fragments

変更ごとに `<issue番号>-<slug>.<type>.md` を追加し、CHANGELOG に載せる
bullet（`- ` で始まる行）を記述します。issue 番号がない場合は PR 番号または
日付を使えます。

利用可能な type は `added`、`changed`、`deprecated`、`removed`、`fixed`、
`security`、`migration` です。commit の Conventional Commits とは別の集合で、
`docs` / `ci` / `chore` / `refactor` / `test` は type として使えません。

## 記述例

`changelog.d/1234-live-chat-auto-reply.changed.md`:

```markdown
- ライブチャットの自動返信を常駐 daemon 化し、配信中も返信を継続できるようにした（#1234）。
- 返信テンプレートを `config/channel/comments.json` から差し替えられるようにした（#1234）。
```

本文は全非空行が `- ` で始まる必要があります。1 bullet が長くなっても継続行を
作らず 1 行に収めるか、bullet 自体を分割します。

## 間違えやすい形

| 誤り | 例 | 正しい形 |
|---|---|---|
| commit の type を流用する | `1234-live-chat-auto-reply.docs.md` | 文書だけの変更でも上記 7 種から選ぶ（`changed` など） |
| 本文を平文で書く | `ライブチャット返信を追加した。` | `- ライブチャット返信を追加した（#1234）。` |
| bullet を継続行で折り返す | `- 1 行目` の次行に `2 行目` | 継続行を作らず 1 bullet 1 行に収める |

## 検証

type 文字列が不正な fragment と、`- ` で始まらない行を含む fragment は、PR CI の
changelog job（`.github/scripts/validate-changelog-fragments.py`）が
`yt-changelog-compile` と同じ実装で検出して fail します。同じ実装をローカルでも
`changelog.d/` 全件に対して実行できます。

```bash
python .github/scripts/validate-changelog-fragments.py
```

リリース時に `yt-changelog-compile` が fragment を type 別に
`CHANGELOG.md` の `[Unreleased]` へ集約し、集約済みファイルを削除します。
詳細なセクション契約は [docs/changelog-contract.md](../docs/changelog-contract.md) を
参照してください。
