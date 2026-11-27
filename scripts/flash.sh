#!/bin/bash
# Always use the qualified firmware pinned in crate config/firmware.json.
set -euo pipefail
# Non-interactive lab SSH sessions may not source the Nix profile.
if ! command -v nix >/dev/null 2>&1; then
    export PATH="$HOME/.nix-profile/bin:/nix/var/nix/profiles/default/bin:$PATH"
fi
exec python3 "$(dirname "$(realpath "$0")")/firmware.py" "$@"
