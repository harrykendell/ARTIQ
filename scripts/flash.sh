#! /bin/bash
# This script builds and flashes the latest artiq release-8 firmware to the crate

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# The directory where the script is located
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
# go to the main artiq directory
cd $SCRIPT_DIR/..

echo $(pwd)
# check for required build tool
TOOL_PATH="$(grep 'set -e; source /opt/Xilinx/Vivado' src/artiq/flake.nix | grep -Po '/opt/Xilinx/Vivado/[0-9]+\.[0-9]+')"

if [[ -d $TOOL_PATH ]]; then
    echo -e "${GREEN}${TOOL_PATH} found, flashing artiq crate${NC}"

    # ensure the reference device_db reflects the currently flashed details
    nix develop git+https://github.com/m-labs/artiq.git/?ref=release-8#boards --command bash -c "artiq_ddb_template crate\ config/bu2402001.json > crate\ config/device_db.py"

    # build firmware - 8.0+
    nix develop git+https://github.com/m-labs/artiq.git/?ref=release-8#boards --command bash -c "python -m artiq.gateware.targets.kasli crate\ config/bu2402001.json"

    # flash crate
    cp -TR artiq_kasli/bu2402001 crate\ config/bu2402001_current && rm -rf artiq_kasli
    nix develop git+https://github.com/m-labs/artiq.git/?ref=release-8#boards --command bash -c "artiq_flash --srcbuild -d crate\ config/bu2402001_current"

    echo -e "${GREEN}Flashing complete, firmware updated in 'crate config/bu2402001_current'${NC}"
else
    echo -e "${RED}${TOOL_PATH} not found, cannot build and flash artiq crate${NC}"
    echo -e "Available versions:\n$(ls /opt/Xilinx/Vivado)"
fi
