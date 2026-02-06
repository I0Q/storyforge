# Storyforge Monitor

This folder contains the LAN-only, token-gated Storyforge Monitor web UI.

For full documentation, see: `docs/monitor.md`.

Quick start (dev):

```bash
cd /raid/storyforge_test
# create monitor/token.txt with a random token
python3 monitor/app.py --host 0.0.0.0 --port 8787 --root monitor
```

Then open:

- `http://<tinybox-ip>:8787/?t=<token>`

