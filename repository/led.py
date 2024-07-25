from artiq.experiment import *
from time import sleep


def input_led_number(num_leds) -> TInt32:
    print("Enter the number of the LED you want to turn on (0 or 1):")
    val = input("Enter desired LED: ")
    return max(0, min(num_leds - 1, int(val)))


class LED(EnvExperiment):
    def build(self):
        self.setattr_device("core")

        self.setattr_device("led0")
        self.setattr_device("led1")

    @kernel
    def run(self):
        self.core.reset()
        num = input_led_number(2)
        # required to prevent progressing the led switching being scheduled immediately and thus the input delay overrunning the submission deadline
        self.core.break_realtime()
        self.led0.off()
        self.led1.off()

        if num == 0:
            self.led0.on()
        elif num == 1:
            self.led1.on()
        else:
            raise ValueError("Invalid LED number")
        print("LED is on")
        sleep(2)
