# Expanding the Storyforge SFX library (repeatable process)

This documents the end-to-end workflow to expand the SFX library safely and predictably.

## Goals

- Add more SFX so we can choose story-specific matches (quality improves a lot with library size).
- Keep **audio out of git**; store in DigitalOcean Spaces.
- Keep **everything identifiable** (filename + metadata + searchable catalog).

## Inputs / prerequisites

- Repo: `storyforge/`
- Freesound token saved in OpenClaw profile (used by `tools/sync_freesound.py`).
- DigitalOcean API token saved in OpenClaw profile `digital-ocean` inside `~/.openclaw/openclaw.json`.
- Bucket: `storyforge-assets` in region `sfo3`.

## 0) Local python env (Mac mini)

Use a venv so we don’t touch system python:

```bash
cd storyforge
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install requests pyyaml
```

## 1) Expand SFX locally (Mac mini)

Edit `manifests/assets.yaml` queries to include the story concepts you want.

Run:

```bash
cd storyforge
. .venv/bin/activate
python -u tools/sync_freesound.py --limit 1000 --max-pages 20
```

Notes:
- The script dedupes by Freesound `id` and `sha256`.
- Pagination can return intermittent 404s; treated as end-of-results.

## 2) Build a searchable catalog

This guarantees we can identify the right SFX later.

```bash
cd storyforge
python3 tools/build_sfx_catalog.py \
  --base-url https://storyforge-assets.sfo3.digitaloceanspaces.com/assets/
```

Outputs:
- `assets/credits/index.jsonl` (authoritative metadata)
- `assets/credits/sfx_catalog.csv`
- `assets/credits/sfx_catalog.md`

## 3) Upload to DigitalOcean Spaces

### 3.1 Create a Spaces key with correct bucket grant

We create a short-lived Spaces key from the DigitalOcean API token and write `tools/s3cfg_storyforge` (chmod 600). The key MUST include a grant:

- bucket: `storyforge-assets`
- permission: `readwrite`

(If grants is empty, uploads will fail with 403 AccessDenied.)

### 3.2 Upload SFX + credits

```bash
cd storyforge
./tools/upload_sfx_tree_s3cmd.sh
```

Uploads:
- `assets/sfx/`
- `assets/credits/index.jsonl`
- `assets/credits/sfx_catalog.csv`
- `assets/credits/sfx_catalog.md`

## 4) Download on tinybox

On tinybox repo (`/raid/storyforge_test`):

```bash
python3 tools/fetch_assets_http.py \
  --base https://storyforge-assets.sfo3.digitaloceanspaces.com/assets/ \
  --outdir . \
  --workers 16
```

This is **index-driven**: it downloads exactly what `index.jsonl` lists.

## 5) Delete local SFX from Mac mini (after tinybox verifies)

```bash
cd storyforge
trash assets/sfx
mkdir -p assets/sfx
```

We keep:
- credits + catalogs under `assets/credits/`
- repo structure (empty `assets/sfx/` directory)

## How to pick better SFX for a story

- Use `assets/credits/sfx_catalog.md` (quick skim/search)
- Or search `assets/credits/index.jsonl` by tags/title and choose filenames.
- SFML references use the **filename** (e.g. `fs-529411__f-synth-wind-whoosh-6-wav__cyclonek__cc-by.mp3`).
