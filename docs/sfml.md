# SFML v1 — StoryForge Markup Language

SFML v1 is a plain-text, script format for **storytelling audio production** designed to be:

- **Self-contained**: includes casting at the top
- **Human readable**: succinct blocks with indentation
- **Deterministic to parse**: simple rules, minimal syntax

SFML supports **pause** events to control pacing.

---

# I - Specification
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
  Narrator:
    - line...
  CharacterName:
    - line...
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
- `Name` must match exactly the speaker block name used later in `Name:` blocks.
- `voice_id` must be a valid StoryForge roster id (`sf_voices.id`).
- Must include at least:
  - `Narrator: <voice_id>`

## 2) Scenes

### Syntax
```text
scene <scene_id> "<title>":
  Name:
    - text...
```

### Rules
- `scene_id` is a short id like `scene-1`, `scene-2`.
- `"<title>"` is recommended but optional (still keep the trailing `:`).
- Scene body lines are indented by **two spaces**.

## 3) Speaker blocks

Scenes typically contain one or more **speaker blocks**.
Each block belongs to a character (or Narrator) and contains one or more lines.

Speaker blocks keep rendering simple and avoid choppy joins.

### Syntax
```text
  Name:
    - line 1...
    - line 2...
```

A block can contain **one** line (that’s OK):
```text
  Name:
    - one line is fine
```

### Optional delivery tag on bullets
Delivery tags influence **intonation / prosody** (how a line is performed).
```text
  Name:
    - {delivery=neutral} line 1...
    - {delivery=urgent} line 2...
```

Allowed delivery values:
- neutral
- calm
- urgent
- dramatic
- shout

### Rules
- The `Name:` line is indented by **two spaces**, and bullet lines are indented by **four spaces**.
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

## Comments

SFML supports comments using `#` (hash).

Rules:
- A line that starts with `#` (after optional whitespace) is a comment.
- Comments are ignored by the parser/renderer.
- Use comments to explain intent, pacing, and delivery choices.

## Example

```text
# SFML v1
# This is an annotated example showing the full shape of an SFML script.

# 1) Casting map (character -> voice id).
# Production uses this to pick the correct voice when rendering.
cast:
  Narrator: terracotta-glow
  Maris: lunar-violet
  Captain: iron-slate

# 2) Scenes
scene scene-1 "Arrival":
  # Speaker blocks: one block per speaker run.
  Narrator:
    - The lighthouse stood silent on the cliff, and the sea breathed below.
    - PAUSE lines can be varied (decimal seconds) to control pacing.
  PAUSE: 0.35
  Maris:
    - {delivery=calm} I can hear it… the water, like a sleeping animal.
  PAUSE: 0.20
  Captain:
    - {delivery=urgent} Keep your voice down. We’re not alone out here.

scene scene-2 "The door":
  Narrator:
    - {delivery=dramatic} The door did not creak. It *sang*—a thin metal note in the fog.
  PAUSE: 0.60
  Maris:
    - {delivery=dramatic} That sound… it’s coming from inside.
  # Use delivery tags to shape intonation/prosody. Avoid over-tagging.
  Captain:
    - {delivery=shout} OPEN UP!

# Notes:
# - Allowed delivery values: neutral|calm|urgent|dramatic|shout
```

---

# II - LLM Generation (prompt + context)
This section documents how StoryForge asks an LLM to convert a text story into an SFML script.
It is intentionally **prompt-oriented**, not a strict language spec.

## LLM context pack (for `/api/production/sfml_generate`)

### A) Prompt header (verbatim)
```text
Return ONLY SFML plain text. No markdown, no fences.
Use SFML v1 (cast: + scenes + speaker blocks).
Think like: premium audiobook narrator + movie/TV drama (Prime) + game cutscene.
Goal: keep the story flowing with good pacing (speaker blocks + varied pauses).
Use delivery tags ({delivery=...}) when helpful for narrator or characters.
Coverage: include the full story; do not summarize.
```

### B) SFML_DOC_FOR_LLM block included in the prompt (verbatim)
This is a compact excerpt of the **SPEC** section above, formatted for the LLM context window.
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

4) Delivery tags
Bullet: - {delivery=urgent} text
Allowed: neutral|calm|urgent|dramatic|shout
Use for narrator or characters when it improves delivery; avoid over-tagging.
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

- **Speaker blocks** are the main lever to improve audio continuity (fewer joins).
- **Pauses** are the main lever to improve pacing (avoid breathless narration).
