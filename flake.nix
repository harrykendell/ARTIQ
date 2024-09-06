{
  # for a specific rev use `git+https://github.com/m-lab/artiq?rev=0ac9e77dc3bc803058d0473e423862d39d49d3f8`
  inputs.artiq.url = "git+https://github.com/m-labs/artiq?ref=release-8";
  inputs.extrapkg.url = "git+https://git.m-labs.hk/M-Labs/artiq-extrapkg?ref=release-8";
  inputs.extrapkg.inputs.artiq.follows = "artiq";
  # We pull Github packages in as flake inputs so we can conveniently update them
  # using `nix lock`, etc., rather than manually having to track hashes.
  inputs.src-ndscan = {url = "github:OxfordIonTrapGroup/ndscan/e7c0211019e3fc77ae0c032869e4833e407874f0"; flake= false;};
  inputs.src-oitg = {url = "github:OxfordIonTrapGroup/oitg/3ecba4b2ea1d407be02a87193e2fde4cd9c09af3"; flake= false;};
  inputs.src-oxart-devices = {url = "github:OxfordIonTrapGroup/oxart-devices/8074c330bc718bda2b0a91eb74b1988dcb5cbdb7"; flake= false;};
  inputs.src-miniconf-mqtt = {url = "github:quartiq/miniconf/d03726db064c61fdbaf55db4788fa56cc09ece10"; flake= false;};
  inputs.src-booster = {url = "github:quartiq/booster/a1f83b63180511ecd68f88a04621624941d17a41"; flake= false;};
  
  outputs = { self, artiq, extrapkg, src-ndscan, src-oitg, src-oxart-devices, src-miniconf-mqtt, src-booster}:
    let
      pkgs = artiq.inputs.nixpkgs.legacyPackages.x86_64-linux;
      aqmain = artiq.packages.x86_64-linux;
      aqextra = extrapkg.packages.x86_64-linux;

      # windfreak packages
      windfreak = pkgs.python3Packages.buildPythonPackage rec {
        pname = "windfreak";
        version = "0.3.0";
        doCheck = false;
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "d0ec652bc57aa630f38d34abd9eba938fb7aae8c4bd42ceb558eb38d170d8620";
        };
        };

      # booster packages
      gmqtt = pkgs.python3Packages.buildPythonPackage rec {
        pname = "gmqtt";
        version = "0.6.12";
        doCheck = false;
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "7df03792343089ae62dc7cd6f8be356861c4fc68768cefa22f3d8de5e7e5be48";
        };
        };
      miniconf-mqtt = pkgs.python3Packages.buildPythonPackage {
        name = "miniconf_mqtt";
        src = "${src-miniconf-mqtt}/py/miniconf-mqtt";
        format = "pyproject";
        propagatedBuildInputs = [
          pkgs.python3Packages.setuptools
          gmqtt
        ];
        };
      booster = pkgs.python3Packages.buildPythonPackage {
        name = "booster";
        src = "${src-booster}/py";
        format = "pyproject";
        propagatedBuildInputs = [
          pkgs.python3Packages.setuptools
          miniconf-mqtt
        ];
        };
      
      
      # ndscan packages
      oxart-devices = pkgs.python3Packages.buildPythonPackage {
        name = "oxart-devices";
        src = src-oxart-devices;
        format = "pyproject";
        propagatedBuildInputs = [
          pkgs.python3Packages.appdirs
          pkgs.python3Packages.pyserial
          pkgs.python3Packages.pyzmq
          pkgs.python3Packages.influxdb
          oitg
          artiq.inputs.sipyco.packages.x86_64-linux.sipyco
        ];
        doCheck = false;
        };
      oitg = pkgs.python3Packages.buildPythonPackage {
        name = "oitg";
        src = src-oitg;
        format = "pyproject";
        doCheck = false;
        propagatedBuildInputs = [
          pkgs.python3Packages.h5py
          pkgs.python3Packages.scipy
          pkgs.python3Packages.statsmodels
          pkgs.python3Packages.poetry-core
          pkgs.python3Packages.poetry-dynamic-versioning
        ];
        # patch out qiskit dependecy as it doesn't support python 3.11 and we dont personally use it
        postPatch = ''
          sed -i -e "s/^qiskit = .*//" pyproject.toml
        '';
        };
      ndscan = pkgs.python3Packages.buildPythonPackage {
        name = "ndscan";
        src = src-ndscan;
        format = "pyproject";
        propagatedBuildInputs = [
          artiq.packages.x86_64-linux.artiq
          oitg
          pkgs.python3Packages.poetry-core
          pkgs.python3Packages.pyqt6
        ];
        dontWrapQtApps = true; # Pulled in via the artiq package; we don't care.
        };


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
            #aqextra.flake8-artiq

            ps.pip
            ps.pandas
            ps.numpy
            ps.scipy
            ps.matplotlib
            ps.pyqt5
            ps.pydantic

            windfreak
            booster

            oxart-devices
            ndscan
          ]))
          aqmain.openocd-bscanspi  # needed if and only if flashing boards
        ];
      };

    };
  nixConfig = {  # work around https://github.com/NixOS/nix/issues/6771
    extra-trusted-public-keys = "nixbld.m-labs.hk-1:5aSRVA5b320xbNvu30tqxVPXpld73bhtOeH6uAjRyHc=";
    extra-substituters = "https://nixbld.m-labs.hk";
  };
}