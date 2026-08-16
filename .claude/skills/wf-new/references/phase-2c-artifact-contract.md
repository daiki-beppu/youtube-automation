# Phase 2c 成果物・再開契約

Phase 2c の thumbnail branch と music branch は、生成順序とは独立にこの契約で結果を確定する。各 branch の検証、state 適用、停止案内はメインエージェントが所有し、subagent は `workflow-state.json` を書き込まない。

## Branch 検証

subagent の完了報告は成功根拠にしない。メインエージェントが同じ固定済み collection の実成果物を読み、branch ごとに成功または失敗と理由を確定する。片方の検証失敗を、もう片方の検証結果へ伝播させない。

### thumbnail

- mode 別の承認または自動確定と既存 QA が完了している
- `/thumbnail --compare` の 320px 視認性検証に合格している
- `10-assets/thumbnail.jpg` が存在し、画像として読み取れる
- `textless.enabled` が `true` の場合は、確定済みの `10-assets/main.png` または `10-assets/main.jpg` が存在し、既存 check に合格している
- `textless.enabled` が `false` の場合は `share_thumbnail_as_main.py` の `status: SHARED`、`thumbnail.jpg` と `main.jpg` の同一 SHA-256、`main.png` 不在を確認している

候補だけ、未承認の画像、空ファイル、symlink、QA 不合格、片方しかない確定成果物は失敗とする。

### music

Suno は次をすべて満たす場合だけ成功とする。

- `20-documentation/suno-patterns.yaml` と `20-documentation/suno-prompts.json` が対象 collection に存在する
- `uv run yt-suno-verify <collection-path>` が exit 0 になる
- semantic review が成功する

Lyria は対象 collection の `20-documentation/lyria-prompt.json` / `.html` pairが共通readerで再読込でき、schemaのengine、provenance、entry style/options/track role、verify・semantic review結果が固定済み theme と `music_engine: lyria` に整合する場合だけ成功とする。この Phase では Lyria API の音源生成を成功条件に含めない。

## State 適用

独立検証した2結果をメインエージェントだけが branch ごとに直列適用する。成功した branch の flag と `updated_at` だけを更新し、失敗 branch、既存の成功済み flag、`phase`、その他の state は変更しない。両 branch が成功するまで後続 phase へ進めない。

| thumbnail | music | state mutation |
|---|---|---|
| 成功 | 成功 | `assets.thumbnail = true` と `assets.music_prompts = true` |
| 失敗 | 成功 | `assets.music_prompts = true` だけ |
| 成功 | 失敗 | `assets.thumbnail = true` だけ |
| 失敗 | 失敗 | 変更しない |

成功済み flag を `false` に戻さない。失敗 branch の flag を `true` にしない。state の読み取り・更新・再読み取りを一度に1 branchずつ行い、subagent の同時書き込みや一方の古い snapshot による上書きを許可しない。

片側または両側が失敗した場合は、成功結果を適用した後に停止する。失敗した branch、実際の検証失敗理由、同じ collection での再開 action を表示する。

## 再開判定

Phase 2c の開始時は flag だけで完了を判断せず、flag と実成果物を再検証する。

- flag が `true` で実成果物も検証成功: 検証成功済み branch は再生成・再承認しない
- flag が `false` で実成果物が検証成功: subagent を再実行せず、State 適用へ進む
- flag が `false` で実成果物が未完成または検証失敗: その branch だけを再実行する
- flag が `true` なのに対応成果物が欠落・破損・不整合: 完了扱いせず fail-closed に停止し、正常な別 branch の state と成果物は変更しない

thumbnail branch だけが未完了なら、`finalize_planning_preview.py` の決定結果に従って preview の品質検証・確定または `/thumbnail <theme>` から再開する。music branch だけが未完了なら、固定済み engine に従い `/music --prompt <theme>` または `/music --generate <theme>` から再開する。

停止報告には collection path、失敗 branch、失敗理由、保持した成功 branch、次の action を含める。別 collection や別 theme へ切り替えず、同じ collection の未完了 branch だけを対象にする。
