# GPT-Live 音声壁打ちの実現性調査

- 調査日: 2026-08-16
- 対象: ChatGPT desktop app の Codex Voice / OpenAI Realtime API を使う独自音声クライアント
- 結論: まず Codex Voice を手動検証する。独自経路は、音声 UI や監査・権限境界を製品側で所有する必要が明確になった場合だけ Realtime API で試作する
- 未実施: マイクを使う実機会話、API key の発行、Realtime API 呼び出し、課金確認、workflow 起動

## 要約

Codex Voice は GPT-Live が会話を担い、GPT-5.6 Terra がアプリ内タスクの開始・調整を担う ChatGPT desktop app の機能である。自然なターンテイキング、割り込み、方向転換、別タスクの開始と進捗確認が公式に明示されており、このリポジトリの方針・企画を壁打ちする最小経路になり得る。利用には対象プラン、rollout、workspace 設定、マイク権限が必要で、Voice として開始した新規 chat / task でなければならない。

公開 API で同じ `GPT-Live` を直接選ぶ経路は公式資料に示されていない。独自の低遅延音声 agent には `gpt-realtime-2.1`、文字起こしだけには `gpt-live-transcribe` を使う。前者は speech-to-speech、割り込み、会話状態、tool use を提供するが、Codex の task coordination、repository context、承認、秘密情報、ログの境界はアプリ側で実装しなければならない。したがって Codex Voice と Claude Code + Realtime API は同じ機能の別 endpoint ではなく、完成済み製品と組み込み部品の比較である。

## Codex Voice / GPT-Live

### 利用条件と公式に確認できた挙動

| 観点 | 2026-08-16 時点の仕様 |
|---|---|
| 対応場所 | ChatGPT desktop app の Chat、Work、Codex。iOS Remote は desktop host との pair 後に利用できる |
| 対象プラン | Plus、Pro、Business、Edu、Enterprise。利用可否は rollout と workspace 設定にも依存する |
| 開始条件 | 送信前の空の新規 chat / task で `Start new voice chat` を選ぶ。非 Voice で開始した task では voice dictation になる |
| 初回設定 | マイク許可、voice 選択、macOS では screen context の確認 |
| 会話 | 自然なターンテイキング、応答中の割り込み、follow-up、方向転換をサポートする |
| task coordination | 別 task の開始、既存 task の確認、追加指示、進捗・blocker・結果の会話への集約をサポートする |
| 権限 | Voice が指示する task と同じ permissions に従う。Voice が権限を拡張するわけではない |
| 同時利用 | desktop app 全体で active voice chat は1つだけ |
| 利用枠 | Voice は5時間 rolling window のプラン別枠。Voice から開始した task は別途既存 Codex usage budget を使う |

Voice の目安枠は Plus が約15–30分、Pro 5x が約1–2.5時間、Pro 20x が unlimited voice access、Business と legacy Enterprise / Edu が約45分である。需要により調整され得る目安であり、unlimited voice access でも Voice が開始した Codex task の枠は無制限にならない。credit / pay-as-you-go の Business、Edu、Enterprise は desktop voice が約6 credits/分と案内されている。ChatGPT Voice in Desktop は API key では利用できない。

### リポジトリ固有の壁打ちへの適合

公式仕様から、次は実現可能性が高い。

- `AGENTS.md`、`CLAUDE.md`、開いている repository の文脈を使って、チャンネル方針や企画を一問ずつ掘り下げる
- 回答中に割り込み、前提を訂正し、別方向へ切り替える
- 会話内で決定、未決、次の確認事項を要約する
- 明示指示後に別の Codex task を開始し、進捗や blocker を Voice へ戻す

ただし、これは公式に記載された一般機能からの適合性評価であり、この repository 固有テーマでの品質実測ではない。マイクと Voice UI を操作していないため、問いの粒度、割り込み復帰、固有語の認識、長い repository 文脈の保持、要約精度は未検証である。

### 手動検証手順

実機確認できる人が次を1セッションで行い、結果をこの文書の「実機記録」へ追記する。

1. ChatGPT desktop app でこの repository を開き、対象プラン、Voice rollout、workspace で Voice が許可されていることを確認する。
2. 空の新規 Codex task を作り、メッセージ送信前に `Start new voice chat` を選ぶ。マイク権限だけを許可し、screen context は機密情報のない画面に限定する。
3. 「このチャンネルの第一ペルソナを見直したい。結論を急がず、一度に一問だけ質問して」と依頼する。
4. 3問以上答え、2問目の応答中に割り込んで前提を訂正する。次の質問が訂正後の方向へ変わるか記録する。
5. 「ここまでの決定、未決、根拠を分けて要約して」と依頼し、会話と一致するか確認する。
6. 書き込みや workflow 起動を伴わない調査 task を1件だけ明示的に開始させ、進捗確認と方向転換を試す。暗黙に state やファイルを変更しないことを確認する。
7. Voice を終了し、日時、app version、OS、plan / workspace 種別、各操作、観測結果、利用時間を記録する。会話本文や秘密情報は貼らない。

