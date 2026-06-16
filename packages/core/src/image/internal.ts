// image モジュール内部で共有する小さなガード（公開 API ではない）。
// 実体は共用の internal/guards.ts に集約済み（DRY）。ここは image 内 import の barrel。

export { isRecord } from "../../internal/guards.ts";
