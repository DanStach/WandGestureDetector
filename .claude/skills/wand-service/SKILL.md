---
name: wand-service
description: Start, stop, restart, or check the status/logs of the IR gesture system on the Raspberry Pi over SSH. Use when the user says "start/stop/restart the wand", "run it on the pi", or asks whether it's running.
---

# wand-service

Control the `ir-gesture.service` systemd unit on the Pi (`raspi@192.168.4.217`, repo at `~/WandGestureDetector`). Argument: `start`, `stop`, `restart`, `status` (default), or `logs`.

All commands run over SSH with `-o BatchMode=yes -o ConnectTimeout=10`. Use `sudo -n` so a missing sudo password fails fast instead of hanging; if it fails, report it and stop.

## Preflight (for start / restart)

1. Check the unit is installed: `systemctl cat ir-gesture.service`. If not found, install it from the repo (this is a persistent system change, so tell the user first):
   ```bash
   sudo -n cp ~/WandGestureDetector/deploy/ir-gesture.service /etc/systemd/system/ && sudo -n systemctl daemon-reload
   ```
2. Check the venv exists: `test -x ~/WandGestureDetector/.venv/bin/python`. If missing, stop and tell the user to run `scripts/setup-pi.sh` on the Pi (or follow the "On Raspberry Pi" section of CLAUDE.md). Don't build it unprompted.

## Actions

- **start**: `sudo -n systemctl start ir-gesture.service`, wait ~3s, then run the status check below.
- **stop**: `sudo -n systemctl stop ir-gesture.service`, then confirm `systemctl is-active` reports `inactive`.
- **restart**: `sudo -n systemctl restart ir-gesture.service`, wait ~3s, then status check.
- **status**: `systemctl is-active ir-gesture.service`, `systemctl is-enabled ir-gesture.service`, and `curl -s -m 5 http://localhost:8000/health` on the Pi.
- **logs**: `journalctl -u ir-gesture.service -n 50 --no-pager`.

## After start / restart

Verify it really came up: the service must be `active` and `/health` must respond. If not, pull the last 50 journal lines and summarize the failure (common causes: camera ribbon/`rpicam-hello --list-cameras` failing, missing venv packages, port 8000 in use). Don't loop on restarts.

## Boot-time enable

Only run `sudo -n systemctl enable ir-gesture.service` (or `disable`) if the user asks for start-on-boot behavior.

## Report

State the resulting active/inactive state and, when running, the web UI address `http://192.168.4.217:8000`.
