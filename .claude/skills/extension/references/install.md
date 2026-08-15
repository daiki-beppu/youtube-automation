# Install / automatic state selection

## Release と対象の解決

official upstream は `automation_update_refs.UPSTREAM_REPO`（既定 `daiki-beppu/youtube-automation`）から導出する。最新 `ext-v*` release の tag と assets を取得し、対象名は modifier の対応表から `suno-helper` / `distrokid-helper` / `community-helper` に変換する。`gh` が未導入または未認証なら `https://github.com/daiki-beppu/youtube-automation/releases` からの手動 download を案内して停止する。

各対象について `~/chrome-extensions/<name>/manifest.json::version` を読む。manifest が無ければ install、release version より古ければ `references/update.md`、一致すれば skip とする。フラグなしの `auto` はこの判定を全対象へ適用し、user に初回か更新かを質問しない。

## Install

対象ごとに release asset `<name>-*.zip` を `~/Downloads` へ取得し、空の `~/chrome-extensions/<name>/` へ展開する。manifest の name / version が対象 asset と release version に一致しない場合は Chrome へ案内せず停止する。

user に Chrome の `chrome://extensions` で Developer mode を有効にし、`~/chrome-extensions/<name>/` を Load unpacked するよう案内する。対象ごとの popup / overlay が表示されることを確認して完了とする。

```bash
UPSTREAM_REPO="$(uv run python -c 'from youtube_automation.commands.system.automation_update_refs import UPSTREAM_REPO; print(UPSTREAM_REPO)')"
gh release download --repo "$UPSTREAM_REPO" <tag> --pattern '<name>-*.zip' --dir ~/Downloads
mkdir -p ~/chrome-extensions/<name>
unzip -o ~/Downloads/<name>-*.zip -d ~/chrome-extensions/<name>
```
