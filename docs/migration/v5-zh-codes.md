# v5.0.0 移行ガイド — 中国語コード `zh-Hans` / `zh-Hant` → `zh-CN` / `zh-TW`

`youtube-channels-automation` v4.x → **v5.0.0** への移行手順。中国語ローカライゼーションコードを
YouTube Data API v3 が公式サポートする `zh-CN` / `zh-TW` に統一する破壊的変更。

> **背景**: YouTube Data API の `i18nLanguages.list()` が返す中国語関連の公式コードは
> `zh-CN` / `zh-HK` / `zh-TW` の 3 種のみで、`zh-Hans` / `zh-Hant` は含まれない。
> 過去は `zh-Hans` / `zh-Hant` で投稿しても黙って受け付けられていたが、2026-04-22 頃から
> アップロード時に `zh-CN` / `zh-TW` へ強制正規化されるよう挙動変化が観測された。
> リポジトリ内のリテラル・期待値・ローカル設定を canonical に揃える。

> **所要時間の目安**: 5〜10 分（`zh-Hans` / `zh-Hant` を使用しているチャンネルのみ対象）

## 前提確認

`config/localizations.json` の `supported_languages` または `languages.*` キー、もしくは
`collections/*/workflow-state.json` の `scene_phrases` キーに `zh-Hans` / `zh-Hant` を含むチャンネルが対象。

ヒット有無を確認:

```bash
grep -rln '"zh-Hans"\|"zh-Hant"' config/ collections/
```

何もヒットしなければ本ガイドの作業は不要（`yt-skills sync --force` のみ実行）。

## ステップ 1 — automation を v5.0.0 に pin-bump

チャンネルリポジトリの `pyproject.toml` で automation のバージョンを v5.0.0 に上げる:

```toml
dependencies = [
    "youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation@v5.0.0",
]
```

`uv sync` を走らせて新バージョンを取得:

```bash
uv sync --extra dev
```

## ステップ 2 — `config/localizations.json` のキー置換

`supported_languages` および `languages.<lang>` キーを `zh-Hans` → `zh-CN`、`zh-Hant` → `zh-TW` に変更:

```bash
python - <<'PY'
import json, pathlib
p = pathlib.Path("config/localizations.json")
if not p.exists():
    raise SystemExit(0)
data = json.loads(p.read_text(encoding="utf-8"))

def rename(code: str) -> str:
    return {"zh-Hans": "zh-CN", "zh-Hant": "zh-TW"}.get(code, code)

if "supported_languages" in data:
    data["supported_languages"] = [rename(c) for c in data["supported_languages"]]
if "languages" in data:
    data["languages"] = {rename(k): v for k, v in data["languages"].items()}

p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"updated: {p}")
PY
```

## ステップ 3 — `collections/*/workflow-state.json` の `scene_phrases` 置換

各コレクションの workflow-state を一括変換:

```bash
python - <<'PY'
import json, pathlib
def rename(code: str) -> str:
    return {"zh-Hans": "zh-CN", "zh-Hant": "zh-TW"}.get(code, code)

count = 0
for ws in pathlib.Path("collections").rglob("workflow-state.json"):
    state = json.loads(ws.read_text(encoding="utf-8"))
    sp = state.get("scene_phrases")
    if not isinstance(sp, dict):
        continue
    new_sp = {rename(k): v for k, v in sp.items()}
    if new_sp == sp:
        continue
    state["scene_phrases"] = new_sp
    ws.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    count += 1
    print(f"updated: {ws}")
print(f"\n{count} workflow-state.json updated")
PY
```

## ステップ 4 — 検証

ローカル監査:

```bash
uv run yt-metadata-audit --local
```

`workflow-state.scene_phrases missing langs` 等の issue が出なくなることを確認。

リモート監査（YouTube API 経由、認証済みチャンネルが対象）:

```bash
uv run yt-metadata-audit --remote
```

`YT zh codes are [...], expected ['zh-CN','zh-TW']` の指摘が出なくなれば完了。

最後に残骸チェック:

```bash
grep -rln '"zh-Hans"\|"zh-Hant"' config/ collections/
```

何もヒットしなければ migration 完了。

## 過去アップロード済み動画の取り扱い

すでに YouTube に投稿済みで `localizations` に `zh-Hans` / `zh-Hant` キーが残っている動画がある場合、
本リリースには専用の書き換え CLI は含まれない（運用ツールは別 issue のスコープ）。

選択肢:

1. **YouTube 側に任せる**: アップロード後 YouTube が `zh-CN` / `zh-TW` に正規化する挙動が
   2026-04-22 頃から観測されている。次回 `videos.update` 時に新キーで上書きされ、
   旧キーは消える可能性が高い（patch ではなく replace セマンティクス）。
2. **手動で `videos.update`**: `gcloud` / `curl` で `videos.update?part=localizations` に
   新キーで上書きする。手数が多い場合は別 issue を起票して CLI 化を検討する。
3. **`yt-metadata-audit --remote` で残存検出**: 上記いずれの方法でも、最終確認として
   audit を回せば残っている動画 ID が一覧化される。

## トラブルシューティング

### `ConfigError: content_model.languages に localizations.supported_languages へ未登録の言語があります: ['zh-CN']`

`config/channel/youtube.json` の `content_model.languages` 配列にも `zh-Hans` / `zh-Hant` が
混入している可能性。同様に `zh-CN` / `zh-TW` に書き換える:

```bash
grep -n '"zh-Hans"\|"zh-Hant"' config/channel/youtube.json
```

### preflight で `scene_phrases missing langs: ['zh-CN']` が出る

ステップ 2 で `localizations.json` を書き換えたが、ステップ 3 で workflow-state を書き換えていない場合に発生。
ステップ 3 のスクリプトを再実行する。

## チェックリスト

- [ ] `config/localizations.json` の `supported_languages` / `languages.*` が `zh-CN` / `zh-TW`
- [ ] `collections/*/workflow-state.json` の `scene_phrases` キーが `zh-CN` / `zh-TW`
- [ ] `config/channel/youtube.json` の `content_model.languages` に `zh-Hans` / `zh-Hant` が残っていない
- [ ] `uv run yt-metadata-audit --local` が zh-codes 関連 issue 0 件
- [ ] `uv run yt-metadata-audit --remote` の zh-codes 指摘が許容範囲（過去動画は別途運用判断）
- [ ] `grep -rln '"zh-Hans"\|"zh-Hant"' config/ collections/` がヒット 0
- [ ] コミット + push
