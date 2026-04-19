# Low-Light and Night Playbook

Crypto and late-night content lives in low light. AI defaults to "noon
sunny" unless corrected; this playbook is for deliberately sending the
model into the dark.

---

## Why low-light is hard for AI

Default AI training is skewed toward well-lit stock photography. Without
intervention, asking for "night" produces:

- Over-lit "night" that's actually overcast
- Suspiciously clean shadow-detail
- No grain (daylight sensors pushed to look dark ≠ actual night)
- Magically-invisible noise
- Warm "streetlamp glow" that's too uniform

Counter all of this by naming specific LIGHT SOURCES (not
"ambient"), naming film stock suited for low light, and demanding
grain + fall-off.

---

## The essential low-light prompt structure

```
[subject and action],
[specific named practical lights visible in frame],
[film stock / sensor known for low light],
[explicit shadow behavior clause],
[grain / noise description],
[negative clause disallowing AI-smoothness]
```

Example:

> A trader at a kitchen counter at 3am,
> lit only by a laptop screen (cool cyan) + a single neon "OPEN" sign
> bleeding through the window (red),
> Cinestill 800T for tungsten halation,
> shadows fall off to near-black past 2 feet from the light sources,
> natural film grain, not digital noise,
> no uniform shadow detail, no glow spread beyond natural fall-off.

---

## Light sources that work in night prompts

**Name them specifically. Model matches.**

| Source | Color temp | Character |
|---|---|---|
| Sodium vapor street lamp | 2000K | Deep amber, grainy, wraps around fog |
| Mercury vapor | 4000K | Cyan-green, industrial, cold |
| Neon sign | Varies | Saturated, localized spill |
| LED streetlight (modern) | 5000K | Cold white, hard shadows |
| Phone screen | 6500K | Blue-cyan, small tight spill on face/hands |
| Monitor glow | 6500K | Same but bigger spill, often multiple screens |
| Tungsten practical (lamp, bulb) | 2700K | Warm orange, pleasant |
| TV cathode glow | Flickering | Blue-green, intermittent, flickery |
| Candle | 1800K | Deep amber, tight spill, flicker implied |
| Car headlight through window | 5500K | Cold white, moving, transient |
| Emergency / ambulance light | Red + blue | Chaotic, alternating, strobe |
| Moon (full, clear sky) | 4100K | Cool white-blue, soft, long shadow |

**Mixed sources = richer night.** "Sodium exterior + tungsten interior +
phone screen glow on face" tells the model exactly where to place color.

---

## Shadows — the single biggest AI tell

AI defaults to LIFTED shadows (always some detail). Real low light has
CRUSHED shadows (much of the frame is near-black).

Force crush with:

- "Shadow side falls off to near-black within 3 feet of the light"
- "No ambient fill. Shadows have no detail."
- "High-contrast lighting: subject illuminated, surroundings not."

Refer to `POSTPROCESS.crushed_shadows` for the fragment.

---

## Grain, noise, and low-light texture

Low light has texture. AI hides it. Demand it:

- **Film low-light**: "natural film grain from pushing Tri-X to 1600,
  coarse and organic"
- **Digital low-light**: "ISO 6400 digital noise, chroma noise in shadows"
- **Degraded video**: "VHS-tape low-light, chroma smear in shadows,
  tracking lines"

If the piece is supposed to feel REAL (documentary, candid) — grain is
the texture of honesty. If it's supposed to feel DREAMLIKE — use Super
8 or lo-fi VHS grain.

---

## Stocks that were made for low light

- **Cinestill 800T** — the lingua franca of crypto-cinematic. Red
  halation around any bright light source is distinctive.
- **Kodak Portra 800** — softer, warmer, pushes well.
- **Ilford Delta 3200** — B&W, massive grain, documentary / fear.
- **Fuji Natura 1600** — pastel-in-dark, unusual.
- **Kodak T-Max P3200** — harsh B&W, very pushed, news/reportage feel.

