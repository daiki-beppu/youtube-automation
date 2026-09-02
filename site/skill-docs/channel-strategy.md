## 何ができるか

調査結果を「誰に、どんな場面で、何をどう作るか」という制作判断へ変換するスキルです。フラグなしなら persona → scene → constraints を状態判定つきで進め、検証済み JSON / HTML ペアを後続の制作スキルへ渡します。開設後にポジショニングを見直す direction は、必要なときだけ単独で実行します。

| mode | すること | 主な成果物 |
|---|---|---|
| `--persona` | 根拠から第一ペルソナを 1 人に絞る | `docs/channel/personas/persona-definition.json` / `.html` |
| `--scene` | 第一ペルソナの視聴シーンを検証・選定 | `docs/plans/viewing-scene-matrix.json` / `.html` |
| `--constraints` | 戦略を音・映像・サムネ・タイトルの制作制約へ翻訳 | `docs/channel/creative-constraints.json` / `.html` |
| `--direction` | ポジショニング・差別化・方向性を再検討 | `docs/channel/channel-direction.json` / `.html` |

## チャンネル戦略を制作可能な形までまとめたいとき

```
/channel-strategy
```

第一ペルソナ、視聴シーン、creative constraints を順に作ります。完了済みの段は skip されるため、調査成果物を更新したあとの再実行や、途中からの再開にも使えます。

## 第一ペルソナを決めたいとき

```
/channel-strategy --persona
```

viewer voice、TTP seed、競合 branding などの検証済み根拠から候補を作り、第一ペルソナを 1 人に統合します。思いつきの属性ではなく、根拠と確度を保存して後から更新できる形にします。

## いつ・どこで視聴されるか決めたいとき

```
/channel-strategy --scene
```

第一ペルソナと、開設前なら競合・viewer voice、公開後なら Analytics を照合し、活動、時間帯、デバイス、求める尺などを視聴シーンとして整理します。

## 戦略を制作ルールへ落とし込みたいとき

```
/channel-strategy --constraints
```

persona と scene を音、映像、サムネイル、タイトル、測定の具体的な制約へ翻訳します。config へ反映できる候補がある場合は、変更内容を提示して承認を得てから更新します。

## 開設後の方向性や差別化を見直したいとき

```
/channel-strategy --direction
```

市場・競合・視聴者の分析を読み、ポジショニング、コンテンツ戦略、ビジュアル、音楽設定を対話で再決定します。通常の立ち上げ chain には含まれないため、方向転換を検討するときだけ明示的に使います。

## つまずいたら

- **`--persona` が viewer voice 不足で止まる** — `/channel-research --voice` を先に実行してください
- **`--scene` が persona 不足で止まる** — `/channel-strategy --persona` を完了してください。公開後は `/analytics --collect` と `/analytics --analyze` のレポートも必要です
- **`--constraints` が入力不足で止まる** — 検証済み persona と viewing scene を揃えてから再実行してください
- **`--direction` が調査不足で止まる** — 案内に従い `/channel-research --benchmark`、`/channel-research --voice`、`/channel-research --market` の必要な段を実行してください
- **Markdown の移行確認で止まる** — 既存文書を JSON / HTML ペアへ移行するか選択してください。拒否した場合は既存ファイルを保持して終了します
