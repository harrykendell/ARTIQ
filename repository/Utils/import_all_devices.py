#!/usr/bin/env python3
from artiq.experiment import *

def import_all(self):
    self.setattr_device("core")

    self.leds = dict()
    self.ttl_outs = dict()
    self.ttl_ins = dict()
    self.urukul_cplds = dict()
    self.urukuls = dict()
    self.samplers = dict()
    self.zotinos = dict()
    self.fastinos = dict()
    self.phasers = dict()
    self.grabbers = dict()
    self.mirny_cplds = dict()
    self.mirnies = dict()
    self.suservos = dict()
    self.suschannels = dict()
    self.almaznys = dict()

    ddb = self.get_device_db()
    for name, desc in ddb.items():
        if isinstance(desc, dict) and desc["type"] == "local":
            module, cls = desc["module"], desc["class"]
            if (module, cls) == ("artiq.coredevice.ttl", "TTLOut"):
                dev = self.get_device(name)
                if "led" in name:  # guess
                    self.leds[name] = dev
                else:
                    self.ttl_outs[name] = dev
            elif (module, cls) == ("artiq.coredevice.ttl", "TTLInOut"):
                self.ttl_ins[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.urukul", "CPLD"):
                self.urukul_cplds[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.ad9910", "AD9910"):
                self.urukuls[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.ad9912", "AD9912"):
                self.urukuls[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.sampler", "Sampler"):
                self.samplers[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.zotino", "Zotino"):
                self.zotinos[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.fastino", "Fastino"):
                self.fastinos[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.phaser", "Phaser"):
                self.phasers[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.grabber", "Grabber"):
                self.grabbers[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.mirny", "Mirny"):
                self.mirny_cplds[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.adf5356", "ADF5356"):
                self.mirnies[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.suservo", "SUServo"):
                self.suservos[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.suservo", "Channel"):
                self.suschannels[name] = self.get_device(name)
            elif (module, cls) == ("artiq.coredevice.mirny", "Almazny"):
                self.almaznys[name] = self.get_device(name)

    # Remove Urukul, Sampler, Zotino and Mirny control signals
    # from TTL outs (tested separately) and remove Urukuls covered by
    # SUServo
    ddb = self.get_device_db()
    for name, desc in ddb.items():
        if isinstance(desc, dict) and desc["type"] == "local":
            module, cls = desc["module"], desc["class"]
            if (module, cls) == ("artiq.coredevice.ad9910", "AD9910") or (
                module,
                cls,
            ) == ("artiq.coredevice.ad9912", "AD9912"):
                if "sw_device" in desc["arguments"]:
                    sw_device = desc["arguments"]["sw_device"]
                    del self.ttl_outs[sw_device]
            elif (module, cls) == ("artiq.coredevice.urukul", "CPLD"):
                if "io_update_device" in desc["arguments"]:
                    io_update_device = desc["arguments"]["io_update_device"]
                    del self.ttl_outs[io_update_device]
            # check for suservos and delete respective urukuls
            elif (module, cls) == ("artiq.coredevice.suservo", "SUServo"):
                for cpld in desc["arguments"]["cpld_devices"]:
                    del self.urukul_cplds[cpld]
                for dds in desc["arguments"]["dds_devices"]:
                    del self.urukuls[dds]
            elif (module, cls) == ("artiq.coredevice.sampler", "Sampler"):
                cnv_device = desc["arguments"]["cnv_device"]
                del self.ttl_outs[cnv_device]
            elif (module, cls) == ("artiq.coredevice.zotino", "Zotino"):
                ldac_device = desc["arguments"]["ldac_device"]
                clr_device = desc["arguments"]["clr_device"]
                del self.ttl_outs[ldac_device]
                del self.ttl_outs[clr_device]
            elif (module, cls) == ("artiq.coredevice.adf5356", "ADF5356"):
                sw_device = desc["arguments"]["sw_device"]
                del self.ttl_outs[sw_device]

    # Sort everything by RTIO channel number
    self.leds = sorted(self.leds.items(), key=lambda x: x[1].channel)
    self.ttl_outs = sorted(self.ttl_outs.items(), key=lambda x: x[1].channel)
    self.ttl_ins = sorted(self.ttl_ins.items(), key=lambda x: x[1].channel)
    self.urukuls = sorted(
        self.urukuls.items(),
        key=lambda x: (x[1].cpld.bus.channel, x[1].chip_select),
    )
    self.samplers = sorted(self.samplers.items(), key=lambda x: x[1].cnv.channel)
    self.zotinos = sorted(self.zotinos.items(), key=lambda x: x[1].bus.channel)
    self.fastinos = sorted(self.fastinos.items(), key=lambda x: x[1].channel)
    self.phasers = sorted(self.phasers.items(), key=lambda x: x[1].channel_base)
    self.grabbers = sorted(self.grabbers.items(), key=lambda x: x[1].channel_base)
    self.mirnies = sorted(
        self.mirnies.items(), key=lambda x: (x[1].cpld.bus.channel, x[1].channel)
    )
    self.suservos = sorted(self.suservos.items(), key=lambda x: x[1].channel)
    self.suschannels = sorted(self.suschannels.items(), key=lambda x: x[1].channel)