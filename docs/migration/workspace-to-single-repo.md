# workspace から 1 チャンネル = 1 リポジトリへ戻す（逆移行ガイド）

マルチチャンネル workspace（ADR-0022）は ADR-0029 で deprecated になり、削除リリース（major）で経路ごと撤去されます。workspace の `channels/<slug>/` を独立したチャンネルリポジトリへ戻す手順を、チャンネル 1 つ分の操作として書きます。決定の根拠と「何を・どの順で・何をもって完了とするか」は [ADR-0029](../adr/0029-return-to-single-channel-repos.md) の移行計画節、`yt-channel-export` の契約は #4876 / #4889、GitHub 新設は #4880、dogfood と展開順は #4878 を参照してください。

「first-party のみ」と書いた節は運営者の 7 チャンネル（`001ch-afro-deep-noir` 〜 `007ch-slowpour`）の運用に固有です。external の workspace 利用者はそれ以外の節をチャンネルごとに繰り返してください。

前提リリース: `yt-channel-export` と本ガイドを含む最初の minor。fan-out `yt-channels` と SessionStart 自動追従は前提にしません。

## 0. 全体の流れ（first-party のみ）

1. dogfood チャンネル **002ch-deepfocus365** を export し、独立リポジトリでフルライフサイクル 1 周を実走する（§8）
2. 合格したら残り 6 チャンネルを **001 → 005 → 006 → 004 → 007 → 003** の順に 1 セッションで export し、各 4 点 smoke で受け入れる（§9）
3. 完了条件 5 点が揃ったら workspace を archive し、ローカルの workspace ディレクトリを削除する（§11）

export から 1 周合格までの上限は **14 日**です。超えたら fix-forward 中でも 6 チャンネル展開を始めず、wayfinder map #4871 へ差し戻します。

## 1. 初回だけの準備

```bash
# 旧リポジトリの削除に delete_repo scope が要る（first-party のみ、初回 1 度）
gh auth refresh -h github.com -s delete_repo
```

first-party のみ: 最初の export と同時に、ツールキット以前の周辺リポジトリ 4 件を削除します。旧世代の config は現行 schema と非互換なので、将来動かす場合は `/setup --channel` で作り直します。

```bash
for repo in youtube-template youtube-channels youtube-fantasy-celtic-music youtube-8bah; do
  gh repo delete "daiki-beppu/${repo}" --yes
done
```

first-party のみ: launchd の定期 analytics 収集（`com.youtube-channels.collect-reporting.plist` → `scripts/collect_reporting.sh`）は workspace の `channels/*` を回って自動 commit を積む二重運用の主要因です。dogfood 開始時点で **workspace 全体について** 止め、1 周中は手動 `/analytics` で代替します。

```bash
launchctl unload ~/Library/LaunchAgents/com.youtube-channels.collect-reporting.plist
```

## 2. export する

対象 slug 配下は git clean が必須です（gitignore されていない untracked も dirty 扱い）。「workspace の最終 commit = 独立リポジトリの初回 commit」の等式を守るため、先に commit します。

```bash
cd <workspace>
git status --porcelain -- channels/<slug>   # 空になるまで commit する
```

戻し先は workspace の外で、存在しないか空のディレクトリです。first-party は workspace の隣 `/Users/mba/02-yt/<slug>` に置き、ディレクトリ名 = リポジトリ名 = registry パスの basename = `YTA_CHANNEL_SLUG` = workspace slug で識別子を 1 本にします。

```bash
uv run yt-channel-export <slug> /Users/mba/02-yt/<slug> --dry-run   # copy 計画・件数・サイズ・registry の計画
uv run yt-channel-export <slug> /Users/mba/02-yt/<slug>
```

export が行うこと:

