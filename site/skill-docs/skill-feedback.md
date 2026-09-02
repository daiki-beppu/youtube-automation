## 何ができるか

下流チャンネルで skill を使ったときの不具合、摩擦、改善案を JSONL に残し、確認済みの項目を youtube-automation の GitHub issue へ還流するスキルです。記録は既存行を変えない append-only、還流は候補選択・重複確認・最終承認を経て 1 件ずつ進みます。YouTube Analytics から得た運営上の学びは対象外で、`--analyze` を指定した意図は `/analytics` へ委譲します。

| mode | すること | 主な成果物 |
|---|---|---|
| 記録 | 直近の skill 利用で生じた feedback を 1 行追加 | `data/feedback/feedback-log.jsonl` |
| 還流 | `recorded` entry を承認後に上流 issue 化 | GitHub issue URL と `filed` 状態 |
| disposition | 解決済み・意図的な見送りを確認後に記録 | `resolved` / `wontfix` と理由・日時 |

## skill の摩擦を記録したいとき

```
/skill-feedback さっきの thumbnail 生成で構図を直しにくかったので記録して
```

直近の文脈から対象 skill、`bug` / `friction` / `idea` の category、要約、再現状況を確定し、schema に準拠した JSON object を末尾へ 1 行だけ追加します。token、secret、password などは `***REDACTED***` に置換し、既存 entry は変更しません。対象 skill を特定できない場合は確認して停止します。

## 記録済み feedback を上流へ還流したいとき

```
/skill-feedback 今週の feedback を上流に還流して
```

schema-valid かつ `recorded` の entry だけを候補として表示し、起票候補、解決済み、意図的に見送り、今回は保留から扱いを選びます。起票候補は本文案と open issue の類似候補を確認し、外部反映の最終承認後にだけ `feedback` label 付き issue を作成します。成功した行だけを `filed` に更新し、失敗時は後続を起票しません。

## 解決済み・見送りを記録したいとき

```
/skill-feedback feedback を整理して、解決済みの項目を更新したい
```

対象行と disposition、空でない理由を利用者が確認した場合だけ `resolved` または `wontfix` にします。更新日時も記録し、未選択行、invalid 行、すでに終端状態の行は byte-for-byte で保ちます。

## 運営上の学びを分析したいとき

```
/skill-feedback --analyze
```

skill 自体の不具合や摩擦ではなく、再生結果から得た学びは feedback log に記録しません。`/analytics --analyze` または伸びなかった動画向けの `/analytics --flop` を案内します。

## つまずいたら

- **記録する skill を特定できない** — 対象 skill 名と、期待したこと・実際に起きたことを添えて再実行してください
- **invalid 行の警告が出る** — 行番号と schema の失敗箇所を確認してください。その行は変更せず除外され、valid な候補の処理は続きます
- **還流候補が 0 件になる** — `filed` / `resolved` / `wontfix` は終端状態です。未還流の `recorded` entry があるか確認してください
- **類似 issue の確認で止まる** — 重複候補を読み、新規起票するか今回スキップするかを明示してください
- **起票直前で止まる** — GitHub への外部反映は取り消せません。件数とタイトルを確認し、「起票する」を明示した場合だけ続行します
