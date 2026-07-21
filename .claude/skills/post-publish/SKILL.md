---
name: post-publish
description: "Use when 動画公開直後の community-post → pinned-comment → metadata-audit を承認ゲート付きで一括実行・途中再開するとき。「公開後処理」「post publish」「アップロード後を続けて」で発動。各処理を単独実行する場合は対応する子スキルを使う"
---

## 前後工程

- `前工程`: `/wf-auto`, `/video-upload`
- `後工程`: `なし`

## Hard Gates

- `config/channel/` と対象 `collections/live/<collection>/workflow-state.json` が存在し、`load_config()` でロード可能であること。満たさなければ `/video-upload` を案内して停止する。
- `references/post-publish-chain-manifest.json` と `references/post-publish-chain-state.py` を読み、chain ID、step 順、重複 ID、未知 step、state script 参照を検証する。違反時は停止する。
- `load_config().workflow.post_publish.configured` が `false` ならチェーンを開始しない。従来互換として `/community-post <collection>` だけを案内し、`/pinned-comment` と `/metadata-audit` は手動実行できると表示して終了する。
- gate が `true` の step は、外部反映の直前に対象動画 ID・対象コレクション・件数を表示し、明示 2 択で承認されるまで子 skill を実行しない。却下時は履歴を更新せずチェーンを停止する。
- 子 skill の内部手順を再実装しない。各段で子 SKILL.md を読み、単独発動との共通手順をそのまま実行する。

## 完了条件

対象 video ID の `post_publish_history.json` で 3 step が完了済みになり、状態判定が全 step を `skip` と返した時点で完了する。却下・失敗時は該当 step 以降を未完了のまま残し、同じコマンドで再開できることを案内する。

## 状態判定契約

チャンネルルートで各 step の前後に次を実行する。video ID 解決と履歴更新ロジックは reference script だけを正とし、本文で再実装しない。

```bash
uv run python .claude/skills/post-publish/references/post-publish-chain-state.py \
  --channel-dir . --collection <collections/live/...> --step <step-id>

uv run python .claude/skills/post-publish/references/post-publish-chain-state.py \
  --channel-dir . --collection <collections/live/...> --step <step-id> --mark-complete
```

| exit | decision | 処理 |
|---:|---|---|
| 0 | `skip` | 完了済み。子 skill を実行せず次段へ進む |
| 10 | `run` | gate を解決後、子 skill を実行する |
| 20 | `blocked` | 前段未完了または video ID 不明。理由を表示して停止する |
| その他 | `error` | manifest / history / 引数エラーとして停止する |

## 実行手順

1. manifest を読み、`chainId == "post-publish"`、step 順が `community-post, pinned-comment, metadata-audit` であることを検証する。
2. `load_config().workflow.post_publish.skip_approvals` を読み、`false` の step だけ承認対象にする。未指定は `true`（承認省略）。旧 `approval_gates` は loader が逆向きの後方互換 alias として解決し、同一 step への新旧同時指定は `ConfigError` にする。
3. manifest 順に状態判定を実行する。exit 0 は skip、exit 20 は停止する。
4. exit 10 かつ `skip_approvals` が `false` の場合、対象 video ID・collection・実行件数 1 件を表示する。外部投稿は公開後に取り消しが必要になり得ることを警告し、「この step を実行する」「チェーンを中止する」の 2 択で確認する。中止時は履歴を変更せず、再開コマンドを表示して停止する。
5. 子 skill を対象 collection 付きで実行する。`community-post` は Studio 投稿準備、`pinned-comment` は dry-run の PASS 条件を確認して apply、`metadata-audit` は既定の local + remote 監査を実行する。チェーン gate で承認済みの step は、同じ video ID・件数の子 skill 承認を再度求めない。`skip_approvals` が `true` でも子 skill 自身が必須としている safety gate は省略しない。
6. 子 skill の完了条件を満たした場合だけ `--mark-complete` を実行する。失敗時は mark せず停止する。
7. 3 step 後に状態判定を再実行し、全て exit 0 であることと履歴の video ID を短く報告する。

## References

- `references/post-publish-chain-manifest.json`: step 順、成果物、gate、判定 script の単一ソース
- `references/post-publish-chain-state.py`: video ID 解決、前段確認、履歴の原子的更新の単一ソース
