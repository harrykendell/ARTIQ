#! /bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

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
cat /dev/null >artiq.log

#  PyQt5 and SO fix
FIX=". ./scripts/nix-fix-pyqt.sh ; export LD_LIBRARY_PATH=$(find /nix/store -type d -wholename '/nix/store/*artiq-env/lib')"

# ARTIQ
SERVER_ADDRESS=137.222.69.28

function on_exit {
    sleep 1
    pkill -9 -f aqctl
    echo "killed aqctl processes on exit"
    exit
}

function artiq_stack {
    MASTER="\"artiq_master -v --repository . --experiment-subdir repository --log-file artiq.log --bind=$SERVER_ADDRESS --name 'GECKO ARTIQ'\""
    CTLMGR="\"sleep 1 && controllers/artiq_ctlmgr.py --bind=$SERVER_ADDRESS -s=$SERVER_ADDRESS -v\""
    JANITOR="\"sleep 1 && ndscan_dataset_janitor\""

    NAMES="master,ctlmgr,janitor"
    CMDS="${MASTER} ${CTLMGR} ${JANITOR}"
    nix shell --command bash -c "concurrently -c=auto --kill-others --prefix='{name} {time}' --timestamp-format='yyyy-MM-dd HH:mm:ss' -n ${NAMES} ${CMDS}"
}

# Run the full ARTIQ stack
echo -e "${NC}Starting up the full stack${NC}"
# if not tmux then warn the user
if [ -z "$TMUX" ]; then
    echo -e "\n${RED}WARNING: You are not running in tmux.\nThis will cause issues if you lose your\nconnection.${NC}\n"

    # check if the user wants to run in the background
    read -p "Do you want to run in the background? (y/n) " answer
    if [[ $answer == "y" || $answer == "Y" ]]; then
        # run in the background
        echo -e "${GREEN}Running in the background${NC}"
        tmux new -s artiq "./run_stack.sh"
        exit 0
    fi
fi

# Be good citizens and clean up old aqctls on exit
trap on_exit SIGCHLD
artiq_stack
