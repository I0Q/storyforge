# SFML — StoryForge Markup Language (v0)

SFML is a **plain-text** markup format used by StoryForge to represent a story as:

- **Scenes** (ordered)
- **Lines** spoken by a character (including **Narrator**)
- An explicit **voice assignment** (voice id from the StoryForge voice roster) for every line

SFML is designed to be:

- easy for an LLM to generate
- easy to diff/review by a human
- easy for a renderer to parse deterministically

This document defines **SFML v0**.

---

## 1) File rules

### Encoding
- UTF-8 text.

### Newlines
- Use `\n` line endings (the parser should tolerate `\r\n`).

### Comments
- Any line starting with `#` is a comment and should be ignored by parsers.

### Whitespace
- Leading/trailing whitespace on a line is ignored.
- Multiple spaces between tokens are equivalent to one.

### Ordering
- Scenes appear in the order they should be rendered.
- Lines appear in the order they should be spoken.

---

## 2) Core directives

SFML v0 intentionally supports only two directives:

- `scene` — declares a new scene
- `say` — declares a spoken line

---

## 3) `scene` directive

### Syntax
```
scene id=<scene_id> title="<title>"
```

### Required attributes
- `id` (string)

### Optional attributes
- `title` (string)

### Recommendations
- Use sequential ids: `scene-1`, `scene-2`, …
- Keep ids short and stable.

---

## 4) `say` directive

### Syntax
```
say <character_id> voice=<voice_id>: <text>
```

### Required fields
- `character_id` (string)
- `voice=<voice_id>` (string; must exist in the voice roster)
- `text` (string; single-line)

### Narrator
Narrator lines use:
- `character_id = narrator`

Example:
```
say narrator voice=indigo-dawn: The lighthouse stood silent on the cliff.
```

### Text rules
- `text` must be single-line.
- Split long paragraphs into multiple `say` lines.

---

## 5) Minimal valid file

A valid SFML file must include:
- at least one `scene`
- at least one `say`
- at least one narrator line (`say narrator ...`)

Example:
```
# SFML v0
scene id=scene-1 title="Intro"

say narrator voice=indigo-dawn: The lighthouse stood silent on the cliff.
say maris voice=lunar-violet: I can hear the sea breathing below.
```

---

## 6) LLM generation contract (recommended)

When asking an LLM to generate SFML:

- Output **plain SFML text only** (no markdown, no code fences).
- Use only `scene` and `say`.
- Always include narrator lines (`say narrator ...`).
- Use only voice ids from a provided casting map.
- Do not output JSON.

---

## 7) Out-of-scope (future)

Not part of v0:
- SFX/music cues
- timing/pauses/emphasis directives
- per-line engine params
- mixing/mastering instructions
