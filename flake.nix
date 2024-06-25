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
        version = "0.6.16";
        doCheck = false;
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "ddd1fdc1c6ae604e74377cf70e99f067e579c03c1c71a6acd494e199e93b7fa4";
        };
      };
      # miniconf-mqtt
      miniconf_mqtt_repo = pkgs.fetchgit {
        url="https://github.com/quartiq/miniconf.git";
        rev="581fda76533c37f789c47015a30e8f1226dc7de1";
        sha256 = "Xp9syrtuDvF84HFaTyIwPW1YQ0OiGdttoiyOMsNzTfA=";
      };
      miniconf_mqtt = pkgs.python3Packages.buildPythonPackage rec {
        name = "miniconf_mqtt";
        version = "0.1.0";
        src = "${miniconf_mqtt_repo}/py/miniconf-mqtt";
        format = "pyproject";
        dependencies = [pkgs.python3Packages.setuptools gmqtt];
      };
      # Booster control
      booster_repo = pkgs.fetchgit {
        url="https://github.com/quartiq/booster.git";
        rev="f84048a119f3a0294ebe8e530827ba2347d057a2";
        sha256 = "7UOuGXYfJe2b8bA3jyeRNTyJjIaeK+MHdZ/TiwmkDNs=";
      };
      booster = pkgs.python3Packages.buildPythonPackage rec {
        name = "booster";
        version = "0.1.0";
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
            ps.qt6
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
      };
    };
  nixConfig = {  # work around https://github.com/NixOS/nix/issues/6771
    extra-trusted-public-keys = "nixbld.m-labs.hk-1:5aSRVA5b320xbNvu30tqxVPXpld73bhtOeH6uAjRyHc=";
    extra-substituters = "https://nixbld.m-labs.hk";
  };
}