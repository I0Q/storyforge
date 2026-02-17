# SFML v1 — StoryForge Markup Language

SFML v1 is a plain-text, code-like script format designed to be:

- **Self-contained**: includes casting at the top
- **Human readable**: succinct blocks with indentation
- **Deterministic to parse**: simple rules, minimal syntax

This is the **only supported format** in the StoryForge UI/editor right now.

SFML supports a small set of **directives** (lines that begin with `@`) and **pause** events to control pacing.

---

## LLM context pack (for SFML generation)
This section is designed to be **complementary**:
- The **exact prompt** starts with a short instruction header.
- Then we include a compact **SFML_DOC_FOR_LLM** block.
- Then we append a **JSON payload** (story + casting + voice profiles).

### A) Prompt header (verbatim)
```text
Return ONLY SFML plain text. No markdown, no fences.
Use SFML v1 (cast: + scene blocks).
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

3) Delivery tags (characters only)
Single line: [Name]{delivery=dramatic} text
Bullet: - {delivery=urgent} text
Allowed: neutral|calm|urgent|dramatic|shout
Avoid: whisper
```

### C) JSON payload appended to the prompt
The API appends a JSON object (via `json.dumps(...)`). The story/casting/voice profiles are filled in dynamically.

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
  "voice_profiles": {
    "<voice_id>": {"engine": "styletts2|tortoise|xtts", "delivery_profile": "neutral|expressive"}
  },
  "sfml_spec": "SFML v1 quick spec (short excerpt)",
  "scene_policy": {"max_scenes": 1, "default_scenes": 1},
  "rules": [
    "Output MUST be plain SFML text only. No markdown, no fences.",
    "FORMAT: Use SFML v1 (succinct blocks + indentation). Do NOT use chevrons like <<CAST>> or <<SCENE>>.",
    "CASTING: At the top, emit a casting block exactly like:\ncast:\n  Name: voice_id",
    "CASTING: One mapping per character. Names must match the speaker tags used later.",
    "CASTING: Always include Narrator.",
    "DIRECTIVES (optional): You may include directives at top-level: @tortoise_preset, @tortoise_candidates, @seed, @tortoise_chunk_chars, @tortoise_chunk_pause_ms",
    "PAUSES (optional): In scene bodies, you may include: PAUSE: 0.25 (indented by two spaces). Use pauses to slow rushed narration.",
    "SCENES: Emit 1..max_scenes scene blocks. Each scene header is: scene <id> \"<title>\":",
    "SCENES: If max_scenes=1, output exactly ONE scene block (scene-1) but still cover the whole story.",
    "SCENES: Otherwise, output between 1 and max_scenes scenes; do not create scenes for minor mood shifts.",
    "BODY: Inside a scene block, content is indented by two spaces.",
    "BODY: You can emit either single speaker lines: [Name] text",
    "DELIVERY: You MUST add delivery tags for character dialogue lines (non-narrator).",
    "DELIVERY: Narrator lines should usually omit delivery tags (default narration is calm). If you do tag narrator, only use neutral or calm.",
    "DELIVERY: Syntax for single lines: [Name]{delivery=calm} text",
    "DELIVERY: Syntax for speaker block bullets: - {delivery=urgent} text",
    "DELIVERY: Allowed values: neutral|calm|urgent|dramatic|shout. (Avoid whisper for now.)",
    "DELIVERY: Use voice_profiles[voice_id].delivery_profile to guide delivery: neutral voices -> neutral/calm; expressive voices may use urgent/dramatic/shout when the text warrants it.",
    "BODY: Or speaker blocks (preferred for consecutive lines by same speaker): Name: then 4-space indented bullets \"- ...\"",
    "BODY: STRONGLY prefer speaker blocks; do not emit lots of single [Name] lines if you can group them.",
    "BODY: If a speaker has 2+ consecutive lines, you MUST use a speaker block for that run.",
    "BODY: Narrator paragraphs should almost always be a Narrator: block with bullets.",
    "BODY: Speaker blocks MUST be treated as one segment; use them to avoid splitting delivery.",
    "BODY: Every [Name] and every Name: in a speaker block must exist in cast: mappings.",
    "Do not invent voice ids; only use voice ids from casting_map values.",
    "For Tortoise delivery, keep punctuation; do not strip commas/periods.",
    "Keep each bullet line to a single line; split long paragraphs into multiple bullets within the speaker block.",
    "COVERAGE: Include the full story content (do not stop early; do not summarize).",
    "COVERAGE: Keep emitting speaker lines until the story reaches a clear ending.",
    "Do not output JSON."
  ],
  "example": "# SFML v1\n@tortoise_preset: standard\n@tortoise_candidates: 2\n@tortoise_chunk_chars: 450\n@tortoise_chunk_pause_ms: 120\n\ncast:\n  Narrator: indigo-dawn\n  Maris: lunar-violet\n\nscene scene-1 \"Intro\":\n  Narrator:\n    - The lighthouse stood silent on the cliff.\n    - The sea breathed below, slow and steady.\n  PAUSE: 0.25\n  Maris:\n    - {delivery=urgent} I can hear the sea breathing below.\n"
}
```

## LLM generation prompt (current behavior)
When StoryForge generates SFML from a story (`/api/production/sfml_generate`), it includes additional constraints beyond the core grammar:

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
