# quality / operations 詳細

`SKILL.md` の必須コマンド、承認順序、hard gate、完了条件を変更せず、設定例・採点・チェックリスト・運用時の詳細だけを補足する。

## thumbnail-text-profile 変換

profile が存在する場合は 3 セクションを次のとおり適用する。

| profile セクション | 適用先 | 変換 |
|---|---|---|
| `## font_tendency` | `image_generation.gemini.thumbnail_text.overlay.font.title`（必要なら `overlay.title.stroke_width` / `stroke_color` も） | 日本語対応 .ttf/.otf/.ttc から `typeface_classification` / `weight` に近い書体を選び、`outline: present` なら縁取りを維持 |
| `## text_content_pattern` | `--title` に渡すコピー生成の制約 | `line_count_range` / `languages` / `character_count_range` / `copy_pattern` に従う。競合のチャンネル名・コレクション名・シリーズ名・コピー原文は使わない |
| `## placement_tendency` | `overlay.layout.anchor` / `margin_x` / `margin_y` | `anchor_position` を 9 アンカーのいずれかへ、`margin` をピクセル値へ変換 |

`unknown` のキーは適用せず実効デフォルト値のまま進む。フォント選定はローカルに既にあるファイルだけを対象とし、同梱・自動ダウンロードはしない。profile 不在でも `overlay.font.title` が未設定なら日本語対応フォントを 1 つ選ぶ。候補がない場合は `<channel_dir>/assets/fonts/` への配置を待つか、AI 焼き込み経路へ fallback するかをユーザーに確認する。

## 承認済みサムネイルのアーカイブ

`archive.enabled: true` のときだけ `assets/thumbnail-gallery/<collection-dir-name>.<ext>` へ元の拡張子と内容のままコピーする。同じ collection の再承認は最新の確定サムネで置き換え、無効時は副作用なしで終了する。シンボリックリンクやコピー失敗は成功として扱わない。アーカイブまたは workflow-state 更新に失敗した自動選択は、確定サムネ・ギャラリー・workflow-state を元に戻す。

## フォント運用

single_step の初回 `diff_prompt_template` はテキスト付き `thumbnail-v*.jpg/png` 候補生成用。AI 焼き込み経路では `single_step.typography_clause` を opt-in で展開し、`{font_description}` を `thumbnail_text.font.copy` で置換する。textless 再生成プロンプトには `${typography_clause}` やタイトル描画指示を入れない。two_phase は Phase 2 で `thumbnail_text.font.copy` / `font.genre_tag` を使う。

決定的合成では `image_generation.gemini.thumbnail_text.overlay.font.title` に channel_dir 相対または絶対パスのフォントを設定する。フォントは `<channel_dir>/assets/fonts/` に配置し、ライセンス条項を確認する。未設定、ファイル不在、壊れたフォントはそれぞれ設定・配置・代替ファイルを見直す。AI 経路へ切り替える場合は厳密なフォント再現が保証されないことを伝える。

## auto-selection 設定と採点

`image_generation.auto_selection` で `enabled`、`mode`、`min_width`、`min_height`、`aspect_tolerance`、`max_reference_distance`（既定 0.40）を設定する。`selection_only` は候補承認だけを省略し、`full` は `SKILL.md` の表に示す 4 ゲートを省略する。

`image_generation.gemini.reference_images.default` の各参照画像から brightness / contrast / saturation / dominant_hue / colorfulness を抽出して centroid を作る。各参照の centroid 距離が上限を超えた場合、`selection_only` は構造化診断を残して警告継続し、`full` は候補確定前に停止する。`yt-generate-image --ttp-strict-references` でも同じ診断を生成 API 呼び出し前に行う。16:9 と最小解像度を満たす候補を採点し、centroid への distance が最小の候補を選ぶ。apply 時は PNG 候補を必要に応じて JPEG へ変換し、`thumbnail_auto_selection` に選択候補・distance・ランキング・参照ごとの診断・実行時刻を記録する。prompt の色・背景指定だけを参照プールの構造的な外れ値対策として扱わない。

