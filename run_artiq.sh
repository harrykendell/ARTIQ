#! /bin/bash

# The directory where the script is located
SCRIPT_DIR="$(dirname "$(realpath "$0")")"

# Check if the script is run from the expected directory
if [ "$SCRIPT_DIR" != "$(pwd)" ]; then
    # Warn the user if the script is not run from the expected directory
    RED='\033[0;31m'
    NC='\033[0m' # No Color

    echo -e "${RED}Error: This script must be run from its directory $SCRIPT_DIR"
    echo -e "Changing directory to $SCRIPT_DIR${NC}"
    cd $SCRIPT_DIR
fi


#  PyQt5 fix
FIX=". ./scripts/nix-fix-pyqt.sh"

# ThorlabsPM
TLPM="(python ./ThorlabsPM/ThorlabsPM.py &)"

# ARTIQ
SERVER_ADDRESS=137.222.69.28
ARTIQ="artiq_session -d=\"-s=$SERVER_ADDRESS\" -d=\"-p=ndscan.dashboard_plugin\" -m=\"--bind=$SERVER_ADDRESS\" -c=\"--bind=$SERVER_ADDRESS\" -c=\"-s=$SERVER_ADDRESS\""


# check if we are running on the artiq server or not
IP_ADDRESSES=$(hostname -I 2>/dev/null);
if [[$IP_ADDRESSES == *"$SERVER_ADDRESS"*]]; then
    echo -e "${GREEN}Running on the ARTIQ server${NC}"
    nix shell --command bash -c "$FIX ; $TLPM ; $ARTIQ"
else
    echo -e "${RED}Not running on the ARTIQ server${NC}"
    artiq_dashboard --server="$SERVER_ADDRESS" -p ndscan.dashboard_plugin
fi

# nix shell --command bash -c '. ./scripts/nix-fix-pyqt.sh ; (python ./ThorlabsPM/ThorlabsPM.py &) ; artiq_session -d="-s=137.222.69.28" -d="-p=ndscan.dashboard_plugin" -m="--bind=137.222.69.28" -c="--bind=137.222.69.28"'
