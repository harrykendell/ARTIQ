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
  inputs.src-miniconf-mqtt = {url = "github:quartiq/miniconf/6b0173ea5e540e1b3c3916bb6c7701cc06db47f0"; flake= false;};
  inputs.src-booster = {url = "github:quartiq/booster/3afc152cfbc5c313df76e238cca0be2b0394477a"; flake= false;};
  inputs.src-aiomqtt = {url = "github:sbtinstruments/aiomqtt/f1a61398f346a8e3a051cf5ea2a4cbbf1df9dbe6"; flake= false;};
  
  outputs = { self, artiq, extrapkg, src-ndscan, src-oitg, src-oxart-devices, src-miniconf-mqtt, src-booster, src-aiomqtt }:
    let
      pkgs = artiq.inputs.nixpkgs.legacyPackages.x86_64-linux;
      aqmain = artiq.packages.x86_64-linux;
      aqextra = extrapkg.packages.x86_64-linux;

      /*
      We can include external packages here, which are not part of the main artiq repository.

      Two main ways to do this, either pulling from github or from pypi.

      For github, use the following:
        1) define a new input source above
                e.g. 
                inputs.src-ndscan = {url = "github:OxfordIonTrapGroup/ndscan/e7c0211019e3fc77ae0c032869e4833e407874f0"; flake= false;};
        2) include the source in the oututs list above
        3) include the package in the nixpkgs list below
                e.g.
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
                };
        4) include the package in the buildEnv desired packages below

      For pypi it is simpler, simply define the package iself.
      Generally you can use a tar.gz release if there is one on pypi releases, otherwise use a wheel. Note most of these variables shouldn't be needed but match them to the release file on pypi
                e.g. for a tar.gz (prefer this option)
                pco = pkgs.python3Packages.buildPythonPackage rec {
                  pname = "pco";
                  version = "2.3.0";
                  doCheck = false;
                  src = pkgs.python3Packages.fetchPypi {
                    inherit pname version format;
                    sha256 = "3mFhw1spvuo2+GDyv09NASetnFa3MLRh2OwJTHy3X0M=";
                  };
                };
      For a wheel define format = "wheel" in the builder
      ```
      */

      # DEVICES
      # windfreak RF synthesizer
      windfreak = pkgs.python3Packages.buildPythonPackage rec {
        pname = "windfreak";
        version = "0.3.0";
        doCheck = false;
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "d0ec652bc57aa630f38d34abd9eba938fb7aae8c4bd42ceb558eb38d170d8620";
        };
        };

      # Booster RF Amplifier
      paho-mqtt = pkgs.python3Packages.buildPythonPackage rec {
        pname = "paho_mqtt";
        version = "2.1.0";
        doCheck = false;
        pyproject = true;
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "12d6e7511d4137555a3f6ea167ae846af2c7357b10bc6fa4f7c3968fc1723834";
        };
        propagatedBuildInputs = [pkgs.python3Packages.hatchling];
        };
      aiomqtt = pkgs.python3Packages.buildPythonPackage rec {
        name = "aiomqtt";
        src = "${src-aiomqtt}";
        format = "pyproject";
        version = "2.1.0";
        propagatedBuildInputs = [
          pkgs.python3Packages.poetry-core
          pkgs.python3Packages.poetry-dynamic-versioning
          paho-mqtt
          pkgs.python3Packages.typing-extensions
        ];
        };
      miniconf-mqtt = pkgs.python3Packages.buildPythonPackage {
        name = "miniconf_mqtt";
        src = "${src-miniconf-mqtt}/py/miniconf-mqtt";
        format = "pyproject";
        propagatedBuildInputs = [
          pkgs.python3Packages.setuptools
          pkgs.python3Packages.typing-extensions
          aiomqtt
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
      
      # PCO camera
      pco = pkgs.python3Packages.buildPythonPackage rec {
        pname = "pco";
        version = "2.3.0";
        doCheck = false;
        format = "wheel";
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version format;
          python = "py3"; # they only release for py3 not py2.py3
          dist= "py3"; # they only release for py3 not py2.py3
          platform = "manylinux2014_x86_64";
          sha256 = "3mFhw1spvuo2+GDyv09NASetnFa3MLRh2OwJTHy3X0M=";
        };
        };

      # Toptica Lasers
      toptica = pkgs.python3Packages.buildPythonPackage rec {
        pname = "toptica_lasersdk";
        version = "3.2.0";
        doCheck = false;
        src = pkgs.python3Packages.fetchPypi {
          inherit pname version;
          sha256 = "UNazng4Za3CZeG7eDq0b+l7gmESEXIU8WMLWGGysmBg=";
        };
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
        # We don't need to do this anymore as oitg made it optional in 3ecba4b
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
            ps.ifaddr

            ps.pyvisa
            windfreak
            booster
            pco
            toptica

            oxart-devices
            ndscan

            artiq.inputs.artiq-comtools
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