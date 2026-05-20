{
  # for a specific rev use `git+https://github.com/m-lab/artiq?rev=0ac9e77dc3bc803058d0473e423862d39d49d3f8`
  inputs.artiq.url = "git+https://github.com/m-labs/artiq?rev=727f0e42846fbcbf9feec55af1f4d81014b786cd";
  inputs.extrapkg.url = "git+https://git.m-labs.hk/M-Labs/artiq-extrapkg?ref=release-8";
  inputs.extrapkg.inputs.artiqpkgs.follows = "artiq";
  # We pull Github packages in as flake inputs so we can conveniently update them
  # using `nix lock`, etc., rather than manually having to track hashes.
  inputs.src-ndscan = {url = "github:harrykendell/ndscan?ref=optimise"; flake = false;};
  inputs.src-oitg = {url = "github:OxfordIonTrapGroup/oitg"; flake= false;};
  inputs.src-oxart-devices = {url = "github:OxfordIonTrapGroup/oxart-devices"; flake= false;};
  inputs.src-miniconf-mqtt = {url = "github:quartiq/miniconf/6b0173ea5e540e1b3c3916bb6c7701cc06db47f0"; flake= false;};
  inputs.src-booster = {url = "github:quartiq/booster/3afc152cfbc5c313df76e238cca0be2b0394477a"; flake= false;};
  inputs.src-aiomqtt = {url = "github:sbtinstruments/aiomqtt/f1a61398f346a8e3a051cf5ea2a4cbbf1df9dbe6"; flake= false;};
  
  outputs = { self, artiq, extrapkg, src-ndscan, src-oitg, src-oxart-devices, src-miniconf-mqtt, src-booster, src-aiomqtt }:
    let
      pkgs = artiq.inputs.nixpkgs.legacyPackages.x86_64-linux;
      py = pkgs.python3Packages;
      aqmain = artiq.packages.x86_64-linux;
      sipyco = artiq.inputs.sipyco.packages.x86_64-linux.sipyco;
      artiq-comtools = artiq.inputs.artiq-comtools;

      mkPyprojectPackage = args:
        py.buildPythonPackage ({
          format = "pyproject";
          doCheck = false;
        } // args);

      stripNumpy = ''sed -i -e "s/^numpy = .*//" pyproject.toml'';

      # DEVICES
      # windfreak RF synthesizer
      windfreak = py.buildPythonPackage rec {
        pname = "windfreak";
        version = "0.3.0";
        doCheck = false;
        src = py.fetchPypi {
          inherit pname version;
          sha256 = "d0ec652bc57aa630f38d34abd9eba938fb7aae8c4bd42ceb558eb38d170d8620";
        };
      };

      # Booster RF Amplifier
      paho-mqtt = py.buildPythonPackage rec {
        pname = "paho_mqtt";
        version = "2.1.0";
        doCheck = false;
        pyproject = true;
        src = py.fetchPypi {
          inherit pname version;
          sha256 = "12d6e7511d4137555a3f6ea167ae846af2c7357b10bc6fa4f7c3968fc1723834";
        };
        propagatedBuildInputs = [py.hatchling];
      };
      aiomqtt = mkPyprojectPackage rec {
        name = "aiomqtt";
        src = src-aiomqtt;
        version = "2.1.0";
        propagatedBuildInputs = [
          py.poetry-core
          py.poetry-dynamic-versioning
          paho-mqtt
          py.typing-extensions
        ];
      };
      miniconf-mqtt = mkPyprojectPackage {
        name = "miniconf_mqtt";
        src = src-miniconf-mqtt + "/py/miniconf-mqtt";
        propagatedBuildInputs = [
          py.setuptools
          py.typing-extensions
          aiomqtt
        ];
      };
      booster = mkPyprojectPackage {
        name = "booster";
        src = src-booster + "/py";
        propagatedBuildInputs = [
          py.setuptools
          miniconf-mqtt
        ];
      };
      
      # PCO camera
      pco = py.buildPythonPackage rec {
        pname = "pco";
        version = "2.3.0";
        doCheck = false;
        format = "wheel";
        src = py.fetchPypi {
          inherit pname version format;
          python = "py3"; # they only release for py3 not py2.py3
          dist = "py3"; # they only release for py3 not py2.py3
          platform = "manylinux2014_x86_64";
          sha256 = "3mFhw1spvuo2+GDyv09NASetnFa3MLRh2OwJTHy3X0M=";
        };
      };
      
      # ndscan packages
      oxart-devices = mkPyprojectPackage {
        name = "oxart-devices";
        src = src-oxart-devices;
        nativeBuildInputs = [py.hatchling];
        propagatedBuildInputs = [
          py.appdirs
          py.pyserial
          py.pyzmq
          py.influxdb
          oitg
          sipyco
        ];
        # patch out numpy dependecy as its incomaptible with the artiq numpy
        postPatch = ''
          ${stripNumpy}
          sed -i -e 's/"hatchling", "uv-dynamic-versioning"/"hatchling"/' pyproject.toml
        '';
      };
      oitg = mkPyprojectPackage {
        name = "oitg";
        src = src-oitg;
        propagatedBuildInputs = [
          py.h5py
          py.scipy
          py.statsmodels
          py.poetry-core
          py.poetry-dynamic-versioning
        ];
        # patch out numpy dependecy as its incomaptible with the artiq numpy
        postPatch = stripNumpy;
      };
      ndscan = mkPyprojectPackage {
        name = "ndscan";
        src = src-ndscan;
        nativeBuildInputs = [py.hatchling];
        propagatedBuildInputs = [
          aqmain.artiq
          oitg
          py.pyqt6
          py.pyqtgraph
          py.torch
          py.gpytorch
          py.botorch
          aqmain.qasync
        ];
        dontWrapQtApps = true; # Pulled in via the artiq package; we don't care.
        # patch out numpy dependecy as its incomaptible with the artiq numpy
        postPatch = ''
          ${stripNumpy}
          sed -i -e 's/"qasync>=0.27.1"/"qasync>=0.24.0"/' pyproject.toml
        '';
      };

      qtPluginPath = pkgs.lib.concatStringsSep ":" [
        "${pkgs.qt5.qtbase}/${pkgs.qt5.qtbase.qtPluginPrefix}"
        "${pkgs.qt6.qtbase}/${pkgs.qt6.qtbase.qtPluginPrefix}"
      ];

      pythonEnv = pkgs.python3.withPackages (ps: [
        aqmain.artiq
        ps.sip
        ps.pip
        ps.pandas
        ps.numpy
        ps.scipy
        ps.matplotlib
        ps.pyqt5
        ps.pydantic
        ps.pyvisa-py
        ps.ifaddr
        ps.pint
        ps.lmfit
        ps.toptica-lasersdk
        ps.pyvisa
        ps.pyqt5_sip
        windfreak
        booster
        pco
        oxart-devices
        ndscan
        artiq-comtools
      ]);

      artiqBaseEnv = pkgs.buildEnv {
        name = "artiq-base-env";
        paths = [
          pythonEnv
          pkgs.libusb1
          pkgs.stdenv.cc.cc.lib
          aqmain.openocd-bscanspi  # needed if and only if flashing boards
        ];
      };

    in {
      defaultPackage.x86_64-linux = pkgs.symlinkJoin {
        name = "artiq-env";
        paths = [
          artiqBaseEnv
        ];
        nativeBuildInputs = [pkgs.makeWrapper];
        postBuild = ''
          for program in "$out"/bin/*; do
            if [ -f "$program" ] && [ -x "$program" ]; then
              wrapProgram "$program" \
                --prefix QT_PLUGIN_PATH : "${qtPluginPath}" \
                --prefix LD_LIBRARY_PATH : "$out/lib"
            fi
          done
        '';
      };

    };
  nixConfig = {  # work around https://github.com/NixOS/nix/issues/6771
    extra-trusted-public-keys = "nixbld.m-labs.hk-1:5aSRVA5b320xbNvu30tqxVPXpld73bhtOeH6uAjRyHc=";
    extra-substituters = "https://nixbld.m-labs.hk";
  };
}
