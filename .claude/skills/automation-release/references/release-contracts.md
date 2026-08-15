# automation-release の配布内 release contract

この reference は `/automation-release` の実行に必要な Python Migration producer と Chrome extension 配布の契約を定める。履歴や検討過程は含めず、SKILL.md の prepare / publish 手順から参照する実行時の単一ソースとする。

## Python Migration producer contract

Python release の prepare では、`[Unreleased]` 配下の `### Migration` を下流 `/automation-update` が読み取る入力として扱う。セクションを置く場合は、次の3要素を保持する。

1. 1行目の `所要時間の目安: X〜Y 分`
2. `local fix 衝突注意:` と対象skillの箇条書き（該当なしは `- 無し`）
3. `サマリ:` と主要変更の箇条書き

`### Migration` が欠落している場合、prepare 1-4 は warning を表示し、`AskUserQuestion` でそのまま続行するかユーザー確認する。欠落だけを理由に無条件 abort しない。ただし、prepare 1-3a の Python module 移動監査で facade 無し移動の対応表が必要と判定された場合は別契約であり、必要な記載が揃うまで prepare を停止する。

## Chrome extension distribution contract

- 配布形態は GitHub Release の zip とし、Chrome Web Storeへ切り替えない。
- 対象は `suno-helper` / `distrokid-helper` / `community-helper` の3拡張で、release workflowは3件すべてのassetを添付する。
- tagは3拡張で共有する統一 `ext-v*` tag 系列とし、拡張ごとの独立tagを作らない。
- 各extensionの `package.json::version` は唯一のpackage versionで、Python 本体 version と独立する。extension releaseはPython側の `pyproject.toml` / `uv.lock` / `CHANGELOG.md` 昇格を変更しない。
- release asset 名は `<name>-<package version>-chrome.zip` とする。統一tagを系列の次番号へ進めた結果tag versionとpackage versionが異なっても、asset名にはtag versionではなくpackage versionを使う。

SKILL.md のPhase E、`references/verify-extensions.sh`、`.github/workflows/release-extensions.yml`、消費側の `/extension` は、このtag・version・asset命名を同じ契約として扱う。
