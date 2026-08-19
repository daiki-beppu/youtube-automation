import type { CleanupSettings } from "@/audio-settings"

type PreviewGraph = {
  context: AudioContext
  muddiness: BiquadFilterNode
  harshness: BiquadFilterNode
}

const previewGraphs = new WeakMap<HTMLAudioElement, PreviewGraph>()

export function applyEqPreview(
  audio: HTMLAudioElement | undefined,
  settings: Pick<CleanupSettings, "eq">
) {
  if (!audio || typeof AudioContext === "undefined") return
  let graph = previewGraphs.get(audio)
  if (!graph) {
    const context = new AudioContext()
    const source = context.createMediaElementSource(audio)
    const muddiness = context.createBiquadFilter()
    const harshness = context.createBiquadFilter()
    muddiness.type = "peaking"
    harshness.type = "peaking"
    source.connect(muddiness).connect(harshness).connect(context.destination)
    graph = { context, muddiness, harshness }
    previewGraphs.set(audio, graph)
  }
  void graph.context.resume()
  graph.muddiness.frequency.value = settings.eq.muddiness_freq_hz
  graph.muddiness.gain.value = settings.eq.enabled
    ? settings.eq.muddiness_gain_db
    : 0
  graph.harshness.frequency.value = settings.eq.harshness_freq_hz
  graph.harshness.gain.value = settings.eq.enabled
    ? settings.eq.harshness_gain_db
    : 0
}
