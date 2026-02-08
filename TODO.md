# StoryForge – TODO

## Voices (curated samples)
- [ ] Replace "Reload voices" button with "Generate / New" (no manual reload)
- [ ] Voices tab is a **list of approved voices** (each must have a sample)
- [x] Separate **Generate / New** screen for trying voices before saving
- [x] Inline **audio player** in voice list (no popups/new tabs)
- [ ] Make `sample_url` required at save-time (enforce in API/UI)
- [ ] Add per-voice fields: notes, gender/role tags (optional)

## Monitor / Bottom sheet
- [x] Make bottom sheet reliably open/close on iOS
- [ ] Ensure monitor toggle uses iOS-style switch + correct labels

## Navigation / UI polish
- [ ] Add copy button for build number + JavaScript error code (boot banner)
- [ ] Fix styling of the Debug UI option in the Settings tab (consistent card layout)
- [x] History tab renamed to Jobs
- [x] Advanced tab renamed to Settings
- [ ] Debug UI card layout consistent everywhere
- [ ] Add Story swatch editing (viewer + DB)

## Story editor
- [ ] Story details: add tabbed navigation (Story default + Characters tab)
- [ ] Story details: add fields used by pipeline (voice selection, etc.)
- [ ] Character extraction tooling

## Reliability
- [ ] Add toasts on all errors (avoid silent failures)
- [ ] Add a simple "state" view for background operations
