{
  inputs.artiq.url = "git+https://github.com/m-labs/artiq.git?ref=release-8";
  inputs.extrapkg.url = "git+https://git.m-labs.hk/M-Labs/artiq-extrapkg.git?ref=release-8";
  inputs.extrapkg.inputs.artiq.follows = "artiq";
  outputs = { self, artiq, extrapkg }:
    let
      pkgs = artiq.inputs.nixpkgs.legacyPackages.x86_64-linux;
      aqmain = artiq.packages.x86_64-linux;
      aqextra = extrapkg.packages.x86_64-linux;

      # BRING A PACKAGE IN FROM PIP  (we then include it below inside 'in') 
      # sha256 comes from the .tar.gz url sha256 at https://pypi.org/pypi/$package/$version/json
      # windfreak to control the RF synth
      windfreak = pkgs.python3Packages.buildPythonPackage rec {
        pname = "windfreak";
        version = "0.3.0";
        doCheck = false;
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "d0ec652bc57aa630f38d34abd9eba938fb7aae8c4bd42ceb558eb38d170d8620";
        };
      };
      # mqtt client
      gmqtt = pkgs.python3Packages.buildPythonPackage rec {
        pname = "gmqtt";
        version = "0.6.12";
        doCheck = false;
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "7df03792343089ae62dc7cd6f8be356861c4fc68768cefa22f3d8de5e7e5be48";
        };
      };
      # miniconf-mqtt
      miniconf_mqtt_repo = pkgs.fetchgit {
        url="https://github.com/quartiq/miniconf.git";
        rev="d03726db064c61fdbaf55db4788fa56cc09ece10";
        sha256 = "qP79+FNykNqyoaPrwYAvO2+Lvzdf7N+rNd6bKpp36gw=";
      };
      miniconf_mqtt = pkgs.python3Packages.buildPythonPackage rec {
        name = "miniconf_mqtt";
        version = "0.8.0";
        src = "${miniconf_mqtt_repo}/py/miniconf-mqtt";
        format = "pyproject";
        dependencies = [pkgs.python3Packages.setuptools gmqtt];
      };
      # Booster control
      booster_repo = pkgs.fetchgit {
        url="https://github.com/quartiq/booster.git";
        rev="a1f83b63180511ecd68f88a04621624941d17a41";
        sha256 = "FS3tb6FFJxrYZQEJ4o+PNBiXmnh2T+qVRmueJmS5XL8=";
      };
      booster = pkgs.python3Packages.buildPythonPackage rec {
        name = "booster";
        version = "0.5.0";
        src = "${booster_repo}/py";
        format = "pyproject";
        dependencies = [pkgs.python3Packages.setuptools miniconf_mqtt];
      };

      # end of packages


    in {
      defaultPackage.x86_64-linux = pkgs.buildEnv {
        name = "artiq-env";
        paths = [
          # ========================================
          # EDIT BELOW
          # ========================================
          (pkgs.python3.withPackages(ps: [
            # List desired Python packages here.
            aqmain.artiq
            #ps.paramiko  # needed if and only if flashing boards remotely (artiq_flash -H)
            aqextra.flake8-artiq

            # The NixOS package collection contains many other packages that you may find
            # interesting. Here are some examples:
            ps.pandas
            ps.numpy
            ps.scipy
            #ps.numba
            ps.matplotlib
            ps.pyqt5
            # or if you need Qt (will recompile):
            #(ps.matplotlib.override { enableQt = true; })
            #ps.bokeh
            #ps.cirq
            #ps.qiskit
            windfreak
            miniconf_mqtt
            booster
          ]))
          #aqextra.korad_ka3005p
          #aqextra.novatech409b
          # List desired non-Python packages here
          aqmain.openocd-bscanspi  # needed if and only if flashing boards
          # Other potentially interesting packages from the NixOS package collection:
          #pkgs.gtkwave
          #pkgs.spyder
          #pkgs.R
          #pkgs.julia
          # ========================================
          # EDIT ABOVE
          # ========================================
        ];
        # We want to include QT Plugin details on the path
        postBuild = ''
        export QT_PLUGIN_PATH=${pkgs.qt5.qtbase}/${pkgs.qt5.qtbase.dev.qtPluginPrefix}:${pkgs.qt5.qtsvg.bin}/${pkgs.qt5.qtbase.dev.qtPluginPrefix}
        export QML2_IMPORT_PATH=${pkgs.qt5.qtbase}/${pkgs.qt5.qtbase.dev.qtQmlPrefix}
        '';
      };
    };
  nixConfig = {  # work around https://github.com/NixOS/nix/issues/6771
    extra-trusted-public-keys = "nixbld.m-labs.hk-1:5aSRVA5b320xbNvu30tqxVPXpld73bhtOeH6uAjRyHc=";
    extra-substituters = "https://nixbld.m-labs.hk";
  };
}