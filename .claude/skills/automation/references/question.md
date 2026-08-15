# automation question mode

下流へ install 済みの `youtube-channels-automation` について、根拠の所在と対象 version を示して回答する。チャンネル運営そのものの相談は、該当する制作・分析 skill を案内して終了する。

## 読み取り専用契約

この mode はファイルを書かず、git 操作、pin 変更、`yt-skills sync`、CLI の更新系 subcommand を実行しない。upstream への issue 作成・コメント・ラベル操作も行わない。質問が未解決でも feedback を代理記録せず、利用者へ `/skill-feedback` を案内するだけに留める。

## 配布物ローカル

最初に install 済み version を取得し、回答へ添える。

```bash
uv run python - <<'PY'
from importlib.metadata import version

print(version("youtube-channels-automation"))
PY
```

質問に関係する範囲だけを次の順で調べる。先にここで回答を構成できた場合、ネットワークへ接続しない。

1. `docs/features.md` と `docs/workflow-cheatsheet.md`
2. 配布済み `.claude/skills/*/SKILL.md` と、その skill が直接参照する `references/`
3. `.claude/CLAUDE.md`
4. CLI の質問では、対象となる install 済み `uv run yt-<command> --help`
5. version / pin の質問では、下流 `pyproject.toml` と install 済み package metadata

回答には参照したローカルファイルまたは CLI help と install 済み version を示す。見つからない情報を推測で補わない。

## upstream GitHub fallback

配布物ローカルだけでは回答を構成できない場合に限り使用する。official upstream は install 済み package の正本から取得する。

```bash
UPSTREAM_REPO="$(uv run python - <<'PY'
from youtube_automation.commands.system.automation_update_refs import UPSTREAM_REPO

print(UPSTREAM_REPO)
PY
)"
```

`gh` が存在し `gh auth status` が成功するときだけ、`$UPSTREAM_REPO` の `README.md`、質問に関係する `docs/`、`CHANGELOG.md`、open issue を必要最小限で読む。`gh` 不在・未認証・ネットワーク不通・取得失敗は fallback 不可として扱い、ローカルで確認できた範囲を返す。これらの失敗を理由に question mode 全体をエラー終了しない。

upstream の情報には参照元が release tag、main、open issue のどれかを添える。install 済み version より新しい release の情報、または未リリースの main / open issue の情報なら、ローカルではまだ利用できない可能性を明示する。release 済みの新機能なら現在の version と対象 version を併記して `/automation --update` を案内し、未リリース情報は update すれば必ず使えるとは案内しない。

## 回答できない場合

ローカルと利用可能な upstream のどちらにも根拠がない場合、または文書化された契約と実際の挙動が異なる質問では、確認できた範囲と未解決点を分けて示し、`/skill-feedback` を案内して終了する。この mode 自身は feedback ファイルを変更せず、issue 作成やコメントも行わない。
