export interface ServerUrlFieldProps {
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onFetch: () => void;
}

// サーバー URL 入力 + データ取得ボタン。
export function ServerUrlField({
  value,
  disabled,
  onChange,
  onFetch,
}: ServerUrlFieldProps) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium text-gray-600" htmlFor="server-url">
        サーバー URL
      </label>
      <input
        id="server-url"
        type="url"
        className="rounded border border-gray-300 px-2 py-1 text-sm"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
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
