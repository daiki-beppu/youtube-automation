import { formatServerSourceLabel, type LocalServerSource } from "../../shared/constants";
import { Select } from "@/components/ui/select";

export interface ServerUrlFieldProps {
  value: string;
  sources: LocalServerSource[];
  disabled: boolean;
  onChange: (value: string) => void;
}

// 登録済みローカル配信元 selector。選択変更は runner の自動取得へ接続する。
export function ServerUrlField({ value, sources, disabled, onChange }: ServerUrlFieldProps) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium text-gray-600" htmlFor="server-url">
        ローカル配信元
      </label>
      <Select id="server-url" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {sources.map((source) => (
          <option key={source.url} value={source.url}>
            {formatServerSourceLabel(source, "distrokid-helper")}
          </option>
        ))}
      </Select>
    </div>
  );
}
