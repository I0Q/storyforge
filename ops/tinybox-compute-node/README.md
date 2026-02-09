# tinybox-compute-node (snapshot)

This folder is a **versioned snapshot** of the Tinybox compute provider service as deployed on Tinybox.

- Live path (Tinybox): `/raid/tinybox-compute-node/app/main.py`
- Service: `tinybox-compute-node.service`
- Listens (Tailscale): `http://100.75.30.1:8790`
- Token file (Tinybox): `~/.config/tinybox-compute-node/token`

Why snapshot? The Tinybox service directory may not be a git clone on the machine; this prevents code drift/loss.
