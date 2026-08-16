# マスター音源 review

`/wf-next` の prepared → mastered 境界では `yt-master-audio-review` を使う。正本は音声ファイル・loudness receipt・selection log・`workflow-state.json` であり、`tmp/reviews/master-audio.html` は毎回再生成する表示専用snapshotである。

- HTMLには候補ID、source、ファイル名、形式、duration、size、loudness検査、選曲情報、raw master直採用の別を表示する
- worktree/mainの同名候補は `worktree:<name>` / `main:<name>` で区別する
- browser/renderer/probe失敗、digest mismatch、allowlist外ID、replayではstateと正規masterを変更しない
- terminal fallbackは黙って自動承認せず、Codex / Claude の同じsessionから `--transport terminal --candidate-id <id>` を使う
- HTMLやbrokerから任意path、command、state patchを受け取らない
- `skip_audio_approval = true` ではreview CLIを呼ばず、HTML/brokerをskipする
