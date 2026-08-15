# Collection server lifecycle

`yt-collection-serve` の起動、既存 server の再利用判定、疎通確認、停止はこのファイルを唯一の正とする。呼び出し元 skill は `/extension` へ委譲せず、必要な対象の節を直接読む。

## 対象別マッピング

| modifier | 起動引数 | 既定 port | 必須 health check |
|---|---|---:|---|
| `--suno` | `--allow-extension suno-helper` | 7873 | `/collections`, origin 付き `/auth/token` |
| `--distrokid` | `--allow-extension distrokid-helper --distrokid-capture-root "$CHANNEL_DIR" --port 7874` | 7874 | `/distrokid/collections`, server log の dir / releases enabled |
| `--community` | `--allow-extension community-helper` | 7873 | `/collections`, origin 付き `/auth/token` |

`--serve` / `--stop` は対象 modifier をちょうど 1 個必須とする。channel root を確定し、collections root には必ず `"$CHANNEL_DIR/collections/planning"` を渡す。collection 単体 path は playlist / directory mode を失うため使わない。

## 既存 server の再利用

固定 registry `http://localhost:7872/.well-known/yt-collection-serve` と既知の port を調べる。既存 server が同じ collections root、対象拡張、必要な capture root を持ち、下記 health check がすべて通る場合は、その URL / port / detected origin を記録して再利用する。追加 process を起動しない。

一致しない server、別用途の server、health check に失敗する server は再利用しない。既定 port が使用中なら既存 process を停止せず、空き port を選ぶ。

## 起動

Suno は先に `uv run yt-collection-preflight <collection-dir-name>` を通す。共通して `.tmp/logs` を作り、line-buffered log へ background 起動する。

```bash
# --suno
PYTHONUNBUFFERED=1 nohup uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" \
  --allow-extension suno-helper --port 7873 \
  > .tmp/logs/collection-serve-7873.log 2>&1 &

# --distrokid
PYTHONUNBUFFERED=1 nohup uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" \
  --distrokid-capture-root "$CHANNEL_DIR" \
  --allow-extension distrokid-helper --port 7874 \
  > .tmp/logs/collection-serve-7874.log 2>&1 &
```

`--allow-extension` が unpacked extension ID を 0 件または複数検出した場合、Preferences 読み取り不可、Preferences JSON parse failure の場合だけ、診断に出た exact ID を `--allow-origin "chrome-extension://<EXTENSION_ID>"` として再実行する。起動ログの `detected extension: suno-helper -> <id> (chrome-extension://<id>)` を確認する。origin lock なしでは起動しない。

## 疎通確認

Suno / community は `/collections` が JSON array を返し、各 collection に `status` / `pattern_count` / `downloaded_count` があることを確認する。Suno はさらに `/collections/<id>/suno/prompts.json` が対象の `suno-prompts.json` を返すことを確認する。server log の `detected extension` origin を使った `GET /auth/token` が token を返すことも必須とする。

DistroKid は `/distrokid/collections` が対象 collection と disc を返し、server log に `distrokid dir mode enabled`、`distrokid releases enabled`、対象 extension の detected origin があることを確認する。

疎通確認が 1 点でも失敗した server は成功扱いにしない。log path、port、失敗した check を報告する。

## 停止

起動または再利用した正確な port を使う。

```bash
uv run yt-collection-serve --stop --port <PORT>
ps aux | grep '[y]t-collection-serve'
```

対象 port の process が残っていないことを確認する。他用途・別 port の server は停止しない。停止に失敗した場合は完了扱いにしない。
