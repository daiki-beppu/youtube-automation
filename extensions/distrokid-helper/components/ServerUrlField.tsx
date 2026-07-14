import { formatServerSourceLabel, type LocalServerSource } from "../../shared/constants";

export interface ServerUrlFieldProps {
  value: string;
  sources: LocalServerSource[];
  disabled: boolean;
  onChange: (value: string) => void;
  onFetch: () => void;
}

// ローカル配信元 selector + データ取得ボタン。
export function ServerUrlField({ value, sources, disabled, onChange, onFetch }: ServerUrlFieldProps) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium text-gray-600" htmlFor="server-url">
        ローカル配信元
      </label>
      <select
        id="server-url"
        className="rounded border border-gray-300 px-2 py-1 text-sm"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        {sources.map((source) => (
          <option key={source.url} value={source.url}>
            {formatServerSourceLabel(source, "distrokid-helper")}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        disabled={disabled}
        onClick={onFetch}
      >
        データ取得
      </button>
    </div>
  );
}
