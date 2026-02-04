# Storyforge Audio Production Subsystem

Story generation is done outside this repo (you/agent writes SFML).
This repo focuses on turning SFML scripts into a single mixed MP3.

---

## Audio Production

Module: `src/storyforge/audio.py`

Goal: render an SFML script into a **single mixed MP3**.

Pipeline:
1. Parse SFML (`src/storyforge/sfml.py`).
2. For each utterance, synthesize a WAV using XTTS (via `tools/voicegen_xtts.sh`).
3. Build a narration track by concatenating utterances + generated silences.
4. Schedule spot SFX relative to narration anchors (`now`, `last_start`, `last_end`).
5. Mix narration + (optional) looping music/ambience + spot SFX with `ffmpeg`.

CLI example:
```bash
./tools/fetch_assets.sh

storyforge render \
  --story out/the-quiet-lantern.sfml \
  --assets-dir assets \
  --out-dir out \
  --ref Ruby=assets/voices/refs/cmu_arctic/slt/ref.wav \
  --ref Onyx=assets/voices/refs/cmu_arctic/bdl/ref.wav
```

Notes:
- This renderer assumes `ffmpeg` and `ffprobe` are installed.
- Voices are resolved by passing `--ref SPEAKER=/path/to/ref.wav`.
- For safety + reproducibility, **assets remain out of git** and are fetched from Spaces.

---

## Cleanup / Security Notes

- Do **not** commit any Spaces credentials (no `.s3cfg` in git).
- Prefer OpenClaw auth profiles / environment variables for secrets.
