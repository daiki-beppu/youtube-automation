# suno-helper に歩留まりガードレールを寄せ、masterup-pairs はキュレーションに専念する

## Status

accepted (2026-06-28)。実装は進行中 (#1266 / #1268)。

2026-07-02 の ADR 監査で 0012 から番号振り直し（並行 PR による番号レースの解消、先着優先ルール）。旧文書中の「ADR-0012」は文脈により本 ADR を指す。

Suno V5 は同一プロンプトでも尺が不安定で、1 分未満や 5 分超の壊れた曲を頻繁に出す。従来この歩留まり判定は masterup-pairs が ffprobe で事後的に行っていたが、NG 曲の補充は人間が手動で suno-helper を再実行する運用だった。suno-helper が Suno UI を操作している最中（feed v3 の `metadata.duration`）に duration を検知できることが判明したため、歩留まりガードレール（duration check + 自動再生成）を suno-helper 側に移す。masterup-pairs の duration filter は二重チェックとして残し、ペア選択 + stock 退避のキュレーション責務に専念させる。

## Considered Options

**A) masterup-pairs に歩留まり判定を残す（現状維持）** — NG 曲の再生成は手動。Suno UI を閉じた後に NG が発覚するため、再度 Suno を開いて手動で `/suno-helper` を回す必要がある。

**B) suno-helper に歩留まりガードレールを移す（採用）** — entry 単位で duration check し、NG なら同じ prompt で自動再 Generate（最大リトライ 2 回）。OK clips のみプレイリストに追加。masterup-pairs の duration filter は二重チェックとして残す。

**C) suno-helper に歩留まりを移し、masterup-pairs から duration filter を撤去** — 責務は明確になるが、手動プレイリスト経由など suno-helper を通さないルートでセーフティネットがなくなる。

B を採用。suno-helper は「生成品質のガードレール」、masterup-pairs は「キュレーション（ペア選択 + stock 退避）」で責務を分離する。

## Consequences

- bridge のインターセプト対象が `/api/feed/v2` GET → `/api/feed/v3` POST に変わる。`ObservedClip` に `duration` フィールドが追加される
- duration 閾値は `suno-prompts.json` の `duration_filter: { min_sec, max_sec }` で collection 単位設定。suno-helper が既存のパイプライン（collection-serve → 拡張）で受け取る
- Playlist Capture 機能（`auto-capture.ts`、`POST /suno/playlists`）は撤去。suno-helper が直接ダウンロードするため URL キャプチャが不要になった
- PatternList が range UI からチェックボックス方式に変わる。任意の entry を指定して再生成可能
