#! /bin/bash
# This script watches the UART output of the ARTIQ server

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Monitoring ARTIQ server${NC}"
stty 115200 < /dev/ttyUSB2
cat /dev/ttyUSB2