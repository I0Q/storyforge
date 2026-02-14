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

Everything else is out of scope for v0.

---

## 3) `scene` directive

### Syntax
```
scene id=<scene_id> title="<title>"
```

### Required attributes
- `id` (string): a short identifier for the scene.

### Optional attributes
- `title` (string): human-friendly title.

### Recommendations
- Use sequential ids: `scene-1`, `scene-2`, …
- Keep `scene_id` short and stable.

### Example
```
scene id=scene-1 title="At the Lighthouse"
```

---

## 4) `say` directive

### Purpose
Represents one spoken line by a character, including narrator lines.

### Syntax
```
say <character_id> voice=<voice_id>: <text>
```

### Required fields
- `character_id` (string): identifier of the character speaking.
- `voice=<voice_id>` (string): StoryForge voice roster id to use for this line.
- `text` (string): the text to speak.

### Narrator
The narrator is represented as:

- `character_id` = `narrator`

Example:
```
say narrator voice=indigo-dawn: The lighthouse stood silent on the cliff.
```

### Text rules (v0)
- `text` must be **single-line** (no embedded newlines).
- If a paragraph is long, split it into multiple consecutive `say` lines.
- Avoid URLs and raw numbers unless you truly want them spoken.

### Examples
```
say maris voice=lunar-violet: I can hear the sea breathing below.

say ocean voice=solar-sands: The tide remembers every footstep.
```

---

## 5) Identifiers

### `scene_id`
- Recommended charset: letters/digits/`-`/`_`
- Examples: `scene-1`, `opening`, `storm-approaches`

### `character_id`
- Recommended charset: letters/digits/`-`/`_`
- Should match the character naming convention in the library when possible.
- Must include `narrator`.

### `voice_id`
- Must be a **valid voice roster id** from StoryForge (`sf_voices.id`).
- The LLM must not invent voice ids.

---

## 6) Minimal valid file

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

## 7) Parsing guidance (for implementers)

A simple parser can be implemented with:

1) Split file into lines.
2) For each line:
   - trim whitespace
   - skip empty lines and comment lines (`#`)
3) If line starts with `scene`:
   - parse `id=` and optional `title=` (quoted)
4) If line starts with `say`:
   - parse: `say` + `<character_id>` + `voice=<voice_id>:` + `<text>`

### Error handling
- If a `say` appears before any `scene`, either:
  - implicitly create `scene-1`, or
  - treat as error (implementation choice). For LLM generation, prefer always emitting a `scene` first.

---

## 8) LLM generation contract (recommended)

When asking an LLM to generate SFML:

- Output **plain SFML text only** (no markdown, no code fences).
- Use only `scene` and `say` directives.
- Include narrator lines using `character_id=narrator`.
- Use only `voice_id` values from a provided casting map.
- Keep lines single-line; split long narration/dialogue into multiple `say` lines.
- Prefer multiple scenes when the story has obvious parts; otherwise produce one scene.

---

## 9) Out-of-scope (future versions)

Not part of v0 (reserved for v1+):

- sound effects / music cues
- timing, pauses, emphasis, SSML-like controls
- per-line engine parameters
- scene transitions
- mixing / mastering directives
- structured metadata blocks
