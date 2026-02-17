# SFML — StoryForge Markup Language

This documentation is split into two complementary files:

1) **Spec (strict format):** `sfml_spec.md`
   - Markup purpose, syntax, indentation rules
   - What the parser/renderer should accept

2) **Generation (LLM prompt + context):** `sfml_generation.md`
   - The prompt/context pack used to generate SFML from a text story
   - Guidance for pacing (pauses), grouping (speaker blocks), and character delivery tags

If you are editing the parser/renderer: start with **`sfml_spec.md`**.
If you are tuning the LLM output: start with **`sfml_generation.md`**.
