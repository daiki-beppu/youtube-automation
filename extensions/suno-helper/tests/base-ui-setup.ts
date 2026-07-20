// jsdom does not implement PointerEvent, while Base UI dispatches one through
// the hidden native form control to preserve browser form semantics.
if (typeof window !== "undefined" && !window.PointerEvent) {
  Object.defineProperty(window, "PointerEvent", {
    configurable: true,
    value: window.MouseEvent,
    writable: true,
  });
}
