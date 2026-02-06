# Storyforge Monitor (LAN-only)

A tiny LAN-only web UI that shows Storyforge render jobs, basic progress, and provides tap-friendly links (WhatsApp/phone friendly).

## Goals

- **Phone-first** UX (big buttons, minimal scrolling).
- **LAN-only** access (no public exposure).
- **Token-gated** + optional CIDR allowlist.
- Fast jobs list view; detailed per-job view with logs and download links.

## Files / Layout

- `monitor/app.py` — HTTP server (ThreadingHTTPServer).
- `monitor/static/index.html` — Jobs list page.
- `monitor/static/job.html` — Job detail page.
- `monitor/static/ping.html` — simple health page.
- `monitor/allow_cidrs.json` — CIDR allowlist (e.g. `127.0.0.1/32`, `192.168.0.0/16`).
- `monitor/token.txt` — **secret token** (NOT committed).
- `monitor/token.example.txt` — template file for token.
- `monitor/jobs/<id>.json` — job metadata (NOT committed).
- `monitor/tmp/<id>/...` — per-job temp dirs + logs (NOT committed).

Repo ignores:
- `monitor/token.txt`
- `monitor/jobs/`
- `monitor/tmp/`

## Security model

The server enforces **both**:

1) **CIDR allowlist** (client IP must match one of the networks in `monitor/allow_cidrs.json`)
2) **Token** (`?t=<token>` query param must match `monitor/token.txt`)

If either fails, requests return `403` / `401`.

Recommended: keep this behind your LAN only (no port forwards, no public exposure).

## Endpoints

- `GET /?t=...` — jobs list UI
- `GET /job/<id>?t=...` — job detail UI
- `GET /ping?t=...` — static ping page

API:
- `GET /api/jobs?t=...` — **lightweight** list view payload (fast)
- `GET /api/job/<id>?t=...` — full per-job payload (cpu/gpu/log tail)

Downloads:
- `GET /dl/<id>?t=...` — MP3 download (only shown by UI when job completed)
- `GET /sfml/<id>?t=...` — SFML source download for that job

## Job model

Jobs are represented by:

- `monitor/jobs/<id>.json` (created by monitored runner)
  - `id` (string)
  - `title`
  - `sfml` (path relative to repo root, e.g. `out/foo.sfml`)
  - `started_at` (unix seconds)
  - `total_segments` (int)
  - optional `mp3` (absolute path)

The monitor infers:

- progress by counting `seg_*.wav` under the active temp directory
- running/completed/aborted state by checking whether the job process is active and whether an MP3 exists

## Monitored runner

Use:

- `tools/storyforge_render_monitored.sh`

What it does:

- creates a job id
- writes `monitor/jobs/<id>.json`
- creates a per-job tmp root `monitor/tmp/<id>/...`
- tees logs into `monitor/tmp/<id>/storyforge-<ts>.log`
- prints a clickable job URL

## Systemd service (tinybox)

A typical unit (installed outside the repo):

- `/etc/systemd/system/storyforge-monitor.service`

The service should:

- run as user `tiny`
- run from repo root `/raid/storyforge_test`
- listen on LAN interface/port (default used so far: `8787`)

### Restart

```bash
sudo systemctl restart storyforge-monitor.service
sudo systemctl status storyforge-monitor.service
journalctl -u storyforge-monitor.service -n 200 --no-pager
```

## Troubleshooting

### Jobs list is slow

`/api/jobs` is intentionally **lightweight**. Heavy probes (CPU/GPU/log tail) are only on `/api/job/<id>`.

### “No jobs yet”

Means `monitor/jobs/*.json` is empty/missing. Re-run the monitored runner or inspect the `monitor/jobs/` directory.

### Job page stuck on “Loading…”

Usually indicates the job page JS is failing or `/api/job/<id>` is returning an unexpected JSON shape.

Check:

```bash
TOKEN=$(cat monitor/token.txt)
curl -s "http://127.0.0.1:8787/api/job/<id>?t=$TOKEN" | head
```

