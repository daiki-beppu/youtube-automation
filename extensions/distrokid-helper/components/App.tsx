import {
  Alert,
  AlertDescription,
  Button,
  Empty,
  EmptyHeader,
  EmptyTitle,
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@youtube-automation/ui";

import { ReleaseReview } from "@/components/ReleaseReview";
import { ServerUrlField } from "@/components/ServerUrlField";
import { StatusBanner } from "@/components/StatusBanner";
import { useDistrokidRunner } from "@/components/useDistrokidRunner";

// overlay body は表示とイベント接続に集中し、runner state と実行制御は
// useDistrokidRunner が所有する（#1361、ADR-0016）。
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
    <main className="flex flex-col gap-3 bg-background p-4 text-foreground">
      <ServerUrlField
        value={serverUrl}
        sources={serverSources}
        disabled={isInjecting}
        onChange={setServerUrl}
        onOpen={refreshServerSources}
      />

      {compatibilityWarning && (
        <Alert variant="warning">
          <AlertDescription>{compatibilityWarning}</AlertDescription>
        </Alert>
      )}

      {/* dir mode: 未配信 disc 一覧のドロップダウン (#934)。suno-helper App.tsx 55-69 行の構造を踏襲。 */}
      {collections.length > 0 && (
        <div className="flex flex-col gap-1 text-sm">
          <span id="collection-select-label">コレクション</span>
          <Select
            value={String(selectedIndex)}
            items={collections.map((item, index) => ({
              value: String(index),
              label: `${item.name} / ${item.disc}（${item.album_title}・${item.track_count} 曲）`,
            }))}
            disabled={isInjecting}
            onValueChange={(value) => selectCollection(Number(value))}
          >
            <SelectTrigger
              data-selected-value={String(selectedIndex)}
              className="w-full"
              aria-labelledby="collection-select-label"
              data-distrokid-control="collection-select"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {collections.map((item, idx) => (
                  <SelectItem
                    key={`${item.collection_id}/${item.disc}`}
                    value={String(idx)}
                  >
                    {`${item.name} / ${item.disc}（${item.album_title}・${item.track_count} 曲）`}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      )}

      {/* dir mode で全 disc が配信済みの場合（#934）。suno-helper の allMapped パターンを踏襲。 */}
      {allReleased && (
        <Empty className="p-4">
          <EmptyHeader>
            <EmptyTitle className="text-sm">
              未配信の disc はありません。
            </EmptyTitle>
          </EmptyHeader>
        </Empty>
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
