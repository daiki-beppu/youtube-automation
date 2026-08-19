import { useEffect, useState } from "react"
import { AlertCircleIcon, AudioLinesIcon, Disc3Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"

type Track = {
  id: string
  file_name: string
  duration_seconds: number
  extension: string
  audio_url: string
}

type TrackResponse = {
  collection_name: string
  tracks: Track[]
}

function isTrackResponse(value: unknown): value is TrackResponse {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false
  }
  const response = value as Record<string, unknown>
  return (
    typeof response.collection_name === "string" &&
    Array.isArray(response.tracks) &&
    response.tracks.every(
      (track) =>
        typeof track === "object" &&
        track !== null &&
        typeof track.id === "string" &&
        typeof track.file_name === "string" &&
        typeof track.duration_seconds === "number" &&
        Number.isFinite(track.duration_seconds) &&
        typeof track.extension === "string" &&
        typeof track.audio_url === "string"
    )
  )
}

function formatDuration(seconds: number): string {
  const rounded = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(rounded / 60)
  return `${minutes}:${String(rounded % 60).padStart(2, "0")}`
}

export default function App() {
  const [data, setData] = useState<TrackResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void fetch("/api/tracks", {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload: unknown = await response.json()
        if (!isTrackResponse(payload)) throw new Error("invalid track response")
        setData(payload)
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "unknown error")
        }
      })
    return () => controller.abort()
  }, [])

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-8 px-4 py-8 sm:px-6 lg:py-12">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Disc3Icon aria-hidden="true" />
          <span>Local collection editor</span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Audio Studio
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          {data?.collection_name ?? "コレクションの音源を読み込んでいます"}
        </p>
      </header>

      {error ? (
        <Alert variant="destructive">
          <AlertCircleIcon aria-hidden="true" />
          <AlertTitle>トラックを読み込めませんでした</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!data && !error ? (
        <section className="grid gap-4" aria-label="トラックを読み込み中">
          {[0, 1, 2].map((item) => (
            <Skeleton key={item} className="h-40 w-full" />
          ))}
        </section>
      ) : null}

      {data?.tracks.length === 0 ? (
        <Card>
          <CardContent>
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <AudioLinesIcon aria-hidden="true" />
                </EmptyMedia>
                <EmptyTitle>トラックはまだありません</EmptyTitle>
                <EmptyDescription>
                  02-Individual-music
                  に音声ファイルを配置してから再起動してください。
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          </CardContent>
        </Card>
      ) : null}

      {data && data.tracks.length > 0 ? (
        <section
          className="grid gap-4"
          aria-label={`${data.tracks.length}件のトラック`}
        >
          {data.tracks.map((track, index) => (
            <Card key={track.id} className="min-w-0">
              <CardHeader>
                <CardTitle className="break-words">
                  {String(index + 1).padStart(2, "0")} · {track.file_name}
                </CardTitle>
                <CardDescription>
                  再生時間 {formatDuration(track.duration_seconds)}
                </CardDescription>
                <CardAction>
                  <Badge variant="secondary">
                    {track.extension.toUpperCase()}
                  </Badge>
                </CardAction>
              </CardHeader>
              <CardContent>
                <audio
                  className="w-full min-w-0"
                  controls
                  preload="metadata"
                  src={track.audio_url}
                  aria-label={`${track.file_name} を再生`}
                />
              </CardContent>
            </Card>
          ))}
        </section>
      ) : null}
    </main>
  )
}