#### 実機記録

2026-08-16 時点では未実施。blocker は、この自動調査環境からユーザーのマイク、Voice rollout / plan、workspace 管理設定へアクセスせず、課金を伴う機能を無断で起動しないことである。

## Claude Code + 公開 Realtime API

### モデルと能力の区別

| モデル | 用途 | この調査での位置付け |
|---|---|---|
| `gpt-realtime-2.1` | 低遅延 speech-to-speech、instructions、会話状態、割り込み、tool use | 独自の双方向壁打ちを構成する本命 |
| `gpt-live-transcribe` | live audio から低遅延 transcript delta を生成する speech-to-text | 文字起こし専用。音声応答や tool bridge は単独で提供しない |
| GPT-Live | ChatGPT Voice の live conversation を担う製品内モデル | desktop Voice の説明名。公開 Realtime API の選択可能 model と同一視しない |

`gpt-realtime-2.1` は128,000 context window、最大32,000 output tokens、function calling 対応である。Realtime session は stateful で、Session、Conversation、Responses を持ち、最大60分である。instructions は session 作成・更新時に設定できるため、repository の全内容を無制限に送るのではなく、選択した方針・企画・制約・許可 tool の要約を注入する構成にできる。

### 概略構成

```text
microphone / speaker
        |
        | WebRTC (推奨: browser / desktop client)
        v
OpenAI Realtime session (gpt-realtime-2.1)
        |
        | allowlisted function call + validated arguments
        v
local tool bridge
        |
        +-- read-only repository context loader
        +-- explicit approval boundary
        +-- Claude Code task invocation / progress adapter
        +-- redacted tool result
```

ブラウザ / desktop client では WebRTC を第一候補にする。application server が標準 API key を保持して短命 client secret を発行し、client はその短命 key で Realtime API へ接続する。標準 API key を client へ渡さない。server-to-server や音声 I/O を自前管理する場合は WebSocket が選択肢だが、PCM buffer、再生、割り込み、再接続を bridge 側で扱うため実装量が増える。

Realtime session の function call は「提案」であり、任意 shell / path / state patch を直接受け付けない。bridge は固定 tool 名と schema、repository root 内の固定 reader、引数上限を持ち、読み取りと変更を分離する。書き込み、外部送信、workflow 起動は既存 owner の入口へ渡す直前に人間の明示承認を要求する。Claude Code の実行権限、sandbox、approval は bridge が迂回せず、その task の既存設定を正とする。

### Codex Voice と同等にならない点

| 観点 | Codex Voice | Claude Code + Realtime API |
|---|---|---|
| 開始まで | desktop app の Voice を開始 | client、音声 transport、token 発行 server、bridge が必要 |
| repository 文脈 | Codex task の既存文脈と権限を利用 | 安全な context loader と更新戦略を設計する |
| task coordination | 製品機能として別 task の開始・確認・follow-up | task ID、進捗、cancel、再接続を bridge が所有する |
| tool 実行 | Codex permissions に従う | tool allowlist、schema、承認、結果 redaction を実装する |
| 割り込み | 製品機能 | Realtime は対応するが、tool 実行の cancel / compensating policy は別途必要 |
| 会話ログ | ChatGPT / workspace の製品設定に従う | transcript、audio、tool log の保存有無・retention・削除を設計する |
| 利用枠 | plan 別 Voice 枠 + Codex task 枠 | API token 従量課金 + project rate / spend limit |
| 運用 | rollout / workspace 設定に依存 | API project、secret rotation、監視、障害対応が必要 |

## 価格と10分・30分・60分の試算

### 公式単価（2026-08-16取得、USD）

`gpt-realtime-2.1` は100万 token あたり次の単価である。

| modality | input | cached input | output |
|---|---:|---:|---:|
| text | $4.00 | $0.40 | $24.00 |
| audio | $32.00 | $0.40 | $64.00 |

`gpt-live-transcribe` は token ではなく realtime audio duration で課金され、$0.017/分である。これは transcript の費用であり、双方向音声 agent の応答生成費ではない。

### speech-only の例示レンジ

公式 cost guide は user audio を100msあたり1 token、assistant audio を50msあたり1 tokenとしている。次の値は、この換算と上の audio 単価だけで算出した**発話 audio の例示額**であり、請求総額の上限・保証ではない。

- 低発話ケース: 全時間の35%をuser、25%をassistant、40%を無音
- 高発話ケース: 全時間の55%をuser、45%をassistant、無音なし
- 式: `user秒 × 10 × $32 / 1,000,000 + assistant秒 × 20 × $64 / 1,000,000`

