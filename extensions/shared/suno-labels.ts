// Suno UI のロケール依存ラベルの SSOT。
// 2026-10 の Suno 改装で UI が日本語化され、aria-label / placeholder / ボタン文言まで翻訳されるようになった。
// 英語 UI と日本語 UI のどちらでも動くよう、ラベルを言語ごとに並べてセレクタ / 照合関数を組み立てる。
// 構造（.clip-row / .multi-select-button / role / data-testid）はロケール非依存なので、
// ここに置くのはロケールで変わる文字列だけにする。
//
// ここが提供するのは完全一致セレクタ（attributeEqualsSelector）と照合関数だけ。
// 部分一致で拾うラベル（Exclude / 奇抜さ / 長さ 等）は要素・属性・一致の強さの組み合わせが
// セレクタごとに異なるため、セレクタ文字列のまま dom.ts の SELECTORS に置く（同所がセレクタの SSOT）。
//
// 値の正本は Suno が配信する翻訳リソース `https://suno.com/locales/{en,ja}/<namespace>.json`。
// 壊れたら chrome-devtools-mcp で同じキーを en / ja 両方から引き直す（キー名を各行に併記する）。

/** Suno UI のラベル。各配列は英語（旧表記を含む）→ 日本語の順で、照合はいずれか一致で成立する。 */
export const SUNO_LABELS = {
  // common:actions.remix（旧英語ラベル "Remix clip" も併記して旧 UI を拾う）
  remixClip: ["Remix clip", "Remix", "リミックス"],
  // common:actions.selectClip / deselectClip
  selectClip: ["Select clip", "クリップを選択"],
  deselectClip: ["Deselect clip", "クリップの選択を解除"],
  // songsAndPlaylists:clipBrowserElements.editTitle
  editTitle: ["Edit title", "タイトルを編集"],
  // songsAndPlaylists:playlist.addToPlaylistTitle（大文字小文字は版で揺れるため照合は case-insensitive）
  playlistDialogHeading: ["Add to playlist", "プレイリストに追加"],
  // songsAndPlaylists:playlist.namePlaceholder
  playlistNamePlaceholder: ["Playlist name", "プレイリスト名"],
  // songsAndPlaylists:playlist.createPlaylist
  createPlaylistButton: ["Create playlist", "プレイリストを作成"],
  // create:createForm.advancedOptionsCardMale / Female
  vocalMale: ["Male", "男性"],
  vocalFemale: ["Female", "女性"],
  // create:createForm.advancedOptionsCardCustom
  durationCustom: ["Custom", "カスタム"],
  // create:createForm.generationInProgress（queue 上限 toast の見出し）
  generationInProgress: ["Generation in progress", "生成中"],
} as const satisfies Record<string, readonly string[]>;

/** clip 再生ボタンの aria-label（songsAndPlaylists:clipBrowserElements.playClipTitle、英語 "Play <曲名>" / 日本語 "<曲名>を再生"）。 */
const PLAY_LABEL_PREFIX = "Play ";
const PLAY_LABEL_SUFFIX = "を再生";

/**
 * `<prefix>[<attribute>="<label>"]` をラベルごとに並べたセレクタリストを返す。
 * prefix はカンマの各項目へ付け直す（`.a > b[x="1"], .a > b[x="2"]`）。
 * ignoreCase で CSS の `i` flag を付ける（英語ラベルの大文字小文字揺れ対策）。
 */
export function attributeEqualsSelector(
  prefix: string,
  attribute: string,
  labels: readonly string[],
  { ignoreCase = false }: { ignoreCase?: boolean } = {}
): string {
  const flag = ignoreCase ? " i" : "";
  return labels
    .map((label) => `${prefix}[${attribute}="${label}"${flag}]`)
    .join(", ");
}

/** 前後空白を除いた text がいずれかのラベルと一致するか（大文字小文字を区別しない）。 */
export function matchesLabel(
  text: string | null | undefined,
  labels: readonly string[]
): boolean {
  const normalized = (text ?? "").trim().toLowerCase();
  return labels.some((label) => label.toLowerCase() === normalized);
}

/** text がいずれかのラベルを部分文字列として含むか（大文字小文字を区別しない）。 */
export function includesLabel(
  text: string | null | undefined,
  labels: readonly string[]
): boolean {
  const normalized = (text ?? "").toLowerCase();
  return labels.some((label) => normalized.includes(label.toLowerCase()));
}

/** 再生ボタンの aria-label から曲名を取り出す。どちらの書式にも合わなければ null。 */
export function titleFromPlayLabel(label: string | null): string | null {
  if (!label) {
    return null;
  }
  let title: string | null = null;
  if (label.startsWith(PLAY_LABEL_PREFIX)) {
    title = label.slice(PLAY_LABEL_PREFIX.length);
  } else if (label.endsWith(PLAY_LABEL_SUFFIX)) {
    title = label.slice(0, -PLAY_LABEL_SUFFIX.length);
  }
  return title?.trim() || null;
}

/** 再生ボタン（`[role="button"]`）のセレクタ。英語は前方一致、日本語は後方一致。 */
export const PLAY_BUTTON_SELECTOR = `[role="button"][aria-label^="${PLAY_LABEL_PREFIX}"], [role="button"][aria-label$="${PLAY_LABEL_SUFFIX}"]`;
