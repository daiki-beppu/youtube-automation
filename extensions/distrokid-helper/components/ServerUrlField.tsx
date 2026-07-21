import {
  ServerSourceField,
  type ServerSourceFieldProps,
} from "@youtube-automation/ui";

export type ServerUrlFieldProps = Pick<
  ServerSourceFieldProps,
  "value" | "sources" | "disabled"
> & {
  onChange: (value: string) => void;
  onOpen: () => Promise<void>;
};

export function ServerUrlField({
  value,
  sources,
  disabled,
  onChange,
  onOpen,
}: ServerUrlFieldProps) {
  return (
    <ServerSourceField
      id="server-url"
      value={value}
      sources={sources}
      disabled={disabled}
      helper="distrokid-helper"
      onValueChange={onChange}
      onRefresh={onOpen}
    />
  );
}