Default for "crypto late-night" = **Cinestill 800T**.

---

## Specific low-light scene recipes

### 1. "Operator at 3am"
```
a 30s hooded operator at a desk,
lit only by two monitors (cool cyan, left) + a warm desk lamp (tungsten, right),
Cinestill 800T, visible red halation around screen edges,
shadow side falls to near-black past the subject's shoulder,
natural grain, no uniform ambient fill,
rule of thirds subject on left, monitor glow on right of frame,
no plastic skin, no symmetric blur, no digital HDR feel.
```

### 2. "Subway platform"
```
an empty subway platform late night,
fluorescent overhead (cold cyan-green) with one tube flickering,
no ambient fill, reflected puddles on platform edge,
Tri-X 400 B&W pushed to 1600, heavy grain,
wide lockoff, platform vanishing to a point,
35mm f/1.4,
no CGI, no smoothing, grain visible.
```

### 3. "Parking garage"
```
underground parking garage, single concrete level, no cars,
lit only by sodium vapor tubes (amber) every 40 feet,
subject walking away from camera at mid-distance,
Cinestill 800T, halation around each tube,
deep shadow pools between lights,
50mm f/1.8,
no wide ambient glow, no detail in shadows,
natural breath visible if cold clause is added.
```

### 4. "Motel room"
```
a 2am motel room, seated subject on bed edge,
lit by a cathode TV (flickering blue-green) + a bedside lamp
(warm tungsten 2700K) on the opposite side,
Cinestill 800T,
40mm framing, subject silhouetted where the TV falls on their face,
heavy curtain pulled, sliver of exterior orange light at the edge,
deep shadows, no uniform ambient, grain forward,
no AI polish, keep natural tonal range.
```

### 5. "Rooftop, city, blue hour"
```
a founder on a city rooftop at blue hour,
sky ambient cobalt + warm practicals from windows in the surrounding
buildings (visible but small, thousands of amber dots),
Kodak Portra 800, filmic roll-off,
35mm f/1.4, rule of thirds, subject on left, skyline in negative space
on right, distant traffic,
subtle grain, crushed blacks,
no overdone neon wash, no cyberpunk styling.
```

---

## Common low-light failures & fixes

**"The 'night' looks like overcast day"**
→ Add: "no ambient fill, shadows fall to near-black within 3 feet of
the light source, only named practicals illuminate the scene."

**"Everything is too evenly lit"**
→ Specify a single key direction. "Lit ONLY by X from Y direction.
Other surfaces in shadow."

**"AI glow looks uniform and fake"**
→ Demand the natural inverse-square fall-off: "Light falls off
geometrically, 4x brighter near the source than 3 feet away."

**"Subject looks retouched / too clean"**
→ Cite grain: "visible Cinestill 800T grain, no digital smoothing,
natural skin texture preserved."

---

## Color temperature pairings that sing

| Mix | Emotional effect |
|---|---|
| Sodium amber exterior + cold monitor interior | Isolation, tech-vs-world |
| Firelight warm + blue moonlight | Ritual at the edge of wild |
| Neon red + fluorescent green | Unease, nightlife-as-nightmare |
| Tungsten warm + blue phone screen | Domestic solitude |
| Candlelight + distant streetlamp through window | Contemplation |
| Headlights sweeping + static tungsten | Motion in stillness |

---

## The low-light self-check

- Are specific LIGHT SOURCES named (not "ambient")?
- Is the film stock / sensor low-light-native?
- Is grain / noise explicitly demanded?
- Is shadow behavior specified (crushed, falls off, no ambient fill)?
- Are 2+ light sources at different color temps? (Mixed light = richer)
- Is there a negative clause disallowing AI-smoothness?
- Would you believe this is a real photograph of a real place at night?

If the piece looks like "cinematic night" and not "a specific photograph
taken at a specific hour" — add specificity.
