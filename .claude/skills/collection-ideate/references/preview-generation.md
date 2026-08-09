# Preview generation

Phase 4 の parallel / sequential preview について、prompt 構築、provider 呼び出し、生成物、検証、retry、failure handling の詳細を定義する。mode 判定、コスト承認、セッション作成、代表的な実行コマンド、停止条件の順序は `../SKILL.md` を正とする。`yt-generate-image` の通常 flag は CLI help を正とし、ここでは再定義しない。候補内容とセルフチェック設定は `preview-contract.md` に従う。

## Parallel 生成詳細

preview contract の候補 schema で確定した prompt を使い、`candidate_count` 件を a / b / c ... の順に生成する。候補ごとに `select-ttp-references.py` が返した別々の benchmark 参照画像を1枚だけ割り当てる。TTP strict preview は一意な benchmark 参照だけを使い、stock を混ぜない。

- Codex provider は `image_generation.codex.default_prompt_template` と `thumbnail/references/codex-prompt.py` を使う。title 引数には画像へ焼く見出しと短いサブタイトルだけを渡し、動画タイトル全文、composition rule、legend、楽器を重複注入しない。候補数ぶんの一意な参照画像が無ければ生成前に停止する。
- Gemini / OpenAI provider は候補の確定済み prompt と一意な参照割当をSKILL本体の代表コマンドへ渡す。provider 内部の追加 retry は行わない。
- 1候補の生成が non-zero でも、残り候補は順番どおり試行する。成功候補は比較対象へ残し、失敗候補は画像無しのテキスト候補として扱う。
- 出力は `collections/planning/_plan-previews/<dir>/plan-<label>-<slug>.png` とする。

成功画像は一度に開き、同じ候補順で画像、タイトル、prompt、オブジェクトの名前とストーリーを提示する。個別画像の再生成は同じ候補と参照割当でその候補の4-4 commandだけを再実行する。企画自体を変える場合は Phase 3 へ戻る。

## Sequential 生成詳細

画像生成前にテキスト候補から1案を選び、選択ラベルの0-based indexと同じ `REF_PATHS` の1枚だけを使う。不採用案は画像を生成しない。indexに対応する参照が無ければproviderを呼ばず停止する。

provider別のprompt構築、TTP strict reference、ファイル名、no-overwrite契約はparallelと同じで、呼び出し回数だけを1回にする。生成commandがnon-zeroなら画像承認や参照履歴保存へ進まない。

成功した1枚を開き、画像、タイトル、prompt、オブジェクトの名前とストーリーを提示して承認を待つ。承認NGの場合は同じ企画を再生成するか、別のテキスト候補を選び直して同じ4-4 commandへ戻る。sequentialは不採用画像を生成しないためstock退避しない。

## 出力検証と再生成

`self_check.enabled: true` の場合は生成後かつユーザー提示前に、SKILL本体の `yt-thumbnail-check --json` commandで成功画像を検証する。exit 0 は全対象合格、exit 1 は1件以上不合格として扱う。

不合格時は `self_check.max_regeneration_attempts` が1以上なら不合格候補だけを再生成し、同じcheckを再実行する。上限到達または値が0なら警告と検査結果を提示し、明示承認なしに採用しない。check自体を実行できない場合は合格扱いにせず停止する。`self_check.enabled: false` の場合だけcheckを省略する。

## Failure handling

- parallelで一部失敗した場合は後続候補を続行し、成功画像だけを比較表示する。失敗候補は「プレビュー生成失敗」と明記してテキストのみ提示する。
- parallelの生成成功が0枚なら画像比較をスキップし、テキスト候補の選択へ進む。存在するセッション残骸はNext Stepのcleanup契約で削除する。
- sequentialの参照不足、provider non-zero、check実行不能はその段階で停止し、画像承認・参照履歴保存・cleanupへ先行しない。原因を解消後、同じ4-4または4-4-checkから再開する。
- 採用企画の参照割当は企画確定後にSKILL本体のNext Stepで1回だけ保存する。生成途中や不採用候補を履歴へ記録しない。
