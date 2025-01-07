#! /bin/bash
# This script sets the PyQt5 environment variables that are missing in the Nix build.
# Without these variables PyQt5 programs will crash unless explicitly hooked like artiq_dashboard.
if [ ${_} != ${0} ]; then
    export QT_PLUGIN_PATH=$(find /nix/store -maxdepth 4 -mindepth 4 -wholename '/*/lib/qt-5.15.15/plugins' | paste -sd ":" -)
    export QT_XCB_GL_INTEGRATION=none
    unset XDG_SESSION_TYPE

    # This avoids the error: qt.qpa.plugin: Could not find the Qt platform plugin "wayland" in ""
    export QT_QPA_PLATFORM=xcb
    # this avoids the error: Gtk-WARNING **: 18:37:02.039: Locale not supported by C library. Using the fallback 'C' locale.
    export LANG=C
    echo -e "PyQt5 environment variables set"
else
    RED='\033[0;31m'
    NC='\033[0m' # No Color
    echo -e "This script must be run with the dot space script syntax, as in \n${RED}. nix-fix-pyqt.sh${NC}"
    echo -e "Otherwise it cannot export environment variables into your shell"
fi