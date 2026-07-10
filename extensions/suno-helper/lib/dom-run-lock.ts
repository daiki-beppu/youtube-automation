const RUN_LOCK_ATTRIBUTE = "data-suno-helper-run-owner";

/** 同一ページに content listener が複数残っても、実処理を開始できる owner を1つに限定する。 */
export function acquireDomRunLock(root: HTMLElement, owner: string): boolean {
  if (root.hasAttribute(RUN_LOCK_ATTRIBUTE)) return false;
  root.setAttribute(RUN_LOCK_ATTRIBUTE, owner);
  return true;
}

/** 別 context が取得した lock を誤って解放しない。 */
export function releaseDomRunLock(root: HTMLElement, owner: string): void {
  if (root.getAttribute(RUN_LOCK_ATTRIBUTE) === owner) {
    root.removeAttribute(RUN_LOCK_ATTRIBUTE);
  }
}
