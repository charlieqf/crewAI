#!/usr/bin/env bash
set -euo pipefail

MINUTES="${1:-10}"
journalctl -u wecom-callback --since "${MINUTES} min ago" --no-pager | tail -n 200
