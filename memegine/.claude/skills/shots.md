# /shots — shot list for a short video piece

## Description

Plan a 3-12s video piece as a sequence of 1-3 shots. Each shot gets a
still_prompt (generate in Grok Nano Banana / Aurora), a motion_prompt
(img2vid via Grok Imagine), named lens + film + lighting + camera move.

## Arguments

`$ARGUMENTS` — intent string for the video. Examples:
- `/shots slow push on a trader at 3am, 5 seconds`
- `/shots kitchen, dusk, rack focus to a letter on the counter`

## Workflow

### 1. Run the shot-list brief
```bash
cd memegine && python -m memegine.cli shots "$INTENT"
```

### 2. Execute the brief
Act as Director per the SYSTEM prompt. Produce the JSON shot list.

Per shot, enforce:
- `duration_sec`: integer 2-6
- `camera_move`: ONE named move (push-in, pull-out, rack focus, orbit,
  lockoff, Ken Burns, whip pan — never "cinematic")
- `lens_and_film` named (e.g. "35mm, Cinestill 800T")
- `lighting` named (not "dramatic")
- `still_prompt`: passes `memegine lint --motion=false`
- `motion_prompt`: passes `memegine lint --motion`

### 3. Score motion prompts
```bash
cd memegine && python -m memegine.cli score "<motion_prompt>" --motion
```
Each motion prompt must name the camera move. If score < 70, revise.

### 4. Stitching plan
After the JSON, remind operator of the assembly commands:
```bash
memegine edit concat out.mp4 shot1.mp4 shot2.mp4 shot3.mp4
memegine edit grade out.mp4 graded.mp4 --preset moody_film
memegine edit audio graded.mp4 music.mp3 posted.mp4 --mode replace
```

### 5. Report
Return the shot list JSON plus the assembly commands tailored to the
actual shot count.

## Notes

- 1-shot pieces are often best. Don't push past 2 shots unless the
  operator asks.
- Total duration: 3-12s. If the shot list sums to >12s, revise down.
- Always specify whether music or silence. Music-free video reads as
  "content", not "piece".
