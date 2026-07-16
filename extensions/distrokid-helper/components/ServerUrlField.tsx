import { useEffect, useRef, useState } from "react";

import { formatServerSourceLabel, type LocalServerSource } from "../../shared/constants";

export interface ServerUrlFieldProps {
  value: string;
  sources: LocalServerSource[];
  disabled: boolean;
  onChange: (value: string) => void;
  onOpen: () => Promise<void>;
}

export function ServerUrlField({ value, sources, disabled, onChange, onOpen }: ServerUrlFieldProps) {
  const [refreshing, setRefreshing] = useState(false);
  const [open, setOpen] = useState(false);
  const disabledRef = useRef(disabled);
  useEffect(() => {
    disabledRef.current = disabled;
  }, [disabled]);

  const refreshBeforeOpen = (): void => {
    if (disabled || refreshing) {
      return;
    }
    setOpen(false);
    setRefreshing(true);
    void onOpen().finally(() => {
      setRefreshing(false);
      if (!disabledRef.current) {
        setOpen(true);
      }
    });
  };

  const selectedSource = sources.find((source) => source.url === value) ?? sources[0];
  const pickerVisible = open && !disabled && !refreshing;

  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium text-gray-600" htmlFor="server-url">
        ローカル配信元
      </label>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={pickerVisible}
        disabled={disabled || refreshing}
        onClick={refreshBeforeOpen}
        className="rounded border border-gray-300 px-2 py-1 text-left text-sm"
      >
        {refreshing
          ? "稼働中の配信元を更新中…"
          : selectedSource
            ? formatServerSourceLabel(selectedSource, "distrokid-helper")
            : "配信元を選択"}
      </button>
      <select
        id="server-url"
        className="sr-only"
        value={value}
        disabled={disabled || refreshing}
        aria-hidden="true"
        tabIndex={-1}
        onChange={(event) => onChange(event.target.value)}
      >
        {sources.map((source) => (
          <option key={source.url} value={source.url}>
            {formatServerSourceLabel(source, "distrokid-helper")}
          </option>
        ))}
      </select>
      {pickerVisible && (
        <div role="listbox" aria-label="ローカル配信元" className="rounded border border-gray-300 bg-white p-1">
          {sources.map((source) => (
            <button
              key={source.url}
              type="button"
              role="option"
              aria-selected={source.url === value}
              disabled={disabled || refreshing}
              className="block w-full rounded px-2 py-1 text-left text-sm hover:bg-gray-100"
              onClick={() => {
                if (disabledRef.current || refreshing) {
                  return;
                }
                onChange(source.url);
                setOpen(false);
              }}
            >
              {formatServerSourceLabel(source, "distrokid-helper")}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
