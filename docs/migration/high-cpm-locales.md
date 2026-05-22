# high-CPM ローカライズ移行ガイド

Issue #272 に対応するための移行手順。`config/localizations.json` の canonical 言語を
高 CPM の `ja` / `en` / `de` に絞り、低 CPM 言語 `ko` / `es` / `pt` / `zh-CN` を削除する。

> **背景**: 本 issue では Analytics 実データの分析は行わず、一般に広告単価が高い市場を優先する。
> 英語圏とドイツ語圏を必須化し、YouTube アクセス制限のある `zh-CN` と low-CPM tier は外す。

> **所要時間の目安**: 5〜10 分（`config/localizations.json` を運用しているチャンネルのみ対象）

## 前提確認

`config/localizations.json` に low-CPM 言語が残っているチャンネルが対象。

```bash
grep -n '"ko"\|"es"\|"pt"\|"zh-CN"' config/localizations.json
```

何もヒットしなければ、この migration の main 作業は不要。

## ステップ 1 - `supported_languages` を high-CPM tier に置換

```bash
python - <<'PY'
import json, pathlib

path = pathlib.Path("config/localizations.json")
if not path.exists():
    raise SystemExit(0)

data = json.loads(path.read_text(encoding="utf-8"))
data["supported_languages"] = ["ja", "en", "de"]

path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"updated: {path}")
PY
```

## ステップ 2 - low-CPM 言語を削除し、`en` / `de` を追加

`examples/localizations.example.json` を canonical 例として、`languages` セクションを更新する。

```bash
python - <<'PY'
import json, pathlib

path = pathlib.Path("config/localizations.json")
if not path.exists():
    raise SystemExit(0)

data = json.loads(path.read_text(encoding="utf-8"))
languages = data.setdefault("languages", {})

for code in ("ko", "es", "pt", "zh-CN"):
    languages.pop(code, None)

languages.setdefault("ja", {
    "title_template": "{scene_phrase} | RPG BGM ({activities})",
    "activities": "ゲーム · 勉強 · 集中",
    "description": {
        "opening_poem": "ピクセルの夜、冒険の調べ",
        "cta_subscribe": "チャンネル登録お願いします！",
        "tagline": "チップチューンアドベンチャーをお届けします！",
        "hashtags": "#chiptune #8bit #BGM",
    },
})
languages["en"] = {
    "title_template": "{scene_phrase} | RPG BGM ({activities})",
    "activities": "Gaming · Study · Focus",
    "description": {
        "opening_poem": "Pixel nights, melodies of adventure",
        "cta_subscribe": "Subscribe for more adventures!",
        "tagline": "Chiptune adventures await you!",
        "hashtags": "#chiptune #8bit #BGM",
    },
}
languages["de"] = {
    "title_template": "{scene_phrase} | RPG BGM ({activities})",
    "activities": "Gaming · Lernen · Fokus",
    "description": {
        "opening_poem": "Pixelnacht, Melodie des Abenteuers",
        "cta_subscribe": "Abonniere für neue Abenteuer!",
        "tagline": "Chiptune-Abenteuer für dich!",
        "hashtags": "#chiptune #8bit #BGM",
    },
}

data["languages"] = {code: languages[code] for code in ("ja", "en", "de")}
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"updated: {path}")
PY
```

## ステップ 3 - `config/channel/youtube.json` の `content_model.languages` を同期

loader は `content_model.languages` が `localizations.supported_languages` の部分集合であることを要求する。

```bash
python - <<'PY'
import json, pathlib

path = pathlib.Path("config/channel/youtube.json")
if not path.exists():
    raise SystemExit(0)

data = json.loads(path.read_text(encoding="utf-8"))
content_model = data.get("content_model")
if not isinstance(content_model, dict):
    raise SystemExit("content_model section is missing")

content_model["languages"] = [code for code in content_model.get("languages", []) if code in {"ja", "en", "de"}]

path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"updated: {path}")
PY
```

## ステップ 4 - `scene_phrases` を新言語セットに揃える

既存コレクションに `workflow-state.json` がある場合は、`supported_languages` と一致するよう再生成する。

```bash
uv run yt-populate-scene-phrases
```

## ステップ 5 - 検証

ローカル監査:

```bash
uv run yt-metadata-audit --local
```

残骸チェック:

```bash
grep -rln '"ko"\|"es"\|"pt"\|"zh-CN"' config/ collections/
```

## 過去アップロード済み動画の取り扱い

この issue では過去動画の遡及再生成や一括書き換え CLI は提供しない。運用判断として次のいずれかを選ぶ。

1. YouTube 側 metadata 更新のタイミングで新しい locale セットに置き換える
2. 必要な動画だけ手動で `videos.update` する
3. `uv run yt-metadata-audit --remote` で残存を検出し、別 issue で追跡する

## チェックリスト

- [ ] `config/localizations.json.supported_languages` が `["ja", "en", "de"]`
- [ ] `config/localizations.json.languages` に `ko` / `es` / `pt` / `zh-CN` が残っていない
- [ ] `config/channel/youtube.json.content_model.languages` が `ja` / `en` / `de` の部分集合
- [ ] `uv run yt-metadata-audit --local` が locale 関連 issue 0 件
- [ ] `grep -rln '"ko"\|"es"\|"pt"\|"zh-CN"' config/ collections/` がヒット 0

## Out Of Scope

- Analytics 実データの取得と分析
- 個別チャンネルの既存コレクション再生成
- 過去アップロード済み動画の自動書き換え
