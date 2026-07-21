import { AlertDialog as AlertDialogPrimitive } from "@base-ui/react/alert-dialog";
import * as React from "react";

import { Button } from "./button";
import { useShadowPortalTriggerRef } from "./use-shadow-portal-trigger-ref";
import { cn } from "./utils";

const AlertDialogPortalContext = React.createContext<{
  container: HTMLElement | ShadowRoot | null;
  setContainer: React.Dispatch<
    React.SetStateAction<HTMLElement | ShadowRoot | null>
  >;
} | null>(null);

function AlertDialog(props: AlertDialogPrimitive.Root.Props) {
  const [container, setContainer] = React.useState<
    HTMLElement | ShadowRoot | null
  >(null);
  const portalContext = React.useMemo(
    () => ({ container, setContainer }),
    [container]
  );
  return (
    <AlertDialogPortalContext.Provider value={portalContext}>
      <AlertDialogPrimitive.Root {...props} />
    </AlertDialogPortalContext.Provider>
  );
}

function AlertDialogTrigger({
  ref,
  ...props
}: AlertDialogPrimitive.Trigger.Props) {
  const portal = React.useContext(AlertDialogPortalContext);
  const setTriggerRef = useShadowPortalTriggerRef(ref, portal?.setContainer);
  return (
    <AlertDialogPrimitive.Trigger
      ref={setTriggerRef}
      data-slot="alert-dialog-trigger"
      {...props}
    />
  );
}

function AlertDialogPortal(props: AlertDialogPrimitive.Portal.Props) {
  const portal = React.useContext(AlertDialogPortalContext);
  return (
    <AlertDialogPrimitive.Portal
      data-slot="alert-dialog-portal"
      container={portal?.container}
      {...props}
    />
  );
}

function AlertDialogOverlay({
  className,
  ...props
}: AlertDialogPrimitive.Backdrop.Props) {
  return (
    <AlertDialogPrimitive.Backdrop
      data-slot="alert-dialog-overlay"
      className={cn(
        "fixed inset-0 isolate z-[2147483647] bg-black/10 duration-100 supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0",
        className
      )}
      {...props}
    />
  );
}

function AlertDialogContent({
  className,
  size = "default",
  ...props
}: AlertDialogPrimitive.Popup.Props & { size?: "default" | "sm" }) {
  return (
    <AlertDialogPortal>
      <AlertDialogOverlay />
      <AlertDialogPrimitive.Popup
        data-slot="alert-dialog-content"
        data-size={size}
        className={cn(
          "group/alert-dialog-content fixed top-1/2 left-1/2 z-[2147483647] grid w-full -translate-x-1/2 -translate-y-1/2 gap-6 rounded-xl bg-popover p-6 text-popover-foreground ring-1 ring-foreground/10 duration-100 outline-none data-[size=default]:max-w-xs data-[size=sm]:max-w-xs data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className
        )}
        {...props}
      />
    </AlertDialogPortal>
  );
}

function AlertDialogHeader({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-header"
      className={cn("grid gap-1.5 text-center", className)}
      {...props}
    />
  );
}

function AlertDialogFooter({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-footer"
      className={cn("flex flex-col-reverse gap-2", className)}
      {...props}
    />
  );
}

function AlertDialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Title>) {
  return (
    <AlertDialogPrimitive.Title
      data-slot="alert-dialog-title"
      className={cn("text-lg font-medium", className)}
      {...props}
    />
  );
}

function AlertDialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Description>) {
  return (
    <AlertDialogPrimitive.Description
      data-slot="alert-dialog-description"
      className={cn("text-sm text-balance text-muted-foreground", className)}
      {...props}
    />
  );
}

function AlertDialogAction({
  className,
  ...props
}: React.ComponentProps<typeof Button>) {
  return (
    <Button
      data-slot="alert-dialog-action"
      className={cn(className)}
      {...props}
    />
  );
}

function AlertDialogCancel({
  className,
  variant = "outline",
  size = "default",
  ...props
}: AlertDialogPrimitive.Close.Props &
  Pick<React.ComponentProps<typeof Button>, "variant" | "size">) {
  return (
    <AlertDialogPrimitive.Close
      data-slot="alert-dialog-cancel"
      className={cn(className)}
      render={<Button variant={variant} size={size} />}
      {...props}
    />
  );
}

export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogTitle,
  AlertDialogTrigger,
};
