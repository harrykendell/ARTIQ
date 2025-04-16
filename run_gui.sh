#! /bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
cd $SCRIPT_DIR

# ARTIQ
SERVER_ADDRESS=137.222.69.28

# check if we are running on the artiq server or not
# NB the truthiness is a return code - i.e. 0 is success
# and > 0 is failure
on_server() {
    IP_ADDRESSES=$(hostname -I 2>/dev/null)
    # Loop through each IP address in the list
    found=0
    for ip in $IP_ADDRESSES; do
        if [[ "$ip" == "$SERVER_ADDRESS" ]]; then
            return 0
            break
        fi
    done
    return 1
}
on_ssh() {
    if [[ $SSH_CONNECTION ]]; then
        return 0
    else
        return 1
    fi
}
check_localhost() {
    local ips
    ips=$(getent ahostsv4 localhost | awk '{print $1}' | sort -u)

    if echo "$ips" | grep -q '127.0.0.1'; then
        return 0
    fi
    return 1
}


# Running locally on server - we run everything locally
if on_server && ! on_ssh; then
    echo -e "${GREEN}Running locally on the ARTIQ server${NC}"
    if check_localhost; then
        echo -e "${RED}WARNING: /etc/hosts has localhost set for remote use.\nThis may cause issues in the system\nPlease reset it to 127.0.1.1${NC}"
        exit 1
    fi
    tmux new -d -s ThorlabsPM "nix shell --command bash -c \"python ./ThorlabsPM/ThorlabsPM.py\""
    nix shell --command bash -c "artiq_dashboard -v --server=\"$SERVER_ADDRESS\" -p ndscan.dashboard_plugin"
    exit 0
fi

# Running remotely on server - we forward to the client
if on_server; then
    if ! check_localhost; then
        echo -e "${RED}WARNING: /etc/hosts has localhost set to 127.0.1.1.\nThis will prevent X-forwarding.\nPlease set it to 127.0.0.1${NC}"
        exit 1
    fi
    echo -e "${GREEN}Remotely running on the ARTIQ server${NC}"
    #  PyQt5 and SO fix
    FIX=". ./scripts/nix-fix-pyqt.sh ; export LD_LIBRARY_PATH=$(find /nix/store -type d -wholename '/nix/store/*artiq-env/lib')"
    nix shell --command bash -c "$FIX ; artiq_dashboard -v --server=\"$SERVER_ADDRESS\" -p=\"ndscan.dashboard_plugin\""
    exit 0
fi

# Running locally on a different machine - we run everything locally
echo -e "${GREEN}Not running on the ARTIQ server${NC}"
(python repository/gui/ArtiqGUI.py) &

# who knows if they have nix installed
if command -v nix 2>&1 >/dev/null; then
    nix shell --command bash -c "artiq_dashboard -v --server=\"$SERVER_ADDRESS\" -p=\"ndscan.dashboard_plugin\""
else
    artiq_dashboard -v --server="$SERVER_ADDRESS" -p="ndscan.dashboard_plugin"
fi
