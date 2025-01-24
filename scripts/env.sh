#! /bin/bash
# This script installs the modules as per flake.nix src directory which is gitignored
# NB you may need to run this manually step by step if you have issues
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color
pip list | sort >start_pip_list.txt
# Windfreak
pip install windfreak

# pco
pip install pco

# toptica laser
pip install toptica-lasersdk

# aiomqtt
pip install aiomqtt

# Booster
pip install -e "git+https://github.com/quartiq/booster.git@a1f83b63180511ecd68f88a04621624941d17a41#subdirectory=py/&egg=booster"

# miniconf-mqtt
pip install -e "git+https://github.com/quartiq/miniconf.git@d03726db064c61fdbaf55db4788fa56cc09ece10#subdirectory=py/miniconf-mqtt&egg=miniconf-mqtt"

# oitg
pip install -e "git+https://github.com/OxfordIonTrapGroup/oitg.git#egg=oitg"

# oxart-devices
pip install -e "git+https://github.com/OxfordIonTrapGroup/oxart-devices.git#egg=oxart-devices"

# artiq - we currently target whatever is on the release-8 branch to avoid any potentially artiq 9.0+unknown breaking changes
pip install -e "git+https://github.com/m-labs/artiq.git@release-8#egg=artiq"

# artiq-comtools
pip install -e "git+https://github.com/m-labs/artiq-comtools.git#egg=artiq-comtools"

# ndscan
pip install -e "git+https://github.com/OxfordIonTrapGroup/ndscan.git#egg=ndscan"

# pydantic
pip install pydantic

############        POST INSTALLATION CHECKS        ############
pip list | sort >end_pip_list.txt

echo -e "\n\n${GREEN}Installed packages:${NC}\n"
pip list | grep 'windfreak\|pco\|booster\|miniconf-mqtt\|oitg\|oxart-devices\|artiq\|ndscan\|pydantic'

echo -e "\n\n${GREEN}Diff:${NC}\n"
diff --color=always start_pip_list.txt end_pip_list.txt

rm start_pip_list.txt end_pip_list.txt

# Conda installed artiq doesn't properly link the site-packages to the python3.10 site-packages
# You may need to run the following commands
#  cd ~/anaconda3/envs/artiq/site-packages
#  for file in *
#  do
#   ln -sf ../../../site-packages/$file ../lib/python3.10/site-packages/$file
#  done
