// service 層共有の default 注入実装（バックオフ sleep と画像の永続化）。
//
// テストではこれらを fake で差し替えるため、ここはユニットテストの対象外の
// production default。#959 で retry / persist の所有が provider から service に
// 移ったため、注入点も `generateImageService` の deps（`persist` / `sleep`）になった。
// `persist` は decode 済みの生バイト列を `outputPath` へ書き出す。Python 版
// `composition.persist_image` の PNG/JPEG dual-save・YouTube サムネ 2MB 上限対応は
// 別モジュール（composition の移植）の責務であり、本抽象のスコープ外なので、
// ここでは生バイトのロスレス書き出しのみを行う。

import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import type { SleepMs } from "../retry.ts";
import type { PersistImage } from "./base.ts";

/** 実時間で待機する default sleep。 */
export const defaultSleep: SleepMs = (ms) => Bun.sleep(ms);

/** 生バイト列を `outputPath` に書き出して保存先パスを返す default persist。 */
export const defaultPersist: PersistImage = async (outputPath, bytes) => {
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, bytes);
  return outputPath;
};