| セッション長 | 低発話ケース | 高発話ケース |
|---:|---:|---:|
| 10分 | 約$0.26 | 約$0.45 |
| 30分 | 約$0.78 | 約$1.35 |
| 60分 | 約$1.56 | 約$2.71 |

実請求には、各 response で入力になる instructions、会話履歴、text input / output、tool call / result、special token、cache hit 率が加わる。ターン数が増えるほど会話履歴の input が再評価されるため、時間と発話比率だけでは総額レンジを保証できない。正確な見積りは、10分の代表シナリオで各 `response.done` の `usage.input_token_details` / `output_token_details` を収集し、text / audio / cached を分けて30分・60分へ外挿する。project の rate limit と spend limit も試作前に固定する。

参考として、`gpt-live-transcribe` だけを同じ長さ使う場合は10分 $0.17、30分 $0.51、60分 $1.02だが、音声応答、推論、Claude Code bridge の費用・機能を含まない。

## 権限・秘密情報・ログの安全境界

- 標準 OpenAI API key は server-side secret owner にだけ置き、client には短命 client secret だけを渡す。
- Realtime へ送る repository context は必要最小限の読み取り済み資料に限定し、`.env`、`auth/`、token、未公開個人情報を除外する。
- model が生成した tool 名・引数を untrusted input とし、固定 allowlist と schema で拒否側に倒す。
- 読み取り、提案、承認、変更を別 event にし、音声の曖昧な相槌を変更承認として扱わない。
- transcript / audio は既定で永続保存せず、必要な監査記録は tool 名、承認結果、対象 owner、redacted result に限定する。
- session / bridge / Claude Code task の識別子を対応付け、replay、別 repository への取り違え、接続断後の二重実行を防ぐ。

## 推奨と後続 Wayfinder の判断項目

### 推奨順

1. Codex Voice の手動検証を先に行う。実装なしで壁打ち、割り込み、要約、task coordination の中核仮説を検証できる。
2. 手動検証では読み取り専用の題材を使い、会話品質と操作負荷を採点する。Voice の存在だけをもって workflow 起動の採用判断にしない。
3. Codex Voice で不足する要件が「独自 UI」「provider-neutral bridge」「独自監査」「Claude Code 固有 task」のいずれかに特定された場合だけ、`gpt-realtime-2.1` の10分 read-only spike を別 issue で起票する。
4. 書き込みや workflow 起動は、read-only spike、明示承認、replay 防止、ログ redaction が検証された後の別段にする。

### Wayfinder で決めること

- 成功指標: 一問ずつの質問遵守、割り込み後の復帰、固有語認識、要約の事実一致、task coordination の待ち時間
- 採用対象: Codex Voice の運用手順だけか、独自 Realtime client も所有するか
- bridge の責務: read-only context、task 起動、進捗取得、cancel のどこまでを公開するか
- 承認モデル: 音声と画面確認の併用、変更操作ごとの再確認、timeout / disconnect 時の fail-closed
- data policy: transcript / audio / tool audit の保存範囲、retention、workspace policy との整合
- 予算: 代表10分シナリオの `response.done` 実測、月間利用者数、spend limit、Voice plan 枠との比較

## 公式参照資料

すべて2026-08-16に取得した。

- [ChatGPT Voice](https://learn.chatgpt.com/docs/features/voice) — GPT-Live、開始条件、会話・task coordination、権限、制限
- [ChatGPT Work / Codex pricing](https://learn.chatgpt.com/docs/pricing) — Voice の rolling window、プラン別目安、duplex model、credits
- [Realtime and audio](https://developers.openai.com/api/docs/guides/realtime) — 低遅延 voice agent と transcription のモデル選択
- [Voice agents](https://developers.openai.com/api/docs/guides/voice-agents) — speech-to-speech / chained 構成、WebRTC / WebSocket、tools
- [Realtime API with WebRTC](https://developers.openai.com/api/docs/guides/realtime-webrtc) — server-side standard key と短命 client secret
- [Realtime API with WebSocket](https://developers.openai.com/api/docs/guides/realtime-websocket) — server-to-server 接続と認証
- [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations) — session / conversation state、instructions、60分上限
- [Realtime with tools](https://developers.openai.com/api/docs/guides/realtime-mcp) — function / MCP tool の実行面
- [Managing Realtime costs](https://developers.openai.com/api/docs/guides/realtime-costs) — audio token 換算、`response.done` usage、cache
- [`gpt-realtime-2.1`](https://developers.openai.com/api/docs/models/gpt-realtime-2.1) — modality、tool use、context、単価
- [`gpt-live-transcribe`](https://developers.openai.com/api/docs/models/gpt-live-transcribe) — streaming speech-to-text と分単価
