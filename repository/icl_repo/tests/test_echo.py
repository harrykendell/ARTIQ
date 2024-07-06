from artiq.experiment import *


class TestEcho(EnvExperiment):
    def build(self):
        pass

    def run(self):
        print("Hello, I'm on the master branch")
