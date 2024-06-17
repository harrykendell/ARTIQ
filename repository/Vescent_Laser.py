from windfreak import SynthHD
kHz = 1e3; MHz = 1e6; GHz = 1e9

def print_channel(channel):
    print("    Channel %s" % channel._index, "(enabled)" if channel.enable else "(disabled)")
    print("        Power: %.2f dBm" % channel.power," - " , channel.power_range)
    print("        Frequency: %.2f Hz" % channel.frequency," - " , channel.frequency_range)

synth = SynthHD('/dev/ttyACM0')

# Set channel 0 power and frequency
synth[0].power = -10.
synth[0].frequency = 77.04*MHz
synth[0].enable = True

synth[1].power = -10.
synth[1].frequency = 2930*MHz
synth[1].enable = True

synth.save()

print(synth.model, "(" , synth.serial_number, ") on ", synth.firmware_version)
print(synth.temperature, "°C")
for channel in synth:
    print_channel(channel)
