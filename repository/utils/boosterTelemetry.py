import asyncio, aiomqtt
from PyQt5.QtCore import QThread, pyqtSignal, QObject

class TelemetryWorker(QObject):
    telemetry_received = pyqtSignal(int,str)

    async def listen(self):
        # we want to listen to updates of channel[0-7]/[state,input power, output power]
        async with aiomqtt.Client("137.222.69.28") as client:
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
