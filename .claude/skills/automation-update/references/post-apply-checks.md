# apply 後の追加チェック

`apply` の smoke check（機械ゲート）を通過した後、Phase 4 のコミットへ進む前に判定するもの。SKILL.md の Step 3-3 から参照される。

## 番号付き重複ファイルの検知と再発防止

`yt-doctor` の `numbered_duplicates` チェック（または `yt-skills sync` の warning）が `.venv/bin/` / `.claude/skills/` への `yt-analytics 2` のような「スペース + 連番」重複を報告した場合、iCloud Drive 等のクラウド同期コンフリクトによる汚染（生成メカニズムは upstream #1409）。放置すると Phase 4 の `git add .claude/skills/` で重複が commit に紛れ込むため、**Phase 4 に進む前に必ず対処する**:

1. `find .claude/skills .venv/bin -name '* [0-9]*'` で分布を確認
2. upstream の [番号付き重複ファイル cleanup guide](https://github.com/daiki-beppu/youtube-automation/blob/main/docs/migration/numbered-duplicate-files-cleanup.md) の手順でクリーンアップ
   （`.venv` は `rm -rf .venv && uv sync` で再作成、`.claude/skills/` は重複削除 →
   `uv run yt-skills sync --asset skills --force`）
3. 再発防止を `[HUMAN STEP]` で案内: リポジトリが iCloud Drive 同期対象
   （`~/Desktop` / `~/Documents` / iCloud Drive フォルダ）にある場合は同期対象外への
   移設が唯一の根本対策。`uv run --frozen` は再発防止にならない（lockfile 再解決を
   止めるだけで venv への sync は走る）。つなぎの対症療法は `uv run --no-sync` または
   `UV_NO_INSTALLER_METADATA=1`

## 自スキルの frontmatter 健全性チェック

`yt-skills sync` で `.claude/skills/automation-update/SKILL.md` 自身が上書きされた場合、新版の frontmatter が壊れていると **次回起動でスキル発動できなくなる**（YAML パース失敗）。sync 直後に必ず確認:

```bash
head -5 .claude/skills/automation-update/SKILL.md
```

`---` で囲まれた YAML が `name:` と `description:` を含み、2 つ目の `---` で閉じていれば OK。

壊れていた場合（YAML パース不能 / frontmatter 不完全）は git でロールバック:

```bash
git checkout .claude/skills/automation-update/SKILL.md
```

その後、本スキルを利用者の手元で再走するのではなく、上流の issue として報告するよう案内する（automation-update 自身に問題があるため再帰的に追従できない状況）。
