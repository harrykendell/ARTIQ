#! /bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

#  PyQt5 and SO fix
FIX=". ./scripts/nix-fix-pyqt.sh ; export LD_LIBRARY_PATH=$(find /nix/store -type d -wholename '/nix/store/*artiq-env/lib')"

# ThorlabsPM
TLPM="(python ./ThorlabsPM/ThorlabsPM.py &)"

# ARTIQ
SERVER_ADDRESS=137.222.69.28

# check if we are running on the artiq server or not
IP_ADDRESSES=$(hostname -I 2>/dev/null)
# Loop through each IP address in the list
found=0
for ip in $IP_ADDRESSES; do
    if [[ "$ip" == "$SERVER_ADDRESS" ]]; then
        found=1
        break
    fi
done

# Run the ARTIQ dashboard with the target IP if found
if [[ $found -eq 1 ]]; then
    echo -e "${GREEN}Running on the ARTIQ server${NC}"
    bash -c "$TLPM ; artiq_dashboard -v --server=\"$SERVER_ADDRESS\" -p ndscan.dashboard_plugin"
else
    echo -e "${RED}Not running on the ARTIQ server${NC}"
    (python repository/gui/ArtiqGUI.py) &
    artiq_dashboard -v --server="$SERVER_ADDRESS" -p="ndscan.dashboard_plugin"
fi
