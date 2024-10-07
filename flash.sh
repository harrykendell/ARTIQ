#! /bin/bash
# This script builds and flashes the latest artiq release-8 firmware to the crate

# ensure packages are up to date
./env.sh
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# check for required build tool
if [[ -d /opt/Xilinx/Vivado/2022.2 ]]; then
    echo -e "${GREEN}Vivado 2020.2 found, flashing artiq crate${NC}"
    cd src/artiq

    # ensure the reference device_db reflects the currently flashed details
    nix develop --command bash -c "artiq_ddb_template ../../crate\ config/bu2402001.json > ../../crate\ config/device_db.py"
    
    # build firmware - 8.0+
    nix develop --command bash -c "export PYTHONPATH=$(pwd):$PYTHONPATH"
    nix develop --command bash -c "python -m artiq.gateware.targets.kasli ../../crate\ config/bu2402001.json"

    # flash crate
    cp -TR artiq_kasli/bu2402001 ../../crate\ config/bu2402001_current
    nix develop --command bash -c "artiq_flash --srcbuild -d artiq_kasli/bu2402001"

    echo -e "${GREEN}Flashing complete, firmware updated in 'crate config/bu2402001_current'${NC}"
else
    echo -e "${RED}Vivado 2020.2 not found, cannot build and flash artiq crate${NC}"
fi
