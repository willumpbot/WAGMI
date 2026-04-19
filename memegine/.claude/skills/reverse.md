# /reverse — reverse-engineer an image into a recreate-the-look prompt

## Description

Operator has an image they love. Reverse-engineer it: extract named lens,
film stock, lighting setup, composition rule, time of day, mood — then
write a prompt that would reproduce that look.

Used to mine reference creators' style into your own codex.

## Arguments

`$ARGUMENTS` — `<image_path> [context note]`. Example:
- `/reverse refs/gregory-crewdson-still.jpg context: want this quiet suburban dread`

## Workflow

### 1. Run the reverse brief
```bash
cd memegine && python -m memegine.cli reverse "$IMAGE_PATH" -c "$CONTEXT"
```

### 2. Analyze the image
You have vision — actually LOOK at the image. Extract:
- **Camera/lens**: focal length + aperture feel (wide/normal/tele, shallow/deep DOF)
- **Film stock / sensor look**: grain structure, color palette, contrast
  curve. Match to a named stock (Portra 400, Cinestill 800T, Tri-X,
  Ektar, etc.)
- **Lighting**: source direction, hardness, color temp. Name the setup.
- **Time of day**: infer from shadows + color
- **Composition rule**: rule of thirds, centered, symmetry, negative space
- **Subject + wardrobe + props**: concrete nouns
- **Atmosphere keyword**: ONE word that describes the mood

### 3. Produce the recreate prompt
Write a Grok-ready prompt using the extracted ingredients. Must pass
`memegine lint`. Must score >= 80 on `memegine score`.

### 4. Suggest variants
Offer 3 tweaks that preserve the look but vary the subject (e.g., same
film+lighting, different character).

### 5. Compound opportunity
If the image is a keeper, remind operator to:
```bash
memegine refs add "$IMAGE" --tags "reference,<creator>,<mood>" \
  --notes "reverse of: <one-line distillation>"
```
Note: don't add with `--winner` for reverse-sourced refs — they weren't
operator-produced.

## Notes

- If the image is blurry or you can't see details, say so. Don't guess.
- Never describe the image using banned superlatives; name the craft.
