import asyncio, aiomqtt
from PyQt5.QtCore import QThread, pyqtSignal, QObject
import logging


class TelemetryWorker(QObject):
    telemetry_received = pyqtSignal(int, str)

    def __init__(self, server="137.222.69.28"):
        super().__init__()
        self.server = server

    async def listen(self):
        # we want to listen to updates of channel[0-7]/[state,input power, output power]
        async with aiomqtt.Client(self.server) as client:
            await client.subscribe(
                "dt/sinara/booster/fc-0f-e7-23-77-30/telemetry/#"
            )
            client._on_message = self.handle_message
            async for message in client.messages:
                self.handle_message(message)


    def handle_message(self, message: aiomqtt.Message):
        """Handle a message from the MQTT broker
        sends a signal with the channel number (int) and the message payload (json str)
        """
        ch = int(message.topic.value[-1])
        data = message.payload.decode()
        self.telemetry_received.emit(ch, data)

    async def set_telem_period(self, period=1):
        try:
            async with aiomqtt.Client(self.server) as client:
                await client.publish(
                    "dt/sinara/booster/fc-0f-e7-23-77-30/settings/telemetry_period",
                    str(period),
                )
        except aiomqtt.exceptions.MqttError as e:
            logging.error(f"Booster: Setting telemetry period failed: {e}")

    async def set_fan_speed(self, speed=0.2):
        if speed < 0 or speed > 1:
            logging.error("Fan speed must be between 0 and 1")
        try:
            async with aiomqtt.Client(self.server) as client:
                await client.publish(
                    "dt/sinara/booster/fc-0f-e7-23-77-30/settings/fan_speed",
                    str(speed),
                )
        except aiomqtt.exceptions.MqttError as e:
            logging.error(f"Booster: Setting fan speed failed: {e}")

    async def set_interlock(self, ch, db=35.0):
        """Set the interlock state of a channel ch to db"""
        try:
            async with aiomqtt.Client(self.server) as client:
                await client.publish(
                    f"dt/sinara/booster/fc-0f-e7-23-77-30/settings/channel/{ch}/output_interlock_threshold",
                    str(db),
                )
        except aiomqtt.exceptions.MqttError as e:
            logging.error(f"Booster: Setting interlock failed: {e}")

    async def set_state(self, ch, state="Enabled"):
        """Set the state of a channel ch to state ['Off','Powered','Enabled']"""
        try:
            async with aiomqtt.Client(self.server) as client:
                await client.publish(
                    f"dt/sinara/booster/fc-0f-e7-23-77-30/settings/channel/{ch}/state",
                    str(state),
                )
        except aiomqtt.exceptions.MqttError as e:
            logging.error(f"Booster: Setting state failed: {e}")

    def run(self):
        asyncio.run(self.listen())


class BoosterTelemetry(QThread):
    """Register a callback to be called when telemetry is received by the worker"""

    def __init__(self, callback, server="137.222.69.28"):
        super().__init__()
        self.failed = False
        self.worker = TelemetryWorker(server=server)
        self.worker.telemetry_received.connect(callback)
        self.start()

    def run(self):
        try:
            self.worker.run()
        except Exception as e:
            logging.error(f"Booster: Failed to subscribe: {e}")
            self.failed = True

    def set_telem_period(self, period=1):
        asyncio.run(self.worker.set_telem_period(period))

    def set_interlock(self, ch, db=35.0):
        asyncio.run(self.worker.set_interlock(ch, db))

    def enable_channel(self, ch):
        asyncio.run(self.worker.set_state(ch, "Powered"))
        asyncio.run(self.worker.set_state(ch, "Enabled"))

    def disable_channel(self, ch):
        asyncio.run(self.worker.set_state(ch, "Off"))



if __name__ == "__main__":

    def callback(ch, data):
        logging.info(f"Booster: Received telemetry from channel {ch}: {data}")

    worker = BoosterTelemetry(callback)
    worker.set_telem_period(1)
    worker.run()
    while True:
        pass
