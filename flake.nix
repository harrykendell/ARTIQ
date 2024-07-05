# {
#   inputs.artiq.url = "git+https://github.com/m-labs/artiq.git?ref=release-8";
#   inputs.extrapkg.url = "git+https://git.m-labs.hk/M-Labs/artiq-extrapkg.git?ref=release-8";
#   inputs.extrapkg.inputs.artiq.follows = "artiq";
#   outputs = { self, artiq, extrapkg }:
#     let
#       pkgs = artiq.inputs.nixpkgs.legacyPackages.x86_64-linux;
#       aqmain = artiq.packages.x86_64-linux;
#       aqextra = extrapkg.packages.x86_64-linux;

#       # BRING A PACKAGE IN FROM PIP  (we then include it below inside 'in') 
#       # sha256 comes from the .tar.gz url sha256 at https://pypi.org/pypi/$package/$version/json
#       # windfreak to control the RF synth
#       windfreak = pkgs.python3Packages.buildPythonPackage rec {
#         pname = "windfreak";
#         version = "0.3.0";
#         doCheck = false;
#         src = pkgs.python3Packages.fetchPypi {
#           inherit pname version;
#           sha256 = "d0ec652bc57aa630f38d34abd9eba938fb7aae8c4bd42ceb558eb38d170d8620";
#         };
#         };
#       # mqtt client
#       gmqtt = pkgs.python3Packages.buildPythonPackage rec {
#         pname = "gmqtt";
#         version = "0.6.12";
#         doCheck = false;
#         src = pkgs.python3Packages.fetchPypi {
#           inherit pname version;
#           sha256 = "7df03792343089ae62dc7cd6f8be356861c4fc68768cefa22f3d8de5e7e5be48";
#         };
#         };
#       # miniconf-mqtt
#       miniconf_mqtt_repo = pkgs.fetchgit {
#         url="https://github.com/quartiq/miniconf.git";
#         rev="d03726db064c61fdbaf55db4788fa56cc09ece10";
#         sha256 = "qP79+FNykNqyoaPrwYAvO2+Lvzdf7N+rNd6bKpp36gw=";
#         };
#       miniconf_mqtt = pkgs.python3Packages.buildPythonPackage rec {
#         name = "miniconf_mqtt";
#         version = "0.8.0";
#         src = "${miniconf_mqtt_repo}/py/miniconf-mqtt";
#         format = "pyproject";
#         dependencies = [pkgs.python3Packages.setuptools gmqtt];
#         };
#       # Booster control
#       booster_repo = pkgs.fetchgit {
#         url="https://github.com/quartiq/booster.git";
#         rev="a1f83b63180511ecd68f88a04621624941d17a41";
#         sha256 = "FS3tb6FFJxrYZQEJ4o+PNBiXmnh2T+qVRmueJmS5XL8=";
#         };
#       booster = pkgs.python3Packages.buildPythonPackage rec {
#         name = "booster";
#         version = "0.5.0";
#         src = "${booster_repo}/py";
#         format = "pyproject";
#         dependencies = [pkgs.python3Packages.setuptools miniconf_mqtt];
#         };
#       # end of packages

#     in {
#       defaultPackage.x86_64-linux = pkgs.buildEnv {
#         name = "artiq-env";
#         paths = [
#           # ========================================
#           # EDIT BELOW
#           # ========================================
#           (pkgs.python3.withPackages(ps: [
#             # List desired Python packages here.
#             aqmain.artiq
#             #ps.paramiko  # needed if and only if flashing boards remotely (artiq_flash -H)
#             aqextra.flake8-artiq

