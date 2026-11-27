#!/bin/bash
# Always use the qualified firmware pinned in crate config/firmware.json.
set -euo pipefail
exec python3 "$(dirname "$(realpath "$0")")/firmware.py" "$@"
