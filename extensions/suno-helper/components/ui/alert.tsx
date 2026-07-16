import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const alertVariants = cva("relative w-full rounded-lg border px-4 py-3 text-sm", {
  variants: {
    variant: {
      default: "bg-card text-card-foreground",
      warning: "border-amber-300 bg-amber-50 text-amber-900",
      destructive: "border-red-300 bg-red-50 text-red-900",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

function Alert({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return (
    <div data-slot="alert" data-variant={variant} className={cn(alertVariants({ variant }), className)} {...props} />
  );
}

export { Alert, alertVariants };
