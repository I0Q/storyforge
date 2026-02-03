# Voice Generator (XTTS v2) — placeholders

This repo includes a **local-only** voice generator wrapper for building a narrator + character bank.

- Engine: **XTTS v2** (Coqui TTS)
- Runs in Docker to avoid host Python version constraints.
- Uses a persistent Docker volume for model cache.

## Build

From the repo root:

```bash
docker build -t i0q-storyforge-voicegen:latest -f docker/voicegen/Dockerfile .
```

## Generate a line

```bash
./tools/voicegen_xtts.sh \
  --text "Hello. This is a test voice." \
  --ref /path/to/speaker_ref.wav \
  --out out/test.wav \
  --lang en \
  --device auto
```

Notes:
- `--device auto` will use CUDA if available.
- The first run downloads the XTTS model into a Docker volume cache.

## Next

- Add `manifests/voice_bank.yaml`
- Add a script to render an intro reel for QA
- Add placeholder reference clips (public-domain / CC) and keep them in Spaces (not git)

