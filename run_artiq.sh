#! /bin/bash
nix shell --command bash -c '. nix-fix-pyqt.sh ; (python ./powermeter/plot.py &) ; artiq_session -d="-p=ndscan.dashboard_plugin"'
