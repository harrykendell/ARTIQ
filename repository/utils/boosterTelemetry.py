import asyncio, aiomqtt
from PyQt5.QtCore import QThread, pyqtSignal, QObject

class TelemetryWorker(QObject):
    server = "137.222.69.28"

    telemetry_received = pyqtSignal(int,str)

    async def listen(self):
        # we want to listen to updates of channel[0-7]/[state,input power, output power]
        async with aiomqtt.Client(TelemetryWorker.server) as client:
            await client.subscribe("dt/sinara/booster/fc-0f-e7-23-77-30/telemetry/#")
            client._on_message = self.handle_message
            async for message in client.messages:
                self.handle_message(message)

    def handle_message(self, message: aiomqtt.Message):
        ''' Handle a message from the MQTT broker
        sends a signal with the channel number (int) and the message payload (json str)'''
        ch = int(message.topic.value[-1])
        data = message.payload.decode()
        self.telemetry_received.emit(ch,data)

    async def _set_telem_period(self, period=1):
        ''' Set the period of the telemetry updates'''
        async with aiomqtt.Client(TelemetryWorker.server) as client:
            await client.publish("dt/sinara/booster/fc-0f-e7-23-77-30/settings/telemetry_period", str(period))

    async def set_interlock(self, ch, db=35.0):
        ''' Set the interlock state of a channel ch to db'''
        async with aiomqtt.Client(TelemetryWorker.server) as client:
            await client.publish(f"dt/sinara/booster/fc-0f-e7-23-77-30/settings/channel/{ch}/output_interlock_threshold", str(db))

    async def set_state(self, ch, state='Enabled'):
        ''' Set the state of a channel ch to state ['Off','Powered','Enabled']'''
        async with aiomqtt.Client(TelemetryWorker.server) as client:
            await client.publish(f"dt/sinara/booster/fc-0f-e7-23-77-30/settings/channel/{ch}/state", str(state))

    def run(self):
        asyncio.run(self.listen())

class BoosterTelemetry(QThread):
    ''' Register a callback to be called when telemetry is received by the worker'''
    def __init__(self, callback):
        super().__init__()
        self.worker = TelemetryWorker()
        self.worker.telemetry_received.connect(callback)
        self.start()

    def run(self):
        self.worker.run()

    def set_telem_period(self, period=1):
        asyncio.run(self.worker._set_telem_period(period))

    def set_interlock(self, ch, db=35.0):
        asyncio.run(self.worker.set_interlock(ch, db))

    def enable_channel(self, ch):
        asyncio.run(self.worker.set_state(ch, 'Powered'))
        asyncio.run(self.worker.set_state(ch, 'Enabled'))

    def disable_channel(self, ch):
        asyncio.run(self.worker.set_state(ch, 'Off'))

if __name__ == "__main__":
    def callback(ch, data):
        print(f"Received telemetry from channel {ch}: {data}")
    worker = BoosterTelemetry(callback)
    worker.set_telem_period(1)
    worker.run()
    while True:
        pass
