import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "./utils";

const alertVariants = cva(
  "relative w-full rounded-lg border px-4 py-3 text-sm",
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        info: "border-info-border bg-info-background text-info-foreground",
        warning:
          "border-warning-border bg-warning-background text-warning-foreground",
        success:
          "border-success-border bg-success-background text-success-foreground",
        destructive:
          "border-destructive-border bg-destructive-background text-destructive-foreground",
      },
      appearance: {
        subtle: "",
        filled: "",
      },
    },
    defaultVariants: {
      variant: "default",
      appearance: "subtle",
    },
  }
);

function Alert({
  className,
  variant = "default",
  appearance = "subtle",
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return (
    <div
      data-slot="alert"
      data-variant={variant}
      data-appearance={appearance}
      className={cn(alertVariants({ variant, appearance }), className)}
      {...props}
    />
  );
}

function AlertDescription({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn("text-sm", className)}
      {...props}
    />
  );
}

export { Alert, AlertDescription, alertVariants };
