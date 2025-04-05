#! /bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(dirname "$(realpath "$0")")"

# Be good citizens and clean up old aqctls on exit
clean_up() {
    sleep 1
    pkill -9 -f aqctl
    echo "killed aqctl processes on exit"
}

artiq_stack() {
    # PyQt5 and .so fix
    FIX=". ${SCRIPT_DIR}/scripts/nix-fix-pyqt.sh ; export LD_LIBRARY_PATH=$(find /nix/store -type d -wholename '/nix/store/*artiq-env/lib') ; export DISPLAY=127.0.0.1:10.0"

    # ARTIQ
    SERVER_ADDRESS=137.222.69.28
    MASTER="\"artiq_master -v --repository ${SCRIPT_DIR} --experiment-subdir repository --log-file ${SCRIPT_DIR}/artiq.log --bind=$SERVER_ADDRESS --name 'GECKO ARTIQ'\""
    CTLMGR="\"sleep 1 && ${SCRIPT_DIR}/controllers/artiq_ctlmgr.py --bind=$SERVER_ADDRESS -s=$SERVER_ADDRESS -v\""
    JANITOR="\"sleep 1 && ndscan_dataset_janitor\""

    NAMES="master,ctlmgr,janitor"
    CMDS="${MASTER} ${CTLMGR} ${JANITOR}"
    nix shell --command bash -c "${FIX} ; concurrently -c=auto --kill-others --prefix='{name} {time}' --timestamp-format='yyyy-MM-dd HH:mm:ss' -n ${NAMES} ${CMDS}"
}

check_tmux() {
    if [ -z "$TMUX" ]; then
        echo -e "\n${RED}WARNING: You are not running in tmux."
        echo -e "This will terminate artiq if you close"
        echo -e "the terminal or drop your ssh session.${NC}\n"
        # check if the user wants to run in the background
        read -p "Do you want to run in a tmux session? (y/n)" answer
        tput cuu1 && tput el  # Move cursor up one line and clear the line
        if [[ $answer == "y" || $answer == "Y" ]]; then
            # run in the background
            echo -e "Running in the background"
            tmux new -d -s artiq "$0"
            exit 0
        fi
    fi
}

# Run the full ARTIQ stack
echo -e "${NC}Starting up the full stack${NC}"
cd $SCRIPT_DIR
cat /dev/null > artiq.log
check_tmux
trap clean_up SIGCHLD
artiq_stack
