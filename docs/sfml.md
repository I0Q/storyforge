# SFML — StoryForge Markup Language (v0)

SFML is a **plain-text** markup format used by StoryForge to represent a story as:

- **Scenes** (ordered)
- **Lines** spoken by a character (including **Narrator**)
- An explicit **voice assignment** (voice id from the StoryForge voice roster) for every line

SFML is designed to be:

- easy for an LLM to generate
- easy to diff/review by a human
- easy for a renderer to parse deterministically

This document defines **SFML v1** (preferred) and SFML v0 (legacy).

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

## 2) Core directives / line types

SFML v0 supports these line types:

- **Casting block delimiters**: `<<CAST>>` and `<<ENDCAST>>`
- **Casting mappings**: `voice [Name] = voice_id`
- **Scene tags**: `<<SCENE id=... title="...">>`
- **Speaker lines**: `[Name] text`

---

## 3) Casting block

### Purpose
Define the voice roster id to use for each character. This makes an exported SFML file **self-contained** (no DB lookups needed to know casting).

### Delimiters
Casting must appear inside a clearly delimited block:

```
<<CAST>>
...
<<ENDCAST>>
```

### Mapping line syntax
Inside the casting block, one line per character:

```
voice [<Character>] = <voice_id>
```

### Requirements
- Must include at least one narrator mapping:
  - `voice [Narrator] = <voice_id>`
- `voice_id` must be a valid StoryForge roster id (`sf_voices.id`).

### Example
```
<<CAST>>
voice [Narrator] = terracotta-glow
voice [Maris] = lunar-violet
voice [Ocean] = solar-sands
<<ENDCAST>>
```

---

## 4) Scenes

### Syntax
Scenes are declared using a chevron-tag line:

```
<<SCENE id=<scene_id> title="<title>">>
```

### Notes
- `<title>` is optional.
- Scenes appear in order.

### Required attributes
- `id` (string)

### Optional attributes
- `title` (string)

### Recommendations
- Use sequential ids: `scene-1`, `scene-2`, …
- Keep ids short and stable.

---

## 5) Speaker lines (`[Character] ...`)

### Syntax
```
[<Character>] <text>
```

### Requirements
- `<Character>` must have a corresponding `voice [<Character>] = ...` mapping above.
- `<text>` must be single-line.

### Examples
```
[Narrator] The lighthouse stood silent on the cliff.
[Maris] I am proud.
[Ocean] The tide remembers every footstep.
```

---

## 6) Minimal valid file

A valid SFML file must include:
- at least one `scene`
- at least one `say`
- at least one narrator line (`say narrator ...`)

Example:
```
# SFML v0
<<CAST>>
voice [Narrator] = indigo-dawn
voice [Maris] = lunar-violet
<<ENDCAST>>

<<SCENE id=scene-1 title="Intro">>

[Narrator] The lighthouse stood silent on the cliff.
[Maris] I can hear the sea breathing below.
```

---

## 7) LLM generation contract (recommended)

When asking an LLM to generate SFML:

- Output **plain SFML text only** (no markdown, no code fences).
- Emit a **casting block at the top** using `voice [Name] = voice_id` lines.
- Then emit one or more `scene ...` blocks.
- For dialogue/narration, use **speaker lines** like `[Name] text...`.
- Always include narrator mapping + narrator lines.
- Do not invent voice ids; only use roster ids provided.
- Do not output JSON.

---

## 7) Out-of-scope (future)

Not part of v0:
- SFX/music cues
- timing/pauses/emphasis directives
- per-line engine params
- mixing/mastering instructions