- `channels/<slug>/` 直下のディスク実体（メディア込み）を staging へ丸ごと copy し、検証後に `rename` で戻し先を publish する。denylist はランタイム状態（`.automation-run/` / `.tmp/` / `*.lock` / `.collection-serve-*.pid` / `.DS_Store` / `__pycache__/`）だけ
- `auth/`（`client_secrets.json` / `token*.json` / `backups/`）はそのまま copy する。`.env` は copy しない（見つけたら「不要のはず」と 1 行報告）
- 対象内の通常ファイルを指す内部 symlink は実体化して copy し、外部・循環・directory を指す symlink は validation error で止める
- 戻し先で `load_config()` が成功すること、元と先のファイル数・総サイズが一致することを検証する。失敗時は自分が作った staging / 戻し先だけ削除して停止する
- `.gitignore` と `auth/client_secrets.template.json` の 2 テンプレートだけ書く（メディア入りの戻し先で `.gitignore` 無しの初回 `git add` を防ぐ安全柵）
- 最終段で channel registry（`~/.config/tayk/channels.json`）の `<workspace>/channels/<slug>` エントリを **同じ index で戻し先に置換**する。一致が無ければ追加のみ（007ch）、戻し先が既にあれば no-op。書く直前に `channels.json.bak` を 1 世代残し、tmp + rename で書く。registry が無ければ `[<dest>]` で新規作成する

export が行わないこと:

- workspace 側の変更（`channels/<slug>/` は残置。切り戻しは戻し先を消すだけ）
- `uv init` / `uv add` / `yt-skills sync` / `git init` / `gh repo create`（§4 以降の手順）
- `yt-doctor` と `collections/**/workflow-state.json` が参照する path の実在確認（案内のみ。戻し先に `pyproject` / skills が無い段階では green にできない）

registry の書込だけ失敗した場合、戻し先は残り、手編集すべき内容が印字されて非 0 で終了します。印字された内容のとおり `channels.json` を編集してから §3 へ進みます（copy はやり直しません）。

## 3. workspace 側の slug を凍結する

export 検証の直後に、workspace 側を 3 層で凍結して二重運用を防ぎます。

```bash
cd <workspace>
chmod -R a-w channels/<slug>          # 機械層。git の追跡モードには影響しない
```

`.claude/CLAUDE.local.md`（AI が読む層）に「凍結中 slug 一覧」を追記します。

```markdown
## 凍結中（独立リポジトリへ export 済み。ここでは触らない）

- 002ch-deepfocus365 → /Users/mba/02-yt/002ch-deepfocus365
```

launchd（自動収集層）は §1 で workspace 全体について停止済みです。未 export のチャンネルの制作は workspace 側で従来どおり続けます。凍結は registry に触りません（registry は export が置換済み）。

`git mv` でディレクトリを退避する案は、tracked ファイルのリネーム commit と gitignore 済みメディアの扱いが煩雑なので採りません。

## 4. 初回 commit と等式の検証

初回 commit は **export 分と bootstrap 分の 2 commit** に分け、export 分を workspace 側と突き合わせてから push します。

```bash
cd /Users/mba/02-yt/<slug>
git init -b main
git add -A
git commit -m "chore: workspace <slug> から export（$(git -C <workspace> rev-parse --short HEAD)）"
```

commit 1 の直後に、tracked ファイルの集合が workspace 側と一致することを検証します。差分が export の書く 2 ファイル（`.gitignore` / `auth/client_secrets.template.json`）だけでなければ push 前に停止します。メディアが tracked に混ざる事故もこの比較で捕まえます。

```bash
diff <(git -C <workspace> ls-files -- "channels/<slug>" | sed "s#^channels/<slug>/##" | sort) \
     <(git ls-files | sort)
# 期待する出力: > .gitignore と > auth/client_secrets.template.json の 2 行だけ
```

次に bootstrap します。正本は `/setup --tool` で、export の完了報告も同じ 1 行を案内します（`uv init` → `uv add git+…` → `yt-skills sync` 3 asset → `yt-setup-dirs` → `yt-doctor --apply`）。auth は copy 済み、ADC はマシン共通なので、GCP / OAuth の項目は doctor が ok で通過します。

```bash
# Claude Code で /setup --tool を実行してから
git add -A
git commit -m "chore: automation bootstrap"
```

