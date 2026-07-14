# workflow-state watcher による半自動チェーン

## 目的

`collections/planning/*/workflow-state.json` と手作業成果物の変化を検知し、
次の `/wf-next` を自動起動する。人間の判断が必要な場合だけ停止・通知し、承認または
成果物の到着後に同じ未完了 step から再開する。

本書は後続 issue のための設計であり、watcher、runner、hooks、launchd 設定、CLI、
config key は実装しない。現行 `/wf-next` の state 更新主体と冪等性の契約も変更しない。

## 現行契約と設計上の前提

- `workflow-state.json` は
  `collections/planning/<YYYYMMDD-short-theme>-collection/` にあり、`phase`、`assets`、
  `upload` の single source of truth である。state を更新するのは `/wf-new` または
  `/wf-next` を実行するメインエージェントだけであり、watcher は書き込まない。
- phase は `planning`、`prepared`、`mastered`、`publishing`、`complete` の 5 値である。
  `/wf-next` は `phase` と `assets` を確認し、完了済みの処理を skip する。
  `publishing` で中断しても再実行時は未完了 step から再開する。
- `config/channel/workflow.json::workflow.wf_next.approval_gates.audio` と `.upload` は
  `load_config().workflow.wf_next` で解決され、未指定時を含む既定値は両方 `false` である。
  `audio` は最終音源を採用して `mastered` に進む直前、`upload` は
  `/video-upload` の直前のゲートである。
- `approval_gates` 以外にも、複数 collection、Suno playlist URL、複数の最終 master
  候補、`masterup` の選曲例外、未作成 playlist の初期化などは現行 skill で人間への
  確認になり得る。半自動 runner はこれらを暗黙に承認しない。入力が一意かつ事前設定
  済みなら進み、そうでなければ `needs_input` として停止する。
- Suno 経路では `02-Individual-music/` の `.mp3` / `.m4a` / `.wav` の実在が
  download 完了判定の primary である。最終 master 候補は `01-master/` の
  `.m4a` / `.wav` / `.flac` / `.aac` / `.mp3` から raw master 自身を除いて検出する。

「`approval_gates = false` なら全自動」とは、既知の承認ゲートを挟まないという意味で
ある。対象 collection を一意に指定でき、playlist 等の外部反映設定が準備済みで、候補
選択に曖昧さがない Lyria 経路、または必要な手作業成果物が揃った Suno 経路では、
watcher が `/wf-next` を繰り返し起動して `complete` まで進める。Suno UI での生成、
`skip_manual_mastering = false` のときの mixing / mastering、未作成 playlist の初期化、
曖昧な候補選択は人間介入として停止する。

## 実現方式の比較

評価は `◎`、`○`、`△`、`×` の順に適合度が高い。

| 方式 | ゲート有効時の停止対応 | Codex / takt 互換 | 常駐コスト | 障害時の再開性 | 実装コスト | 判定 |
|---|---|---|---|---|---|---|
| agmsg 型: 常駐 watcher + ローカル耐久イベント配送 | ◎ gate を durable な待機状態として保持できる | ◎ runtime 非依存の queue と adapter に分離できる | ○ watcher 1 process と SQLite | ◎ lease、dedupe、起動時 scan で回収できる | △ queue、runner、運用 CLI が必要 | **採用** |
| `fswatch` / launchd + headless agent の直接起動 | △ event ごとに起動するだけでは承認待ちを保持できない | ○ headless command の差を wrapper で吸収可能 | ◎ event 待機中は軽い | △ file event の重複・欠落と実行中 crash の記録を別途補う必要がある | ○ | 不採用 |
| Claude Code hooks | ○ Claude Code 内なら停止を差し込める | × 既存設計どおり Codex / takt では hook 実行を前提にできない | ◎ session 中だけ | △ session が無い時間と hook 失敗を回収できない | ◎ | 不採用 |
| cron / shell loop の polling | △ 待機状態は別ファイル等が必要 | ◎ agent runtime から独立 | △ scan と agent 誤起動が周期的に発生 | ○ 毎周期再走査できるが、dedupe が別途必要 | ◎ | fallback のみ |

`fswatch` はこの環境の必須依存ではない。launchd は process supervisor としては使うが、
file event から headless agent を直接起動する設計にはしない。イベントはいったん SQLite
へ永続化し、dispatcher が実行可否を決める。

