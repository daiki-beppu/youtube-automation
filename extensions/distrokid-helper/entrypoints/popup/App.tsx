import { Button, Select } from "@youtube-automation/ui";

import { ReleaseReview } from "@/components/ReleaseReview";
import { ServerUrlField } from "@/components/ServerUrlField";
import { StatusBanner } from "@/components/StatusBanner";
import { useDistrokidRunner } from "@/components/useDistrokidRunner";

// popup は表示とイベント接続に集中し、runner state と実行制御は useDistrokidRunner が
// 所有する（#1361、ADR-0016 の helper extension shell 構成）。
export function App() {
  const {
    serverUrl,
    setServerUrl,
    serverSources,
    refreshServerSources,
    payload,
    busy,
    isInjecting,
    phase,
    message,
    compatibilityWarning,
    collections,
    allReleased,
    selectedIndex,
    selectCollection,
    inject,
    stop,
  } = useDistrokidRunner();

  return (
    <main className="flex flex-col gap-3 p-4">
      <h1 className="text-base font-bold text-gray-900">DistroKid Helper</h1>

      <ServerUrlField
        value={serverUrl}
        sources={serverSources}
        disabled={isInjecting}
        onChange={setServerUrl}
        onOpen={refreshServerSources}
      />

      {compatibilityWarning && (
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {compatibilityWarning}
        </div>
      )}

      {/* dir mode: 未配信 disc 一覧のドロップダウン (#934)。suno-helper App.tsx 55-69 行の構造を踏襲。 */}
      {collections.length > 0 && (
        <label className="flex flex-col gap-1 text-sm">
          コレクション
          <Select
            value={selectedIndex}
            disabled={isInjecting}
            onChange={(e) => selectCollection(Number(e.target.value))}
          >
            {collections.map((item, idx) => (
              <option key={`${item.collection_id}/${item.disc}`} value={idx}>
                {`${item.name} / ${item.disc}（${item.album_title}・${item.track_count} 曲）`}
              </option>
            ))}
          </Select>
        </label>
      )}

      {/* dir mode で全 disc が配信済みの場合（#934）。suno-helper の allMapped パターンを踏襲。 */}
      {allReleased && (
        <p className="text-xs text-gray-600">未配信の disc はありません。</p>
      )}

      {payload !== null && <ReleaseReview payload={payload} />}

      <div className="flex gap-2">
        <Button
          type="button"
          className="flex-1"
          disabled={payload === null || busy}
          onClick={() => void inject()}
        >
          フォーム一括入力
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={!isInjecting}
          onClick={() => void stop()}
        >
          停止
        </Button>
      </div>

      <StatusBanner phase={phase} message={message} />
    </main>
  );
}
