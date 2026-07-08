// 速度プリセット (#875) の解決・jitter 算出・chrome.storage I/O を 1 箇所に集約する。
//
// 純関数 (resolveSpeedPreset / applyJitter) と既定 id (DEFAULT_SPEED_PRESET_ID) は content / popup の
// 双方が import する SSOT。I/O (readSpeedPresetId / writeSpeedPresetId) は @wxt-dev/storage の型付き
// wrapper で chrome.storage.local を読み書きする。storage.defineItem は呼ぶと内部で chrome.runtime へ
// アクセスするため、node 環境 (vitest) で純関数だけを import したときに副作用を起こさないよう遅延生成する
// (純関数テスト preset-state.test.ts を壊さないため。resume-state.ts と同方針)。
import { storage } from "wxt/utils/storage";

import {
  RUN_MODE_STORAGE_KEY,
  SPEED_PRESET_STORAGE_KEY,
  SPEED_PRESETS,
  type RunModeId,
  type SpeedPreset,
  type SpeedPresetId,
} from "../../shared/constants";

export type { SpeedPresetId };
export type { RunModeId };

/** 既定の速度プリセット (要件2: デフォルトは Balanced)。 */
export const DEFAULT_SPEED_PRESET_ID: SpeedPresetId = "balanced";
/** 既定の投入方式 (#1586): 既存の直列実行を維持する。 */
export const DEFAULT_RUN_MODE_ID: RunModeId = "serial";

/**
 * preset id を SpeedPreset へ解決する (要件3)。
 * 未知の id は silent に既定 preset へ落とさず throw する（設定取り違えを fail-loud で検出）。
 */
export function resolveSpeedPreset(id: SpeedPresetId): SpeedPreset {
  const preset = SPEED_PRESETS[id];
  if (!preset) {
    throw new Error(`不正な速度プリセット id: ${id}`);
  }
  return preset;
}

/**
 * 基準待機 baseMs に ±jitterMs の振れを加える (要件3/7)。
 * `baseMs + (random()*2-1)*jitterMs` で [base-jitter, base+jitter] に分布させる。jitterMs=0 なら base 固定。
 * random は DI 可能（テストで min/max を pin する）。production の content からは省略呼び出しで Math.random を使う。
 */
export function applyJitter(baseMs: number, jitterMs: number, random: () => number = Math.random): number {
  return baseMs + (random() * 2 - 1) * jitterMs;
}

// --- chrome.storage.local I/O（storage item は遅延生成。理由はファイル冒頭コメント参照） ---

// fallback 付き defineItem の型は実呼び出しから推論する（getValue が SpeedPresetId を返す
// fallback 版オーバーロードに解決させるため。型引数 + ReturnType だと null 込みの版に解決してしまう）。
function createPresetItem() {
  return storage.defineItem<SpeedPresetId>(`local:${SPEED_PRESET_STORAGE_KEY}`, {
    fallback: DEFAULT_SPEED_PRESET_ID,
  });
}

function createRunModeItem() {
  return storage.defineItem<RunModeId>(`local:${RUN_MODE_STORAGE_KEY}`, {
    fallback: DEFAULT_RUN_MODE_ID,
  });
}

let cachedPresetItem: ReturnType<typeof createPresetItem> | null = null;
let cachedRunModeItem: ReturnType<typeof createRunModeItem> | null = null;

function presetItem(): ReturnType<typeof createPresetItem> {
  if (!cachedPresetItem) {
    cachedPresetItem = createPresetItem();
  }
  return cachedPresetItem;
}

function runModeItem(): ReturnType<typeof createRunModeItem> {
  if (!cachedRunModeItem) {
    cachedRunModeItem = createRunModeItem();
  }
  return cachedRunModeItem;
}

/** 永続化済みの preset id を読む。未設定は既定 (Balanced)。 */
export async function readSpeedPresetId(): Promise<SpeedPresetId> {
  return presetItem().getValue();
}

/** popup の選択を永続化する (要件2)。 */
export async function writeSpeedPresetId(id: SpeedPresetId): Promise<void> {
  await presetItem().setValue(id);
}

export async function readRunModeId(): Promise<RunModeId> {
  return runModeItem().getValue();
}

export async function writeRunModeId(id: RunModeId): Promise<void> {
  await runModeItem().setValue(id);
}
