import { overlayHiddenStyle } from "@youtube-automation/extensions-shared/overlay-state";
import type { OverlayState } from "@youtube-automation/extensions-shared/overlay-state";
import type { ReactNode } from "react";

import { Button } from "./button";
import { Card, CardContent, CardHeader } from "./card";
import { useOverlayController } from "./use-overlay-controller";
import { cn } from "./utils";

const DEFAULT_OVERLAY_WIDTH = 360;

export interface OverlayShellProps {
  title: ReactNode;
  children: ReactNode;
  initialState: OverlayState | null;
  onStateChange: (state: OverlayState) => void | Promise<void>;
  subscribeToggle: (toggle: () => void) => () => void;
  onError?: (error: unknown) => void;
  width?: number;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
  brandColors?: OverlayBrandColors;
}

export interface OverlayBrandColors {
  headerBackground: string;
  headerForeground: string;
  primary?: string;
  primaryForeground?: string;
}

/**
 * Service-neutral overlay shell. Consumers inject identity, storage and
 * action-message subscriptions while the shared component owns interaction.
 */
export function OverlayShell({
  title,
  children,
  initialState,
  onStateChange,
  subscribeToggle,
  onError,
  width = DEFAULT_OVERLAY_WIDTH,
  className,
  headerClassName,
  contentClassName,
  brandColors,
}: OverlayShellProps) {
  const controller = useOverlayController({
    initialState,
    width,
    onStateChange,
    subscribeToggle,
    onError,
  });
  const handlePointerDown = controller.onPointerDown;
  const handleToggleMinimized = controller.toggleMinimized;

  return (
    <Card
      ref={controller.containerRef}
      data-overlay-shell=""
      className={cn(
        "fixed gap-0 overflow-hidden rounded-lg py-0 shadow-xl",
        className
      )}
      style={{
        ...(brandColors
          ? {
              "--overlay-header-background": brandColors.headerBackground,
              "--overlay-header-foreground": brandColors.headerForeground,
              ...(brandColors.primary && brandColors.primaryForeground
                ? {
                    "--primary": brandColors.primary,
                    "--primary-foreground": brandColors.primaryForeground,
                  }
                : {}),
            }
          : {}),
        left: controller.position.x,
        top: controller.position.y,
        width,
        zIndex: 2_147_483_647,
        ...overlayHiddenStyle(controller.hidden),
      }}
    >
      <CardHeader
        data-overlay-handle=""
        layout="stack"
        onPointerDown={handlePointerDown}
        className={cn(
          "flex flex-row items-center justify-between gap-0 rounded-t-lg bg-overlay-header px-3 py-2 text-sm font-semibold text-overlay-header-foreground select-none",
          headerClassName
        )}
        style={{
          cursor: controller.dragging ? "grabbing" : "grab",
          pointerEvents: "auto",
        }}
      >
        <span>{title}</span>
        <Button
          type="button"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={handleToggleMinimized}
          aria-label={controller.minimized ? "展開" : "最小化"}
          variant="ghost"
          className="h-auto w-auto rounded px-2 py-0 leading-none text-overlay-header-foreground hover:bg-overlay-header-foreground/10 hover:text-overlay-header-foreground"
        >
          {controller.minimized ? "▢" : "—"}
        </Button>
      </CardHeader>
      <CardContent
        data-overlay-content=""
        className={cn("overflow-y-auto p-0", contentClassName)}
        style={{
          pointerEvents: controller.minimized ? "none" : "auto",
          display: controller.minimized ? "none" : "block",
          maxHeight: "calc(100vh - 120px)",
        }}
      >
        {children}
      </CardContent>
    </Card>
  );
}
