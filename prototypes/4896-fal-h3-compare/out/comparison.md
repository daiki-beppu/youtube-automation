# fal.ai H3 Max / Turbo vs Veo Fast 実測比較（#4896）

- 生成日時: 2026-09-04T06:59:02+00:00
- プロンプト（Veo と同一）: `Locked cinematic Afro House cover-art scene. Subtle gold light flicker, slow haze in a dark club or desert-night atmosphere, no rain, no cafe, no jazz bar, no new objects. Preserve composition and text readability.`
- 条件: 8 秒 / 768P / seed=4896 / first = last 同一画像 / 後処理は strip_audio → 1920×1080 lanczos → trim 1.0s + xfade 0.5s（CRF 18 slow）
- 単価は通常価格（Turbo 0.04 / Max 0.08 USD/s）。9/7 まで 75% off のためプロモ値を併記

| 候補 | mode | 入力 | submit→file (s) | inference (s) | 生出力 実寸/fps | 音声 | 生 size (MB) | 生 bitrate (Mbps) | final size (MB) | USD 通常 / プロモ | 状態 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Veo Fast 1080p（承認済み） | — | original | —（typ. 60〜120） | — | 1920×1080 @ 24/1 | あり (aac) | 7.6 | 7.6 | 4.0 | 0.80 / — | baseline |
| turbo-balanced | balanced | original | 14.04 | 3.5584127879992593 | 1344×768 @ 24/1 | あり (aac 32000Hz 2ch) | 11.3 | 11.3 | 6.9 | 0.32 / 0.08 | ok |
| turbo-quality | quality | original | 34.26 | 3.2259232790675014 | 1344×768 @ 24/1 | あり (aac 32000Hz 2ch) | 10.9 | 10.9 | 7.4 | 0.32 / 0.08 | ok |
| max-balanced | balanced | original | 22.49 | 5.725056977011263 | 1344×768 @ 24/1 | あり (aac 32000Hz 2ch) | 10.2 | 10.2 | 6.4 | 0.64 / 0.16 | ok |
| max-quality | quality | original | 53.84 | 5.605323424999369 | 1344×768 @ 24/1 | あり (aac 32000Hz 2ch) | 11.3 | 11.3 | 6.7 | 0.64 / 0.16 | ok |
| turbo-balanced-resized | balanced | resized | 12.26 | 3.5539538109951536 | 1344×768 @ 24/1 | あり (aac 32000Hz 2ch) | 11.2 | 11.2 | 6.7 | 0.32 / 0.08 | ok |

## expanded_prompt と静止指示の残存

### turbo-balanced

- 残存語: static

```
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] Cinematic, live-action shot. The scene opens with <Picture 1>, featuring a distinguished older Black man (S1) with a short, well-groomed white beard and hair, wearing a high-collared black garment with gold embroidery along the neckline. He stands behind a professional DJ mixer, his right hand resting firmly on the knobs and faders. The background is a vast, dark desert night atmosphere under a black sky, where a massive, dimly lit crowd stretches toward jagged mountain silhouettes. To the right, a powerful golden spotlight beams down from the upper corner, illuminating floating dust particles and a subtle haze. The camera remains in a Static Shot, maintaining the composition of the cover art. As the shot progresses, a subtle golden light flicker pulses across S1's face and the metallic surfaces of the DJ equipment, synchronized with a rhythmic beat. A slow, ethereal haze drifts lazily across the mid-ground, softening the distant lights of the desert festival. S1 remains stoic, staring intensely into the lens with a steady gaze, his expression unwavering. The atmospheric lighting shifts slightly in intensity, creating a breathing effect of gold and shadow. By the end of the 8-second duration, the subtle movements of the haze and the light pulses converge back to the exact composition and state of <Picture 2>.

overall_soundscape: A deep, thumping kick drum of Afro House music vibrates through the air, accompanied by the distant, muffled roar of a massive crowd. There are subtle, high-frequency metallic clicks and the tactile sound of a DJ's hand shifting a fader on a mixer.

non_diegetic_music: A polished Afro House track featuring a heavy, rhythmic 4/4 bass drum, melodic synth stabs, and percussive shakers, maintaining a steady, mid-tempo dance energy throughout the duration.
```

### turbo-quality

