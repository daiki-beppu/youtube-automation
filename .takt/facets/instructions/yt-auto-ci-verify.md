CI 同等ゲートをローカルで全件実行し、結果を判定してください。本リポジトリはローカル git hook を持たず、品質ゲートは CI(`.github/workflows/ci.yml`)が正です(docs/development.md「品質ゲート(CI)」)。workflow 完了後の auto_pr による push を止める関門はここしかありません。**PR の CI で落ちる失敗を、push 前にこの step で見つけます。**

## 手順

1. 以下の全ゲートを **順不同でよいので全件** 実行する。1 つが落ちても残りを実行し、全体像を掴む:

   ```
   nix develop --command uv run ruff check .
   nix develop --command uv run ruff format --check .
   bash .github/scripts/any-usage-gate.sh
   nix develop --command uv run pytest
   ```

2. 変更内容に応じた追加ゲートを実行する:
   - 実コード(`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`)を変更している → `CHANGELOG.md` の `[Unreleased]` に今回の変更が記載されているかを確認する。無ければ追記する
   - `.claude/skills/` を変更している → `uv run yt-skills lint` を実行する
   - `.takt/workflows/` または `.takt/facets/` を変更している → `takt workflow doctor` を実行する(takt が環境に無い場合はスキップし、その旨を報告に残す)
3. 落ちたゲートを分類する:
   - **機械的に直せる**: `ruff format` の適用、ruff の自明な指摘(未使用 import の削除等)、CHANGELOG の追記漏れ。→ この step で直し、**直した内容を報告に列挙して**全ゲートを再実行する
   - **実装の欠陥**: テストの失敗、any-gate の検出、ruff の設計に関わる指摘。→ この step では直さない。実装ゲートへ差し戻す
4. 各ゲートの結果(green / red / スキップと理由)を漏れなく報告する

## 制約

- **テストの削除・skip・アサーション緩和でゲートを通さない。** red のテストは差し戻しの根拠であって、消す対象ではない
- 機械的修正の範囲を超えない。「ついでにこの実装も直す」はしない — 実装の修正は実装レビューのループ(レビューの目が届く場所)で行う
- ゲートを 1 つでも未実行のまま「green」と報告しない。実行できなかったゲートは、その理由とともに red 扱いで報告する
- `--no-verify` / ゲート定義の書き換え / CI 設定の弱体化で通さない

## 判定

- 全ゲートが green(機械的修正のみで到達した場合を含む)→ 次のゲートへ進む
- 実装の欠陥が原因で green にできない → 実装ゲートへ差し戻す。**どのゲートがどう落ちたか**(コマンド・失敗出力の要点・該当ファイル)を報告に残す — 差し戻し先のレビューはこの報告を読めないため、レポートに書くことでのみ伝わる
- 環境障害(nix / uv が動かない等)でゲートを実行できない → ABORT。実行できなかったコマンドと失敗の内容を残す