参考にする agmsg は、実際には daemon や network を持たず、ローカル SQLite の
append-only event log と host runtime ごとの delivery mechanism を組み合わせる。
本設計は storage / runner / notification の分離と耐久イベント配送を取り入れる一方、
ファイル変更の監視 process は launchd から常駐・再起動可能にする。agmsg の topology
そのものをコピーするものではない。

## 採用アーキテクチャ

```text
workflow-state.json ─┐
02-Individual-music/ ├─ watcher ── event log / jobs (SQLite) ── dispatcher
01-master/ ──────────┘                                      │
                                                             ├─ wait + notify
                                                             │   (approval / input / artifact)
                                                             └─ runner adapter
                                                                  └─ /wf-next main agent
                                                                        │
                                                                        └─ state / artifact verification
```

### 責務境界

1. **watcher** は planning collection と対象成果物を scan し、変更を正規化した event として
   enqueue する。state や collection 成果物は変更しない。
2. **SQLite store** は event、job、実行 attempt、待機理由、承認を永続化する。
   database は `workflow-state.json` の代替ではなく、配送と実行履歴だけの source of truth
   である。
3. **dispatcher** は collection 単位の排他、dedupe、gate / 手作業待ち判定を行い、
   runnable job だけを runner に渡す。
4. **runner adapter** は Claude Code の `claude -p`、Codex の `codex exec` などの起動差を
   隠蔽する。初期実装は一つの adapter から始めても、queue と判定契約は runtime 固有に
   しない。`takt watch` は takt task の監視であって `workflow-state.json` の監視では
   ないため、この watcher の代用にはしない。
5. **`/wf-next` を実行するメインエージェント**だけが state を更新する。runner 終了後は
   終了コードや自然言語の成功報告だけでなく、state の再読込と期待成果物の実在を検証
   して job を完了させる。
6. **notifier** は通知だけを担う。通知失敗で待機情報を失わず、再送可能にする。

この分離により Claude Code hooks を使わず、Codex と同じ skill を実行できる。takt とも
同じ worktree / repository で共存できるが、初期実装で takt の issue workflow を
`/wf-next` の実行 engine として流用しない。将来 takt 用 runner preset を追加する場合も、
同じ job 入出力契約の adapter として追加する。

### event と job の契約

後続実装では少なくとも次を保存する。

| record | 必須情報 | 用途 |
|---|---|---|
| event | ID、collection の canonical path、種別、観測時刻、trigger fingerprint | file event の正規化と監査 |
| job | ID、collection、state digest、状態、待機理由、作成・更新時刻 | 一回だけの dispatch と再開 |
| attempt | job ID、runner、開始・終了時刻、終了コード、log path | crash と agent failure の切り分け |
| approval | request ID、gate、対象、state digest、decision、決定時刻 | 対象を固定した一回限りの承認 |

job 状態は最低限 `pending`、`running`、`waiting_artifact`、`waiting_approval`、
`waiting_input`、`succeeded`、`failed` を持つ。同一 collection の `running` は一件に限定し、
`pending` は `(collection, trigger fingerprint)` で重複排除する。runner は期限付き lease を
取得し、process crash で lease が失効した job は起動時 recovery で `pending` に戻す。

fingerprint は event を処理した証拠であり、workflow の完了判定には使わない。dispatcher
は実行直前に JSON parse、canonical path、`phase`、`assets` と対象ファイルを再検証する。
state が不完全な書き込み途中、symlink、未知 phase、schema 不整合なら agent を起動せず
`failed` にして通知する。

watcher 起動時は `collections/planning/*/workflow-state.json` を必ず full scan する。
これにより停止中に起きた変更を回収する。`/video-upload` により collection が
`planning/` から `live/` へ移動した場合は、直前 job の state と移動先の
`phase = complete`、`stage = live`、`upload.video_id` を runner が検証し、単なる source
path 消失を failure にしない。

### 自動チェーン

runner が一段を正常完了したら、dispatcher は変更後 state から次を判定する。

- `complete`: job を `succeeded` にし、完了通知を送る。
- 次 step が自動実行可能: 新しい state digest で次 job を enqueue する。
- 承認が必要: `waiting_approval` にする。
- Suno 生成、download、mixing / mastering などの成果物が必要: `waiting_artifact` にする。
- 候補選択、playlist 初期化など追加入力が必要: `waiting_input` にする。
- agent error または成果物不整合: `failed` にして自動 retry しない。

無限再起動を防ぐため、runner 前後で state digest と期待成果物が変わらず、待機理由も返ら
なかった attempt は progress failure とする。同じ digest を自動で再 enqueue しない。

