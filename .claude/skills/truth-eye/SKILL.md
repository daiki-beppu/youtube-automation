---
name: truth-eye
purpose: 振り返る
description: "Use when 競合の伸びた側 / 伸びなかった側のサムネペアで人間が先にブラインド回答し、AI の封印分析と照合して観察眼を鍛える訓練セッションを行うとき。未完了の記録があれば自動で再開し、なければ新規ペアを提案する。「真実の目」「サムネ訓練」「観察眼を鍛える」「目を鍛える」「ブラインド分析」「訓練セッション」「サムネの答え合わせ」で発動。AI に競合サムネを分析させるなら channel-research の thumbnail mode、自チャンネルのサムネ生成・改善は /thumbnail を使う"
---

## 前後工程

- `前工程`: `/channel-research --benchmark`
- `後工程`: `/thumbnail`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `docs/benchmarks/training/*.md`
- `読み込む`: `docs/benchmarks/training/*.md`, `data/benchmark_*.json`, `docs/benchmarks/thumbnails/*.jpg`, `config/channel/analytics.json`

## 前提ガード

`config/channel/` が存在し `load_config()` で読めることを確認する。満たさなければ `/setup` を案内して停止する。`yt-truth-eye pair` が旧 shape または benchmark JSON 不在で停止した場合は、そのメッセージをそのまま示して停止し、収集を代行しない。

## 完了条件

`next_try` が非 null の訓練記録と同 stem の `.sealed.md` が存在し、`uv run yt-truth-eye verify <record.md>` が成功していること。

## Phase 0: 準備

1. `uv run yt-truth-eye status` を実行する。未完了 1 件なら再開か破棄かを尋ねる。2 件以上なら一覧を示して新規開始を拒む。
2. 破棄時は対象の記録と封印分析を示し、**rm は復元不可**と警告する。`AskUserQuestion` で「2 ファイルを破棄する / 中止する」の明示 2 択を出し、承認前には削除しない。
3. `last_next_try` は読み上げるだけで達成を問わない。反復観点は `recurring_ai_only_viewpoints` の観点名だけを伝える。
4. `uv run yt-truth-eye pair` の先頭候補を `references/pair-selection.md` の形式で 1 組提示する。却下は `--rejected <video_id>` を累積して再実行し、3 回で終了して funnel と bottleneck を示す。
5. 承認後、subagent に `references/sealed-analysis.md` を渡し、指定された画像・メタデータだけから下書きを作らせる。メインセッションは内容を受け取らず path だけを受け取る。
6. `uv run yt-truth-eye seal --pair <pair.json> --sealed-draft <draft.md>` を実行する。不合格なら subagent にやり直させるのは最大 2 回。なお不合格なら中止し、メインセッションは代筆しない。
7. sha256 と自動 commit の成否だけを伝える。メインセッションは Phase 4 の verify 成功前に `.sealed.md` を読まない。

## Phase 1: ブラインド回答

人間に記録 Markdown の表を直接編集して「記入した」と宣言してもらう。AI は転記しない。空欄は許容する。

## Phase 2: grilling

`references/grilling.md` の 5 型だけを使い、最大 8 問。人間の言葉を一字一句転記し、要約・言い換え・誤字修正をしない。AI 自身の見立ては言わない。

## Phase 3: 出し切り宣言と促し

出し切り宣言後、`references/viewpoints.md` に従って未言及観点を 1 つずつ「答える / パス」で尋ねる。必須から任意の順で最大 3 観点。全てパスでも進む。

## Phase 4: 開示と照合

1. `uv run yt-truth-eye verify <record.md>` で hash を照合する。成功するまで封印分析を読まない。
2. `references/record-format.md` の 4 列表を記録へ書く。対立点を寄与順位順で 1 つ選び、「維持 / 変更 / 保留」の三択で再見解を尋ねる。事実の相違は問い直さない。
3. 封印分析全文を開示し、人間からの質問があれば答える。

## Phase 5: 学び

照合表の「AI だけ」「対立」と「表にないもの」から「試す 1 点」を選択式で 1 つ決める。人間の言葉を一字一句、frontmatter の `next_try.viewpoint`（表外は null）と `next_try.text` に転記する。完了時の commit は人間に委ねる。

## 中断・再開

記録ファイルだけを状態の正本とする。`status` の `resume_phase` から再開し、Phase 2 は `phase2_turns` を 8 問の上限から差し引く。同じ封印ファイルを `verify` して使う。
