#! /bin/bash
# This script installs the modules as per flake.nix src directory which is gitignored
# NB you may need to run this manually step by step

# Windfreak
pip install windfreak==0.3.0

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

# ndscan
pip install -e "git+https://github.com/OxfordIonTrapGroup/ndscan.git#egg=ndscan"

# pydantic
pip install pydantic

# Check the installed packages - we should see if any of the above failed
echo -e "\n\nInstalled packages:\n"
pip list | grep 'windfreak\|booster\|miniconf-mqtt\|oitg\|oxart-devices\|artiq\|ndscan\|pydantic'