# What You Need to Know

This codebase is relatively substantial and not the easiest to get to grips with. Thankfully you can ignore almost all of it and just interact with the topmost level in most cases. 
This only fails when the underlying hardware constraints crop up without warning to stab you in the back. This is complicated further by opaque error messages or silent failures.
For this reason I'd reccomend being very careful of any changes you make to the codebase itself, and to verify the behaviour is as expected at all possible opportunities.

The primary interface for this codebase is [run_gui.sh](run_gui.sh). This should start up the Artiq system and allow experiments to be easily run.
> [!WARNING]
> If this doesn't work it's likely you need to run [run_stack.sh](run_stack.sh) on the server

<details>
<summary>

### Why is it Doing Weird Things?
</summary>

  Artiq as mentioned has some sharp corners, here are some:
#### self.core.reset()
>This will reinitialise many of the devices, this is particularly problematic for SUServo. It will reset the overall enable flag which prevents Sampler updates until set with self.suservo_device.set_config(1). This will then silently serve stale voltage readings to you.
>
>To fix this you should **ONLY** use it at the start of a top level device_setup, so not if this `Fragment` will ever be included.
>```python
>@kernel
>  def device_setup(self) -> None:
>    self.core.reset()
>    self.device_setup_subfragments()
>```
</details>


## Commit formatting and CI

Ruff 0.17.4 formats staged Python files automatically before committing when the repository hook is installed. Install the hook in a standard checkout with `install -m 755 scripts/ruff_pre_commit.py .git/hooks/pre-commit` (check for an existing hook first). It uses `uvx` or a matching Ruff executable; set `git config --local artiq.ruffPath /path/to/ruff` if needed. Only staged project Python files are formatted, and a file needing formatting that also has unstaged changes stops the commit without modifying either version. The CI workflow checks formatting of changed Python files on pull requests and runs the hardware-independent regression suite. It does not push formatting commits or hold write credentials.

## Crate firmware and flashing

