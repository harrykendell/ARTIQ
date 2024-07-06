#! /bin/bash
# This script installs the modules as per flake.nix into the windows_src file which is gitignored
# NB you may need to run this manually step by step

cd src

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

# ndscan
pip install -e "git+https://github.com/OxfordIonTrapGroup/ndscan.git#egg=ndscan"

# pydantic
pip install pydantic