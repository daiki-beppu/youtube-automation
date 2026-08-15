# apply 後の追加チェック

`apply` の smoke check（機械ゲート）を通過した後、Phase 4 のコミットへ進む前に判定するもの。SKILL.md の Step 3-3 から参照される。

## 番号付き重複ファイルの検知と再発防止

`yt-doctor` の `numbered_duplicates` チェック（または `yt-skills sync` の warning）が `.venv/bin/` / `.claude/skills/` への `yt-analytics 2` のような「スペース + 連番」重複を報告した場合、iCloud Drive 等のクラウド同期コンフリクトによる汚染（生成メカニズムは upstream #1409）。放置すると Phase 4 の `git add .claude/skills/` で重複が commit に紛れ込むため、**Phase 4 に進む前に必ず対処する**:

### 1. 削除候補を限定して列挙する

repository root で次を実行する。走査対象は `.venv/bin` 直下と `.claude/skills` 配下だけで、repository 外へは広げない。scan error が1件でもあれば削除へ進まず、原因を解消して再実行する。

```bash
uv run python - <<'PY'
import sys
from pathlib import Path

from youtube_automation.infrastructure.collections.numbered_duplicates import (
    format_duplicate_name,
    format_scan_error_reason,
    scan_numbered_duplicates,
)

root = Path.cwd().resolve(strict=True)
targets = (
    (root / ".venv" / "bin", False),
    (root / ".claude" / "skills", True),
)
failed = False
for target, recursive in targets:
    result = scan_numbered_duplicates(target, recursive=recursive, root_boundary=root)
    for error in result.errors:
        failed = True
        print(
            f"scan error: {error.path}: {format_scan_error_reason(error.reason)}",
            file=sys.stderr,
        )
    for path in result.duplicates:
        print(f"duplicate: {path.absolute()} ({format_duplicate_name(path)})")
if failed:
    raise SystemExit(1)
PY
```

結果が空なら削除は不要。`.claude/skills` の候補があれば実在する絶対 path を1件ずつ提示し、「削除後は復元できない」と警告して `[HUMAN STEP]` で「列挙した skills 対象を削除 / 中止」の2択を取る。`.venv/bin` の候補は Step 3 の別承認へ回す。**承認前に削除しない**。候補が増減した場合は、更新後の全pathを再提示して承認を取り直す。

### 2. 承認された `.claude/skills` の候補だけを削除する

承認時に提示した `.claude/skills` の絶対pathを JSON 配列として `<approved JSON array>` へ入れ、次を実行する。再scan結果が承認済み集合と一致しない場合や scan error がある場合は何も削除せず停止する。`.claude/skills` 外のpathは拒否する。

```bash
uv run python - <<'PY'
import json
import shutil
from pathlib import Path

from youtube_automation.infrastructure.collections.numbered_duplicates import scan_numbered_duplicates

root = Path.cwd().resolve(strict=True)
skills = root / ".claude" / "skills"
approved = {Path(value) for value in json.loads(r'''<approved JSON array>''')}
result = scan_numbered_duplicates(skills, recursive=True, root_boundary=root)
if result.errors:
    raise SystemExit("scan error があるため削除しません")
current = {path.absolute() for path in result.duplicates}
if current != approved:
    raise SystemExit("承認後に候補が変化したため削除しません。再scan・再承認してください")
for path in sorted(current):
    path.relative_to(skills)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    print(f"removed: {path}")
PY
```

### 3. 汚染された `.venv` を再作成する

Step 1 で `.venv/bin` の候補が1件以上あった場合は個別削除せず、`.venv` 全体を再作成する。`${PWD}/.venv` の絶対path、削除後は復元できないこと、再作成コマンドを提示し、skills候補とは別に `[HUMAN STEP]` で「この `.venv` を削除して再作成 / 中止」の2択を取る。承認された場合だけ実行する。

```bash
rm -rf -- "$PWD/.venv"
uv sync
```

### 4. skills を再同期して再検証する

承認済みcleanupの後に正規ファイルを再展開し、重複と再インストールloopが消えたことを確認する。いずれかが失敗・warningなら Phase 4 へ進まない。

```bash
uv run yt-skills sync --asset skills --force
uv run yt-doctor
uv run yt-skills list
uv run yt-skills list
```

`yt-doctor` の `numbered_duplicates` が ok で、2回目の `yt-skills list` に再インストールwarningが無いことを完了条件とする。

### 5. iCloud 起因の再発を防ぐ

再発防止を `[HUMAN STEP]` で案内する。repository が `~/Desktop` / `~/Documents` / iCloud Drive 配下なら、同期対象外（例: `~/dev` / `~/02-yt`）への移設が根本対策。repositoryを移せない場合は `UV_PROJECT_ENVIRONMENT` で venv だけを同期対象外pathへ置く。

一時的な対症療法は `uv run --no-sync` または `UV_NO_INSTALLER_METADATA=1`。`uv run --frozen` はlockfile再解決を止めるだけでvenvへのsyncは走るため、再発防止にはならない。

## 自スキルの frontmatter 健全性チェック

`yt-skills sync` で `.claude/skills/automation/SKILL.md` 自身が上書きされた場合、新版の frontmatter が壊れていると **次回起動でスキル発動できなくなる**（YAML パース失敗）。sync 直後に必ず確認:

```bash
head -5 .claude/skills/automation/SKILL.md
```

`---` で囲まれた YAML が `name:` と `description:` を含み、2 つ目の `---` で閉じていれば OK。

壊れていた場合（YAML パース不能 / frontmatter 不完全）は git でロールバック:

```bash
git checkout .claude/skills/automation/SKILL.md
```

その後、本スキルを利用者の手元で再走するのではなく、上流の issue として報告するよう案内する（automation 自身に問題があるため再帰的に追従できない状況）。
