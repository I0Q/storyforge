# storyforge
Storyforge: a GPU-accelerated, open-source story audio engine for generating narrated bedtime stories with distinct character voices, background music, and sound effects from a simple script/markup.

## Assets

Audio assets are **not committed** to this repository.

They live in a public DigitalOcean Spaces bucket and can be fetched after cloning:

```bash
./tools/fetch_assets.sh
```

Environment overrides:
- `STORYFORGE_ASSETS_BUCKET` (default `storyforge-assets`)
- `STORYFORGE_ASSETS_REGION` (default `sfo3`)
- `STORYFORGE_ASSETS_PREFIX` (default `assets`)
- `STORYFORGE_ASSETS_OUTDIR` (default `assets`)


## Markup

See `docs/storyforge-markup.md` and `examples/umbrella.sfml`.


## App Platform UI

A small FastAPI UI for DigitalOcean App Platform lives at:
- `apps/app-platform/`

It talks to the droplet gateway over VPC.

## Related repos

- Tinybox compute provider API: https://github.com/I0Q/tinybox-compute-node
- Tinybox compute gateway (droplet proxy): https://github.com/I0Q/tinybox-compute-node-gateway
- StoryForge infrastructure/specs: https://github.com/I0Q/storyforge-infra