#             # The NixOS package collection contains many other packages that you may find
#             # interesting. Here are some examples:
#             ps.pandas
#             ps.numpy
#             ps.scipy
#             #ps.numba
#             ps.matplotlib
#             ps.pyqt5
#             # or if you need Qt (will recompile):
#             #(ps.matplotlib.override { enableQt = true; })
#             #ps.bokeh
#             #ps.cirq
#             #ps.qiskit
#             windfreak
#             miniconf_mqtt
#             booster
#           ]))
#           #aqextra.korad_ka3005p
#           #aqextra.novatech409b
#           # List desired non-Python packages here
#           aqmain.openocd-bscanspi  # needed if and only if flashing boards
#           # Other potentially interesting packages from the NixOS package collection:
#           #pkgs.gtkwave
#           #pkgs.spyder
#           #pkgs.R
#           #pkgs.julia
#           # ========================================
#           # EDIT ABOVE
#           # ========================================
#         ];
#       };

#     };
#   nixConfig = {  # work around https://github.com/NixOS/nix/issues/6771
#     extra-trusted-public-keys = "nixbld.m-labs.hk-1:5aSRVA5b320xbNvu30tqxVPXpld73bhtOeH6uAjRyHc=";
#     extra-substituters = "https://nixbld.m-labs.hk";
#   };
# }