## 人間介入

### config 駆動の承認ゲート

dispatcher は `load_config().workflow.wf_next` で解決済み設定を読み、gate が `false` なら
確認を作らない。gate が `true` なら次の操作直前で止める。

| gate | 停止位置 | request に固定する対象 | 承認後 |
|---|---|---|---|
| `audio` | 最終候補を `assets.master_audio` に採用し、`phase` を `mastered` にする直前 | collection、候補 ID / filename、state digest | 同じ対象と digest を再検証し、音源採用処理から再開 |
| `upload` | `/video-upload` の直前 | collection、公開範囲または予約日時、動画・概要欄、state digest | upload plan を再検証し、upload から再開 |

音源 gate は既存 `master_audio_transition.py` の `needs_selection`、`needs_approval`、
承認対象一致検証を再利用し、判定を watcher に複製しない。upload gate は後続実装で
headless runner が upload plan と `needs_approval` を構造化して返す seam を設ける。
対話できない process 内で AskUserQuestion を待たせてはならない。

承認は将来の運用 CLI（例: `yt-wf-watch approve <request-id>` / `reject <request-id>`）から
SQLite に decision event を追加する。承認後に state digest または対象ファイルが変わって
いたら古い承認を無効化し、新しい request を作る。reject は state を変更せず待機を終了
し、明示的な再開操作または新しい成果物 event を待つ。

### 通知方式

| 候補 | 長所 | 制約 | 位置づけ |
|---|---|---|---|
| macOS 通知（`/usr/bin/osascript` の `display notification`） | OS 標準で cmux 外でも見える | 通知自体から durable な承認結果は返せない | primary |
| `cmux notify` / status | 対象 workspace の作業文脈を示せる | cmux 実行中かつ command 利用可能な環境に限定 | optional |
| terminal / log | 追加依存がなく障害調査に使える | 人が見ていないと気付けない | 常時記録する fallback |

通知本文には request ID、collection、停止理由、確認コマンドを含める。macOS 通知と
cmux は best effort とし、真の待機状態は SQLite に残す。運用 CLI の `status` / `pending`
で未処理 request を再表示できるようにする。

### 手作業成果物の待機と検知

| 状態 | 待つもの | 検知後の動作 |
|---|---|---|
| Suno playlist URL 済み、音源なし | `02-Individual-music/` の `.mp3` / `.m4a` / `.wav` | directory event を debounce し、対象ファイルが二回連続の観測で size / mtime 不変になってから enqueue |
| `assets.raw_master` 済み、`skip_manual_mastering = false` | `01-master/` の raw master 以外の対応音源 | 候補を再列挙。一件なら audio gate 判定、複数なら `waiting_input` |
| 手作業不要または `skip_manual_mastering = true` | なし | raw master を最終候補にする既存処理へ進み、audio gate 判定 |

file event は「到着の可能性」を示すだけで、成果物完成の証拠にはしない。安定確認後も
`/wf-next` / reference script の既存検証を通す。途中 download、0 byte、非対応拡張子、
命名・曲数検証の失敗は `failed` または `waiting_input` とし、fallback で処理を続けない。

## chain manifest 案 A との関係

本設計は `chain-manifest-schema.md` の案 A を**置換せず、併存する実行トリガー層として
拡張する**。

- 案 A は「何をどの順で実行し、どの成果物・gate・冪等判定を使うか」を宣言する。
- watcher は「いつ再評価し、どの job を一回だけ配送し、待機・再開をどう永続化するか」
  を担当する。
- manifest interpreter が実装された後は runner adapter の委譲先にできる。それまでは
  現行 `/wf-next` と reference script を呼び、step ロジックを watcher に複製しない。

案 A が hooks を不採用にした理由は Codex / takt で実行されないためであり、本設計でも
変わらない。ヘッドレス runner が対話型承認を扱えないという制約は、gate が有効な step
または別の入力が必要な場面に限って適用する。そこで headless process を起動したまま
対話させず、durable な `waiting_approval` / `waiting_input` に変換する。gate が `false`
で入力が一意な step は headless runner で実行可能である。この整理により、案 A の
承認契約を弱めず、既定 `false` のチャンネルを無人チェーンの対象にできる。

## 障害・安全性

- watcher と runner は channel root 外の path を受け付けず、state と対象 directory の
  symlink を拒否する。SQLite に token、OAuth credential、prompt 本文の secret を保存
  しない。
