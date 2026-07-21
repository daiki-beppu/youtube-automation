import {
  formatServerSourceLabel,
  type HelperProcessName,
  type LocalServerSource,
} from "@youtube-automation/extensions-shared/constants";
import * as React from "react";

import { Field, FieldLabel } from "./field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";
import { cn } from "./utils";

export interface ServerSourceFieldProps {
  value: string;
  sources: LocalServerSource[];
  disabled: boolean;
  helper: HelperProcessName;
  onValueChange: (value: string) => void;
  onRefresh: () => Promise<void>;
  id?: string;
  fieldProps?: React.ComponentProps<typeof Field>;
  triggerProps?: React.ComponentProps<typeof SelectTrigger>;
  fieldDataAttributes?: Record<string, string>;
  triggerDataAttributes?: Record<string, string>;
}

/** Programmatic selection contract for extension automation without a hidden native select. */
export const SERVER_SOURCE_SELECT_EVENT =
  "youtube-automation:server-source-select";

export function ServerSourceField({
  value,
  sources,
  disabled,
  helper,
  onValueChange,
  onRefresh,
  id,
  fieldProps,
  triggerProps,
  fieldDataAttributes,
  triggerDataAttributes,
}: ServerSourceFieldProps) {
  const fieldRef = React.useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const disabledRef = React.useRef(disabled);
  React.useEffect(() => {
    disabledRef.current = disabled;
    if (disabled) {
      setOpen(false);
    }
  }, [disabled]);

  const handleOpenChange = (nextOpen: boolean): void => {
    if (!nextOpen) {
      setOpen(false);
      return;
    }
    if (disabledRef.current || refreshing) {
      return;
    }
    setOpen(false);
    setRefreshing(true);
    void onRefresh().finally(() => {
      setRefreshing(false);
      if (!disabledRef.current) {
        setOpen(true);
      }
    });
  };

  const items = sources.map((source) => ({
    value: source.url,
    label: formatServerSourceLabel(source, helper),
  }));
  const { className: fieldClassName, ...restFieldProps } = fieldProps ?? {};
  const { className: triggerClassName, ...restTriggerProps } =
    triggerProps ?? {};
  const selectedValue = value || sources[0]?.url || "";
  const committedValueRef = React.useRef(selectedValue);
  React.useEffect(() => {
    committedValueRef.current = selectedValue;
  }, [selectedValue]);
  const commitValue = React.useCallback(
    (nextValue: string): void => {
      if (
        nextValue &&
        nextValue !== committedValueRef.current &&
        !disabledRef.current &&
        !refreshing
      ) {
        committedValueRef.current = nextValue;
        onValueChange(nextValue);
      }
    },
    [onValueChange, refreshing]
  );
  React.useEffect(() => {
    const field = fieldRef.current;
    if (!field) return;
    const handleProgrammaticSelection = (event: Event): void => {
      const nextValue = (event as CustomEvent<string>).detail;
      if (typeof nextValue === "string") commitValue(nextValue);
    };
    field.addEventListener(
      SERVER_SOURCE_SELECT_EVENT,
      handleProgrammaticSelection
    );
    return () =>
      field.removeEventListener(
        SERVER_SOURCE_SELECT_EVENT,
        handleProgrammaticSelection
      );
  }, [commitValue]);

  return (
    <Field
      ref={fieldRef}
      data-disabled={disabled || refreshing}
      data-selected-value={selectedValue}
      data-source-values={sources.map((source) => source.url).join(" ")}
      className={cn("gap-1", fieldClassName)}
      {...restFieldProps}
      {...fieldDataAttributes}
    >
      <FieldLabel htmlFor={id}>ローカル配信元</FieldLabel>
      <Select
        items={items}
        value={selectedValue}
        open={open}
        disabled={disabled || refreshing}
        onOpenChange={handleOpenChange}
        onValueChange={(nextValue) => nextValue && commitValue(nextValue)}
      >
        <SelectTrigger
          id={id}
          data-selected-value={selectedValue}
          className={cn("w-full justify-start text-left", triggerClassName)}
          {...restTriggerProps}
          {...triggerDataAttributes}
        >
          {refreshing ? <span>稼働中の配信元を更新中…</span> : <SelectValue />}
        </SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          <SelectGroup>
            {sources.map((source) => (
              <SelectItem key={source.url} value={source.url}>
                {formatServerSourceLabel(source, helper)}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  );
}
