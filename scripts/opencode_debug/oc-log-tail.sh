#!/usr/bin/env bash
set -euo pipefail

LINES="${1:-200}"
tail -n "$LINES" "$(ls -t /root/.local/share/opencode/log/*.log | head -1)"