- runner command は argv 配列で構築し、collection 名や path を shell 展開しない。
- collection 単位で一件だけ実行する。初期値は全体 concurrency も一件とし、YouTube API
  への外部反映と同一 config の書き戻しを並行させない。並列化は安全性を別途検証してから
  後続 issue にする。
- retry は watcher / runner process crash の lease 回収だけ自動化する。agent の非 0 終了、
  validation failure、外部 API error は同じ入力で無限 retry せず、人間へ通知する。
- launchd は process 再起動だけを担う。SQLite の migration、job recovery、health check は
  watcher CLI の責務とする。
- dry-run では scan、判定、通知予定、runner command を表示するが agent と外部 API を
  起動しない。導入時は dry-run の event / job 履歴を確認してから apply を有効化する。

## 後続 implementation issue の分割

各 phase は前 phase の成果物に依存する。Phase 0 から一行ずつ別 issue に分ける。

| Phase | 成果物 | 依存関係 | 完了条件 |
|---|---|---|---|
| 0. 実行判定 contract | 現行 state / config / reference script を読む pure planner、構造化結果 schema（`run` / `wait_artifact` / `needs_approval` / `needs_input` / `complete` / `error`） | なし | fixture で全 phase、gate true / false、曖昧候補、publishing 再開を判定でき、state を変更しない |
| 1. store と one-shot scan | SQLite schema / migration、event dedupe、collection lock / lease、`scan` / `status` / dry-run CLI | Phase 0 | 二重 event が一 job になり、crash 後に lease を回収し、起動時 full scan で停止中の変更を拾う |
| 2. runner と自動チェーン | runner adapter 一種、collection 固定の headless `/wf-next` 起動、前後検証、progress guard | Phase 1 | gate false の Lyria fixture が `prepared` から `complete` まで進み、`publishing` 中断を再開できる |
| 3. 承認と通知 | approval / reject / pending CLI、audio・upload request、macOS notifier、optional cmux notifier | Phase 2 | gate true で操作直前に停止し、対象固定承認後だけ再開し、stale approval を拒否する |
| 4. artifact watcher | `workflow-state.json`、`02-Individual-music/`、`01-master/` の監視、debounce / stable-file 判定、polling fallback | Phase 1、2 | Suno download と最終 master 到着で一回だけ再開し、partial file では起動しない |
| 5. 常駐運用と runtime 拡張 | launchd plist の install / uninstall / health、log rotation、追加 runner adapter、運用 runbook | Phase 1〜4 | logout / restart / process kill 後に full scan から復旧し、dry-run から安全に有効化できる |

Phase 0 では既存 `/wf-next` を大規模に書き換えず、headless 実行に必要な構造化判定 seam
だけを作る。Phase 2 の初期 adapter は、実装時に CI / 運用環境で認証・permission mode・
終了形式を検証できた runtime を一つ選ぶ。Codex、Claude Code、takt を一 issue で同時対応
しない。

## 関連トラック

- #1667 `yt-wf-batch` は人間が開始する直列 batch。本設計は state / artifact event を
  起点に再開するため、入口が異なる。将来は batch runner を adapter として再利用できる。
- #1824 の post-publish chain は `phase = complete` 後の consumer になり得るが、本設計の
  初期 scope は `/wf-next` 完了までとする。
- #1826 は orchestration 改善の tracking。本書の Phase 0〜5 を個別 issue として紐付ける。
- #1893 の Suno 定期無人実行は、本設計の `waiting_artifact` と artifact watcher を利用できる。
  Suno UI 自体の自動化可否は #1893 側の責務とする。

## 参照

- [`chain-manifest-schema.md`](./chain-manifest-schema.md)
- [`subagent-orchestration.md`](./subagent-orchestration.md)
- [`workflow-cheatsheet.md`](../workflow-cheatsheet.md)
- [`.claude/skills/wf-next/SKILL.md`](../../.claude/skills/wf-next/SKILL.md)
- [`.claude/skills/wf-next/references/master_audio_transition.py`](../../.claude/skills/wf-next/references/master_audio_transition.py)
- [`src/youtube_automation/utils/config/workflow.py`](../../src/youtube_automation/utils/config/workflow.py)
- [`src/youtube_automation/utils/config/loader.py`](../../src/youtube_automation/utils/config/loader.py)
- [agmsg README](https://github.com/fujibee/agmsg)
- [agmsg Architecture](https://github.com/fujibee/agmsg/blob/main/ARCHITECTURE.md)
