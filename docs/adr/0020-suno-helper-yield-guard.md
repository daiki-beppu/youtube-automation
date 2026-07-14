# suno-helper に歩留まりガードレールを寄せ、masterup-pairs はキュレーションに専念する

## Status

accepted (2026-06-28)。#1733 により 2026-07-14 更新。

2026-07-02 の ADR 監査で 0012 から番号振り直し（並行 PR による番号レースの解消、先着優先ルール）。旧文書中の「ADR-0012」は文脈により本 ADR を指す。

Suno V5 は同一プロンプトでも尺が不安定で、1 分未満や 5 分超の壊れた曲を頻繁に出す。従来この歩留まり判定は masterup-pairs が ffprobe で事後的に行っていたが、NG 曲の補充は人間が手動で suno-helper を再実行する運用だった。suno-helper が Suno UI を操作している最中（feed v3 の `metadata.duration`）に duration を検知できることが判明したため、duration check と選択可能な自動再生成を suno-helper 側に移す。masterup-pairs の duration filter は二重チェックとして残し、ペア選択 + stock 退避のキュレーション責務に専念させる。

## Considered Options

**A) masterup-pairs に歩留まり判定を残す（現状維持）** — NG 曲の再生成は手動。Suno UI を閉じた後に NG が発覚するため、再度 Suno を開いて手動で `/suno-helper` を回す必要がある。

**B) suno-helper に歩留まりガードレールを移す（採用、#1733 で更新）** — entry 単位で duration check する。「異常値の曲を再生成する」が ON なら、NG 時に同じ prompt で自動再 Generate（最大リトライ 2 回）し、duration OK clips のみプレイリストへ追加する。OFF なら自動再生成せず、NG の警告を progress・snapshot・resume state に残し、その entry の全 clips を採用候補としてプレイリストへ追加する。OFF 時も連続実行を止めず、異常値 clip を silent skip しない。masterup-pairs の duration filter は二重チェックとして残す。

**C) suno-helper に歩留まりを移し、masterup-pairs から duration filter を撤去** — 責務は明確になるが、手動プレイリスト経由など suno-helper を通さないルートでセーフティネットがなくなる。

B を採用。suno-helper は「生成品質のガードレール」、masterup-pairs は「キュレーション（ペア選択 + stock 退避）」で責務を分離する。

## Consequences

- bridge のインターセプト対象が `/api/feed/v2` GET → `/api/feed/v3` POST に変わる。`ObservedClip` に `duration` フィールドが追加される
- duration 閾値は `suno-prompts.json` の `duration_filter: { min_sec, max_sec }` で collection 単位設定。suno-helper が既存のパイプライン（collection-serve → 拡張）で受け取る
- popup の「異常値の曲を再生成する」は既定 ON。実行開始時の選択を run payload・snapshot・resume state に保持し、popup 再表示と resume でも同じ契約を維持する
- OFF で保持した duration NG 警告は完了表示にも残す。ユーザーは playlist / download 後に警告対象を確認して手動採否を判断する
- Playlist Capture 機能（`auto-capture.ts`、`POST /suno/playlists`）は撤去。suno-helper が直接ダウンロードするため URL キャプチャが不要になった
- PatternList が range UI からチェックボックス方式に変わる。任意の entry を指定して再生成可能
