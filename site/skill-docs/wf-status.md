## 何ができるか

planning / live collection の制作進捗を、読み取り専用の一覧で確認するスキルです。`workflow-state.json` だけでなく企画、サムネイル、音源、動画、公開記録の実ファイルも突き合わせ、不整合を blocker として表示します。制作工程や YouTube API は実行せず、進め方を判断するための snapshot だけを作ります。

| mode | すること | 主な成果物 |
|---|---|---|
| フラグなし | 全 collection の状態と実成果物を一覧表示 | `tmp/reviews/workflow-status.html` |

## 制作中の collection を一覧で見たいとき

```
/wf-status
```

チャンネル内の canonical state と実成果物を毎回読み直し、固定 path の HTML を atomic に上書きして開きます。「すべて / 企画中 / 公開工程 / 完了」の filter は表示だけを切り替え、state や成果物には触れません。

## どこで止まっているか確認したいとき

```
/wf-status
```

各 collection の phase と assets を整形し、状態に記録済みなのに成果物が無い、といった食い違いも同じ一覧に表示します。壊れた `workflow-state.json` がある collection だけを隠すことはありません。確認後に作業を進める場合は `/wf-next` を使います。

## YouTube のチャンネル統計を見たいとき

`/wf-status` の対象はローカルの制作進捗です。登録者数や再生回数など YouTube 側の統計は、次を使います。

```
/analytics --status
```

## つまずいたら

- **browser が開かない** — コマンドが表示した `tmp/reviews/workflow-status.html` の絶対 path をブラウザで開いてください。生成済み snapshot は保持されます
- **state 不在・破損の card が出る** — collection path を確認し、未初期化なら `/wf-new` から開始してください。このスキル自身は修復しません
- **表示と手元のファイルが違う** — 過去の HTML ではなく `/wf-status` を再実行してください。snapshot は正本ではなく、毎回 canonical state から作り直されます
- **次の工程を実行したい** — `/wf-next` を使ってください。一気通貫で継続する場合は `/wf-new --auto` です
