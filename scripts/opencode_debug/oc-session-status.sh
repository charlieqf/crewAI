#!/usr/bin/env bash
set -euo pipefail

curl -s http://localhost:4096/session/status | python3 -m json.tool
