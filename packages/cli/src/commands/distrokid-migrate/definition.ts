export const distrokidMigrateCommandArgs = {
  apply: {
    default: false,
    description: "distrokid.json を更新する",
    type: "boolean",
  },
  backup: {
    default: true,
    description: "--apply 時に distrokid.json.bak を作成する",
    type: "boolean",
  },
  json: {
    default: false,
    description: "JSON で出力する",
    type: "boolean",
  },
  target: {
    description: "対象チャンネルディレクトリ",
    type: "string",
  },
} as const;

export const distrokidMigrateCommandMeta = {
  description: "DistroKid profile config を新 schema へ移行する",
  name: "distrokid-migrate",
} as const;
