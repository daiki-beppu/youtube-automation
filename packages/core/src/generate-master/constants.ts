export const GENERATE_MASTER_REGISTRY_KEY = "masterup.generate-master";

export const MASTERUP_CONFIG_DIR = "config/skills";
export const MASTERUP_JSON_FILENAME = "masterup.json";
export const MASTERUP_YAML_FILENAME = "masterup.yaml";
export const AUDIO_SECTION_KEY = "audio";

export const MUSIC_DIRNAME = "02-Individual-music";
export const MASTER_DIRNAME = "01-master";
export const MASTER_FILENAME = "master.mp3";

export const SUPPORTED_AUDIO_EXTENSIONS = [".mp3", ".m4a", ".wav"] as const;
export const OUTPUT_CODEC_ARGS = ["-c:a", "libmp3lame"] as const;
export const AUTO_SEED_BOUND = 2 ** 32;
