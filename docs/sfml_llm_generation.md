# SFML v1 — LLM Generation (prompt + context)

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
