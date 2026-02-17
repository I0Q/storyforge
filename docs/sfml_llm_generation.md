# SFML v1 — LLM Generation (prompt + context)

This section documents how StoryForge asks an LLM to convert a text story into an SFML script.
It is intentionally **prompt-oriented**, not a strict language spec.

## LLM context pack (for `/api/production/sfml_generate`)

Note: The generator now feeds `docs/sfml.md` (strict spec portion) into the LLM context after the header as `SFML_SPEC:`.

### A) Prompt header (verbatim)
The runtime uses a compiler-style strict output contract. See `apps/app-platform/app/main.py` (`/api/production/sfml_generate`) for the exact header string.

### B) SFML spec
See the authoritative SFML spec: https://github.com/I0Q/storyforge/blob/main/docs/sfml.md

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
