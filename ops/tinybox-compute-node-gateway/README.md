# tinybox-compute-node-gateway

This folder is a **versioned snapshot** of the gateway code deployed on the DO droplet `sf-cloud-1`.

- Live path (droplet): `/opt/tinybox-compute-node-gateway/app/main.py`
- Service: `tinybox-compute-node-gateway.service`
- Listens (VPC-only): `http://10.108.0.3:8791`
- Forwards to Tinybox over Tailscale: `http://100.75.30.1:8790`

Note: deployment is currently managed directly on the droplet (systemd + venv). This snapshot prevents drift/loss.
