# distrokid-helper は suno-helper から helper extension shell だけを取り込む

## Status

accepted (2026-07-01)。

distrokid-helper は、先行している suno-helper の機能一式ではなく helper extension shell を取り込む。開発ゲート、manifest 管理、server 連携、popup/background/content の責務境界、エラー表示の考え方は揃えるが、DistroKid 固有の安全境界である「フォーム注入後にユーザーが目視確認して手動で続行する」運用を守るため popup UI は維持し、overlay / MAIN world bridge / download watcher / resume state は移植しない。

## Consequences

- distrokid-helper の書き込み境界は suno-helper と同じく background service worker に寄せ、server state を更新する POST は serve token を必須にする。
- shared 化は API client、route/storage constants、compatibility check、token 付き POST helper のような拡張間契約に限定し、runner hook と UI component は各 helper が所有する。
- distrokid-helper は `useDistrokidRunner` 相当の runner hook を持ち、popup component から fetch / injection / released record の実行制御を分離する。
- Phase enum は完全共通化せず、`injecting` / `done` / `error` / `stopped` のような共通語彙だけを揃える。
- distrokid-helper の manifest permissions は lib 定数を SSOT とし、manifest test で drift を検知する。
