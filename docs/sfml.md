# SFML v1 — StoryForge Markup Language

SFML v1 is a plain-text, script format for **storytelling audio production** designed to be:

- **Self-contained**: includes casting at the top
- **Human readable**: succinct blocks with indentation
- **Deterministic to parse**: simple rules, minimal syntax

SFML supports **pause** events to control pacing.

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

A **scene** is a continuous segment of the story in a specific time/place where actions and emotions evolve. Use a new scene when the setting, time, or narrative beat clearly shifts.

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
- `PAUSE:` lines can appear **anywhere inside a scene** (indented by two spaces):
  - between speaker blocks
  - at the start/end of a scene (to create space around a scene transition)
- `<seconds>` is a decimal number of seconds (recommended range: `0.10`–`2.00`).
- Inserts an explicit pause (silence) into the audio.

## Comments

SFML supports comments using `#` (hash).

Rules:
- A line that starts with `#` (after optional whitespace) is a comment.
- Comments are ignored by the parser/renderer.

## Example

```text
# SFML v1
# This is an annotated example showing the full shape of an SFML v1 script.

# 1) Casting map (character -> voice id)
# Production uses this to pick the correct voice when rendering.
cast:
  Narrator: terracotta-glow
  Maris: lunar-violet
  Captain: iron-slate

# 2) Scenes
# A scene is a continuous segment in a specific time/place.
# Start a new scene when the setting, time, or narrative beat clearly shifts.
scene scene-1 "Arrival":
  # Speaker blocks: one block per speaker run.
  Narrator:
    - The lighthouse stood silent on the cliff, and the sea breathed below.

  # PAUSE controls pacing (decimal seconds). Vary it intentionally.
  PAUSE: 1.25

  # Delivery tags influence intonation / prosody.
  # Allowed delivery: neutral|calm|urgent|dramatic|shout
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
  # Use delivery tags when it improves performance; avoid over-tagging.
  Captain:
    - {delivery=shout} OPEN UP!
```
