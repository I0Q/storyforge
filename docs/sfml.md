# SFML v1 — StoryForge Markup Language

SFML v1 is a plain-text, code-like script format designed to be:

- **Self-contained**: includes casting at the top
- **Human readable**: succinct blocks with indentation
- **Deterministic to parse**: simple rules, minimal syntax

SFML supports **pause** events to control pacing.

---

# Section 1 — SPEC (strict format)
This section defines the **strict SFML v1 format** (what the renderer/parser should accept).

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

## 1) Casting map

### Syntax
```text
cast:
  Name: voice_id
  Name2: voice_id2
```

### Rules
- Indentation is **two spaces** for mapping lines.
- `Name` must match exactly the speaker tag used later in `[Name] ...` or `Name:` blocks.
- `voice_id` must be a valid StoryForge roster id (`sf_voices.id`).
- Must include at least:
  - `Narrator: <voice_id>`

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

## 3) Speaker lines

### Syntax (single line)
```text
  [Name] text...
```

### Optional delivery tag (inline)
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
- Delivery is **optional**.
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

## 4) Pauses

### Syntax
A pause line has a **tag** and a **duration** in **decimal seconds**:

```text
  PAUSE: <seconds>
```

Examples:
```text
  PAUSE: 0.15
  PAUSE: 0.40
  PAUSE: 1.20
```

### Rules
- Scene-level line (indented by two spaces).
- `<seconds>` is a decimal number of seconds (recommended range: `0.10`–`2.00`).
- Inserts an explicit pause (silence) into the audio.

## Minimal valid example

```text
# SFML v1
cast:
  Narrator: terracotta-glow
  Maris: lunar-violet

scene scene-1 "Intro":
  [Narrator] The lighthouse stood silent on the cliff.
  [Maris]{delivery=urgent} I can hear the sea breathing below.
  PAUSE: 0.25
```

---

# Section 2 — GENERATION (LLM prompt + context)
This section documents how StoryForge asks an LLM to convert a text story into an SFML script.
It is intentionally **prompt-oriented**, not a strict language spec.

## LLM context pack (for `/api/production/sfml_generate`)

### A) Prompt header (verbatim)
```text
Return ONLY SFML plain text. No markdown, no fences.
Use SFML v1 (cast: + scene blocks).
Think like: premium audiobook narrator + movie/TV drama (Prime) + game cutscene.
Goal: keep the story flowing with good pacing (speaker blocks + varied pauses).
Prefer speaker blocks (Name: + bullets) to avoid choppy audio joins.
Add delivery tags ONLY for non-narrator character dialogue.
Coverage: include the full story; do not summarize.
```

### B) Documentation block included in the prompt (verbatim)
```text
SFML_DOC_FOR_LLM:
1) Casting
cast:
  Narrator: <voice_id>
  Name: <voice_id>

2) Scenes
scene scene-1 "Title":
  Narrator:
    - line...
  Name:
    - {delivery=urgent} line...
  PAUSE: 0.25

3) Pauses (variable seconds)
Use PAUSE lines to control pacing, and choose the duration intentionally.
PAUSE syntax is decimal seconds (examples: 0.15, 0.40, 1.20).
Typical 0.15-0.35, strong beat 0.4-0.8, rare 1.0+.

4) Delivery tags (characters only)
Single line: [Name]{delivery=dramatic} text
Bullet: - {delivery=urgent} text
Allowed: neutral|calm|urgent|dramatic|shout
Avoid: whisper
```

### C) JSON payload appended to the prompt
The API appends runtime inputs as JSON (via `json.dumps(...)`):

```json
{
  "format": "SFML",
  "version": 0,
  "story": {
    "id": "<story_id>",
    "title": "<title>",
    "story_md": "<full story markdown>"
  },
  "casting_map": {
    "Narrator": "<voice_id>",
    "<CharacterName>": "<voice_id>"
  },
  "scene_policy": {"max_scenes": 1, "default_scenes": 1}
}
```

## Notes / intent

- **Delivery tags are guidance**, not required by the SFML spec; the generator uses them to hint character delivery.
- **Speaker blocks** are the main lever to improve audio continuity (fewer joins).
- **Pauses** are the main lever to improve pacing (avoid breathless narration).
