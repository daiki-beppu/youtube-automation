# Provider / Codex 詳細ガイド

`SKILL.md` で `image_generation.provider` を決定した後、provider 障害からの切り替え、または Codex wrapper の protocol・失敗診断が必要な場合だけ読む。provider の決定、正規コマンド、費用・承認・成果物の gate は `SKILL.md` を正とする。

## Provider 障害時の設定例

Gemini API 障害、GCP 課金切れ、ADC 認証不備、quota 超過が疑われる場合も provider は自動切替しない。生成物の品質差を確認したうえで、明示変更して再実行する。

GCP 課金なしで Codex を使う場合:

```yaml
# config/skills/thumbnail.yaml
image_generation:
  provider: codex
```

OpenAI API に切り替える場合:

```yaml
image_generation:
  provider: openai
  openai:
    aspect_ratio: "16:9"
    # quality 未指定時の既定は medium。high は単価が数倍高いので明示 opt-in のみ
    # quality: high
```

Gemini / OpenAI の全 attempt が失敗した場合、`uv run yt-generate-image` が出す案内からこの設定を選ぶ。自動で別 provider の成果物を上書きしない。

## Codex wrapper の前提と protocol

- codex CLI 0.131 系以降を使う。旧 stdout プロトコル `generated image <id> <base64>` は 0.131 で削除済み
- `codex login status` が `Logged in using ChatGPT` を返し、`jq` が PATH 上にあることを確認する
- wrapper は生成前に最小 `codex exec --json` プローブで CLI とサーバー側デフォルトモデルの互換性を確認する。非互換時は本番生成を呼ばず、CLI version・検出モデル・upgrade 手順を stderr に出して停止する
- TTP 生成では `--require-reference` を付け、参照画像を1件以上渡す。汎用生成では同flagを付けない

直接実行例:

```bash
bash .claude/skills/thumbnail/references/codex-image.sh --require-reference \
  "TTP this reference thumbnail, then improve it into a stronger original thumbnail for cozy cafe morning coffee. Keep the winning layout and make the title readable on mobile." \
  collections/planning/sample/10-assets/thumbnail-codex-v1.png \
  data/thumbnail_compare/benchmark/<channel>/<reference>.jpg
```

複数候補の manifest は `id` / `prompt` / `output` / 任意の `reference` を持つ JSON 配列にする。互換 preflight は batch 全体で1回、各jobは独立した出力先で stale-artifact / PNG / MD5 gate を通る。一部失敗時も残りを完走し、最後に失敗一覧と非0 exitを返す。

wrapper の protocol:

- `codex --version` とloginを確認後、`codex exec --json --skip-git-repo-check -- "Reply with exactly codex-model-compat-ok."` を実行する
- 本番は `codex exec --json --sandbox workspace-write --add-dir <out_dir> --skip-git-repo-check` で起動する
- prompt末尾に新規画像生成、reference非copy、`<out>` へのcopy、最終応答pathの指示を自動付与する
- agent は `~/.codex/generated_images/<thread_id>/ig_*.png` から `<out>` へcopyし、最終 `agent_message.text` で `<out>` を返す
- wrapper は起動前に `rm -f <out>` で stale artifact を削除する
- wrapper は JSONL を `jq` でフィルタし、最後の `agent_message.text` が `<out>` と完全一致すること、成果物の存在・サイズ・PNG headerを検証する
- referenceごとのMD5を事前取得し、最終的に `<out>` の MD5 と一致したら、生成toolを使わずreferenceをcopyした失敗として非0終了する

## 失敗時の診断

- **prompt過長**: 長すぎる prompt は agent が `image_generation` tool 呼び出しを skip して path だけ echo する。既定templateへ戻し、`{title}` だけを差し替える
- **reference copy**: 弱い差分指示では agent が reference を `<out>` に cp するだけで終わる。色味・構図・主役など変更点を明記する
- wrapper は失敗時に CLI version、デフォルトモデル推定値、最終agent message、stderr末尾30行を出す。CLI upgrade、prompt短縮、reference見直しの順で切り分ける
- **NG word**: `codex exec` 前に `image_generation.gemini.forbid_keywords` と照合する。`CODEX_IMAGE_FORBID_KEYWORDS` が非空ならそれを優先し、それ以外はmerged skill configから解決する
