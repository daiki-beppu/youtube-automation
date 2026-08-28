# 公開日時を決めて予約公開する

公開する曜日と時刻をあらかじめ設定しておくと、`/publish --upload` でアップロードした動画を YouTube の「予約済み」状態にできます。毎回 YouTube Studio で日時を入力せず、チャンネルの更新ペースに沿って公開したいときに使います。

アップロード直後の動画は非公開に見えますが、予約公開では正常な状態です。動画は予約日時まで `private` になり、設定された日時に自動で公開されます。

## できること

- チャンネルのタイムゾーンで公開曜日と時刻を指定する
- すでに公開済み・予約済みの動画を考慮して、次の公開枠を選ぶ
- アップロード前に、計算された予約日時を plan で確認する
- 必要なときは自動予約を明示的に無効化する

## 始める前に

動画をアップロードできる状態までチャンネルのセットアップを済ませてください。予約公開の設定は、チャンネルリポジトリにある `config/schedule_config.json` の `schedule` セクションへ記述します。

公開時刻は `timezone` を基準に解釈されます。実際のアップロード前に、曜日・時刻・タイムゾーンが意図した公開枠になっているか plan で確認してください。

## 公開曜日と時刻を設定する

たとえば、日本時間の月・水・金曜日、20時に公開する場合は次のように設定します。

```json
{
  "schedule": {
    "timezone": "Asia/Tokyo",
    "publish_time": "20:00",
    "cadence": ["mon", "wed", "fri"]
  }
}
```

`timezone` は公開時刻のタイムゾーン、`publish_time` は時刻、`cadence` は公開する曜日です。`cadence` か `publish_time` を明示すれば、`auto_schedule_enabled` を省略しても自動予約が有効になります。これは、公開枠を設定したのに有効化キーを入れ忘れて即時公開してしまうことを避けるための救済挙動です。

設定後に `/publish --upload` を実行すると、予約日時を `publishAt` として付けるため `privacyStatus` は `private` になります。YouTube Studio では公開前の動画が「予約済み」と表示され、予約日時になると公開されます。

詳しい優先順位、曜日名、plan による確認方法は[予約投稿（スケジュール公開）セットアップ](../.claude/skills/publish/references/scheduled-publish.md)を参照してください。

## 自動予約を調整する

一時的に予約日時を付けず非公開でアップロードしたい場合は、`auto_schedule_enabled: false` を明示します。`cadence` や `publish_time` が残っていても、この設定が優先されます。

```json
{
  "schedule": {
    "auto_schedule_enabled": false,
    "publish_time": "20:00",
    "cadence": ["mon", "wed", "fri"]
  }
}
```

この場合も即時公開は行われません。動画は予約日時のない非公開状態でアップロードされるため、公開するときは YouTube Studio で手動設定します。自動予約へ戻すときは `false` を取り除くか、`true` へ変更してから plan で公開予定を確認してください。
