#! /bin/bash
# this script compiles and flashes the kernels located in ../repository/kernels
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
cd $SCRIPT_DIR/..

echo -e "${RED}This script must be run in a nix shell\n${GREEN}Compiling and flashing kernels...${NC}"
for TYPE in idle startup; do
    artiq_compile $SCRIPT_DIR/../repository/kernels/$TYPE\_kernel.py
    artiq_coremgmt config write -f $TYPE\_kernel $SCRIPT_DIR/../repository/kernels/$TYPE\_kernel.elf
done
