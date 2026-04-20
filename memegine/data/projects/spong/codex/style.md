# $SPONG — Style Codex

> **Tagline:** *we like the moon.*
>
> **Brand thesis:** Spongmonkeys are the 2003 cursed-meme lineage
> (Joel Veitch, rathergood.com) that went global via the 2004 Quiznos
> Super Bowl commercial. "Spong" — the verb, from the b3ta forum — means
> adding huge googly eyes with tiny pupils to any image. That move IS
> the brand. Everything else is dressing.

## Canon (cite this — authenticity comes from the lineage)

- **Origin:** Joel Veitch, rathergood.com. "We Like The Moon" Flash
  video uploaded **January 24, 2003**. Uploaded to YouTube
  November 3, 2007 — over 1.1M views.
- **The Quiznos campaign (2004):** "We love the subs! 'Cuz they are
  good to us. The Quiznos subs." Aired on Super Bowl broadcasts.
  Quiznos corporate received **30,000+ complaint calls in the first
  week**. That's the pinnacle: a mainstream sandwich chain paid money
  to air cursed low-fi animation at the biggest-audience moment in
  American TV, and half the country panicked. That is the bar.
- **The word "spong":** a b3ta forum term meaning *"the practice of
  adding large staring eyes with small pupils to an image."* This is
  the single most important visual move. If the eyes aren't spong'd,
  it isn't Spong.
- **Revival:** 2023 — Quiznos brought the spongmonkeys back in a new
  ad. The character is 22+ years old and still reads as cursed.
- **Token:** $SPONG on Solana.
  Contract: `A1zvkas7XaGYaV9ztokfN11VwaiNGHkhqGCi4AYwpump`.
  Supply 1B, tax 0/0, LP burned.
- **Operator socials:** `@SpongmonkeyMoon` (X), `@SpongMonkeys`
  (TikTok), `spongmonkeys.fun` (website with trait customizer).

## Visual rules

### The head (NEVER violate)

1. **Photo-cutout of a real monkey/rodent head**, slightly blurry,
   desaturated, pasted onto a different flat illustrated body. The
   edges must look cut-out — visible matte lines, no clean alpha.
2. **Huge googly eyes layered on top of the photo.** Pure white
   circles with tiny black pupils. The eye whites should nearly touch.
   This is "spong" — it is the single defining move.
3. **Open singing mouth** showing cream buck teeth and red gums. The
   monkey is mid-note.
4. **Lo-fi 2003 aesthetic:** jpeg compression pushed deliberately,
   yellowed background, Flash-banner color palette. Crisp 4K renders
   are WRONG for this brand.

### The body

- Flat illustrated (not photo). Crude MSPaint-tier linework.
- Outfit overlays from the `spongmonkeys.fun` trait library:
  Napoleon coat, Wall Street suit, astronaut suit, samurai armor,
  cowboy hat, wizard robe, hip-hop fit, black tie, knight armor,
  pirate, top gun jacket, superhero cape.
- Accessories: cigarette, gold chain, round glasses, grillz, crown,
  face tattoos, eye patch, money bag.

### The scene

- Pick ONE from the canonical scene library:
  **Oval Office, Space, Red Carpet, Tokyo Night, Beach, Moon, Yacht,
  Lambo.** Each scene rendered in cursed 2003 MSPaint illustration
  style — NOT photoreal, NOT clean vector.
- Caption is either a song lyric ("we like the moon"), a sincere
  declaration, or a Quiznos-style ad parody. Always low-stakes,
  always earnest.

### Fur variants (trait differentiation)

Normal, Black, White, Pink, Neon Green, Red, Blue, Purple, Rainbow.
Use fur color to differentiate spongmonkey characters in multi-monkey
pieces.

### Typography

- Primary: hand-scrawled marker caption in **all lowercase**,
  centered at the bottom.
- Song lyrics: childlike Comic Sans or hand-drawn.
- Speech bubbles: MSPaint-jagged outlines.
- No modern sans-serifs. No sleek vector type.

## What this brand DOES

- Sincerely love things it has no business loving. "we like the moon"
  is the ur-example. Every piece should read as a spongmonkey
  earnestly declaring love for something mundane or absurd.
- Lean into the cursed 2003 aesthetic. Jpeg compression is a feature.
- Parody mainstream ad copy in the most oblivious voice possible.
- Mix absurd couplings: spongmonkey in the Oval Office, spongmonkey
  on a yacht, spongmonkey as a samurai. The mismatch is the joke.
- Stay musical — spongmonkeys sing. Captions should read like the
  second line of a song.

## What this brand DOES NOT do

- Clean up. No high-res, no sharp, no polished. The cursedness is
  load-bearing.
- Wink at the camera. The spongmonkey doesn't know it's cursed.
- Irony. The spongmonkey genuinely loves the moon / the subs /
  the Lambo / the oval office. Sincerity is the whole comedy engine.
- Small eyes. If a reader can't see the pupils from across the room,
  the eyes aren't spong'd enough.
- Modern type. No Inter, no Helvetica Neue. This is a 2003 Flash
  banner, not a 2026 product page.
- Invented lore. The real lineage (Joel Veitch → Quiznos) is already
  richer than anything we'd make up. Cite it.

## Prompt scaffolds (drop into a brief)

### Classic solo spongmonkey, scene-based
```
A cursed 2003-Flash-animation style still: a single spongmonkey (photo
cutout of a real monkey head, slightly blurry, peach-brown fur, HUGE
white googly eyes nearly touching with tiny black pupils, open singing
mouth showing buck teeth and red gums) attached to a crude MSPaint-style
illustrated body wearing {outfit} and {accessory}, standing in a
flat-illustrated {scene}. Yellowed beige background with visible jpeg
compression. Hand-scrawled lowercase caption centered at the bottom:
"{lyric or sincere declaration}". 2003 aesthetic — NOT 4K, NOT clean.
```

### Multi-spongmonkey duet
```
A cursed rathergood-era scene: two spongmonkeys side by side, one with
{fur_A} fur, one with {fur_B} fur, both mid-song with huge googly eyes
and open mouths, standing in front of {scene}. Crude MSPaint illustrated
background, jpeg compression artifacts visible. Song-lyric caption in
Comic Sans: "{we-like-the-X-style lyric}".
```

### Quiznos-ad parody
```
A 2004 broadcast-TV advertisement still: a spongmonkey centered in a
Quiznos-style yellow-and-red branded scene, singing directly to camera
with lyrics displayed as a broadcast lower-third: "we love the {product},
'cuz they are good to us." Deliberate composite artifacts, slight
interlacing lines, 480p TV-broadcast quality. The spongmonkey does not
know it's selling anything — absolute sincerity.
```

## Compounded Patterns

*(will grow as winners land — add from `corpus distill` output)*

## Ingest workflow (for expanding the codex)

Since memedepot.com/d/spong renders client-side, the operator should
grab reference material directly:

```bash
memegine project use spong
# save spongmonkey references into any folder (X saves, TikTok rips,
# screenshots from memedepot, the original rathergood video)
memegine corpus seed ./spong-refs/
# Claude-in-session extracts craft patterns per frame (no API key)
# operator saves patterns.json, then:
memegine corpus apply patterns.json
memegine corpus distill
```
