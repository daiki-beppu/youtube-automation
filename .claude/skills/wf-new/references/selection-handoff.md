# Selection and handoff

ユーザーが企画を選択した後の保存、reference assignment、stock archive、cleanup、後工程 handoff の判断詳細を定義する。選択分岐、停止条件、不可逆操作の順序、実行コマンド、Next Step、完了条件は `../SKILL.md` を正とする。

## 採用候補の保存

採用企画は `collection-plan-documents.md` に従い、全件proposedの `20-documentation/plan_proposals.json` + `.html` draft pairから `yt-collection-plan-select` で確定する。候補、制約適合、evidence、insight ID、preview asset、選択 status/source を構造化し、proposal IDとJSON/preview digestを再検証した確定pairの成功後だけ owner CLI が `workflow-state.json` の `planning.generated = true`、`planning.final_title`、`planning.target_persona` を更新する。`preview.skip_cost_confirm: true` なら Phase 4-2 の生成条件と想定 API call 数も candidate に残す。

採用画像がある場合だけ `10-assets/planning-preview.png` として保存する。この画像は企画参照素材であり、textless 動画背景の `main.png/jpg` へコピーしない。採用画像が無い経路では空ファイルや代替画像を作らない。

## Reference assignment

画像を生成した場合は、企画確定後かつセッション cleanup 前に、採用企画へ実際に割り当てた `REF_PATHS[$REF_INDEX]` だけを `record-ttp-reference-assignments.py` で履歴へ保存する。生成途中の候補、不採用候補、未生成候補は記録しない。

履歴保存が non-zero の場合は後続のコピー、stock archive、cleanupへ進まない。原因を解消して同じコマンドを再実行する。コスト拒否または全画像生成失敗の経路では割当履歴を追加しない。

## Stock archive

parallel は採用画像をコピーした後、不採用の成功画像だけを `yt-stock-archive` で `assets/stock/<theme>/` へ退避する。`--exclude` は採用ファイル1枚を除外し、metadataには実際の provider、model、generation mode、prompt、reference images、personaを渡す。

`preview.stock_archive: false` または thumbnail側の `image_generation.stock.enabled: false` でstock退避を無効化した場合は、採用画像を残したままCLIの削除経路へ切り替える。sequentialは不採用画像を生成しないためstock archiveを実行しない。

## Cleanup と失敗時処理

cleanupは必要な保存とarchiveがすべて成功した後にだけ実行する。

- parallel: reference assignment → 採用画像コピー → 不採用画像archive → セッション削除。
- sequential: reference assignment → 採用画像コピー → セッション削除。stock archiveは行わない。
- コスト拒否または成功画像0枚: reference assignmentとコピーを行わず、存在するセッション残骸だけを削除する。
- 一部生成失敗: 採用可能な成功画像の経路を使い、失敗画像をコピーやarchive対象にしない。

放棄された `_plan-previews` セッションは7日以上経過したものだけを手動cleanup対象にする。stock側は先に `uv run yt-stock-prune --dry-run` で候補を確認し、確認なしに削除しない。

## Handoff semantics

完了条件は、検証済み企画 JSON+HTML pair の保存、`planning.generated` と `planning.final_title` の更新、画像がある場合の採用画像とreference assignmentの保存、mode別cleanupの完了である。失敗した必須操作があればhandoffせず、同じ段階から再開する。

完了後は `/thumbnail <theme>` へ渡し、ベンチマーク参照からテキスト付き `thumbnail.jpg` を生成・承認してから、その承認済み画像を入力にtextless `main.png/jpg`を別成果物として確定する。企画プレビューを動画背景に流用しない。サムネイル確定後にだけ `/music --prompt <theme>` へ進む。
