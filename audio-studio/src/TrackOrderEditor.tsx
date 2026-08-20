import { useEffect, useRef, useState } from "react"
import {
  GripVerticalIcon,
  LockKeyholeIcon,
  SaveIcon,
  ShuffleIcon,
  SlidersHorizontalIcon,
} from "lucide-react"

import {
  isOrderResponse,
  type OrderResponse,
  type Track,
} from "@/audio-settings"
import { CleanupPanel } from "@/CleanupPanel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"

function formatDuration(seconds: number): string {
  const rounded = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(rounded / 60)
  return `${minutes}:${String(rounded % 60).padStart(2, "0")}`
}

function seededRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state += 0x6d2b79f5
    let value = state
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

function shuffleTracks(tracks: Track[], seed: number): Track[] {
  const result = [...tracks]
  const random = seededRandom(seed)
  for (let index = result.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1))
    ;[result[index], result[target]] = [result[target], result[index]]
  }
  return result
}

function pinsFirst(tracks: Track[], pins: string[]): Track[] {
  const pinned = new Set(pins)
  return [
    ...pins.flatMap((name) =>
      tracks.filter((track) => track.file_name === name)
    ),
    ...tracks.filter((track) => !pinned.has(track.file_name)),
  ]
}

export function TrackOrderEditor({
  initialTracks,
}: {
  initialTracks: Track[]
}) {
  const [tracks, setTracks] = useState(initialTracks)
  const [pins, setPins] = useState<string[]>([])
  const [seed, setSeed] = useState<number | null>(null)
  const [seedInput, setSeedInput] = useState("")
  const [status, setStatus] = useState("曲順を読み込んでいます")
  const [selectedTrack, setSelectedTrack] = useState<Track | null>(null)
  const [selectedAudio, setSelectedAudio] = useState<HTMLAudioElement>()
  const audioElements = useRef(new Map<string, HTMLAudioElement>())
  const draggedId = useRef<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void fetch("/api/order", {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload: unknown = await response.json()
        if (!isOrderResponse(payload)) throw new Error("invalid order response")
        const byName = new Map(
          initialTracks.map((track) => [track.file_name, track])
        )
        if (payload.order.length !== initialTracks.length)
          throw new Error("order length mismatch")
        const ordered = payload.order.map((name) => byName.get(name))
        if (ordered.some((track) => track === undefined))
          throw new Error("order filename mismatch")
        setTracks(ordered as Track[])
        setPins(payload.pin_first)
        setSeed(payload.shuffle_seed)
        setSeedInput(
          payload.shuffle_seed === null ? "" : String(payload.shuffle_seed)
        )
        setStatus(payload.saved ? "保存済みの曲順です" : "ファイル名順です")
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setStatus(
            `曲順を読み込めませんでした: ${reason instanceof Error ? reason.message : "unknown error"}`
          )
        }
      })
    return () => controller.abort()
  }, [initialTracks])

  function updatePins(filename: string, checked: boolean) {
    const nextPins = checked
      ? [...pins, filename]
      : pins.filter((name) => name !== filename)
    setPins(nextPins)
    setTracks((current) => pinsFirst(current, nextPins))
    setSeed(null)
    setStatus("未保存の変更があります")
  }

  function applyShuffle() {
    const entered = seedInput === "" ? null : Number(seedInput)
    const nextSeed =
      entered !== null &&
      Number.isSafeInteger(entered) &&
      entered >= 0 &&
      entered <= 4294967295
        ? entered
        : crypto.getRandomValues(new Uint32Array(1))[0]
    const pinned = new Set(pins)
    const fixed = pinsFirst(initialTracks, pins).filter((track) =>
      pinned.has(track.file_name)
    )
    const remaining = initialTracks.filter(
      (track) => !pinned.has(track.file_name)
    )
    setTracks([...fixed, ...shuffleTracks(remaining, nextSeed)])
    setSeed(nextSeed)
    setSeedInput(String(nextSeed))
    setStatus("未保存のシャッフル順です")
  }

  function moveTrack(targetId: string) {
    const sourceId = draggedId.current
    if (!sourceId || sourceId === targetId) return
    draggedId.current = null
    setTracks((current) => {
      const sourceIndex = current.findIndex((track) => track.id === sourceId)
      const targetIndex = current.findIndex((track) => track.id === targetId)
      const next = [...current]
      const [moved] = next.splice(sourceIndex, 1)
      next.splice(targetIndex, 0, moved)
      return pinsFirst(next, pins)
    })
    setSeed(null)
    setSeedInput("")
    setStatus("未保存の手動順です")
  }

  async function saveOrder() {
    setStatus("保存しています")
    try {
      const response = await fetch("/api/order", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          order: tracks.map((track) => track.file_name),
          shuffle_seed: seed,
          pin_first: pins,
        }),
      })
      const payload: unknown = await response.json()
      if (!response.ok) {
        const message =
          typeof payload === "object" && payload !== null && "error" in payload
            ? String(payload.error)
            : `HTTP ${response.status}`
        throw new Error(message)
      }
      if (!isOrderResponse(payload)) throw new Error("invalid order response")
      const saved = payload as OrderResponse
      setSeed(saved.shuffle_seed)
      setPins(saved.pin_first)
      setStatus("曲順を保存しました")
    } catch (reason) {
      setStatus(
        `保存できませんでした: ${reason instanceof Error ? reason.message : "unknown error"}`
      )
    }
  }

  return (
    <section className="grid gap-4" aria-label={`${tracks.length}件のトラック`}>
      <Card>
        <CardHeader>
          <CardTitle>Master の曲順</CardTitle>
          <CardDescription>
            ドラッグで並べ替えるか、seed を指定してシャッフルします。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="grid flex-1 gap-2">
            <Label htmlFor="shuffle-seed">Shuffle seed</Label>
            <Input
              id="shuffle-seed"
              type="number"
              step="1"
              min="0"
              max="4294967295"
              placeholder="空欄なら自動生成"
              value={seedInput}
              onChange={(event) => setSeedInput(event.target.value)}
            />
          </div>
          <Button type="button" variant="outline" onClick={applyShuffle}>
            <ShuffleIcon aria-hidden="true" />
            シャッフル
          </Button>
          <Button type="button" onClick={() => void saveOrder()}>
            <SaveIcon aria-hidden="true" />
            曲順を保存
          </Button>
        </CardContent>
        <CardContent>
          <p className="text-sm text-muted-foreground" role="status">
            {status}
          </p>
        </CardContent>
      </Card>

      {tracks.map((track, index) => (
        <Card
          key={track.id}
          className="min-w-0"
          onDragOver={(event) => event.preventDefault()}
          onDrop={() => moveTrack(track.id)}
          onPointerEnter={() => moveTrack(track.id)}
          onPointerUp={() => {
            draggedId.current = null
          }}
        >
          <CardHeader className="flex flex-col gap-3 sm:flex-row sm:justify-between">
            <div className="flex min-w-0 items-start gap-2">
              <button
                type="button"
                draggable
                className="mt-0.5 shrink-0 cursor-grab rounded p-1 text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={`${track.file_name} をドラッグして並べ替え`}
                onPointerDown={() => {
                  draggedId.current = track.id
                }}
                onDragStart={() => {
                  draggedId.current = track.id
                }}
                onDragEnd={() => {
                  draggedId.current = null
                }}
              >
                <GripVerticalIcon aria-hidden="true" />
              </button>
              <div className="min-w-0">
                <CardTitle className="break-words">
                  {String(index + 1).padStart(2, "0")} · {track.file_name}
                </CardTitle>
                <CardDescription>
                  再生時間 {formatDuration(track.duration_seconds)}
                </CardDescription>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
              <Label htmlFor={`pin-${track.id}`} className="gap-2 text-xs">
                <LockKeyholeIcon aria-hidden="true" />
                <span className="sr-only">{track.file_name} を</span>先頭固定
              </Label>
              <Switch
                id={`pin-${track.id}`}
                size="sm"
                checked={pins.includes(track.file_name)}
                onCheckedChange={(checked) =>
                  updatePins(track.file_name, checked)
                }
              />
              <Badge variant="secondary">{track.extension.toUpperCase()}</Badge>
              <Button
                type="button"
                size="sm"
                variant={selectedTrack?.id === track.id ? "default" : "outline"}
                aria-expanded={selectedTrack?.id === track.id}
                onClick={() => {
                  setSelectedTrack(track)
                  setSelectedAudio(audioElements.current.get(track.id))
                }}
              >
                <SlidersHorizontalIcon aria-hidden="true" />
                調整
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <audio
              className="w-full min-w-0"
              controls
              preload="metadata"
              src={track.audio_url}
              aria-label={`${track.file_name} を再生`}
              ref={(element) => {
                if (element) audioElements.current.set(track.id, element)
                else audioElements.current.delete(track.id)
              }}
            />
          </CardContent>
        </Card>
      ))}

      {selectedTrack ? (
        <CleanupPanel
          key={selectedTrack.id}
          track={selectedTrack}
          audio={selectedAudio}
        />
      ) : null}
    </section>
  )
}
