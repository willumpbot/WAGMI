# Color Grading by Mood Playbook

Color does 70% of the emotional work in any piece. Named palettes lock
the model onto specific color logic; vague adjectives ("cinematic
colors", "vibrant", "muted") don't.

This playbook maps operator-intended moods to the color language that
carries them.

---

## The emotional color atlas

| Mood | Palette | Why it works |
|---|---|---|
| Quiet dread | **Cold monochrome blue** + single warm practical | The isolation comes from a color system that doesn't forgive. One warm light in a cold frame feels like "the only thing alive". |
| Smug resignation | **Faded Kodak** / warm slightly-yellowed | Looks like a memory already fading. Nothing aspires. |
| Cope | **Sodium amber + cyan highlights** | The amber is "warmth-coded" but sickly. Cyan highlights = fluorescent reality intruding. |
| Absurd calm | **Neutral documentary palette** | No grading. The absurdity reads louder against normal-looking color. |
| Unhinged joy | **Crushed blacks + blown highlights** | Emotional intensity encoded as tonal intensity. |
| Defeat | **Bleached pastel** | The color has been drained out. |
| Reverent | **Deep emerald** OR warm tungsten gold | Stained-glass / candlelight logic. Light = sacred. |
| Dread / threat | **Monochrome blue** + almost-black | Removes reassurance. |
| Contempt | **Teal / orange filmic** | Hollywood-default but weaponized: subject warm, world cold. |
| Nostalgia | **Kodachrome / Ektachrome** | Slide-film saturation = "recorded memory". |
| Hero | **Golden hour warm** + long rim light | Light = triumph. |

---

## How to name a palette in a prompt

Name it like a colorist would, not like a stock-photo tag:

**Weak:**
- "cinematic colors"
- "vibrant"
- "moody tones"
- "dreamy palette"

**Strong (name references):**
- "Roger Deakins teal-orange, subject warm against cold environment"
- "Gregory Crewdson cool blue suburbia palette, singular warm practical
  window"
- "Wes Anderson pastel palette, symmetric color blocking"
- "Blade Runner 2049 amber-sodium + cyan highlights"
- "Bill Henson deep emerald + near-black shadows"

A reference-grounded palette gives the model something specific to aim
at. Memegine's `COLOR_PALETTE.*` fragments are pre-named aim points.

---

## The three color levers in every prompt

1. **Shadow color** — what's the color of the darkest parts?
   - Warm shadows (warm blacks) = intimate, cinematic
   - Cool shadows = clinical, lonely, modern-digital
   - Pure black (crushed) = dramatic, poster-like

2. **Highlight color** — what's the color of the brightest parts?
   - Warm highlights (golden) = hero, nostalgia, warmth
   - Cool highlights = tech, surveillance, sterility
   - Preserved whites = documentary, non-graded

3. **Midtone bias** — what's the global cast?
   - Warm midtones = welcoming, vintage
   - Cool midtones = detached, modern, troubled
   - Green midtones = uneasy (cross-process feel)
   - Magenta midtones = nightlife, unreality

Name all three when mood is the main lift. Example:

> **Cold blue shadows, warm sodium highlights, green midtone bias.**
> Subject face caught between the two light colors.

---

## Time of day == color temperature (always)

| Time | Kelvin | Color cast | Emotional default |
|---|---|---|---|
| Noon clear sky | 5600K | Clinical white | Flat, honest |
| Overcast noon | 6500K | Slightly blue | Neutral, documentary |
| Golden hour | 3200K | Warm amber | Hero, nostalgia |
| Blue hour (post-sunset) | 10,000K (sky) + 2700K (practicals) | Cobalt sky, warm windows | Quiet, transitional |
| Indoor tungsten | 2700K | Warm orange | Intimate, cozy, dated |
| Fluorescent | 4000K + green | Green-cyan | Institutional, dead |
| Neon practicals | Mixed | Colored spill | Urban night, crypto-coded |
| Moonlight | 4100K | Cool white-blue | Loneliness, stealth |
| Candlelight / firelight | 1800K | Deep amber | Ritual, intimacy |
| Monitor / phone screen | ~6500K | Cool blue-cyan | Digital solitude |

Mixed light sources = richer palettes. "Sodium amber exterior + cold
phone screen interior" tells the model to mix two temps in the same
frame.

---

## Contrast — the loudness knob

Named contrast ranges force the model to stop defaulting to "balanced":

- **Flat profile**: compressed tonal range, shadows lifted to gray.
  Documentary, analytical. Think: Associated Press, Vice.
- **Standard**: natural roll-off. Most photoreal defaults.
- **Filmic S-curve**: subtle roll-off at both ends. Movies.
- **Crushed**: shadows go to near-black, highlights preserved. Poster,
  meme, editorial.
- **Blown**: whites clip intentionally. Summer, heat, overexposure-as-
  style.

A `crushed shadows + filmic roll-off in the highlights` clause usually
saves a prompt that feels "too AI".

---

## Grain / texture

Grain is mood too. Name it:

- **No grain** = digital, clinical, modern
- **Subtle grain** (Portra, Fuji) = cinematic intimacy
- **Coarse grain** (Tri-X 1600, Delta 3200) = grit, documentary, fear
- **VHS / chroma-smear** = nostalgia, lo-fi, degraded-record

Memegine's `POSTPROCESS.*` fragments cover these directly.

---

## Palette + stock pairings that work

| Palette intent | Film stock pairing |
|---|---|
| Warm editorial portrait | Portra 400 |
| Night-cold + warm practicals | Cinestill 800T |
| Gritty documentary | Tri-X pushed to 1600 |
| High-saturation editorial | Ektar 100 or Velvia 50 |
| Dreamy pastel | Fuji 400H |
| Archival documentary still | Kodak Vision3 500T |
| Lo-fi memory | VHS-stock emulation |
| Muted nostalgia | Polaroid 600 or Instax Mini |

Pair intentionally. Not every palette works with every stock.

---

## When in doubt, cite a specific frame

The fastest way to lock color is to tell the model "the palette of
[specific frame]":

- "palette of _Joker_ (2019) subway scene"
- "palette of Gregory Crewdson's _Twilight_ series"
- "palette of _Blade Runner 2049_ Las Vegas sequence"
- "palette of a Pantone 1950s postcard of Miami"

Give the model a frame. It'll match the system, not just the hue.

---

## The grading self-check

- Is the palette named (not adjective-d)?
- Is the shadow color stated?
- Is the highlight color stated?
- Is the midtone bias stated?
- Is a named reference frame or director/photographer cited (when
  ambition is high)?
- Does the contrast profile match the emotional register?
- Is the grain logic named (no grain / subtle / coarse / degraded)?

Under 5/7? The piece will default to "AI-default filmic teal-orange",
the single most overused palette.
