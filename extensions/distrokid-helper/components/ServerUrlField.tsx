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

function withDistrokidSourceLabel(
  source: ServerSourceFieldProps["sources"][number]
): ServerSourceFieldProps["sources"][number] {
  const mode = source.capabilities?.distrokid.mode;
  if (mode === undefined) return source;
  const detail =
    mode === "dir" && source.collectionsRoot
      ? `${mode}/${source.collectionsRoot}`
      : mode;
  return { ...source, label: `${source.label} [${detail}]` };
}

export function ServerUrlField({
  value,
  sources,
  disabled,
  onChange,
  onOpen,
}: ServerUrlFieldProps) {
  const labeledSources = sources.map(withDistrokidSourceLabel);
  return (
    <ServerSourceField
      id="server-url"
      value={value}
      sources={labeledSources}
      disabled={disabled}
      helper="distrokid-helper"
      onValueChange={onChange}
      onRefresh={onOpen}
    />
  );
}
