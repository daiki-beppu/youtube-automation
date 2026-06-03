import type { ReleasePayload } from "@/lib/types";

export interface ReleaseReviewProps {
  payload: ReleasePayload;
}

// 取得した release.json の内容（プロファイル + 動的データ）をレビュー表示する。
export function ReleaseReview({ payload }: ReleaseReviewProps) {
  const { profile, release } = payload;
  return (
    <div className="flex flex-col gap-2 rounded border border-gray-200 p-3 text-sm">
      <div className="font-semibold text-gray-800">{release.album_title}</div>
      <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs text-gray-600">
        <dt>言語</dt>
        <dd className="text-gray-900">{profile.language}</dd>
        <dt>ジャンル</dt>
        <dd className="text-gray-900">{profile.main_genre}</dd>
        <dt>リリース日</dt>
        <dd className="text-gray-900">{release.release_date ?? "未定"}</dd>
        <dt>曲数</dt>
        <dd className="text-gray-900">{release.tracks.length}</dd>
        <dt>ジャケット</dt>
        <dd className="text-gray-900">{release.cover?.filename ?? "なし"}</dd>
      </dl>
    </div>
  );
}
