# SFML Generation — LLM prompt + context

This file documents how StoryForge asks an LLM to convert a text story into an SFML script.

It is intentionally **prompt-oriented**, not a strict language spec.

---

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

3) Pauses (vary them)
Use PAUSE lines to control pacing. Typical 0.15-0.35, strong beat 0.4-0.8, rare 1.0+.

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
  "voice_profiles": {
    "<voice_id>": {"engine": "styletts2|tortoise|xtts", "delivery_profile": "neutral|expressive"}
  },
  "scene_policy": {"max_scenes": 1, "default_scenes": 1}
}
```

---

## Notes / intent

- **Delivery tags are guidance**, not required by the SFML spec; the generator uses them to hint character delivery.
- **Speaker blocks** are the main lever to improve audio continuity (fewer joins).
- **Pauses** are the main lever to improve pacing (avoid breathless narration).

See also: `sfml_spec.md` for the strict format.
