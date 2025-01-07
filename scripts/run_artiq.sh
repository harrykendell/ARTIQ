#! /bin/bash
nix shell --command bash -c '. nix-fix-pyqt.sh ; (python ../ThorlabsPM/ThorlabsPM.py &) ; artiq_session -d="-p=ndscan.dashboard_plugin"'
