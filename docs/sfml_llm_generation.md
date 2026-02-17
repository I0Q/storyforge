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

### B) SFML spec
See the authoritative SFML spec: `docs/sfml.md`

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
  }
}
```

## Notes / intent

- **Speaker blocks** are the main lever to improve audio continuity (fewer joins).
- **Pauses** are the main lever to improve pacing (avoid breathless narration).
