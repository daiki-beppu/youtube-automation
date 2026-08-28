# タイトルと概要欄を多言語化する

海外の視聴者にも動画を見つけてもらいやすいように、collection 型チャンネルではタイトルと概要欄の多言語版を生成し、YouTube の localization メタデータとして登録できます。対象言語は `config/localizations.json` にまとめて指定するため、動画ごとに言語の一覧を重複して管理する必要はありません。

## できること

- 対象言語ごとのタイトルと概要欄を生成する
- 生成した文面を YouTube の localization メタデータへ反映する
- 言語ごとのタイトル形式を、視聴シーンや用途に合わせて調整する
- 投稿済みの collection Shorts にも localization を後から反映する

## 始める前に

対象言語の唯一の正は `config/localizations.json` の `supported_languages` です。別の設定ファイルへ言語一覧を重複して書かず、追加や削除はここだけで行います。

多言語向けの生成が有効になるのは、`supported_languages` に2言語以上を指定したときだけです。この場合に `scene_phrases`、概要欄の多言語版、YouTube localization メタデータが生成されます。単一言語チャンネルではこれらの生成物は増えず、`scene_phrases` も必要ありません。

設定の作成・更新方法と、チャンネル方針に応じた言語の選び方は [`config/localizations.json` の生成ルール](../.claude/skills/setup/references/config-generation-rules.md#ルート設定ファイル)を参照してください。

## 多言語化を使う

`config/localizations.json` の `supported_languages` に、チャンネルで使う言語を並べます。公開時は通常どおり `/publish --upload` を実行すると、この一覧をもとに概要欄の多言語版と YouTube localization メタデータが生成・検証されます。

```text
/publish --upload
```

アップロード経路の詳しい動作は [YouTube アップロード手順](../.claude/skills/publish/references/upload.md#channel-adaptation)を参照してください。

投稿済みの collection Shorts へ後から localization を反映したい場合は、まず dry-run で更新対象を確認します。

```bash
uv run yt-shorts-bulk-update-loc --dry-run
```

確認後の更新方法は [`/short` の Quick Reference](../.claude/skills/short/SKILL.md#quick-reference)を参照してください。

## タイトルを調整する

言語ごとのタイトル形式は `languages.<lang>.title_template` で調整できます。使用できるプレースホルダは **`{scene_phrase}` / `{activities}` / `{scene_emoji}` の3つだけ**です。

`content.json` のタイトル用キーである `{style}`、`{theme}`、`{activity}`、`{duration_display}`、`{axis_label}` などは流用できません。設定を変更したら、次のコマンドでチャンネル設定を検証してください。

```bash
uv run yt-doctor --json
```

翻訳文そのものを動画ごとに手作業で管理するのではなく、対象言語は `supported_languages`、言語別のタイトル形式は `languages.<lang>.title_template` に分けて調整すると、次回以降の公開でも同じ方針を再利用できます。
