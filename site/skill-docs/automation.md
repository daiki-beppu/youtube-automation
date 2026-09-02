## 何ができるか

下流のチャンネルリポジトリを youtube-automation の最新 release へ追従させたり、導入中の version に即してツールキットの使い方を調べたりするスキルです。更新は差分確認と人間の承認を挟む wizard、質問はローカル資料を優先する読み取り専用処理として分離されています。upstream 本体ではなく、automation package を依存に持つ下流リポジトリで使います。

| mode | すること | 主な結果 |
|---|---|---|
| `--update` | package、lock、skill を最新 release へ追従 | 更新済みファイルとローカル commit |
| `--question` | 仕様、skill、CLI の質問に根拠つきで回答 | version と参照元を示した回答 |

## 最新 release へ追従したいとき

```
/automation --update
```

現在の依存と local fix を調べ、更新 plan の確認後に package と配布 skill を同期し、機械チェックと commit まで進めます。手書き skill の上書き、sha pin の更新先決定、`--force-sync` や `--prune` による破壊的変更は、人間が明示的に同意するまで実行しません。push は利用者が行います。

## ツールキットについて質問したいとき

```
/automation --question "thumbnail の入力は何ですか？"
/automation yt-automation-update の使い方を教えて
```

明示的な `--question` の後ろ、または mode flag のない自然文を質問として扱います。導入済みの skill、ドキュメント、CHANGELOG の順に根拠を探し、必要な場合だけ GitHub を参照します。この mode はファイル、git、upstream を変更しません。

## つまずいたら

- **mode 未指定で止まる** — 引数が空だと処理を選べません。更新なら `/automation --update`、質問なら質問文を添えて実行してください
- **`--question` が空だと言われる** — flag の後ろに具体的な質問を記述してください
- **実行場所が違うと言われる** — youtube-automation upstream では実行できません。`youtube-channels-automation` を依存に持つ下流チャンネルリポジトリへ移動してください
- **更新が承認待ちで止まる** — local fix の破棄や旧 skill の削除など、取り消しにくい変更の確認です。差分を読み、実行するかを明示してください
- **質問の答えが見つからない** — `/skill-feedback` で不足している仕様や資料を記録してください
