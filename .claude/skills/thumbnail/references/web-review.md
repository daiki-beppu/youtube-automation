# Thumbnail Web review

手動承認は、成功候補と既存QAを固定してから `yt-thumbnail-review` へ渡す。HTMLは表示とmanifest内IDの選択だけを担い、正本・採点入力・path入力にはしない。

## 候補QA sidecar

各候補と同じdirectoryに `<画像filename>.review.json` を置く。たとえば `thumbnail-v1.jpg.review.json`。UTF-8 JSONの必須形は次のとおり。

```json
{
  "schema_version": 1,
  "candidate_id": "thumbnail-v1",
  "artifact": "thumbnail",
  "pattern": null,
  "image_sha256": "<64 lowercase hex>",
  "thumbnail_check": {"status": "not_applicable", "summary": "text付き候補は比較QAで確認"},
  "comparison_qa": {"status": "passed", "summary": "320px可読性、コントラスト、主役認識を確認"},
  "metadata": {"attempt": 1, "provider": "gemini"},
  "evidence": ["採用TTPの構図を維持"],
  "constraints": ["16:9", "logoなし", "署名なし"]
}
```

- `candidate_id`: run内で一意なopaque ID。filenameやpathとして解釈しない。
- `artifact`: `thumbnail` または `main`。候補名から判定した種別と一致させる。
- `pattern`: 通常thumbnail/mainは `null`、`thumbnail-<pattern>-vN.*` は `<pattern>`。
- `image_sha256`: QAを実行した画像そのもののSHA-256。
- `thumbnail_check` / `comparison_qa`: 両方必須。`status` は `passed` / `failed` / `not_applicable`、`summary` は非空文字列。CLIのJSON出力と目視比較結果を要約し、自由編集可能なHTMLへは保存しない。
- `metadata` / `evidence` / `constraints`: 候補の生成attempt/provider、採用根拠、制約確認を空でない値として固定する。同じcardへescapeして表示する。

候補画像・sidecar・`10-assets`・正規出力のsymlinkは禁止する。候補名は `thumbnail-vN.*` / `thumbnail-codex-vN.png` / `thumbnail-<pattern>-vN.*` / `main-vN.*` の固定形だけを列挙する。外部URL、absolute path、`..`、sidecar内の任意pathは入力契約に存在しない。

## 実行

```bash
uv run yt-thumbnail-review --collection <collection-path> --artifact thumbnail
uv run yt-thumbnail-review --collection <collection-path> --artifact thumbnail --pattern a
uv run yt-thumbnail-review --collection <collection-path> --artifact main
```

出力は固定名 `tmp/reviews/thumbnail-selection.html` へatomic overwriteする。各候補を原寸と実幅320pxで並べ、filename、dimensions、QA summaryを同じcardに表示する。CSPはscript/外部resourceを拒否し、文字列はescapeする。

browserが使えない場合は `--transport terminal` でID一覧を出し、会話確認後に `--candidate-id <ID>` を追加する。Web/terminalとも選択直前に画像とsidecarを再hashし、scopeとdigestが一致した場合だけ確定する。automatic modeはこのHTML/brokerを通さず、既存 `yt-thumbnail-auto-select --apply` を使う。