- 残存語: static

```
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] This is a live-action, cinematic shot. An older Black man with a silver-white beard and cropped hair, dressed in a dark, textured tunic with gold-threaded trim, stands behind a professional DJ console in a sprawling desert-night venue. The scene is enveloped in a low-hanging, atmospheric haze, illuminated by flickering, warm golden stage lights. The camera holds a static, focused position on the DJ. In the first seconds, the man subtly adjusts a fader on the console, his fingers moving with precise, practiced rhythm against the knobs. As he works, his expression remains cool and composed, his gaze fixed directly into the lens. The background reveals a vast, dark desert landscape silhouette under a night sky, with a distant, bright golden spotlight beam cutting diagonally across the frame. Midway through, the subtle golden light in the background pulses, creating a soft, rhythmic flickering effect that enhances the depth of the haze. He continues to gently manipulate the deck controls, his hand sliding across the surface as the ambient glow subtly shifts intensity around him. Toward the end of the clip, he maintains his steady, confident posture, his hand lingering on the mixer as the scene settles into a vibrant, pulsing rhythm of light and shadow, landing perfectly on his stoic, commanding presence.

overall_soundscape: A low, bass-heavy ambient hum resonates in the foreground, establishing the deep, rhythmic essence of an Afro House club setting. This deep rumble is punctuated by the sharp, metallic click of mixer knobs and the rhythmic sliding of the fader as he manipulates the console. Faint, distant echoes of an excited crowd murmur in the background, creating a sense of space that stretches out into the desert air. As the light flickers, a subtle, rhythmic "thump" of a kick drum begins to swell, growing more pronounced. The sound of a soft, airy hiss from the stage haze machines adds texture to the environment, blending with the steady, pulsing electronic beat that builds in intensity as the clip nears its conclusion.

non_diegetic_music: A deep, hypnotic Afro House track with a steady, bass-driven rhythm begins at low volume and gradually swells in clarity, anchored by a prominent, rhythmic bassline and subtle, shimmering percussion.
```

### max-balanced

- 残存語: static

```
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] Cinematic, Static Shot anchored to <Picture 1>. A distinguished mature Black DJ with trimmed white hair and beard stands composed behind a dual-deck DJ controller in an expansive desert night festival setting. Warm, directional golden light illuminates his features, casting subtle flickering highlights across his dark embroidered tunic. Thin layers of atmospheric haze and fine golden dust drift slowly through the background spotlight beam and over the silhouettes of the distant crowd and rugged hills. The DJ maintains steady, focused eye contact toward the camera with minimal micro-movements, his fingers lightly resting on the mixer knobs as lighting levels gently pulse. The atmospheric haze continuously shifts before settling into the precise composition of <Picture 2>.

overall_soundscape: A low, resonant desert night breeze blends with the muted, distant roar of a festival crowd and subtle tactile clicks from DJ controller faders.

non_diegetic_music: A deep, rolling Afro House sub-bassline pulses steadily under restrained percussion and hypnotic wooden shaker rhythms.
```

### max-quality

- 残存語: locked, static, still

```
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] This is a live-action, cinematic shot. In the foreground, an older man with a stark white beard and hair, dressed in a black high-collared jacket with gold embroidery, stands attentively at a large DJ mixing deck. The background reveals a dark desert-night festival atmosphere, densely packed with a distant crowd and lit by warm gold practical lights and a prominent diagonal beam on the right. The camera holds a static shot throughout the clip to preserve a locked, cover-art composition. Early on, a slow, atmospheric haze drifts across the dark sky, while the gold light beam on the right flickers subtly. Deep, rhythmic Afro House music is already playing from t=0 through the unseen stage speakers. Approaching the middle of the clip, the DJ's right hand, which rests on the mixer, makes a minor, deliberate adjustment, his fingers rolling slightly over a knob. His intense, serious gaze remains locked forward without breaking focus. Later, the warm gold lights illuminating the distant crowd pulse gently in time with the music, and the haze continues to swirl slowly in the midground. By the end of the clip, the DJ's hand relaxes back into its exact starting position on the deck, perfectly matching the final frame's still composition.

overall_soundscape: A low, continuous rumble of desert wind and ambient atmosphere establishes the dark outdoor setting. This is immediately anchored by the heavy, rhythmic thud of the Afro House bassline dominating the foreground. As the DJ moves his hand, a faint, tactile click of a plastic knob is distinctly heard over the music. The track continues to drive forward, accompanied by the subtle, muffled roar of the distant crowd swaying to the beat, which transitions into a steady, hypnotic groove that carries through to the end of the clip.

non_diegetic_music: N/A
```

