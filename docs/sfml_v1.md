# SFML v1 — StoryForge Markup Language (preferred)

SFML v1 is a plain-text, code-like script format designed to be:

- **Self-contained**: includes casting at the top
- **Human readable**: succinct blocks with indentation
- **Deterministic to parse**: simple rules, minimal syntax

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

### Syntax
```text
  [Name] text...
```

### Rules
- Speaker tag is always `[Name]`.
- `Name` must exist in the casting map.
- Text must be single-line; split long paragraphs into multiple lines.

---

## Minimal valid example

```text
# SFML v1
cast:
  Narrator: terracotta-glow
  Maris: lunar-violet

scene scene-1 "Intro":
  [Narrator] The lighthouse stood silent on the cliff.
  [Maris] I can hear the sea breathing below.
```