## 5. GitHub リポジトリを新設し、旧リポジトリを削除する

リポジトリ名は workspace slug そのまま（`001ch-afro-deep-noir` … `007ch-slowpour`）。旧名の再利用（unarchive → rename）と新しい接頭辞は採りません。archive 済み旧リポジトリ持ち（001〜006ch）と workspace 生まれ（007ch）で手順は同じです。

```bash
cd /Users/mba/02-yt/<slug>
gh repo create <slug> --private --source . --remote origin --push
```

first-party のみ: push 直後（機外コピーが 1 つできた時点）に旧チャンネルリポジトリを削除します。事前確認は「push 済み + §4 の等式 pass」だけで、旧リポジトリの中身との突き合わせはしません（2026-07 以降乖離しており、git 履歴は捨てると ADR-0029 で確定済み）。

| slug | 旧リポジトリ |
|---|---|
| 001ch-afro-deep-noir | `youtube-afro-deep-noir` |
| 002ch-deepfocus365 | `deepfocus365` |
| 003ch-soulful-grooves | `soulful-grooves` |
| 004ch-veluvia | `youtube-veluvia` |
| 005ch-abyss | `youtube-abyss` |
| 006ch-harana-island-sounds | `harana-island-sounds` |
| 007ch-slowpour | （なし。workspace 生まれ） |

```bash
gh repo delete daiki-beppu/<旧リポジトリ名> --yes
```

## 6. 手で持ち込む物の一覧

workspace root の first-party 固有カスタマイズは export の責務外です。同居運用のために生まれた物で、単一リポジトリ回帰で大半は不要になります。必要な物だけ手で持ち直してください。

| workspace root の物 | 扱い |
|---|---|
| `.claude/CLAUDE.local.md` | チャンネル固有の記述だけ抜き出して戻し先へ。凍結中一覧は workspace 側に残す |
| `.claude/settings.local.json` | 必要な permission だけ戻し先へ |
| `scripts/collect_reporting.sh` + launchd plist | 持ち込まない。単一リポジトリ版の定期収集は別 effort（fan-out CLI が存在してから設計） |
| 手書き `docs/*.md` | チャンネル固有の物だけ戻し先へ |
| Actions variables `YTA_*` | 持ち込まない（002ch の cloud planning test 用。workspace と共に終了） |

## 7. 追従と cloud の設定

独立リポジトリ側の追従は、Claude Code で `/automation --update` を 1 回実行します（単一リポジトリで wizard が動く証拠を兼ねます）。fan-out と SessionStart 自動追従は 6 チャンネル展開後の初回 fan-out で検証します。

cloud（hybrid cloud runner / Claude Code cloud session）を使うチャンネルだけ、opt-in で設定します。secrets は自動移行されません。

- `CLAUDE_CODE_OAUTH_TOKEN` は 1 アカウント 1 token をリポジトリごとに `gh secret set` する
- workspace の `YTA_*` variables は写さず、`/wf-new --schedule` で新規に設定する。`YTA_CHANNEL_SLUG` にはリポジトリ名 = slug を入れる
- 単一リポジトリで hybrid cloud runner が動かない 2 点（#4899）の修正が入ったリリース以降で有効化する。手順本体は `/wf-new --schedule`（`.claude/skills/wf-new/references/schedule.md`）と `docs/cloud-execution.md` を正とする

## 8. dogfood のフルライフサイクル 1 周（first-party のみ）

dogfood チャンネルは **002ch-deepfocus365**（live 82 + planning 進行中で、全段階を実データで踏める唯一の候補）。export 時点で進行中だった planning collection は独立リポジトリ側で続行し、workflow-state の継続性も検証に含めます。

1 周 = 独立リポジトリ側で次を各 1 回:

1. `/wf-next` を planning から upload まで
2. 公開後処理（playlist / community / pinned）
3. `/analytics`（collect → report）
4. `/audit --metadata`

合格条件:

- 各段の成果物が独立リポジトリ配下に書かれ、**移行起因の失敗（ConfigError / パス不在 / workspace 検出の誤発火）が 0 件**
- `yt-doctor` が green
- dashboard に独立リポジトリ側のチャンネルが表示される（`~/.config/tayk/channels.json` は戻し先を指している）

動画の成績は判定に含めません。

失敗したら **fix-forward が既定**です。戻し先と凍結を維持したまま toolkit へ修正 PR を出し、リリース後に `/automation --update` で追従して再実行します。切り戻し（§10）は「独立リポジトリで collection を 1 つも前に進められない構造的欠陥」が出た場合だけです。

## 9. 残り 6 チャンネルの展開と smoke check（first-party のみ）

順序は **001 → 005 → 006 → 004 → 007 → 003**（進行中なし・小さい順。planning 中の 007ch と 12GB + cloud 前提の 003ch を最後）。1 セッションでまとめて §2 〜 §7 を繰り返します。007ch は registry 未登録・untracked 多数なので、export 前の commit と export の registry 追加で他と同じ手順に乗ります。

チャンネルごとの受け入れは 4 点 smoke だけです（フル 1 周は dogfood の 1 回で済ませたと見なす）。

| # | smoke | 期待 |
|---|---|---|
| 1 | §4 の等式検証 | 差分が 2 ファイルだけ |
| 2 | `uv run yt-doctor` | green |
| 3 | `/wf-status` | collections を読める |
| 4 | `/analytics --status` | 統計が返る |

## 10. 切り戻し

戻し先を消して workspace 側を再開するだけです。git 履歴は捨てると確定しているので、旧チャンネルリポジトリの復活は不要です。

```bash
cd <workspace>
chmod -R u+w channels/<slug>
# .claude/CLAUDE.local.md の凍結中一覧から <slug> を消す
rm -rf /Users/mba/02-yt/<slug>
cp ~/.config/tayk/channels.json.bak ~/.config/tayk/channels.json   # workspace パスを復元する手編集。CLI に undo は無い
```

`.bak` は 1 世代なので、複数チャンネルを export した後に 1 つだけ戻す場合は `channels.json` を直接編集して該当行を `<workspace>/channels/<slug>` に戻します。dogfood を切り戻して workspace 側の運用に戻る場合は launchd も再 load します（`launchctl load ~/Library/LaunchAgents/com.youtube-channels.collect-reporting.plist`）。

## 11. 完了判定と workspace の後始末（first-party のみ）

次の 5 点が揃った時点で完了とし、削除リリース（B 系 stack）のゲートが開きます。

1. 7 リポジトリが push 済みで §4 の等式 pass
2. registry が独立リポジトリ 7 パスのみ（workspace パス 0 件。`uv run yt-channels list` で確認、残っていれば手編集）
3. launchd plist を削除
4. 旧チャンネルリポジトリ 6 件 + 周辺 4 件が削除済み
5. workspace リポジトリに最終 commit「7ch export 完了」を積んで archive

```bash
rm ~/Library/LaunchAgents/com.youtube-channels.collect-reporting.plist
cd <workspace>
git commit --allow-empty -m "chore: 7ch export 完了"
git push
gh repo archive --yes
cd .. && rm -rf <workspace>   # メディア込み 19GB 超。7 リポジトリへ copy 済み、Time Machine が控え
```

archive 後に registry へ不在パスが残っていると fan-out は error（`yt-channels list` で発見、修正は手編集）、dashboard は `invalid_channel` 行になります。完了条件 (2) が守られていれば残りません。

## 参照

- [ADR-0029](../adr/0029-return-to-single-channel-repos.md) 移行計画節（決定の正本）
- [ADR-0022](../adr/0022-multi-channel-workspace.md)（superseded。順移行の履歴）
- `docs/architecture.md` プロジェクト用語集（channel export / dogfood チャンネル / フルライフサイクル 1 周 / 凍結 / smoke check）
- 本ガイドは削除リリースの B7（`yt-channel-export` と共に削除）で撤去されます
