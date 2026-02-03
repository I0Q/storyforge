# Asset Sources

## DigitalOcean Spaces (primary distribution)
- Bucket: `storyforge-assets`
- Region endpoint: `sfo3` (S3-compatible)
- Prefix: `assets/`

Assets are stored in Spaces and fetched after cloning via:

```bash
./tools/fetch_assets.sh
```

## Freesound
SFX are sourced from Freesound where licensing allows (CC0 / CC-BY).
Note: Freesound “original downloads” require OAuth2; for automation we use the preview URLs.
