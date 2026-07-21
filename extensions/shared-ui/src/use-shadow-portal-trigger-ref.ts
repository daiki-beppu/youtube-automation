import * as React from "react";

export function useShadowPortalTriggerRef<T extends HTMLElement>(
  forwardedRef: React.Ref<T> | undefined,
  setContainer:
    | React.Dispatch<React.SetStateAction<HTMLElement | ShadowRoot | null>>
    | undefined
): React.RefCallback<T> {
  return React.useCallback(
    (node: T | null) => {
      if (typeof forwardedRef === "function") {
        forwardedRef(node);
      } else if (forwardedRef) {
        forwardedRef.current = node;
      }
      if (node) {
        setContainer?.(node.parentElement);
      }
    },
    [forwardedRef, setContainer]
  );
}