候補なし、参照なし、解像度や 16:9 条件を満たす候補なし、確定済みファイル存在、無効設定は silent fallback せず停止する。

## QA チェックリスト

テキスト付き thumbnail 候補生成後:

- [ ] ベンチマーク参照の構図・主役スケール・光・色温度・背景テクスチャが維持されている
- [ ] `/thumbnail-compare` で 320px 縮小時のタイトル可読性・コントラスト・主役認識を確認した
- [ ] タイトルテキストが `composition_rules.text_lines` の制約内である
- [ ] `thumbnail_text.channel_name` が表示され、署名・ロゴ・透かしが焼き込まれていない
- [ ] `image_generation.gemini.style` に記載されたスタイルが維持されている
- [ ] `fixed_character` の外見が維持されている（設定されている場合）
- [ ] キャラの顔が `fixed_character.face` の指示どおり見えている
- [ ] **解剖学チェック（手・指）**: 各手 5 本指、指の分離、本数異常・融合・溶融・プロポーション破綻がないことを等倍で目視確認した

textless main 候補生成後:

- [ ] 承認済み `thumbnail.jpg` の構図・主役スケール・光・色温度・背景テクスチャが維持されている
- [ ] タイトル文字、字幕、ロゴ、透かし、タイポグラフィ、チャンネル名が残っていない
- [ ] 新しい文字や記号が追加されていない
- [ ] `/loop-video` 入力や `/videoup` 静止背景として使える

手指の破綻が出るチャンネルは `image_generation.gemini.single_step.anatomy_clause` を opt-in で展開する。`/wf-new` の single_step プレビューは企画参照素材であり、最終 thumbnail に流用しない。

## プロンプト保存テンプレート

```markdown
# Thumbnail Prompts - <コレクション名>

*プロバイダー: {image_generation.provider}*
*スタイル: {image_generation.gemini.style}*
*モデル: {image_generation.gemini.model}*

## Reference Assignments

| attempt | output | reference_image | benchmark_channel |
|---:|---|---|---|
| 1 | `10-assets/thumbnail-v1.jpg` | `<参照画像 1>` | `<benchmark_channel>` |
| 2 | `10-assets/thumbnail-v2.jpg` | `<参照画像 2>` | `<benchmark_channel>` |
| 3 | `10-assets/thumbnail-v3.jpg` | `<参照画像 3>` | `<benchmark_channel>` |

## Text-Included Thumbnail Prompt (thumbnail.jpg)

<テキスト付きサムネを生成したプロンプト>

## Textless Background Prompt (main.png/main.jpg)

<テキストなし背景を生成したプロンプト>

## A/B Test Pattern Prompts

| pattern | final output | variation |
|---|---|---|
| `a` | `10-assets/thumbnail-a.jpg` | `<pattern a variation>` |
| `b` | `10-assets/thumbnail-b.jpg` | `<pattern b variation>` |

### Pattern a Final Prompt

<diff_prompt_template 展開結果 + pattern a variation>

### Pattern b Final Prompt

<diff_prompt_template 展開結果 + pattern b variation>
```

## stock 退避と再利用

隣接 `<image>.meta.json` は schema_version=1 とし、prompt / provider / model / generation_mode / source_collection / reference_images / generated_at / rejected_at を保存する。`image_generation.stock` の `enabled`、`retention_days`、`max_per_theme` で退避と保持上限を調整する。

stock 参照は `reference_images.default` と別スコープにし、`--ttp-strict-references` では混在させない。汎用参照生成でだけ `enabled: true` を明示し、`max_count` / `shuffle` / `theme_match` / `source_role` を調整する。採用時は stderr の `[INFO] stock 採用` ログで path / theme / role を監査する。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| GCP ADC 未取得/失効 | `ConfigError` / ADC 認証エラー | `gcloud auth application-default login`（必要なら `set-quota-project`）を再実行 |
| Vertex AI rate | HTTP 429 | 時間を置いて再実行し、並列実行を避ける |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Vertex AI のステータスを確認し、時間を置く |
| 画像 provider 障害 | 片方の provider のエラー | `image_generation.provider` を `gemini` ↔ `openai` で切り替える |