{
  description = "Environment for running ARTIQ master in lab one/HOA2";

  inputs = {
    artiq.url = "git+https://github.com/m-labs/artiq.git?ref=release-8";
    extrapkg.url = "git+https://git.m-labs.hk/M-Labs/artiq-extrapkg.git?ref=release-8";
    extrapkg.inputs.artiq.follows = "artiq";

    # We pull Github packages in as flake inputs so we can conveniently update them
    # using `nix lock`, etc., rather than manually having to track hashes.
    src-ndscan = {
      url = "github:OxfordIonTrapGroup/ndscan";
      flake = false;
      };
    src-oitg = {
      url = "github:OxfordIonTrapGroup/oitg";
      flake = false;
      };
    src-oxart-devices = {
      url = "github:OxfordIonTrapGroup/oxart-devices";
      flake = false;
      };
    src-miniconf-mqtt = {
      url = "github:quartiq/miniconf";
      flake = false;
      };
    src-booster = {
      url = "github:quartiq/booster";
      flake = false;
      };
  };
  outputs = { self, artiq, src-ndscan, src-oitg, src-oxart-devices, src-miniconf-mqtt, src-booster}:
    let
      nixpkgs = artiq.nixpkgs;
      sipyco = artiq.inputs.sipyco;
      # PIP: sha256 comes from the .tar.gz url sha256 at https://pypi.org/pypi/$package/$version/json
      windfreak = nixpkgs.python3Packages.buildPythonPackage rec {
        pname = "windfreak";
        version = "0.3.0";
        doCheck = false;
        src = nixpkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "d0ec652bc57aa630f38d34abd9eba938fb7aae8c4bd42ceb558eb38d170d8620";
        };
        };
      gmqtt = nixpkgs.python3Packages.buildPythonPackage rec {
        pname = "gmqtt";
        version = "0.6.12";
        doCheck = false;
        src = nixpkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "7df03792343089ae62dc7cd6f8be356861c4fc68768cefa22f3d8de5e7e5be48";
        };
        };
      oitg = nixpkgs.python3Packages.buildPythonPackage {
        name = "oitg";
        src = src-oitg;
        format = "pyproject";
        propagatedBuildInputs = with nixpkgs.python3Packages; [
          h5py
          scipy
          statsmodels
          nixpkgs.python3Packages.poetry-core
          nixpkgs.python3Packages.poetry-dynamic-versioning
        ];
        # Whatever magic `setup.py test` does by default fails for oitg.
        installCheckPhase = ''
          ${nixpkgs.python3.interpreter} -m unittest discover test
        '';
        };
      ndscan = nixpkgs.python3Packages.buildPythonPackage {
        name = "ndscan";
        src = src-ndscan;
        format = "pyproject";
        propagatedBuildInputs = [
          artiq.packages.x86_64-linux.artiq
          oitg
          nixpkgs.python3Packages.poetry-core
          nixpkgs.python3Packages.pyqt6
        ];
        # ndscan depends on pyqtgraph>=0.12.4 to display 2d plot colorbars, but this
        # is not yet in nixpkgs 23.05. Since this flake will mostly be used for
        # server-(master-)side installations, just patch it out for now. In theory,
        # pythonRelaxDepsHook should do this more elegantly, but it does not seem to
        # be run before pipInstallPhase.
        # FIXME: qasync/sipyco/oitg dependencies which explicitly specify a Git source
        # repo do not seem to be matched by the packages pulled in via Nix; what is the
        # correct approach here?
        postPatch = ''
          sed -i -e "s/^pyqtgraph = .*//" pyproject.toml
          sed -i -e "s/^qasync = .*//" pyproject.toml
          sed -i -e "s/^sipyco = .*//" pyproject.toml
          sed -i -e "s/^oitg = .*//" pyproject.toml
        '';
        dontWrapQtApps = true; # Pulled in via the artiq package; we don't care.
        };
      oxart-devices = nixpkgs.python3Packages.buildPythonPackage {
        name = "oxart-devices";
        src = src-oxart-devices;
        format = "pyproject";
        propagatedBuildInputs = [
          nixpkgs.python3Packages.appdirs
          oitg
          sipyco.packages.x86_64-linux.sipyco
        ];
        # Need to manually remove .pyc files conflicting with oxart (both share the
        # oxart.* namespace).
        postFixup = ''
          rm -r $out/${nixpkgs.python3.sitePackages}/oxart/__pycache__
        '';
        # Auto-discovery pulls in some ``test`` modules for manual interactive testing
        # (that also require Windows and/or hardware).
        doCheck = false;
        };
      miniconf-mqtt = nixpkgs.python3Packages.buildPythonPackage {
        name = "miniconf_mqtt";
        src = "${src-miniconf-mqtt}/py/miniconf-mqtt";
        format = "pyproject";
        propagatedBuildInputs = [
          gmqtt
        ];
        };
      booster = nixpkgs.python3Packages.buildPythonPackage {
        name = "booster";
        src = src-booster;
        format = "pyproject";
        propagatedBuildInputs = [
          miniconf-mqtt
        ];
        };
      python-env = (nixpkgs.python3.withPackages (ps:
        (with ps; [ aiohttp h5py influxdb llvmlite numba pyzmq pandas numpy scipy pyqt5 matplotlib]) ++ [
          # ARTIQ will pull in a large number of transitive dependencies, most of which
          # we also rely on. Currently, it is a bit overly generous, though, in that it
          # pulls in all the requirements for a full GUI and firmware development
          # install (Qt, Rust, etc.). Could slim down if disk usage ever becomes an
          # issue.
          aqmain.artiq
          windfreak
          ndscan
          oitg
          oxart-devices
          miniconf-mqtt
          booster
        ]));
      artiq-master-dev = nixpkgs.mkShell {
        name = "artiq-master-dev";
        buildInputs = [
          python-env
          aqmain.openocd-bscanspi
          nixpkgs.julia_19-bin
          nixpkgs.lld_14
          nixpkgs.llvm_14
          nixpkgs.libusb-compat-0_1
        ];
        shellHook = ''
            export QT_PLUGIN_PATH=${nixpkgs.qt5.qtbase}/${nixpkgs.qt5.qtbase.dev.qtPluginPrefix}
            export QML2_IMPORT_PATH=${nixpkgs.qt5.qtbase}/${nixpkgs.qt5.qtbase.dev.qtQmlPrefix}
        '';
        postShellHook = ''
          PYTHONPATH = ${nixpkgs.python3.sitePackages}:$PYTHONPATH
          echo "To use the ARTIQ master environment, run 'artiq-master' in this shell."
        '';
      };
    in {
      defaultPackage.x86_64-linux = artiq-master-dev;
    };

  nixConfig = { # work around https://github.com/NixOS/nix/issues/6771
    extra-trusted-public-keys = "nixbld.m-labs.hk-1:5aSRVA5b320xbNvu30tqxVPXpld73bhtOeH6uAjRyHc=";
    extra-substituters = "https://nixbld.m-labs.hk";
  };
}
