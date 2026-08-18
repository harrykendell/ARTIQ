from artiq.experiment import *


class InteractiveArgumentTest(EnvExperiment):
    def run(self):
        with self.interactive(title="Interactive argument test") as interactive:
            interactive.setattr_argument(
                "boolean",
                BooleanValue(True),
            )

            interactive.setattr_argument(
                "number",
                NumberValue(1.23, step=0.1),
            )

            interactive.setattr_argument(
                "string",
                StringValue("hello"),
            )

            interactive.setattr_argument(
                "enumeration",
                EnumerationValue(
                    ["option_a", "option_b", "option_c"],
                    default="option_a",
                ),
            )

            interactive.setattr_argument(
                "pyon",
                PYONValue({"foo": 1, "bar": [1, 2, 3]}),
            )

            interactive.setattr_argument(
                "scan",
                Scannable(
                    default=NoScan(0.0),
                ),
            )

        # Experiment exits immediately after the arguments are submitted.
        print("Submitted arguments:")
        print("boolean:", interactive.boolean)
        print("number:", interactive.number)
        print("string:", interactive.string)
        print("enumeration:", interactive.enumeration)
        print("pyon:", interactive.pyon)
        print("scan:", interactive.scan)
