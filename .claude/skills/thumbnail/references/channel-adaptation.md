# Channel adaptation

すべての設定は `config/skills/thumbnail.yaml` から読み取り、スキル内にチャンネル固有値をハードコードしない。作業前に Read tool（Codex では同等のファイル閲覧）で `.claude/skills/thumbnail/config.default.yaml` とチャンネル側上書きの `config/skills/thumbnail.yaml` を開き、deep-merge 後の実効値を確認する。

実行前に次を確認する。

1. `image_generation.provider`: 使用するプロバイダー（`gemini` / `openai` / `codex`）
2. `image_generation.gemini.model`: 使用する Gemini モデル
3. `image_generation.gemini.style`: 参照画像ベースのスタイル説明
4. `image_generation.gemini.prompt_prefix`: キャラ描写などプロンプト冒頭の固定文
5. `image_generation.gemini.reference_images.default`: 同じベンチマークチャンネル内の参照画像リスト（single_step では必須）
6. `image_generation.gemini.fixed_character`: 固定キャラ設定
7. `image_generation.gemini.composition_rules`: 構図ルール。既定は `text_lines` のみで、旧個別キーは deprecated。意図は `diff_prompt_template` 本文へ移す
8. `image_generation.gemini.thumbnail_text`: テキストオーバーレイ設定。`text_overlay_prompt` が単一入口で、旧個別フィールドは deprecated
9. `image_generation.gemini.generation_mode`: 生成モード
10. `image_generation.gemini.brand_background`: single_step / diff_from_reference で使うチャンネル統一背景色
11. `image_generation.gemini.color_themes`: single_step で差し替えるテーマ別カラーパレット
12. `archive.enabled`: 承認済みサムネイルのギャラリー保存（既定 `false`）
13. `image_generation.gemini.forbid_keywords`: NG ワード。最終プロンプトへ大小文字無視で部分一致したら生成前に停止する。未設定・空なら no-op で、Gemini / codex の両入口に適用する
14. `image_generation.auto_selection.enabled` / `mode`: 承認ゲートの分岐。`mode` 未設定時は `selection_only`
15. `ab_test.enabled` / `ab_test.patterns`: Studio Test & compare 用 pattern。既定 `false`、有効時は 1〜3 件の `name` / `variation`
