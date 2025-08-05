import asyncio
import logging
import time
from functools import partial
from enum import Enum, auto
from typing import Optional, Callable
from sipyco.sync_struct import Subscriber
from sipyco.pc_rpc import Client
import aiomqtt


class ConnectionState(Enum):
    CONNECTING = auto()  # Actively trying to connect
    CONNECTED = auto()  # Successfully connected
    BACKOFF = auto()  # Waiting before retry


class ServiceConnection:
    """Manages connection state for a service with simple state machine."""

    def __init__(
        self,
        name: str,
        connect_func: Callable,
        ping_func: Optional[Callable] = None,
    ):
        self.name = name
        self.connect_func = connect_func
        self.ping_func = ping_func
        self.state = ConnectionState.CONNECTING
        self.task = None
        self.ping_task = None
        self.ping_interval: float = 10.0
        self.backoff_delay = 1  # Initial backoff delay
        self.max_backoff = 30  # Maximum backoff delay
        self.backoff_factor = 2.0  # Multiply by this each retry
        self.state_change_callback = None  # Add callback for state changes

    def __str__(self):
        return f"{self.name}: {self.state.name.lower()}"

    def reset_backoff(self):
        """Reset backoff delay to initial value."""
        self.backoff_delay = 1

    def increase_backoff(self):
        """Increase backoff delay with exponential factor."""
        self.backoff_delay = min(
            self.backoff_delay * self.backoff_factor, self.max_backoff
        )

    async def connect(self):
        """Attempt to connect to service."""
        if self.state == ConnectionState.BACKOFF:
            logging.debug(f"[{self.name}] In backoff state, ignoring connect request")
            return

        self.state = ConnectionState.CONNECTING
        logging.debug(f"[{self.name}] State: {self.state.name}")

        try:
            await self.connect_func()
            self.state = ConnectionState.CONNECTED
            self.reset_backoff()
            logging.debug(f"[{self.name}] State: {self.state.name}")

            # Start ping task if ping function is provided
            if self.ping_func and self.ping_interval > 0:
                await self.start_ping_task()

        except Exception as e:
            logging.error(f"[{self.name}] Connection failed: {str(e)}")
            await self.handle_disconnect(e)

    async def start_ping_task(self):
        """Start a periodic ping task to check if service is alive."""
        # Cancel any existing ping task
        if self.ping_task and not self.ping_task.done():
            self.ping_task.cancel()

        # Create new ping task
        self.ping_task = asyncio.create_task(self.ping_loop())
        logging.debug(
            f"[{self.name}] Started ping task with interval {self.ping_interval}s"
        )

    async def ping_loop(self):
        """Periodically ping the service to check if it's alive."""
        try:
            while self.state == ConnectionState.CONNECTED:
                await asyncio.sleep(self.ping_interval)
                if self.state != ConnectionState.CONNECTED:
                    break

                try:
                    if not await self.ping_func():
                        logging.warning(
                            f"[{self.name}] Ping failed, service may be down"
                        )
                        await self.handle_disconnect(Exception("Ping failed"))
                        break
                    logging.debug(f"[{self.name}] Ping successful")
                except Exception as e:
                    logging.error(f"[{self.name}] Ping error: {str(e)}")
                    await self.handle_disconnect(e)
                    break
        except asyncio.CancelledError:
            logging.debug(f"[{self.name}] Ping task cancelled")
        except Exception as e:
            logging.error(f"[{self.name}] Ping loop error: {str(e)}")

    async def handle_disconnect(self, error=None):
        """Handle disconnection by entering backoff state."""
        if self.state == ConnectionState.BACKOFF:
            return

        error_msg = f": {str(error)}" if error else ""
        logging.debug(f"[{self.name}] Disconnected{error_msg}")

        # Cancel ping task if running
        if self.ping_task and not self.ping_task.done():
            self.ping_task.cancel()
            self.ping_task = None

        # Enter backoff state
        await self.start_backoff()

    async def start_backoff(self):
        """Enter backoff state and schedule reconnection."""
        self.state = ConnectionState.BACKOFF

        logging.debug(
            f"[{self.name}] Waiting {self.backoff_delay}s before reconnecting"
        )

        # Wait for backoff period
        await asyncio.sleep(self.backoff_delay)
        self.increase_backoff()

        # Cancel any existing task
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await asyncio.wait_for(self.task, timeout=1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Change state to CONNECTING before attempting connection
        self.state = ConnectionState.CONNECTING
        logging.debug(
            f"[{self.name}] State changed to {self.state.name} for reconnection"
        )

        # Create new connection task with better error handling
        try:
            logging.debug(f"[{self.name}] Attempting reconnection...")
            self.task = asyncio.create_task(self.connect())
            # Register a callback to log any errors
            self.task.add_done_callback(self._handle_reconnect_result)
        except Exception as e:
            logging.error(f"[{self.name}] Failed to schedule reconnection: {str(e)}")
            # Try again after a delay
            asyncio.create_task(self._retry_reconnect())

    def _handle_reconnect_result(self, task):
        """Handle the result of a reconnection task."""
        try:
            # Check if the task raised an exception
            if task.done() and not task.cancelled():
                exc = task.exception()
                if exc:
                    logging.error(f"[{self.name}] Reconnection failed: {str(exc)}")
                    # Schedule another attempt
                    asyncio.create_task(self._retry_reconnect())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.error(f"[{self.name}] Error handling reconnection result: {str(e)}")

    async def _retry_reconnect(self):
        """Retry reconnection after a short delay."""
        await asyncio.sleep(1)
        await self.start_backoff()

    def set_state(self, new_state):
        """Set state with callback notification"""
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            if self.state_change_callback:
                self.state_change_callback(self.name, old_state, new_state)


class MonitorClient:

    def __init__(
        self, app=None, server="137.222.69.28", port_control=3251, port_notify=3250
    ):
        self.app = app
        self.server = server
        self.port_control = port_control
        self.port_notify = port_notify
        self.subscribers: dict[str, Subscriber] = {}
        self.main_window = None
        self.tasks = []

        # Services with state tracking
        self.services = {}

        # Initialize data dictionaries
        self.datasets = dict()
        self.schedule = dict()
        self.booster = dict()
        self.dlcpro = None

        # Initialize DLCPro cache with empty values
        self.dlcpro_cache = {
            "emission": False,
            "emission-button-enabled": False,
            "last_update": 0,
        }
        self.dlcpro_cache_lock = asyncio.Lock()

        loop = asyncio.get_event_loop()
        task = loop.create_task(self.connect())
        self.tasks.append(task)

    def set_main_window(self, window):
        """Set the main window for direct updates."""
        self.main_window = window

    async def connect(self):
        """Connect to all services."""
        # Create service connections with ping functions where appropriate
        self.services["datasets"] = ServiceConnection(
            "datasets",
            partial(
                self.connect_subscriber, "datasets", self.datasets, self.port_notify
            ),
            ping_func=None,  # disconnect callback
        )

        self.services["schedule"] = ServiceConnection(
            "schedule",
            partial(
                self.connect_subscriber, "schedule", self.schedule, self.port_notify
            ),
            ping_func=None,  # disconnect callback
        )

        self.services["booster"] = ServiceConnection(
            "booster",
            self.connect_booster,
            ping_func=None,  # disconnect callback
        )

        # Configure DLCPro with faster ping interval for data fetching
        dlcpro_service = ServiceConnection(
            "dlcpro",
            self.connect_dlcpro,
            ping_func=self.ping_dlcpro,
        )
        dlcpro_service.ping_interval = 0.5
        self.services["dlcpro"] = dlcpro_service

        # Start all connections
        connect_tasks = [service.connect() for service in self.services.values()]
        logging.debug("Connecting to services...")

        # No need to start a separate background task anymore
        # as ping_dlcpro will be called regularly by the ping task

        await asyncio.gather(*connect_tasks, return_exceptions=True)

    async def ping_dlcpro(self):
        """
        Ping DLCPro and fetch data.

        Returns True if connection is healthy, False otherwise.
        """
        if not self.dlcpro:
            return False

        try:
            new_cache = {}

            # Fetch common data
            new_cache["emission"] = self.dlcpro.get("emission", False)
            new_cache["emission-button-enabled"] = self.dlcpro.get(
                "emission-button-enabled", False
            )
            new_cache["last_update"] = time.time()

            # Fetch laser data
            for laser_num in [1, 2]:
                prefix = f"laser{laser_num}"

                # Fetch all the required data in a more concise format
                keys = [
                    "label",
                    "enabled",
                    "dl:cc:current_set",
                    "amp:cc:current_set",
                    "dl:lock:lock_enabled",
                    "scope:data",
                    "scope:channel1:signal",
                    "dl:lock:candidates",
                    "dl:lock:background_trace",
                    "scan:enabled",
                ]

                for key in keys:
                    full_key = f"{prefix}:{key}"
                    default = (
                        f"Laser {laser_num}"
                        if key == "label"
                        else (
                            0.0
                            if "current" in key
                            else (True if key == "dl:lock:lock_enabled" else False)
                        )
                    )
                    new_cache[full_key] = self.dlcpro.get(full_key, default)

            # Update cache
            async with self.dlcpro_cache_lock:
                self.dlcpro_cache = new_cache

            logging.debug(f"Updated DLCPro cache with {len(new_cache)} items")
            return True

        except Exception as e:
            logging.error(f"Error in DLCPro ping and data fetch: {e}")
            return False

    async def connect_subscriber(self, name, db: dict, port=None, server=None):
        """Connect to a subscriber service with state machine-based reconnection."""
        port = self.port_notify if port is None else port
        server = self.server if server is None else server
        service = self.services[name]

        def _create(data):
            db.update(data)
            # Update state on successful connection
            service.state = ConnectionState.CONNECTED
            service.reset_backoff()
            return db

        def _update(mod):
            if self.main_window:
                # Call the appropriate update method directly
                update_method = getattr(self.main_window, f"update_{name}")
                update_method(mod)
            return

        def disconnect_cb(*args):
            logging.debug(f"Disconnected from {name} at {server}:{port}")
            # Let the state machine handle the reconnection
            asyncio.create_task(service.handle_disconnect())

        subscriber = Subscriber(name, _create, _update, disconnect_cb)
        await subscriber.connect(server, port)
        self.subscribers[name] = subscriber
        logging.debug(f"Connected to {name} at {server}:{port}")

    async def connect_booster(self):
        """Connect to Booster with state machine-based reconnection."""
        service = self.services["booster"]

        def disconnected_booster(*_):
            logging.info("Booster disconnected")
            # Let the state machine handle the reconnection
            asyncio.create_task(service.handle_disconnect())

        def handle_booster_message(message):
            ch = int(message.topic.value[-1])
            data = message.payload.decode()
            self.booster[ch] = data

            # Update state on successful message
            if service.state != ConnectionState.CONNECTED:
                service.state = ConnectionState.CONNECTED
                service.reset_backoff()
                if self.main_window:
                    self.main_window.update_connection_status()

            if self.main_window:
                self.main_window.update_booster(ch)

        async with aiomqtt.Client(self.server) as client:
            client._on_message = handle_booster_message
            client._on_disconnect = disconnected_booster
            await client.subscribe("dt/sinara/booster/fc-0f-e7-23-77-30/telemetry/#")
            service.state = ConnectionState.CONNECTED
            service.reset_backoff()
            logging.debug("Connected to Booster")

            async for message in client.messages:
                handle_booster_message(message)

    def get_dlcpro_data(self, key: str, default=None):
        """Get data from DLCPro cache with a default value if not found"""
        val = self.dlcpro_cache.get(key, default)
        return val if val is not None else default

    def get_dlcpro_cache(self):
        """Get a copy of the entire DLCPro cache"""
        return dict(self.dlcpro_cache)

    async def connect_dlcpro(self):
        """Connect to DLCPro service and initialize cache"""
        service = self.services["dlcpro"]

        try:
            # Create DLCPro client with custom get method
            self.dlcpro = Client(self.server, 3272, "TopticaDLCPro", timeout=1)

            # Define get method to handle attribute access
            def get_dlcpro(name, _=None):
                try:
                    result = self.dlcpro.__getattr__(
                        name.replace(":", "_").replace("-", "_")
                    )()

                    # On success, update state if needed
                    if service.state != ConnectionState.CONNECTED:
                        service.state = ConnectionState.CONNECTED
                        service.reset_backoff()

                    return result
                except Exception as e:
                    # Only trigger reconnection if currently connected
                    if service.state == ConnectionState.CONNECTED:
                        logging.error(f"DLCPro communication error: {name}: {str(e)}")
                        asyncio.create_task(service.handle_disconnect(e))
                    return None

            # Attach custom get method
            self.dlcpro.get = get_dlcpro

            # Test connection
            test_result = self.dlcpro.get("time")
            if test_result is not None:
                service.state = ConnectionState.CONNECTED
                service.reset_backoff()
                logging.debug("Connected to DLCPro")
            else:
                raise Exception("Connection test failed")

        except Exception as e:
            logging.error(f"Failed to connect to DLCPro: {str(e)}")
            raise

        # Initialize cache after successful connection
        if self.dlcpro:
            # Start with basic connection data
            self.dlcpro_cache = {
                "emission": False,
                "emission-button-enabled": False,
                "last_update": time.time(),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    client = MonitorClient()
    asyncio.run(client.connect())
    # Keep the event loop running
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
