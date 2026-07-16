import type { ReleasePayload } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface ReleaseReviewProps {
  payload: ReleasePayload;
}

// 取得した release.json の内容（プロファイル + 動的データ）をレビュー表示する。
export function ReleaseReview({ payload }: ReleaseReviewProps) {
  const { profile, release } = payload;
  return (
    <Card className="gap-2 py-3 text-sm">
      <CardHeader className="px-3">
        <CardTitle>{release.album_title}</CardTitle>
      </CardHeader>
      <CardContent className="px-3">
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
      </CardContent>
    </Card>
  );
}