### turbo-balanced-resized

- 残存語: static

```
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] This is a cinematic, live-action shot. The scene opens on <Picture 1>, featuring a dignified older man (S1) with a short, well-groomed white beard and hair, wearing a high-collared black jacket with intricate gold embroidery along the placket. He is positioned in a medium close-up, his right hand resting firmly on a professional DJ mixer with various knobs and faders, and two platters visible on either side. The setting is a dark, vast outdoor environment at night, with a massive, dimly lit crowd filling the mid-ground and jagged desert mountains silhouetted against a black sky in the background. To the right, a powerful golden spotlight cuts through the air from a high angle, casting a sharp beam of light. Throughout the shot, the camera remains in a Static Shot, preserving the exact composition of the cover art. Subtle, rhythmic flickers of gold light pulse across S1's face and the metallic surfaces of the DJ equipment, synchronized with an unheard beat. A thin, translucent layer of golden haze drifts slowly across the frame from left to right, adding depth and atmospheric texture to the dark void. S1 maintains a steady, intense gaze toward the camera, his expression stoic and focused, with no lip movement or speech. The lighting remains high-contrast, with deep blacks and rich golden highlights. The visual state evolves gradually, maintaining absolute consistency in subject and environment, eventually converging on the identical composition and lighting seen in <Picture 2> by the end of the 8-second duration.

overall_soundscape: A deep, resonant atmospheric drone of a large outdoor crowd, characterized by a low-frequency murmur and distant cheering. The physical sound of a finger subtly adjusting a metallic knob on the mixer is audible, paired with the faint, electrical hum of high-powered stage lighting.

non_diegetic_music: A sophisticated Afro House track featuring a steady, driving 4/4 kick drum, syncopated wooden percussion, and a deep, melodic synth bassline that pulses rhythmically.
```

## 目視評価（ユーザー記入）

`compare.html` を開き、継ぎ目・静止対象の逸脱・画質の 3 観点で Veo と「同等以上 / 劣る」を候補ごとに記録する。

| 候補 | 継ぎ目 | 静止対象の逸脱 | 画質 | 総合 |
|---|---|---|---|---|
| turbo-balanced |  |  |  |  |
| turbo-quality |  |  |  |  |
| max-balanced |  |  |  |  |
| max-quality |  |  |  |  |
| turbo-balanced-resized |  |  |  |  |

## request 保持・CDN 寿命

`recheck` の結果は `retention.jsonl` を参照。

## 客観指標（metrics.py）

- seam: 2 周連結した動画の継ぎ目での隣接フレーム差（Y 平均）。median / p95 は継ぎ目以外の同指標。継ぎ目が p95 以下なら継ぎ目は動き幅の内側
- drift SSIM min: 先頭フレームに対する各フレームの SSIM の最小値（低いほど静止対象が逸脱）。argmin はその時刻
- first vs input: 先頭フレームと main.png（1080p 化）の SSIM。first = 入力 の忠実度

| 候補 | seam | median | p95 | drift SSIM min (at s) | drift SSIM mean | first vs input SSIM |
|---|---|---|---|---|---|---|
| veo-fast-1080p | 0.67 | 1.01 | 1.58 | 0.930 (3.58) | 0.951 | 0.893 |
| turbo-balanced | 1.50 | 2.11 | 3.71 | 0.798 (3.67) | 0.885 | 0.806 |
| turbo-quality | 1.52 | 3.31 | 5.92 | 0.644 (3.46) | 0.810 | 0.809 |
| max-balanced | 1.10 | 2.35 | 4.28 | 0.798 (3.29) | 0.887 | 0.812 |
| max-quality | 0.92 | 1.92 | 2.99 | 0.775 (3.83) | 0.855 | 0.808 |
| turbo-balanced-resized | 1.02 | 1.73 | 2.98 | 0.829 (2.71) | 0.887 | 0.814 |
