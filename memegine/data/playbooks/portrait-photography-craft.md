# Portrait Photography Playbook

Photoreal portraits are where AI most often gives itself away: plastic
skin, dead eyes, symmetric blur, wedding-photographer lighting. This
reference is for keeping portraits feeling like a real photograph a real
human shot — named lens, named lighting ratio, named stock.

---

## Default "photoreal portrait" stack

A portrait that doesn't trip the AI detector almost always cites:

1. **A specific camera + lens** (not just "camera")
2. **A specific film stock or sensor look** (not just "warm tones")
3. **A named lighting setup with a ratio** (not just "soft light")
4. **A specific time of day + weather** (not just "natural")
5. **A composition rule** (not just "well composed")
6. **A named emotion + micro-movement** (not just "expressive")
7. **A "no X, no Y" negative clause** (not implicit trust)

If any of those seven is vague, ship value drops ~20%.

---

## Lens by subject framing

| Framing | Lens | Why |
|---|---|---|
| Environmental portrait (subject in a place) | 28mm f/1.8 or 35mm f/1.4 | Keeps the place legible. Distortion starts at 24mm. |
| Standard portrait | 50mm f/1.8 or 50mm f/1.2 | Closest to what the eye "sees". Feels documentary. |
| Headshot / compressed portrait | 85mm f/1.2 or 85mm f/1.8 | Background separates cleanly. Skin looks flattering. |
| Long tele portrait | 135mm f/2 or 200mm f/2.8 | Monumental. Background becomes abstract wall of color. |
| Tight detail (hands, jewelry, eye) | 100mm macro | Tack-sharp without losing the body language. |

Default for "a character in a place" = **35mm f/1.4**.
Default for "a character's face, no place" = **85mm f/1.2**.

---

## Lighting ratios — the single biggest craft signal

Ratios describe how much brighter the key is than the fill. Naming the
ratio makes the model actually build lighting instead of defaulting to
"even everywhere" (which looks fake).

| Ratio | Look | Use for |
|---|---|---|
| 1:1 | Flat, even | Beauty / commercial |
| 2:1 | Gentle modeling | Mainstream portrait |
| **3:1** | Dimensional, balanced | **Default for editorial photoreal** |
| 4:1 | Moody, shadow-side strong | Documentary, cinematic |
| 8:1+ | Deep shadow side (Rembrandt, split) | Dark lore / fine-art |

Always write: `key camera-right at 3:1 ratio, fill from a {source}`, not
just "soft light". If you don't know the ratio, default to 3:1 for
narrative portraits and 2:1 for "approachable" subjects.

---

## Named lighting patterns (cite these by name)

- **Butterfly**: key above and in front, straight down. Creates
  symmetric under-chin shadow. Glamour default.
- **Rembrandt**: key 45° camera-right, slightly above. Produces a
  triangle of light on the shadow-side cheekbone. Classical.
- **Split**: key exactly 90° camera-side. Half face in deep shadow.
  Drama, polarization.
- **Loop**: key ~30° off axis. The nose shadow forms a small loop
  beside the nose. Most natural-looking portrait.
- **Clamshell**: soft key above + soft fill below. Tight crops. Beauty.
- **Rim backlight**: key strong from behind, separates subject from
  dark background. Narrative / editorial.

If the subject is supposed to look "quiet" or "unresolved", **Rembrandt
at 3:1** is almost always the right call. If they're supposed to look
"alienated" or "threatened", **split at 8:1** is the move.

---

## Skin — the dead giveaway

AI skin looks like glass or wax. Counter with:

- **Name the stock**: `Portra 400` / `Fuji 400H` / `Cinestill 800T` /
  `Tri-X pushed to 1600`. These stocks have specific skin renderings.
- **Cite texture**: `natural skin texture, visible pores, no digital
  smoothing, no beauty retouching`.
- **Name the grain**: `subtle film grain, not digital noise`.
- **Force imperfections**: `one strand of hair across the cheek, slight
  asymmetry, a tiny catchlight in the right eye only`.

Default negatives: `no plastic skin, no symmetric blur, no AI-smoothness,
no uniform skin tone across face`.

---

## Eyes

Always name what the subject is looking at or a specific internal state:

- "eyes locked on the screen in front of them"
- "eyes unfocused, middle-distance, dissociated"
- "eyes narrowed, reading something just off-frame"
- "eye contact with camera, no affect"

Never write just "expressive eyes". It's a null phrase — the model
defaults to symmetric catchlights and glossy irises. Dead.

---

## Wardrobe — concrete wins over adjectives

- Not: "stylish outfit"
- Yes: "black crew-neck t-shirt, visible seam at collar, gold chain
  partially hidden"
- Not: "casual clothes"
- Yes: "gray hoodie, left drawstring longer than right, pen clipped to
  pocket"

Operator-specific pattern: the same wardrobe across pieces makes a
recurring character feel real. Pick 3-5 wardrobe sets and cycle.

---

## Background — "context over cosmetics"

The background says where the subject is. Name it concretely:

- Not: "a studio"
- Yes: "a seamless gray roll backdrop, 8-feet deep, no other objects"
- Not: "a moody background"
- Yes: "a parking garage, concrete columns, two flickering fluorescent
  tubes, no cars"

The bokeh should be a consequence of the lens choice, not a styling
decision. If you want heavy bokeh, use 85mm f/1.2. If you want
legible-but-soft, use 35mm f/1.4. Don't ask for "beautiful bokeh".

---

## Composition defaults

- **Rule of thirds, subject on left third**: classic narrative portrait.
- **Centered, tight crop**: confession, intimacy, or meme reaction.
- **Low angle up-tilt**: hero, monumental, threatening.
- **High angle down-tilt**: small, vulnerable, judged.
- **Dutch tilt 12°**: unsettled, wrong.

Default for "a character feeling something": **rule of thirds, subject
left, negative space right half, eyes on upper third**.

---

## Negative clause — always present

Every photoreal portrait prompt should end with:

> no extra fingers, no warped text, no logo watermarks, no lens flares
> unless specified, no plastic skin, no symmetric blur, natural skin
> texture preserved, no CGI look.

Memegine's `NEGATIVE.photoreal_defaults` fragment expands to this. Use
it.

---

## The portrait self-check (before you ship)

A photoreal portrait prompt that's ready to paste into Grok answers all
of these yes:

- Is there a named lens with aperture?
- Is there a named film stock or sensor look?
- Is there a named lighting pattern (Rembrandt, split, butterfly,
  clamshell, loop, rim-backlight)?
- Is there a named lighting ratio (2:1, 3:1, 4:1)?
- Is there a named time-of-day + weather?
- Is there a named composition rule?
- Are the eyes described as doing a specific thing?
- Is the wardrobe concrete (not "casual")?
- Is the background a specific place (not "moody")?
- Is there a negative clause at the end?

Under 8/10? Run `memegine fix-prompt` before you paste it.
