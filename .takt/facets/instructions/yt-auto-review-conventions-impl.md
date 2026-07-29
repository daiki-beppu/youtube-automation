**実装差分が本リポジトリの規約に整合しているか** だけをレビューしてください。承認された方針どおりに実装されているか、実装の過程で規約から外れていないかを見ます。

他のレビュアーの有無を前提にしないでください。コーディング作法・テスト品質はこのレビューの担当外です。

## 手順

1. 規約文書を Read で開き、**本文を全文取得する**。要約や記憶で判定しない。検査対象は次の 4 系統:
   - リポジトリルートの `CLAUDE.md`
   - `docs/development.md`
   - `docs/skill-design/skill-authoring-guidelines.md`
   - `docs/adr/` の有効 ADR（ADR-0013 = dashboard TS 例外、ADR-0021 = メンテナンスモード）
2. 各文書の規範的な決定（「必ず」「禁止」「〜すること」）を列挙する（取捨選択しない）
3. 変更差分のファイル構成を確認する。特に以下を機械的に検査する:
   - 変更対象モジュールに対応するテストが `tests/test_<対象>.py` の pytest として置かれているか
   - チャンネル固有値のハードコーディングがないか（`config/channel/*.json` + `load_config` 経由になっているか）
   - パッケージ内 import が fully-qualified（`from youtube_automation.xxx import ...`）か
   - 生の `Exception` / `KeyError` を catch していないか（`infrastructure/errors.py` のドメイン例外を使っているか）
   - 新規 CLI が `yt-*` プレフィックスで `pyproject.toml::[project.scripts]` に登録されているか
   - `google-auth-httplib2` の直 import が新規追加されていないか
   - TypeScript の変更が `dashboard/` + `extensions/` の限定例外の範囲に収まっているか（ADR-0021 のメンテナンスモード）
   - 実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したのに `CHANGELOG.md` の `[Unreleased]` が未更新でないか
   - skill を変更した場合、SKILL.md frontmatter の `description:` が double-quoted string か（`uv run yt-skills lint` で検証できる）
4. 承認済みレポート（`diagnosis.md` 等）の「規約整合性の事前申告」と実装を突き合わせる。**申告になかった逸脱が実装に入っていれば違反**
5. 逸脱に対する規約文書の改訂が差分に含まれているかを確認する。含まれていなければ「要規約改訂」で差し戻す（黙って逸脱せず、正当な逸脱は規約文書の改訂を要求する）

**これは {step_iteration} 回目のレビューです。** 再走査の対象は **累積差分全体 × 全規約文書の全決定**です（直近の修正差分ではありません）。Policy の再走査ポリシーと収束ポリシーに従ってください（形式・記載整備の指摘は違反にせず「非ブロッキング指摘」へ）。

## 判定の 3 値

| 判定                                        | 条件                                                                            |
| ------------------------------------------- | ------------------------------------------------------------------------------- |
| 整合                                        | 規約文書の決定に沿っている                                                      |
| 要規約改訂（NEEDS_CONVENTION_REVISION）     | 逸脱に技術的正当性はあるが、差分に規約文書の改訂が含まれていない。**差し戻す**  |
| 違反                                        | 正当性のない逸脱。**差し戻す**                                                  |

## 禁止

- 規約文書に書かれていない設計上の好みを指摘すること
- 規約文書の本文を引用できない指摘を出すこと
- 「既存コードがそうなっている」を正当性として受け入れること
- TS 版（tayk リポジトリ）の実装との差分を根拠にすること
