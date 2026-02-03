# Storyforge Markup Language (SFML) v0.1

SFML is a plain-text, line-oriented markup language for generating a **single mixed audio track** from:

- Narration and character dialogue (TTS)
- Background music beds
- Ambience beds
- Spot SFX
- Pauses and timing anchors
- Performance controls (prosody, pacing, emphasis, breath, intonation)

This document defines the format, recommended semantics, and a reference example.

> Status: **v0.1 (draft)** — stable enough to start implementing parsers/renderers.

---

## 1. File extension and encoding

- Extension: `.sfml` (or `.sf` if you prefer short)
- Encoding: UTF‑8
- Newlines: `\n`

---

## 2. Core concepts

### 2.1 Tracks
SFML renders into these conceptual tracks (the engine may implement them differently):

- **Narration/dialogue track** (TTS)
- **Beds** (looping / long-running): `music`, `ambience`
- **Spot SFX** (short one-shots)

### 2.2 Timeline and anchors
Every spoken line has:

- `start_time`
- `end_time`

SFML can schedule events relative to anchors:

- `now` — current timeline cursor
- `last_start` — start of last spoken line
- `last_end` — end of last spoken line

The engine advances the cursor to the end of each spoken line unless overridden.

---

## 3. Syntax overview

SFML is **line-based**. Each line is one of:

1) **Directive** (starts with `@`)
2) **Spoken line** (a speaker label + `:`)
3) **Event line** (SFX / PAUSE)
4) Comment/blank

### 3.1 Comments
- Full-line comment: `# like this`
- Inline comment: allowed only after a space: `...  # comment`

### 3.2 Identifiers
- `id`: `[A-Za-z_][A-Za-z0-9_\-]*`

### 3.3 Key-value options
Options are written as `key=value` pairs separated by spaces:

```
@music bed=music_01 gain_db=-18 loop=true
```

Values:
- string: `"quoted"` (supports spaces) or `bareword`
- numbers: `-18`, `0.9`, `120`
- booleans: `true|false`

---

## 4. Directives

Directives set metadata or long-running beds.

### 4.1 Title
```
@title: The Clockwork Fireflies
```

### 4.2 Global render settings
```
@mix target_lufs=-16 truepeak_db=-1.0
@defaults narration_gain_db=0 sfx_gain_db=-10 music_gain_db=-20 ambience_gain_db=-24
```

### 4.3 Voice assignments (casting)

Assign a voice to a speaker (character or narrator):

```
@voice NARRATOR sex=female voice_id=ivory
@voice MIRA     sex=female voice_id=amber
@voice CLOCKMAKER sex=male voice_id=onyx
```

Required keys (recommended):
- `sex=male|female` (for casting consistency)
- `voice_id=<id>` (maps to voice bank)

Optional keys:
- `style=<id>`
- `seed=<int>`
- `speaker_ref=<path>` or `speaker_id=<int>` (engine-specific)

### 4.4 Background music bed

Start/replace the music bed:

```
@music id=music_sb_echoes_soft gain_db=-18 loop=true fade_in=2.0 fade_out=2.0
```

Stop music:

```
@music off
```

### 4.5 Ambience bed

Start/replace ambience:

```
@ambience id=amb_rain_soft gain_db=-24 loop=true
```

Stop ambience:

```
@ambience off
```

---

## 5. Spoken lines (dialogue / narration)

Format:

```
SPEAKER: <text> [<inline-controls>]
```

Examples:

```
NARRATOR: The lanterns swayed in the rain.
MIRA: (whisper) I think the fireflies are mechanical.
```

### 5.1 Parenthetical performance hints
Parentheticals at the start of the line are performance hints:

- `(whisper)`
- `(softly)`
- `(sleepy)`
- `(excited)`

Engines may map these to prosody changes.

---

## 6. Inline performance controls

Inline controls are written as **tags** in braces, inspired by SSML but simplified.

### 6.1 Prosody

```
NARRATOR: {prosody rate=0.92 pitch=-1st} Slow footsteps on the stairs.{/prosody}
```

Keys:
- `rate`: float (0.5–1.5 typical)
- `pitch`: semitones, `-2st`, `+1st`
- `volume_db`: `-6`, `+3`

### 6.2 Emphasis

```
MIRA: That is {emph level=strong}definitely{/emph} a secret door.
```

`level`: `reduced|moderate|strong`

### 6.3 Breath

Insert an audible breath (or a short pause if breath audio isn’t available):

```
NARRATOR: And then—{breath kind=inhale}—everything went quiet.
```

`kind`: `inhale|exhale`

### 6.4 Break / micro-pause

```
NARRATOR: The key turned{break dur=0.25} and the lock clicked.
```

`dur` in seconds.

### 6.5 Intonation (question/statement contour)

```
MIRA: {intonation kind=question}You heard that too?{/intonation}
```

`kind`: `neutral|question|statement|up|down`

### 6.6 Pacing / timing stretch

```
NARRATOR: {pace word_gap=0.08}One… two… three…{/pace}
```

`word_gap` in seconds.

---

## 7. Event lines

### 7.1 PAUSE

Move the timeline cursor forward:

```
PAUSE: 0.8
```

### 7.2 SFX

Play a spot sound effect relative to an anchor:

```
SFX: id=door_soft_01 at=last_end +0.15 gain_db=-10
```

Fields:
- `id` (required)
- `at`: `now|last_start|last_end` (default `now`)
- offset: `+0.15` or `-0.10` seconds (default `+0`)
- `gain_db` (default from `@defaults`)

---

## 8. Recommended engine behaviors

- **Ducking**: narration should duck beds (music/ambience), but not duck spot SFX.
- **Normalization**: final output should target a consistent loudness (e.g., -16 LUFS).
- **Caching**: cache per-line TTS by stable hash of text + voice + controls.
- **Safety**: cap sudden gain changes; optionally clamp sfx peaks.

---

## 9. Complete example

```sfml
@title: The Umbrella of Paper Stars
@mix target_lufs=-16 truepeak_db=-1.0
@defaults music_gain_db=-20 ambience_gain_db=-24 sfx_gain_db=-10

@voice NARRATOR sex=female voice_id=ivory
@voice MIRA sex=female voice_id=amber
@voice CLOCKMAKER sex=male voice_id=onyx

@ambience id=amb_rain_soft gain_db=-24 loop=true fade_in=2.0
@music id=music_sb_echoes_soft gain_db=-18 loop=true fade_in=2.0

NARRATOR: The rain was gentle tonight—like a blanket for the city.
SFX: id=rain_window_tap at=last_start +0.40 gain_db=-14

MIRA: (whisper) {intonation kind=question}Do you see them?{/intonation}
PAUSE: 0.5

NARRATOR: {prosody rate=0.92}Tiny clockwork fireflies{/prosody} drifted past the window.
SFX: id=soft_chime at=last_end +0.10 gain_db=-12

@music off
@ambience off
```

---

## 10. Versioning

- Each file may optionally declare: `@sfml: 0.1`
- Engines should reject unknown major versions.

