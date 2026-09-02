## 何ができるか

automation と一緒に使う Chrome 拡張の導入・更新と、拡張が collection を読むためのローカル server を管理するスキルです。suno-helper、distrokid-helper、community-helper の 3 種を扱い、対象だけを modifier で絞れます。フラグなしでは各拡張の状態を調べ、未導入なら install、旧版なら update、最新版なら skip します。

| mode | すること | 主な結果 |
|---|---|---|
| `--install` | GitHub Release から拡張を新規導入 | `~/chrome-extensions/<name>/` |
| `--update` | 導入済み拡張を最新 release に置換 | release と一致した manifest version |
| `--serve` | 対象拡張用 collection server を起動・確認 | ローカル server URL |
| `--stop` | 対象拡張用 server を停止 | 対象 process の停止確認 |

対象は `--suno`、`--distrokid`、`--community` で絞ります。install / update / フラグなしでは複数選択でき、省略時は 3 拡張すべてが対象です。serve / stop では対象をちょうど 1 つ指定します。

## 必要な拡張を自動で揃えたいとき

```
/extension
/extension --suno --community
```

対象の導入状況と version を release と比較し、必要な install / update だけを実行します。Chrome の Load unpacked や reload は自動操作せず、最後に利用者が操作するディレクトリと手順を案内します。

## 拡張を新規導入したいとき

```
/extension --install
/extension --install --distrokid
```

release を取得して専用ディレクトリへ展開し、manifest を確認します。前者は全拡張、後者は distrokid-helper だけを対象にします。

## 導入済み拡張を更新したいとき

```
/extension --update --suno
```

suno-helper を最新 release へ置換し、manifest version の一致を確認します。完了後は Chrome 側で拡張を reload してください。

## collection server を起動したいとき

```
/extension --serve --distrokid
```

distrokid-helper 用 server の既存 process を再利用するか、新規起動して疎通を確認します。server ごとに引数や port が異なるため、`--serve` では対象 modifier を 1 つだけ指定します。

## collection server を止めたいとき

```
/extension --stop --community
```

community-helper 用の対象 port を特定して server を停止し、process が残っていないことまで確認します。

## つまずいたら

- **release を取得できず止まる** — `gh` CLI の認証と `ext-v*` release を確認してください。利用できない場合は案内された release page から手動で取得します
- **`--serve` で対象を求められる** — `--suno`、`--distrokid`、`--community` のうち 1 つを指定してください
- **複数の mode を指定して止まる** — `--install` / `--update` / `--serve` / `--stop` は 1 回に 1 つだけ指定します
- **導入後も Chrome に反映されない** — 新規導入は Load unpacked、更新は拡張管理画面で reload が必要です。表示されたディレクトリを Chrome で操作してください
