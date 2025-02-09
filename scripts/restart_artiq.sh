#! /bin/bash
# This script restarts the crate

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# The directory where the script is located
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
# go to the main artiq directory
cd $SCRIPT_DIR/..

nix shell --command bash -c "artiq_flash start"