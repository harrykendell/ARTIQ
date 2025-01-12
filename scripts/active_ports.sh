#! /bin/bash
# This script installs the modules as per flake.nix src directory which is gitignored
# NB you may need to run this manually step by step if you have issues
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# We dont care about failures here
set +e

echo -e "${GREEN}Core device management${NC}"
sudo netstat -nlp | grep '1380'

echo -e "${GREEN}Core device main${NC}"
sudo netstat -nlp | grep '1381'

echo -e "${GREEN}Core device analyzer${NC}"
sudo netstat -nlp | grep '1382'

echo -e "${GREEN}MonInj core device or proxy${NC}"
sudo netstat -nlp | grep '1383'

echo -e "${GREEN}MonInj proxy control${NC}"
sudo netstat -nlp | grep '1384'

echo -e "${GREEN}Core analyzer proxy proxy${NC}"
sudo netstat -nlp | grep '1385'

echo -e "${GREEN}Core analyzer proxy control${NC}"
sudo netstat -nlp | grep '1386'

echo -e "${GREEN}Master logging input${NC}"
sudo netstat -nlp | grep '1066'

echo -e "${GREEN}Master broadcasts${NC}"
sudo netstat -nlp | grep '1067'

echo -e "${GREEN}Core device logging controller${NC}"
sudo netstat -nlp | grep '1068'

echo -e "${GREEN}InfluxDB bridge${NC}"
sudo netstat -nlp | grep '3248'

echo -e "${GREEN}Controller manager${NC}"
sudo netstat -nlp | grep '3249'

echo -e "${GREEN}Master notifications${NC}"
sudo netstat -nlp | grep '3250'

echo -e "${GREEN}Master control${NC}"
sudo netstat -nlp | grep '3251'

echo -e "${GREEN}PDQ2 out-of-tree${NC}"
sudo netstat -nlp | grep '3252'

echo -e "${GREEN}LDA out-of-tree${NC}"
sudo netstat -nlp | grep '3253'

echo -e "${GREEN}Novatech 409B out-of-tree${NC}"
sudo netstat -nlp | grep '3254'

echo -e "${GREEN}Thorlabs T-Cube out-of-tree${NC}"
sudo netstat -nlp | grep '3255'

echo -e "${GREEN}Korad KA3005P out-of-tree${NC}"
sudo netstat -nlp | grep '3256'

echo -e "${GREEN}Newfocus 8742 out-of-tree${NC}"
sudo netstat -nlp | grep '3257'

echo -e "${GREEN}PICam out-of-tree${NC}"
sudo netstat -nlp | grep '3258'

echo -e "${GREEN}PTB Drivers out-of-tree${NC}"
sudo netstat -nlp | grep '3259'

echo -e "${GREEN}HUT2 out-of-tree${NC}"
sudo netstat -nlp | grep '3271'

echo -e "${GREEN}TOPTICA Laser SDK out-of-tree${NC}"
sudo netstat -nlp | grep '3272'

echo -e "${GREEN}HighFinesse out-of-tree${NC}"
sudo netstat -nlp | grep '3273'

echo -e "${GREEN}InfluxDB schedule bridge${NC}"
sudo netstat -nlp | grep '3275'

echo -e "${GREEN}InfluxDB driver out-of-tree${NC}"
sudo netstat -nlp | grep '3276'

set -e