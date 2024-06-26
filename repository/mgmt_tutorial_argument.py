from artiq.experiment import *


class MgmtTutorialArg(EnvExperiment):
    """Management tutorial argument"""

    def build(self):
        self.setattr_argument("count", NumberValue(precision=0, step=1))

    def run(self):
        for i in range(self.count):
            print("Hello World ", i)
