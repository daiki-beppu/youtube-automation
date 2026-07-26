# local fix 衝突の特例ハンドリング

`yt-skills diff` に差分が出たとき、通常の (a)/(b)/(c) 判断へ進む**前に**割り込ませる 2 つの特例。SKILL.md の Step 3-1 から参照される。

## 自スキル (automation-update) が差分対象に含まれる場合

`yt-skills diff` の出力に **`automation-update` 自身** が含まれる場合、(a)/(b)/(c) prompt の **前に** 自スキル更新の特例 prompt を出して、変更内容を構造的に提示してから確認を取る:

```bash
# 自スキル分の同梱版を取得し、unified diff として表示
# youtube_automation を import するため uv 管理の venv 経由で実行する
uv run python - <<'PY' > /tmp/automation-update-bundled.SKILL.md
from youtube_automation.cli.skills_sync import _asset_root

print((_asset_root("skills") / "automation-update" / "SKILL.md").read_text(encoding="utf-8"), end="")
PY
diff -u .claude/skills/automation-update/SKILL.md /tmp/automation-update-bundled.SKILL.md || true
```

`yt-skills` には export コマンドは無い。wheel 同梱 asset は `youtube_automation.cli.skills_sync._asset_root("skills")` から取得する。

AI は取得した unified diff を **H2 セクション境界（`## `）で集約** し、「Phase X の手順が変わる」「Gotchas に Y が追加」のようなセクション単位の要約を作って提示する:

```
> [HUMAN STEP]
> ⚠ このスキル自身 (automation-update) が更新対象に含まれています。
>
> 変更内容（セクション単位の要約）:
>   - Phase 3-1: <要約>
>   - Gotchas: <要約>
>
> 仕様:
>   - sync 実行後も、本セッションは旧版 SKILL.md の手順で完走します
>     （Claude Code はセッション開始時に SKILL.md をロードしてメモリ保持するため）
>   - 次回 /automation-update を起動した時点から新版が適用されます
>   - 手書き改造（local fix）がある場合は破棄されます
>
> 続行してよければ "yes"、自スキルだけ手動マージしたければ "manual" と返してください。
```

`"manual"` が返ってきた場合は、自スキルは利用者に手動マージを依頼する。他に上書きしてよい skill が明確な場合だけ、local fix を解消した後に Step 3-2 の (b) `--sync-only <safe-skill...>` でその skill だけ同期する（`--sync-only` は skills asset の除外指定ではなく allowlist 指定。claude-md も別 asset として同期されるため、差分が残っている場合は CLI の local fix guard で停止する）。

## `config.default.yaml` の直接編集が検出された場合

`yt-skills diff` の出力に **`.claude/skills/<skill>/config.default.yaml`** が含まれる場合、それは運営者が直接編集してしまっている可能性が高い。`config.default.yaml` は upstream 管理のデフォルト設定で、運営者のカスタム値は **`config/skills/<skill>.yaml`** に置く運用が正しい（deep-merge される）。直接編集を維持して `--force-sync` で上書きすると変更が失われる。

検出時は通常の (a)/(b)/(c) prompt の **前に** 移行案内 prompt を出す:

```
> [HUMAN STEP]
> ⚠ config.default.yaml の直接編集が検出されました:
>   - .claude/skills/<skill1>/config.default.yaml
>   - .claude/skills/<skill2>/config.default.yaml
>
> これらは upstream 管理のデフォルト設定です。直接編集すると yt-skills sync で失われます。
>
> 正しい運用:
>   1. 編集内容を <channel-repo>/config/skills/<skill>.yaml に移す（無ければ新規作成）
>      → config.default.yaml の上に deep-merge される。上書きしたいキーだけ書けば OK
>   2. .claude/skills/<skill>/config.default.yaml は upstream 版で上書き
>
> 対応を選んでください:
>   (a) 移行を手伝う — AI が差分を読み取って config/skills/<skill>.yaml に書き出す
>   (b) 今は対応しない、直接編集を維持（次回 sync で再度警告される）
>   (c) 中止して手動マージ
> a / b / c を返してください。
```

`(a) 移行を手伝う` が選ばれた場合:

1. `yt-skills diff` の出力から該当 `config.default.yaml` の差分を抽出
2. **追加・変更されたキーだけ** を `<channel-repo>/config/skills/<skill>.yaml` に書き出す（既存ファイルがあれば deep-merge、無ければ新規作成）
3. ディレクトリ `config/skills/` が無ければ作成
4. 利用者に書き出した内容を提示して確認
5. その後 Step 3-2 で `--force-sync` を付けて `.claude/skills/<skill>/config.default.yaml` を upstream 版に戻す
6. Step 3-2 へ進む

`(b)` が選ばれた場合は通常の (a)/(b)/(c) 分岐へ進む（今回は直接編集を維持し、Step 3-2 で `--sync-only` allowlist または上書き同期を選ばせる）。