We maintain firmware changes in [harrykendell/artiq-firmware](https://github.com/harrykendell/artiq-firmware), on the `release-8-lab` branch, separately from this experiment repository. The upstream base, exact maintained source revision, qualified release, board configuration hash, image checksums and required boot settings are pinned in [crate config/firmware.json](crate%20config/firmware.json). The host Python ARTIQ pin in `flake.nix` remains independent: a firmware reflash must not implicitly change the experiment environment.

The current [BU2402001 telemetry v2 release](https://github.com/harrykendell/artiq-firmware/releases/tag/bu2402001-rtio-v2) is the exact tested gateware/runtime pair, with the simplified RTQ9-only runtime and unchanged qualified FPGA bitstream. The [v1 release](https://github.com/harrykendell/artiq-firmware/releases/tag/bu2402001-rtio-v1) is retained for rollback. The persistent `rtio_analyzer_snapshot=2` setting is preserved for v1 rollback compatibility; v2 does not use it to select a capture mode. It provides the non-destructive 2 MiB analyser on port 1392, hardware SED lane telemetry and bounded kernel-priority scheduling. The website uses the local `~/artiq-tool/.rtio-snapshot-host` marker. The unused dashboard waveform controller has been removed. MonInj and core logging remain independent. The website publisher supports only the extended RTQ9 transport. To roll back to the original destructive firmware, restore the previous compatible publisher revision as well.

| Command | Effect |
| --- | --- |
| `scripts/flash.sh` or `scripts/flash.sh prepare` | Download or verify the pinned images; no hardware access. |
| `scripts/flash.sh dry-run` | Generate the actual OpenOCD commands without connecting to the crate. |
| `scripts/flash.sh build` | Full source build from the pinned fork and its locked Nix environment, with telemetry enabled; never flashes. |
| `scripts/flash.sh flash --confirm-idle` | Flash only the qualified pair, restore/verify required configuration, and verify core identity and analyser protocol. |

For a real reflash, establish a maintenance window, put the apparatus in a safe state, confirm the scheduler is empty, gracefully stop the master/controller stack, dashboard and any standalone kernels, and run `sudo systemctl stop artiq-viewer.service`. The script refuses to flash while those services or kernel/analyser connections are present. It preserves the bootloader and configuration storage; it does not start the experiment stack automatically. After successful verification, restart the master, GUI and `artiq-viewer.service` and verify a scheduled smoke capture. If anything fails, keep the stack stopped and use the qualified recovery procedure rather than guessing at flash addresses.

Qualified images are cached under `crate config/bu2402001_qualified/<release>/`. The historical `bu2402001_current` directory may contain the old build and is **not** an input to the new flashing workflow. A source rebuild goes into a separate `bu2402001_build_<revision>/` directory. Do not replace the qualified release with its output until checking Vivado timing, register-map compatibility, runtime behaviour and experiment timing on hardware. For an update, rebase the small firmware patch series on a chosen upstream revision, qualify a new matched image pair, create a new tag/release, and change the pin and checksums together. Never flash a moving upstream branch or overwrite an already-qualified release.

The original stock images and exact readbacks, production qualification results and rollback instructions are retained on the lab PC under `~/rtio-production-20261127/`.

## TC-08 temperature monitor

The Pico USB TC-08 is owned by a **native ARTIQ controller**,
`controllers/aqctl_temperature_logger.py`, started and supervised by the
existing `artiq_ctlmgr`. Its only USB client continuously samples approximately
every 5 seconds, maintains seven days of SQLite-WAL history and persists the
channel configuration. It starts with the ARTIQ stack and stops when the
controller manager shuts down, as intended.

The cold junction is recorded independently as a read-only history source
(ID 0), including when every physical thermocouple is disabled. It is not
an ndscan experiment channel. Existing laboratory history was migrated to
this layout when CJC recording was introduced.

`repository/models/device_db.py` registers `temperature_logger_controller`
as a `type="controller"` device on loopback port 3273. The single
controller manager treats `127.0.0.1` as a local controller host and starts
it without a separate `launch_host` setting. This assumption would need
revisiting if additional controller-manager hosts were introduced.
ARTIQ experiments use the separate
lightweight `temperature_logger` **local device adapter** in
`repository/utils/temperature_logger.py`, which makes short-lived Sipyco
RPC requests with a 350-ms socket timeout and returns an unavailable state
on failure. No Pico SDK or USB access occurs within experiment workers or
RTIO kernels. For simple host-side access, use
`self.get_device("temperature_logger").read()`: the result contains
`timestamp`, `cold_junction_c` and `channels` keyed by physical channel
number, each with `temperature_c`, `timestamp` and `valid`. Invalid or
unavailable temperatures are NaN. For time-correlated data, use
`get_nearest(timestamp)`; other controller methods are `get_config()`,
`get_latest()`, `get_channel(channel)`, `get_history(start, end, channels,
max_points)`, `configure_channel(channel, expected_revision)`, `ping()`
and `terminate()`.

By default, the persistent SQLite file is
`~/.local/state/artiq-temperature/history.sqlite3` for the ARTIQ process
account; override with `ARTIQ_TEMPERATURE_DB` when more appropriate (for example
on `/storage`). The Pico official `libusbtc08.so` is required for hardware
acquisition, optionally selected with `PICO_TC08_LIBRARY`. The controller
binds strictly to loopback because native Sipyco RPC is not authenticated.
Provide the ARTIQ account with **persistent** USB `0ce9:1000` access,
using the example udev rule in `controllers/temperature_logger/` (adjust
the group to the actual lab account). Do not change device permissions or
restart the ARTIQ stack during experiments.

During `AbsorptionImageExpFrag.build_fragment()`, the configured selection
is frozen as optional `lab_temp_ch1` through `lab_temp_ch8` ndscan
`FloatChannel` result IDs: **one °C value per selected thermocouple**, or
NaN when invalid. No sample-age or validity result channels are published.
The host-side `update_images()` RPC requests the nearest previously
**recorded** sample relative to a host observation timestamp taken after the
imaging kernel, **not** the optical pulse timestamp. Missing, stale, invalid
and unavailable readings become NaN rather than interrupting imaging.
Configuration changes never mutate an active experiment's result schema.
The controller also reports `recording_ok` separately from USB connection.
SQLite configuration or write failures log a traceback, invalidate cached
readings for experiments, and are retried on the next sampling cycle without
reopening a healthy USB driver or attempting a second write in the handler.

The `artiq-tool` repository provides the demand-driven website adapter
through the existing `artiq-control` process and the
`/devices/temperature-logger` UI. It never takes ownership of the USB.
No per-experiment temperature artefacts, special experiment tabs or RTIO
integrations are introduced.

**Lab operations:** The controller has been verified against the physical
TC-08 and its SQLite store. Probe names, types and experiment-recording flags
must be configured for the actual sensors before using the resulting data in
experiments. The lab's temporary USB ACL must still be replaced with the
scoped udev rule above to survive device reconnection. See
`artiq-tool/artiq_lab_control/TEMPERATURE_LOGGER.md` for acceptance checks.

## Libraries
Any code that we write is based on top of Artiq and NDScan, This allows us to take a much higher level approach than if we were spinning our own control system.

> [!TIP]
> You should familiarise yourself with the reference documentation for [Artiq](https://m-labs.hk/artiq/manual/) and [NDScan](https://oxfordiontrapgroup.github.io/ndscan/index.html)

However in summary, *Artiq* is difficult to work with because it has to compile experiments down to FPGA code. This means it is
- Strongly typed
- A subset of Python
- Restricted by hardware timing constraints

*NDScan* provides a convenience layer nominally just for running experimental sweeps. However, it is much more generally useful introducing the idea of `Fragments` and `ExpFragments` allowing for a nice object oriented approach to experimental design. Almost all of our code relies on *NDScan* due to how nuch easier it is to work with.

The general outline is that `Fragment` classes are defined that represent "building blocks that accept parameters and produce result data", they can recursively contain other `Fragments` as member variables building up more complex blocks.
We can then upgrade to `ExpFragments` which support the notion of also being run on their own. This effectively translates to being a full experiment. A nice feature is they natively support exposing parameters to the end user and sweeping over these parameters in, as the name suggests, N dimensional scans.

## Repository
Any code that we write lives inside the `repository` directory.
- Generic code to handle devices should prefer the *`fragments`\ `imaging`\ `gui`* directories.
- Code for actual experiments should prefer the *`tests`\ `utils`* directories.

The description of our experimental setup, and indeed generic default data, should live inside of [repository/models](repository/models).<br>
The main location is [devices.py](repository/models/devices.py) which contains Pydantic Dataclasses representing components which are serialisable for the FPGA and contain default values.
There is further Artiq specific configuration info in [device_db.py](repository/models/device_db.py)

> [!TIP]
> Devices.py is used by most code as the default values for equipment and should reflect a safe state

The primary interface to hardware itself are the `Fragments` below. These reflect a lightweight translation layer from *Artiq* to *NDScan*:
- [SUServoFrag](repository/fragments/suservo_frag.py): Controls a [SUServo channel](https://m-labs.hk/artiq/manual/core_drivers_reference.html#artiq.coredevice.suservo.SUServo) DDS generally driving a stabilised AOM
- [EomFrag](repository/fragments/eom_setter.py): Controls a [Mirny channel](https://m-labs.hk/artiq/manual/core_drivers_reference.html#module-artiq.coredevice.mirny)/[Almazny channel](https://m-labs.hk/artiq/manual/core_drivers_reference.html#module-artiq.coredevice.almazny) PLL VCO hooked up to an EOM
- [SetSupplies](repository/fragments/supply_setter.py): Controls a [Fastino channel](https://m-labs.hk/artiq/manual/core_drivers_reference.html#module-artiq.coredevice.fastino) DAC controlling:
  - Current Supplies
  - Unlock and push of lasers
- [ReadADC](repository/fragments/read_adc.py): Controls a [Sampler channel](https://m-labs.hk/artiq/manual/core_drivers_reference.html#module-artiq.coredevice.sampler) ADC to read a voltage
- [PcoCamera](repository/imaging/PCO_Camera.py): Controls the [PCO Pixelfly 1.4 USB](https://www.excelitas.com/product/pcopixelfly-14-usb) camera over Ethernet and analog triggers

These are augmented by higher level `Fragments` exposing experimental concepts:
- [SetBeamsToDefaults](repository/fragments/default_beam_setter.py): To reset beams to their default settings of Freq./Amp./etc.
- [ControlBeamsWithoutCoolingAOM](repository/fragments/beam_setter.py): To toggle beam(s) on/off with a shutter/AOM combo.
- [AbsorptionImage](repository/imaging/absorption_image.py): To take triple exposure images of atoms.
- [Ramp](repository/fragments/ramp.py): A generic linear ramp step in an experiment ([see below](#ramps))
- [MOT](repository/fragments/mot.py): This represents the whole MOT
  - Loading
  - Cooling
-[KDC101_serial](\repository\Thorlabs\KDC101_serial.py) is used to control the moving stage with full passive control. Active control is currently under development. A high-level API, [moving_stage.py], is available at (repository\Dipole_trap\moving_stage.py) for direct integration with ARTIQ.


Many of these `Fragments` also define `ExpFragments` in their own file to support being run on their own.

### Ramps
The ramp fragment has been created to address the common problem of wanting to vary some number of parameters smoothly in a single ramp. 
It represents a single stage of an experiment with some useful features:
- Simultaneous ramping of any number of devices
- Pulls default values from devices.py
- Can use the final from other ramps as its initial value
- Creates *NDScan* parameters for all values that aren't chained
See the [example](repository/tests/ramping_phase.py) for more details.

## GUI
We also have a [basic GUI](repository/gui/artiq_gui.py) which offers general control over the experiment in real time. This is run as an experiment and blocks other experiments while it runs.
>[!CAUTION]
>This is built on an older concept of devices and does not synchronise state with other experiments

An [updated GUI](repository/gui/ArtiqMonitor.py) that doesn't block experiments, can be run remotely, and repsects state is in the works.
