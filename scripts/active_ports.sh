#! /bin/bash
# This script installs the modules as per flake.nix src directory which is gitignored
# NB you may need to run this manually step by step if you have issues
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# We dont care about failures here
set +e

echo -e "${GREEN}Core device management :1380${NC}"
sudo netstat -nlp | grep ':1380'

echo -e "${GREEN}Core device main :1381${NC}"
sudo netstat -nlp | grep ':1381'

echo -e "${GREEN}Core device analyzer :1382${NC}"
sudo netstat -nlp | grep ':1382'

echo -e "${GREEN}MonInj core device or proxy :1383${NC}"
sudo netstat -nlp | grep ':1383'

echo -e "${GREEN}MonInj proxy control :1384${NC}"
sudo netstat -nlp | grep ':1384'

echo -e "${GREEN}Core analyzer proxy proxy :1385${NC}"
sudo netstat -nlp | grep ':1385'

echo -e "${GREEN}Core analyzer proxy control :1386${NC}"
sudo netstat -nlp | grep ':1386'

echo -e "${GREEN}Master logging input :1066${NC}"
sudo netstat -nlp | grep ':1066'

echo -e "${GREEN}Master broadcasts :1067${NC}"
sudo netstat -nlp | grep ':1067'

echo -e "${GREEN}Core device logging controller :1068${NC}"
sudo netstat -nlp | grep ':1068'

echo -e "${GREEN}InfluxDB bridge :3248${NC}"
sudo netstat -nlp | grep ':3248'

echo -e "${GREEN}Controller manager :3249${NC}"
sudo netstat -nlp | grep ':3249'

echo -e "${GREEN}Master notifications :3250${NC}"
sudo netstat -nlp | grep ':3250'

echo -e "${GREEN}Master control :3251${NC}"
sudo netstat -nlp | grep ':3251'

echo -e "${GREEN}PDQ2 out-of-tree :3252${NC}"
sudo netstat -nlp | grep ':3252'

echo -e "${GREEN}LDA out-of-tree :3253${NC}"
sudo netstat -nlp | grep ':3253'

echo -e "${GREEN}Novatech 409B out-of-tree :3254${NC}"
sudo netstat -nlp | grep ':3254'

echo -e "${GREEN}Thorlabs T-Cube out-of-tree :3255${NC}"
sudo netstat -nlp | grep ':3255'

echo -e "${GREEN}Korad KA3005P out-of-tree :3256${NC}"
sudo netstat -nlp | grep ':3256'

echo -e "${GREEN}Newfocus 8742 out-of-tree :3257${NC}"
sudo netstat -nlp | grep ':3257'

echo -e "${GREEN}PICam out-of-tree :3258${NC}"
sudo netstat -nlp | grep ':3258'

echo -e "${GREEN}PTB Drivers out-of-tree :3259${NC}"
sudo netstat -nlp | grep ':3259'

echo -e "${GREEN}TOPTICA Laser Publisher out-of-tree :3271${NC}"
sudo netstat -nlp | grep ':3271'

echo -e "${GREEN}TOPTICA Laser SDK out-of-tree :3272${NC}"
sudo netstat -nlp | grep ':3272'

echo -e "${GREEN}HighFinesse out-of-tree :3273${NC}"
sudo netstat -nlp | grep ':3273'

echo -e "${GREEN}InfluxDB schedule bridge :3275${NC}"
sudo netstat -nlp | grep ':3275'

echo -e "${GREEN}InfluxDB driver out-of-tree :3276${NC}"
sudo netstat -nlp | grep ':3276'

set -e