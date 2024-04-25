from artiq.experiment import *


class Test(EnvExperiment):
    '''Test all devices in the device_db.'''
    def build(self):
        self.setattr_device("core")
        self.setattr_device("led0")
        self.setattr_device("led1")

        for i in range(16):
            self.setattr_device("ttl"+str(i))

        self.setattr_device("fastino") # Fastino

        self.setattr_device("mirny_cpld") # Mirny
        for i in range(4):
            self.setattr_device("mirny_ch"+i) # ADF5356
            self.setattr_device("ttl_mirny_sw"+str(i)) # TTLOut

        self.setattr_device("almazny") # Almazny

        self.setattr_device("suservo") # SUServo
        for i in range(8):
            self.setattr_device("suservo_ch"+i) # SUServo Channel

        for i in range(2):
            self.setattr_device("urukul"+str(i)+"_cpld") # CPLD
            self.setattr_device("urukul"+str(i)+"_dds") # AD9910

    @kernel
    def run(self):
        self.init()

        self.test()

    @kernel
    def init(self):
        '''Call the init() method of each device in the device_db.'''
        self.core.break_realtime()
        self.core.reset()

        # Fastino
        self.fastino.init()
        print("fastino (Fastino) initialised")
        delay(1*ms)

        # Mirny
        self.mirny_cpld.init()
        print("mirny (Mirny) initialised")
        delay(1*ms)
        for i in range(4):
            self.__dict__["mirny_ch"+str(i)].init()
            delay(1*ms)
        print("mirny (ADF5356) initialised")
        self.almazny.init()
        print("almazny (Almazny) initialised")
        delay(1*ms)

        # SUServo
        self.suservo.init()
        print("suservo (SUServo) initialised")
        delay(1*ms)

        # Urukul
        for i in range(2):
            self.__dict__["urukul"+str(i)+"_cpld"].init()
            delay(1*ms)
            self.__dict__["urukul"+str(i)+"_dds"].init()
            delay(1*ms)
        print("urukuls initialised")

    # printing must be off the kernel
    @rpc(flags={"async"})
    def prnt(self, channel, adc):
        print("{} ADC: {:10s}".format(channel,"#" * int(adc)),end="\r",)
    
    @kernel
    def test(self):
        self.core.break_realtime()

        # user LEDs
        self.led0.on()
        self.led1.on()

        # Suservo
        for i in range(8):
            self.__dict__["suservo_ch"+str(i)].set_dds(profile=0, frequency=10e6*(1+i), offset=0)
            self.__dict__["suservo_ch" + str(i)].set(en_out=1, en_iir=0, profile=0)
            delay(1*ms)
            prnt(i,self.suservo.get_adc(i))

        # Mirny
        for i in range(4):
            self.__dict__["ttl_mirny_sw"+str(i)].on()
            self.__dict__["mirny_ch"+str(i)].set_frequency(100e6*(1+i))
            delay(1*ms)
        self.almazny.output_toggle(True)

        # Fastino
        self.fastino.set_leds(0b11111111)

        # TTL
        for i in range(4):
            self.__dict__["ttl"+str(i)].on()
            delay(1*ms)
        for i in range(4,16):
            self.__dict__["ttl"+str(i)].output()
            self.__dict__["ttl"+str(i)].on()
            delay(1*ms)



