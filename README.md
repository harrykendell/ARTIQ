# What you need to know

This codebase is relatively substantial and not the easiest to get to grips with. Thankfully you can ignore almost all of it and just interact with the topmost level in most cases. 
This only fails when the underlying hardware constraints crop up without warning to stab you in the back. This is complicated further by opaque error messages or silent failures.
For this reason I'd reccomend being very careful of any changes you make to the codebase itself, and to verify the behaviour is as expected at all possible opportunities.

The primary interface for this codebase is [run_gui.sh](run_gui.sh). This should start up the Artiq system and allow experiments to be easily run.
> [!WARNING]
> If this doesn't work it's likely you need to run [run_stack.sh](run_stack.sh) on the server

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

An [updated GUI](repository/gui/ArtiqGUI.py) that doesn't block experiments, can be run remotely, and repsects state is in the works.
