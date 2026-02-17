# SFML v1 — StoryForge Markup Language

SFML v1 is a plain-text, code-like script format designed to be:

- **Self-contained**: includes casting at the top
- **Human readable**: succinct blocks with indentation
- **Deterministic to parse**: simple rules, minimal syntax

This is the **only supported format** in the StoryForge UI/editor right now.

SFML supports a small set of **directives** (lines that begin with `@`) and **pause** events to control pacing.

---

## LLM generation prompt (current behavior)
When StoryForge generates SFML from a story (`/api/production/sfml_generate`), it prompts the LLM with additional constraints beyond the core grammar:

- **Speaker blocks are strongly preferred**.
  - If a speaker has 2+ consecutive lines, generation should use a `Name:` block with bullet lines.
  - Narrator paragraphs should almost always be a `Narrator:` block with bullets.
- **Delivery tags are for character dialogue only (for now)**.
  - Non-narrator dialogue lines should include a delivery tag.
  - Narrator lines should usually omit delivery tags (default narration is calm).
  - Whisper is intentionally not supported.

### Delivery tag syntax used by the generator
- Single line:
  - `[Name]{delivery=urgent} text...`
- Speaker block bullets:
  - `- {delivery=dramatic} text...`

Allowed delivery values:
- neutral
- calm
- urgent
- dramatic
- shout

---

## Overview

An SFML v1 file has:

1) A **casting map** block:

```text
cast:
  CharacterName: voice_id
  ...
```

2) One or more **scene blocks**:

```text
scene scene-1 "Title":
  [CharacterName] line...
  [Narrator] line...
```

---

## 1) Casting map

### Syntax
```text
cast:
  Name: voice_id
  Name2: voice_id2
```

### Rules
- Indentation is **two spaces** for mapping lines.
- `Name` must match exactly the speaker tag used later in `[Name] ...`.
- `voice_id` must be a valid StoryForge roster id (`sf_voices.id`).
- Must include at least:
  - `Narrator: <voice_id>`

---

## 2) Scenes

### Syntax
```text
scene <scene_id> "<title>":
  [Name] text...
  [Name] text...
```

### Rules
- `scene_id` is a short id like `scene-1`, `scene-2`.
- `"<title>"` is recommended but optional (still keep the trailing `:`).
- Scene body lines are indented by **two spaces**.

---

## 3) Speaker lines

### Syntax (single line)
```text
  [Name] text...
```

### Optional delivery tag
You can attach an optional delivery tag to influence the TTS renderer:

```text
  [Name]{delivery=calm} text...
```

Allowed values:
- neutral
- calm
- urgent
- dramatic
- shout

Notes:
- Delivery is **optional**; omit it for normal lines.
- Whisper is intentionally not supported right now.

### Syntax (speaker block; preferred for consecutive lines)
```text
  Name:
    - line 1...
    - line 2...
    - line 3...
```

### Optional delivery tag on bullets
```text
  Name:
    - {delivery=neutral} line 1...
    - {delivery=urgent} line 2...
```

### Rules
- Speaker tag is always `[Name]` for single lines.
- For a **speaker block**, the `Name:` line is indented by **two spaces**, and the bullet lines are indented by **four spaces**.
- `Name` must exist in the casting map.
- A speaker block is treated as **one audio segment** (the lines are read in one go), to avoid audible joins.
- For Tortoise, keep punctuation in the lines; punctuation helps delivery.

---

## 4) Directives (optional)

### Syntax
```text
@key: value
```

### Supported (initial)
- `@tortoise_preset: standard|fast|high_quality|ultra_fast`
- `@tortoise_candidates: 1|2|3` (generate multiple candidates and pick best)
- `@seed: 12345` (best-effort determinism)
- `@tortoise_chunk_chars: 450` (soft cap for longform chunk merging)
- `@tortoise_chunk_pause_ms: 120` (silence inserted between longform chunks)

## 5) Pauses

### Syntax
```text
  PAUSE: 0.25
```

### Rules
- Scene-level line (indented by two spaces).
- Insert an explicit pause (silence) into the audio.

## Minimal valid example

```text
# SFML v1
cast:
  Narrator: terracotta-glow
  Maris: lunar-violet

scene scene-1 "Intro":
  [Narrator]{delivery=calm} The lighthouse stood silent on the cliff.
  [Maris]{delivery=urgent} I can hear the sea breathing below.
```
