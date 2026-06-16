// 動画アップロード feature の公開 API（ADR-0003 canonical 配置 packages/core/src/<feature>/）。
//
// 公開 API:
// - uploadVideoService(input, deps): ADR-0003 Result 境界（resumable + thumbnail + metadata）
// - UploadInput / UploadOutput: service 境界の zod schema（+ z.infer 型）
// - UploadDeps: 構築済み YouTube クライアントを渡す注入 seam の型

export { UploadInput, UploadOutput } from "./schema.ts";
export { type UploadDeps, uploadVideoService } from "./service.ts";
