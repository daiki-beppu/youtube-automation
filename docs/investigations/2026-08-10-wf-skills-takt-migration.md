# 制作ワークフロー skill を takt workflow + facet で代替できるか

調査日: 2026-08-10

対象 takt: 0.55.1

対象 issue: [#2576](https://github.com/daiki-beppu/youtube-automation/issues/2576)

## 結論

4 択では **「現行 skill 維持」**を選ぶ。

takt 0.55.1 は step、facet、決定的な `when(...)`、人間入力 rule、run 保存を備えており、制作工程の順序を YAML へ写すこと自体はできる。実際、この repository でも issue から PR までの開発 workflow 7 本を `.takt/workflows/` で管理している。しかし制作 workflow の難所は工程順ではなく、次の 4 つである。

1. `workflow-state.json` と実成果物を一段ごとに突合する domain 固有の再開判定
2. config によって有無が変わる承認 gate と、承認対象を実ファイル・公開予定へ結び付ける検証
3. Suno、YouTube、OAuth など外部 UI / API の副作用を重複させない reconciliation
4. login / CAPTCHA / マスタリングのように、同じ agent session の外まで停止が続く人間 handoff

これらを takt の run 進行にも持たせると、`workflow-state.json` と takt の run / session が同じ「現在地」を二重に所有する。逆に `workflow-state.json` を正として残すなら、takt workflow は毎 step で既存 skill または resolver を呼ぶ薄い外殻になり、現行 `/wf-auto` と責務が重複する。下流配布にも takt binary、version pin、provider 認証、workflow/facet 配布という新しい運用前提が増える。

したがって制作の正規入口は `/wf-auto`、単段入口は `/wf-new` / `/wf-next` のまま維持する。takt は現在採用済みの開発 workflow に限定する。全面移行・部分置換の PoC は本調査では行っていない。

## 調査方法と一次証跡

記憶ではなく、checkout の現行ファイルとインストール済み CLI を一次情報にした。

| 確認項目 | コマンド / 一次情報 | 2026-08-10 の観測結果 |
|---|---|---|
| takt version | `takt --version` | `0.55.1` |
| workflow authoring | `takt workflow --help` | `init` / `doctor` を提供 |
| facet catalog | `takt catalog --help` | `personas` / `policies` / `knowledge` / `instructions` / `output-contracts` |
| project workflow 妥当性 | `takt workflow doctor` | tracked workflow 7 本すべて `Workflow OK` |
| 人間入力 rule | takt 0.55.1 同梱 `builtins/skill/references/yaml-schema.md` の Rules 定義 | `requires_user_input` と `interactive_only` を確認 |
| run 保存 | takt 0.55.1 同梱 `builtins/skill/references/engine.md` の実行アーティファクト管理 | `.takt/runs/{timestamp}-{slug}/` に reports / context / logs / meta.json |
| interactive session | takt 0.55.1 `dist/infra/config/project/sessionState.js` | project `.takt/session-state.json` を使用 |
| 現行制作 state | [`wf-new/references/schema.md`](../../.claude/skills/wf-new/references/schema.md) | `planning → prepared → mastered → publishing → complete` |
| 現行制作入口 | [`workflow-cheatsheet.md`](../workflow-cheatsheet.md) | `/wf-auto` が正規入口、`/wf-new` / `/wf-next` が phase 別入口 |
| 下流配布 | `pyproject.toml` の wheel `force-include` と `skills_sync::_ASSET_SPECS` | skills / Claude 設定 / docs / auth template を配布。takt asset は無し |

現在の `.takt/config.yaml` は provider を `codex`、base branch を `main` とし、`.takt/workflows/yt-auto-docs.yaml` などを issue 実装用に使う。これは下流チャンネルで起動する制作 workflow ではない。

### 過去 PoC の扱い

2026-04-27 の [#88](https://github.com/daiki-beppu/youtube-automation/issues/88) では takt 0.38.0 を使い、collection 制作を 8 step の `collection-pipeline` として試作した。結果は、構造化ログに利点がある一方、TTY 前提の人間入力、二重メンテ、追加の実行環境を理由に採用見送りだった。実装 [PR #87](https://github.com/daiki-beppu/youtube-automation/pull/87) は close され、main へ入っていない。

この結果は人間 gate と state 二重化の既知リスクを示す参考証跡として使った。ただし 0.38.0 の仕様を 0.55.1 の事実として転記せず、現行 CLI と同梱 schema を再確認した。

## 判定基準

工程対照表では次の 3 段階を使う。

| 判定 | 意味 |
|---|---|
| 写像可 | takt の通常 step / deterministic rule だけで責務を失わず表せる |
| 条件付き可 | custom instruction、既存 CLI / resolver、`workflow-state.json` のいずれかを残せば表せる。takt 単独の代替ではない |
| 写像不可 | takt に自動突破させてはならない。blocked handoff として停止を表すことだけ可能 |

## 工程対照表

### `/wf-auto`

`/wf-auto` は単なる step 列ではない。lease を取り、固定 collection の state と実成果物から canonical action を毎回計算し、子 skill 完了後に再計算する controller である。

| 現行工程 | 現行の正本 | takt への写像 | 判定 | 理由 |
|---|---|---|---|---|
| channel config / skill 前提確認 | `wf-auto/SKILL.md` Hard Gates | intake step | 写像可 | 読み取り検査と ABORT は step / rule で表せる |
| lease acquire / heartbeat / release | `wf-auto-state.py` | 前処理・各 step instruction・終了処理 | 条件付き可 | takt の task/run と制作 lease は識別子・寿命が違う。既存 resolver を残す必要がある |
| active collection の固定 | `plan --collection` | intake output を後続へ渡す | 条件付き可 | collection identity を全 step で固定する custom contract が要る |
| state + 成果物から action 決定 | `wf-auto-state.py plan` | router step + deterministic rule | 条件付き可 | 判定ロジックを YAML の自然言語へ複製せず resolver を呼ぶ必要がある |
| `/wf-new` / `/lyria` / `/suno-helper` / `/masterup` / `/wf-next` / `/post-publish` 委譲 | 各 child skill | workflow step / workflow call | 条件付き可 | child skill の tool、config、成果物 contract は facet だけでは置換できない |
| 成果物検証 → history record → 再 plan | resolver と各 child skill | verify step → router loop | 条件付き可 | `workflow-state.json` を正として再評価する限り表せる |
| external publish 禁止 | durable config | deterministic `when(...)` | 写像可 | config 解決を既存 loader に一元化すれば決定的に分岐できる |
| login / CAPTCHA handoff | browser の実画面 | blocked rule | 写像不可 | 停止は表せるが、認証や CAPTCHA の突破は workflow が行ってはならない |
| complete / post-publish / release | state、history、lease | terminal verify step | 条件付き可 | remote ID、post-publish history、lease release の既存検証が必要 |

結論として `/wf-auto` を takt workflow に置き換えても、resolver と child skill はほぼ全て残る。YAML 化できるのは外側の順序であり、現在地の正規判定ではない。

### `/wf-new`

| 現行工程 | takt への写像 | 判定 | 理由 |
|---|---|---|---|
| config / TTP / pilot / analytics 前提確認 | intake / research step | 条件付き可 | freshness 判定と前工程誘導は既存 CLI・skill を呼ぶ必要がある |
| analytics 更新または benchmark fallback | workflow call | 条件付き可 | 入力 mode と再検証を自然言語 rule へ複製しないことが条件 |
| 企画候補生成 | agent step | 写像可 | research / planning persona と output contract に分離できる |
| 企画選択 | interactive rule | 条件付き可 | `requires_user_input` で停止できるが、選択肢・default・skip config の contract が別途必要 |
| collection 初期化 + `workflow-state.json` 作成 | edit step から `yt-init-collection` | 条件付き可 | 作成と schema 検証は決定的 CLI に残すべき |
| scene phrase / localization | agent step + validator | 条件付き可 | 生成は agent、language completeness は CLI に分離が必要 |
| thumbnail 候補生成 | agent step / child skill | 条件付き可 | image provider、cost gate、参照画像、成果物 QA を残す必要がある |
| thumbnail 承認・確定 | interactive rule + deterministic apply | 条件付き可 | 承認対象と確定コピーの同一性を既存 script で検証する必要がある |
| Suno / Lyria の prompt・設計生成 | agent step | 条件付き可 | child skill の domain instruction と validator を再利用する必要がある |
| loop video | agent step / child skill | 条件付き可 | provider cost、外部 API、fallback 禁止、成果物検証が必要 |
| `phase = prepared` 更新 | verify step | 条件付き可 | takt の現在 step ではなく、成果物検証後に domain state を更新する必要がある |
| Suno collection server 起動 | command step 相当 | 条件付き可 | long-lived process の所有・疎通・終了責務を custom instruction で持つ |

企画生成のような純粋な AI 作業は takt と相性がよい。一方、`/wf-new` 全体では gate と state update が生成作業の間に細かく入り、facet 化しても controller の複雑さは消えない。

### `/wf-next`

| 現行工程 | takt への写像 | 判定 | 理由 |
|---|---|---|---|
| active collection 選択 / preflight | intake step | 条件付き可 | 複数 collection の選択は人間 gate、骨格補完は既存 CLI が必要 |
| Suno download 状態 / URL 判定 | router step | 条件付き可 | URL とローカル音源の優先契約を決定的コードに残す必要がある |
| `/masterup` / `/lyria` 生成 | child workflow call | 条件付き可 | long-running tool と成果物検証を child skill に残す |
| raw master 後の停止 | terminal / blocked rule | 条件付き可 | 停止自体は可能。再開時は takt run でなく domain state から再判定する必要がある |
| final master 検出・音源承認 | interactive rule + `master_audio_transition.py` | 条件付き可 | 候補 identity と承認対象を script が一致検証する必要がある |
| video + description 並列生成 | parallel step | 写像可 | 独立な 2 作業と合流後検証は takt の得意領域 |
| `phase = publishing` 更新 | verify step | 条件付き可 | 両成果物 PASS 後だけ domain state を更新する必要がある |
| upload plan / 承認 | interactive rule | 条件付き可 | 実際の privacy / publishAt を plan 結果から承認文面へ固定する必要がある |
| playlist 初期化 | interactive rule + CLI | 条件付き可 | upload 承認とは別 gate で、YouTube write と config 書換えを伴う |
| upload / tracking / planning→live | command step | 条件付き可 | remote reconciliation と atomic move は既存 uploader に一元化すべき |
| publishing recovery | router / retry loop | 条件付き可 | remote ID と tracking schema の突合を既存 contract に残す |
| complete 案内 | terminal step | 写像可 | domain complete 検証後の表示だけなら表せる |

parallel step は明確な利点だが、現行 `/wf-next` も video と description を既に 2 agent で並列化している。takt へ移すだけでは、この部分の実行時間短縮は増えない。

## 人間介入・承認 gate

takt 0.55.1 は rule に `requires_user_input: true` と `interactive_only: true` を指定できる。これは「人間入力が必要な遷移」を表現する能力であって、承認対象の生成・本人確認・外部画面操作を保証する能力ではない。

| 停止点 | takt での表現 | 判定 | 必要な追加 contract |
|---|---|---|---|
| 企画選択 | 選択 rule →次 step | 条件付き可 | 候補 ID、推奨 default、`skip_plan_selection`、回答と初期化入力の同一性 |
| サムネ承認 | approval / regenerate / stop rule | 条件付き可 | 実画像の preview、候補 hash/path、QA、cost gate、自動選択 mode、承認済み画像だけを確定する apply |
| upload 承認 | approve / stop rule | 条件付き可 | `yt-upload-collection --plan` の privacy / publishAt、今回の要求との conflict、承認後の plan 不変性 |
| `phase = prepared` のマスタリング待ち | blocked または正常中断 →再起動 | 条件付き可 | 放置時間を run timing に含めないこと、再開時に final master と domain state を再検証すること |
| login / CAPTCHA / OAuth 認証待ち | blocked handoff のみ | 写像不可 | 本人に必要な 1 操作だけを依頼し、token / password を prompt や run log に保存せず、新しい run で画面と成果物を再確認すること |

特に login / CAPTCHA は「takt で表現不可」ではなく、「自動工程としては不可、停止理由としてのみ表現可」と区別する。pipeline mode で自動承認へ落とす設計は認められない。

## 状態管理: 二重化の判定と回避策

### 二重化するもの

そのまま全面移行すると、少なくとも次の 3 種の状態が並ぶ。

| 状態 | 本来の責務 |
|---|---|
| `workflow-state.json` + collection の実ファイル | 制作 domain の durable state。phase、assets、upload ID、再実行可否 |
| `.automation-run/history.json` + lease | `/wf-auto` の attempt、停止理由、timing、排他 |
| takt `.takt/runs/` + `.takt/session-state.json` | agent workflow の実行記録、report、prompt context、provider session |

takt の current step を制作 phase として扱うと、例えば takt が `upload` step まで進んだのに remote upload だけ成功して local state write が失敗したケースで、takt と `workflow-state.json` が食い違う。逆に `workflow-state.json` だけで再判定すると、takt resume の step pointer は正規状態になれない。

### 回避策は存在する

共存する場合は、次を全て守れば二重化を「役割分担」にできる。

1. **domain SSOT は `workflow-state.json` と実成果物のままにする。** takt current step を制作完了判定に使わない。
2. **各再開は最初に resolver を呼ぶ。** takt の前回 step から無条件に続けず、collection identity を固定して action を再計算する。
3. **takt run は観測・report に限定する。** phase、remote ID、approval 済み対象を独自保存しない。
4. **state update は既存 deterministic CLI / script に一元化する。** agent output や status tag だけで phase を進めない。
5. **外部副作用の直前と直後に reconciliation を行う。** upload、playlist、post-publish を takt retry だけで再発行しない。
6. **長期 handoff は run を閉じる。** マスタリングや login 待ちの放置時間を生きた agent session として保持せず、次回は新しい attempt で再検証する。

ただしこの回避策では takt が既存 `/wf-auto` resolver の外殻になる。二重化事故は避けられるが、置換による削減効果も小さい。

## 下流配布と `yt-skills sync` の共存

### 現状

wheel は `.claude/skills`、Claude 設定、workflow cheatsheet、features、OAuth template を同梱する。`_ASSET_SPECS` には takt workflow / facet の entry が無く、`yt-skills sync` は下流 `.takt/` を作らない。repository の tracked `.takt/` は upstream の開発 workflow であり、wheel に force-include されていない。

### 下流で takt 制作 workflow を使う前提

移行するなら、各チャンネル repository に次が必要になる。

- takt 0.55.1 と互換な binary、および version pin / upgrade 手順
- provider CLI / SDK の認証と、画像・ブラウザ・長時間 command に必要な権限
- `.takt/config.yaml`、制作 workflow、custom step / facet、schema の配布
- `takt workflow doctor` を release 前と sync 後に実行する検証入口
- upstream 共通資産と channel 固有 override の優先順位
- `.takt/runs/` / session / runtime file の ignore、retention、secret 非保存方針
- skill と workflow が併存する期間の唯一の正規入口

### 共存可否

技術的には共存可能である。`_ASSET_SPECS` は asset 追加を想定した構造なので、将来 `takt` directory asset を増やせる。しかし現在の `skills` 配布とは別 asset にしなければならない。`.claude/skills` と `.takt/` は更新・prune・channel override の扱いが異なるためである。

また、配布できることと運用できることは別である。takt binary と provider 認証は wheel に同梱できず、workflow version と CLI version の互換も `yt-skills sync` だけでは保証できない。したがって配布経路の拡張は、採用判断より先に行わない。

## 子 skill 3 例の facet 写像

facet は skill directory を 1 ファイルへ変換する機構ではない。1 skill の中に persona、policy、knowledge、instruction、output contract と、facet 外に残すべき deterministic command が混在する。

### `/thumbnail`

| 要素 | 写像先 | 例 | 限界 |
|---|---|---|---|
| 役割 | persona | CTR とチャンネル表現を両立する visual designer | provider/tool の画像生成能力は persona では得られない |
| 不変条件 | policy | config deep-merge、reference provenance、cost gate、symlink 拒否、承認前 state 更新禁止 | policy は archive/check script の代替にならない |
| 参照情報 | knowledge | champion、benchmark、creative constraints、文字・配色・構図 | channel 固有画像と config は実行時に読む必要がある |
| 手順 | instruction | theme 解決 → prompt →候補生成 → QA → textless → archive | AskUserQuestion と画像 preview は workflow / tool 側の責務 |
| 完了形 | output-contract | candidate path、prompt doc、QA 結果、生成対象 | 実ファイル存在・hash・画像妥当性は validator が必要 |

判定は **条件付き可**。生成 substep は facet 化できるが、`/thumbnail` 全体は image tool、承認 controller、deterministic checks を伴う child workflow になる。

### `/suno`

| 要素 | 写像先 | 例 | 限界 |
|---|---|---|---|
| 役割 | persona | collection の音像を複数曲へ展開する music prompt designer | Suno UI 実行・download は別 skill / browser 責務 |
| 不変条件 | policy | mode 判定、曲間差別化、track count、禁止表現、state 更新条件 | JSON schema / 重複検査は code に残す |
| 参照情報 | knowledge | video analysis、genre line、planning.music、Suno prompt vocabulary | 最新 collection データは実行時入力 |
| 手順 | instruction | 入力収集 → prompt 設計 → JSON/Markdown 生成 →検証 | browser の login/CAPTCHA はこの instruction に入れない |
| 完了形 | output-contract | `suno-prompts.json` / `.md`、entry 数、検証結果 | ファイルと schema の実検証が必要 |

判定は **条件付き可**。prompt 生成は facet の代表的な適用対象だが、`/suno-helper` まで一体化すると外部 UI state と domain state の二重化が起きる。

### `/video-upload`

| 要素 | 写像先 | 例 | 限界 |
|---|---|---|---|
| 役割 | persona | publish operator | remote write の可否を AI persona に決めさせない |
| 不変条件 | policy | plan-first、privacy/publishAt 表示、metadata path、重複 upload 禁止、tracking reconciliation | durable config と remote state の検証は code が正本 |
| 参照情報 | knowledge | posting checklist、scheduled publish、YouTube metadata contract | OAuth credential 自体を knowledge / report に入れない |
| 手順 | instruction | plan → preflight →承認済み条件突合 → uploader 実行 → tracking/live 検証 | 実 upload は deterministic CLI を明示的に呼ぶべき |
| 完了形 | output-contract | plan、video ID、tracking path、live state、post-publish handoff | agent の自己申告だけで成功にできない |

判定は **条件付き可**。plan / review は facet 化できるが、不可逆な upload と reconciliation は `yt-upload-collection` / `yt-upload-auto` に残す。

## 4 択の比較

| 選択肢 | 評価 | 判断 |
|---|---|---|
| 現行 skill 維持 | domain state、既存 gate、browser handoff、下流配布を維持。新しい二重状態を作らない | **採用** |
| 部分置換 | AI 生成 substep は facet 化しやすいが、skill と facet の同じ指示を二重保守しやすい。現行も child agent 委譲済み | 今は不採用 |
| 全面移行 | YAML で工程は表せるが、state resolver / CLI / browser boundary は残る。下流の takt 運用前提も増える | 不採用 |
| 見送り | takt 自体の評価を止める選択。開発 workflow では既に有効活用している | 選ばない |

「現行 skill 維持」は takt 全体の否定ではない。開発 workflow は takt、チャンネル制作 workflow は配布済み skill と domain state、という責務境界を維持する判断である。

## 後続 issue 候補

本結論では移行実装 issue を直ちに起票しない。再評価条件が成立した場合だけ、次を独立 issue にする。

1. **制作 workflow の read-only takt adapter PoC**: `workflow-state.json` を一切更新せず、resolver の action と takt step 遷移が一致するかを mock provider で検証する。成功条件は通常・blocked・retry・remote partial success の各ケースで current action が一致すること。
2. **takt 制作 asset の versioned 配布設計**: `yt-skills sync --asset takt` 相当、CLI version constraint、channel override、prune、`takt workflow doctor` を 1 つの配布 contract として設計する。PoC 1 が採用可能の場合だけ着手する。
3. **5 human gate の非本番 contract test**: 企画、サムネ、upload、mastering、login/CAPTCHA について、interactive / pipeline / restart 時に自動承認・副作用再発行が起きないことを最小 fixture で検証する。実 OAuth、Suno、YouTube は呼ばない。
4. **facet 正本化の単一 skill 実験**: `/suno` の prompt 生成部分だけを対象に、SKILL.md と facet の二重記述を作らない source-of-truth / export 方法を検証する。生成 JSON validator は既存 code を再利用する。

## 未確認事項

- takt 0.55.1 で制作 workflow を TTY interactive 完走させた挙動は未確認。本 issue は PoC をスコープ外としているため実行していない。
- Suno / YouTube / OAuth の実サービスを takt から操作した挙動は未確認。認証情報と外部副作用を伴うため実行していない。
- takt 0.55.1 と将来版の workflow schema 互換は未確認。下流配布を採用する場合は version pin と upgrade test が必要になる。

これらは「現行 skill 維持」の判断を妨げない。現行方式を置換する利点を立証する側に必要な追加証拠である。

## 参照

- [`wf-auto/SKILL.md`](../../.claude/skills/wf-auto/SKILL.md)
- [`wf-new/SKILL.md`](../../.claude/skills/wf-new/SKILL.md)
- [`wf-next/SKILL.md`](../../.claude/skills/wf-next/SKILL.md)
- [`workflow-state.json schema v2`](../../.claude/skills/wf-new/references/schema.md)
- [`workflow チートシート`](../workflow-cheatsheet.md)
- [`architecture.md`](../architecture.md)
- [`development.md`](../development.md)
- [`skill authoring guidelines`](../skill-design/skill-authoring-guidelines.md)
- [`takt-operations.md`](../takt-operations.md)
- [#64: takt OSS 技術調査](https://github.com/daiki-beppu/youtube-automation/issues/64)
- [#86: channel-new takt PoC](https://github.com/daiki-beppu/youtube-automation/issues/86)
- [#88: interactive / wf-new / wf-next PoC](https://github.com/daiki-beppu/youtube-automation/issues/88)
- [PR #87: close された PoC 実装](https://github.com/daiki-beppu/youtube-automation/pull/87)
- [PR #90: main に残した asset 抽象化](https://github.com/daiki-beppu/youtube-automation/pull/90)
