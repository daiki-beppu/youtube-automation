import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "./utils";

const alertVariants = cva(
  "relative w-full rounded-lg border px-4 py-3 text-sm",
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        warning: "border-amber-300 bg-amber-50 text-amber-900",
        destructive: "text-destructive bg-card",
      },
      appearance: {
        subtle: "",
        filled: "",
      },
    },
    compoundVariants: [
      {
        variant: "destructive",
        appearance: "filled",
        className: "border-red-300 bg-red-50 text-red-900",
      },
    ],
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
